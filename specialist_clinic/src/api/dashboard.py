from datetime import datetime

from flask import Blueprint, render_template, g
from src.api.auth import login_required
from src.adapters.sqlite.core import get_db
from src.adapters import accounting_bridge
from src.adapters.sqlite.wallet_repo import WalletRepository
from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.services.revenue_service import RevenueService
from src.common.utils import format_jalali_datetime, format_jalali_date, today_str, iran_now

bp = Blueprint("dashboard", __name__)

# Follow-up reason → Persian label (mirrors the worklist labels).
REASON_FA = {
    'refill': 'تجدید نسخه', 'uncontrolled': 'کنترل‌نشده', 'lapsed': 'بدون مراجعه', 'recall': 'دعوتِ بازگشت',
    'visit_due': 'موعد ویزیت', 'manual': 'دستی', 'monitoring': 'پایش',
    'screening': 'غربالگری', 'vaccine': 'واکسن',
}


@bp.route("/")
@login_required
def index():
    """Physician-first clinic-at-a-glance: who needs attention today, plus business KPIs."""
    db = get_db()
    today = today_str()

    # ---- Clinical: per-patient latest control vitals (one pass) ----
    rows = db.execute(
        """
        SELECT p.id, p.full_name, p.phone_number,
          (SELECT v.value FROM vital_readings v WHERE v.patient_link_id=p.id AND v.type='hba1c'        ORDER BY v.measured_at DESC LIMIT 1) AS hba1c,
          (SELECT v.value FROM vital_readings v WHERE v.patient_link_id=p.id AND v.type='fbs'          ORDER BY v.measured_at DESC LIMIT 1) AS fbs,
          (SELECT v.value FROM vital_readings v WHERE v.patient_link_id=p.id AND v.type='bp_systolic'  ORDER BY v.measured_at DESC LIMIT 1) AS sys,
          (SELECT MAX(v.measured_at) FROM vital_readings v WHERE v.patient_link_id=p.id) AS last_vital
        FROM patient_links p WHERE p.is_active=1
        """
    ).fetchall()

    now = iran_now()
    measured = 0
    lapsed_count = 0
    attention = []
    for r in rows:
        assessable = (r['hba1c'] is not None) or (r['sys'] is not None)
        if assessable:
            measured += 1
        # lapsed: no reading in the last 120 days
        if r['last_vital']:
            try:
                d = datetime.strptime(str(r['last_vital'])[:10], '%Y-%m-%d')
                if (now - d).days > 120:
                    lapsed_count += 1
            except ValueError:
                pass
        issues = []
        if r['hba1c'] is not None and r['hba1c'] > 8:
            issues.append({'label': 'HbA1c', 'value': r['hba1c'], 'unit': '٪'})
        if r['sys'] is not None and r['sys'] >= 140:
            issues.append({'label': 'فشار سیستول', 'value': r['sys'], 'unit': ''})
        if r['fbs'] is not None and r['fbs'] >= 180:
            issues.append({'label': 'قند ناشتا', 'value': r['fbs'], 'unit': ''})
        if issues:
            attention.append({
                'id': r['id'], 'name': r['full_name'], 'phone': r['phone_number'],
                'issues': issues, 'score': len(issues),
                'last_fa': format_jalali_date(r['last_vital']) if r['last_vital'] else '—',
            })
    attention.sort(key=lambda a: -a['score'])
    uncontrolled_count = len(attention)
    controlled = max(measured - uncontrolled_count, 0)
    control_rate = round(controlled / measured * 100) if measured else 0

    # ---- Clinical: due/overdue follow-ups (today or earlier) ----
    today_followups = db.execute(
        """
        SELECT f.id, f.reason, f.detail, f.due_date, p.id AS pid, p.full_name, p.phone_number
        FROM followup_tasks f JOIN patient_links p ON p.id=f.patient_link_id
        WHERE f.status='open' AND (f.due_date IS NULL OR f.due_date <= ?)
        ORDER BY (f.due_date IS NULL), f.due_date LIMIT 12
        """, (today,)
    ).fetchall()
    today_followups = [dict(t) for t in today_followups]
    for t in today_followups:
        t['reason_fa'] = REASON_FA.get(t['reason'], t['reason'])
        t['due_fa'] = format_jalali_date(t['due_date']) if t['due_date'] else '—'
    followups_today = db.execute(
        "SELECT COUNT(*) c FROM followup_tasks WHERE status='open' AND (due_date IS NULL OR due_date <= ?)",
        (today,)).fetchone()['c']

    refills_due = db.execute(
        "SELECT COUNT(*) c FROM patient_medications WHERE is_active=1 AND refill_due_date IS NOT NULL AND refill_due_date <= ?",
        (today,)).fetchone()['c']

    stats = {
        "patients": db.execute("SELECT COUNT(*) c FROM patient_links WHERE is_active=1").fetchone()["c"],
        "appointments_open": db.execute("SELECT COUNT(*) c FROM appointments WHERE status='scheduled'").fetchone()["c"],
        "followups_open": db.execute("SELECT COUNT(*) c FROM followup_tasks WHERE status='open'").fetchone()["c"],
        "uncontrolled": uncontrolled_count,
        "followups_today": followups_today,
        "lapsed": lapsed_count,
        "refills_due": refills_due,
        "control_rate": control_rate,
        "controlled": controlled,
        "measured": measured,
    }
    wallet_outstanding = WalletRepository().total_outstanding()

    # ---- Business: revenue (read-only from accounting); never breaks the page ----
    try:
        revenue = RevenueService().dashboard()
    except Exception as e:
        print(f"[dashboard] revenue error: {e}")
        revenue = {'available': False}

    upcoming = AppointmentRepository().upcoming(limit=8)
    for a in upcoming:
        a['scheduled_fa'] = format_jalali_datetime(a['scheduled_at'])

    return render_template(
        "dashboard.html",
        active_page='dashboard',
        stats=stats,
        attention=attention[:10],
        attention_total=uncontrolled_count,
        today_followups=today_followups,
        wallet_outstanding=wallet_outstanding,
        revenue=revenue,
        bridge_ok=accounting_bridge.is_available(),
        upcoming=upcoming,
    )
