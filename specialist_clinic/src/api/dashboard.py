from flask import Blueprint, render_template, g
from src.api.auth import login_required
from src.adapters.sqlite.core import get_db
from src.adapters import accounting_bridge
from src.adapters.sqlite.wallet_repo import WalletRepository
from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.services.revenue_service import RevenueService
from src.common.utils import format_jalali_datetime

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def index():
    db = get_db()
    stats = {
        "patients": db.execute("SELECT COUNT(*) c FROM patient_links WHERE is_active=1").fetchone()["c"],
        "appointments_open": db.execute(
            "SELECT COUNT(*) c FROM appointments WHERE status='scheduled'").fetchone()["c"],
        "followups_open": db.execute(
            "SELECT COUNT(*) c FROM followup_tasks WHERE status='open'").fetchone()["c"],
        "campaigns": db.execute("SELECT COUNT(*) c FROM sms_campaigns").fetchone()["c"],
    }
    wallet_outstanding = WalletRepository().total_outstanding()

    # Revenue (read-only from accounting). Never breaks the dashboard if bridge is down.
    try:
        revenue = RevenueService().dashboard()
    except Exception as e:
        print(f"[dashboard] revenue error: {e}")
        revenue = {'available': False}

    # Upcoming appointments
    upcoming = AppointmentRepository().upcoming(limit=8)
    for a in upcoming:
        a['scheduled_fa'] = format_jalali_datetime(a['scheduled_at'])

    # Recent patients
    recent_patients = db.execute(
        "SELECT id, full_name, phone_number, enrolled_at FROM patient_links WHERE is_active=1 ORDER BY id DESC LIMIT 8"
    ).fetchall()

    return render_template(
        "dashboard.html",
        active_page='dashboard',
        stats=stats,
        wallet_outstanding=wallet_outstanding,
        revenue=revenue,
        bridge_ok=accounting_bridge.is_available(),
        upcoming=upcoming,
        recent_patients=[dict(r) for r in recent_patients],
    )
