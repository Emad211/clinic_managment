"""Administrative dashboard; clinical interpretation belongs to Engine v2."""
from flask import Blueprint, render_template

from src.adapters import accounting_bridge
from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.wallet_repo import WalletRepository
from src.api.auth import login_required
from src.common.utils import format_jalali_date, format_jalali_datetime, today_str
from src.services.control_room_service import ControlRoomService
from src.services.followup_projection_service import FollowupProjectionService
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
    """Daily launchpad using one event-aware follow-up projection."""
    db = get_db()
    today = today_str()
    followup = FollowupProjectionService().summary(as_of=today)
    population = ControlRoomService().panel(show_value=False)["summary"]

    today_followups = []
    for source in followup["due"][:12]:
        item = dict(source)
        item["pid"] = int(item["patient_link_id"])
        item["full_name"] = item.get("patient_name") or "—"
        item["reason_fa"] = REASON_FA.get(item["reason"], item["reason"])
        due = item.get("current_due_at")
        item["due_fa"] = format_jalali_date(due) if due else "—"
        today_followups.append(item)

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
        "followups_open": followup["open_tasks"],
        "action_required": population["action_required"],
        "followups_today": followup["due_tasks"],
        "due_callbacks": followup["due_callbacks"],
        "lapsed": population["lapsed"],
        "with_observation": population["with_observation"],
        "refills_due": refills_due,
        "open_followup_patients": followup["open_patients"],
        "no_show_patients": population["no_show_patients"],
    }
    wallet_outstanding = WalletRepository().total_outstanding()

    try:
        revenue = RevenueService().dashboard()
    except Exception as exc:
        print(f"[dashboard] revenue error: {exc}")
        revenue = {"available": False, "error_code": "DASHBOARD_REVENUE_ERROR"}

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
        projection_policy="UNIFIED_EVENT_AWARE_V1",
    )
