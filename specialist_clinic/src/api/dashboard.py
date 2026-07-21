from flask import Blueprint, render_template
from src.api.auth import login_required
from src.adapters.sqlite.core import get_db
from src.adapters import accounting_bridge
from src.adapters.sqlite.wallet_repo import WalletRepository
from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.services.revenue_service import RevenueService
from src.services.control_room_service import ControlRoomService
from src.common.utils import format_jalali_datetime, format_jalali_date, today_str

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
    """Daily clinic launchpad; prioritisation itself belongs to Control Room."""
    db = get_db()
    today = today_str()

    # The Control Room owns prioritisation and editable clinical thresholds.
    # Dashboard consumes only its population summary, never a second ranking.
    population = ControlRoomService().panel(show_value=False)['summary']

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
        "patients": population['total'],
        "appointments_open": db.execute("SELECT COUNT(*) c FROM appointments WHERE status='scheduled'").fetchone()["c"],
        "followups_open": db.execute("SELECT COUNT(*) c FROM followup_tasks WHERE status='open'").fetchone()["c"],
        "action_required": population['action_required'],
        "uncontrolled": population['uncontrolled'],
        "followups_today": followups_today,
        "lapsed": population['lapsed'],
        "refills_due": refills_due,
        "control_rate": population['control_rate'],
        "controlled": population['controlled'],
        "measured": population['measured'],
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
        today_followups=today_followups,
        wallet_outstanding=wallet_outstanding,
        revenue=revenue,
        bridge_ok=accounting_bridge.is_available(),
        upcoming=upcoming,
    )
