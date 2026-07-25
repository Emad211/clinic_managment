"""Administrative dashboard; clinical interpretation belongs to Engine v2."""
from flask import Blueprint, render_template

from src.adapters import accounting_bridge
from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.wallet_repo import WalletRepository
from src.api.auth import login_required
from src.common.utils import format_jalali_date, format_jalali_datetime, today_str
from src.services.control_room_service import ControlRoomService
from src.services.revenue_service import RevenueService


bp = Blueprint("dashboard", __name__)

REASON_FA = {
    "refill": "تجدید نسخه",
    "uncontrolled": "پیگیری قدیمی",
    "lapsed": "بدون مراجعه",
    "recall": "دعوت بازگشت",
    "visit_due": "موعد ویزیت",
    "manual": "دستی",
    "monitoring": "پایش",
    "screening": "غربالگری",
    "vaccine": "واکسن",
}


@bp.route("/")
@login_required
def index():
    """Daily launchpad with operational counts and no measurement grading."""
    db = get_db()
    today = today_str()
    population = ControlRoomService().panel(show_value=False)["summary"]

    rows = db.execute(
        """SELECT f.id, f.reason, f.detail, f.due_date,
                  p.id AS pid, p.full_name, p.phone_number
           FROM followup_tasks f
           JOIN patient_links p ON p.id=f.patient_link_id
           WHERE f.status='open'
             AND (f.due_date IS NULL OR f.due_date <= ?)
           ORDER BY (f.due_date IS NULL), f.due_date
           LIMIT 12""",
        (today,),
    ).fetchall()
    today_followups = [dict(row) for row in rows]
    for item in today_followups:
        item["reason_fa"] = REASON_FA.get(item["reason"], item["reason"])
        item["due_fa"] = (
            format_jalali_date(item["due_date"])
            if item["due_date"]
            else "—"
        )

    followups_today = db.execute(
        """SELECT COUNT(*) AS count FROM followup_tasks
           WHERE status='open' AND (due_date IS NULL OR due_date <= ?)""",
        (today,),
    ).fetchone()["count"]
    refills_due = db.execute(
        """SELECT COUNT(*) AS count FROM patient_medications
           WHERE is_active=1 AND refill_due_date IS NOT NULL
             AND refill_due_date <= ?""",
        (today,),
    ).fetchone()["count"]

    stats = {
        "patients": population["total"],
        "appointments_open": db.execute(
            "SELECT COUNT(*) AS count FROM appointments WHERE status='scheduled'"
        ).fetchone()["count"],
        "followups_open": db.execute(
            "SELECT COUNT(*) AS count FROM followup_tasks WHERE status='open'"
        ).fetchone()["count"],
        "action_required": population["action_required"],
        "followups_today": followups_today,
        "lapsed": population["lapsed"],
        "with_observation": population["with_observation"],
        "refills_due": refills_due,
        "open_followup_patients": population["open_followup_patients"],
        "no_show_patients": population["no_show_patients"],
    }
    wallet_outstanding = WalletRepository().total_outstanding()

    try:
        revenue = RevenueService().dashboard()
    except Exception as exc:
        print(f"[dashboard] revenue error: {exc}")
        revenue = {"available": False}

    upcoming = AppointmentRepository().upcoming(limit=8)
    for appointment in upcoming:
        appointment["scheduled_fa"] = format_jalali_datetime(
            appointment["scheduled_at"]
        )

    return render_template(
        "dashboard.html",
        active_page="dashboard",
        stats=stats,
        today_followups=today_followups,
        wallet_outstanding=wallet_outstanding,
        revenue=revenue,
        bridge_ok=accounting_bridge.is_available(),
        upcoming=upcoming,
        projection_policy="ADMINISTRATIVE_ONLY",
    )
