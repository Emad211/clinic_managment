"""Administrative dashboard; clinical interpretation belongs to Engine v2."""
from flask import Blueprint, flash, g, redirect, render_template, url_for

from src.adapters import specialist_accounting_invoice_reader
from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.wallet_repo import WalletRepository
from src.api.auth import login_required
from src.common.utils import format_jalali_date, format_jalali_datetime, today_str
from src.security.permissions import Permission, has_permission, permission_required
from src.services.activity_logger import log_activity
from src.services.control_room_service import ControlRoomService
from src.services.followup_projection_service import FollowupProjectionService
from src.services.revenue_service import RevenueService
from src.services.specialist_financial_reconciliation_service import (
    SpecialistFinancialReconciliationService,
)


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


@bp.post("/finance/reconcile")
@permission_required(Permission.OPERATIONAL_HEALTH_VIEW)
def reconcile_finance():
    result = SpecialistFinancialReconciliationService().reconcile_all()
    log_activity(
        "specialist_finance_reconcile",
        "eligible={eligible} observed={observed} changed={changed} issues={issues}".format(
            eligible=result["eligible"],
            observed=result["observed"],
            changed=result["changed"],
            issues=len(result["issues"]),
        ),
    )
    if result["issues"]:
        flash(
            f"همگام‌سازی مالی با {len(result['issues'])} خطا کامل نشد؛ اعداد حدسی نمایش داده نمی‌شوند.",
            "error",
        )
    else:
        flash(
            f"{result['observed']} فاکتور واجد شرایط بررسی شد و {result['changed']} snapshot جدید ثبت شد.",
            "success",
        )
    return redirect(url_for("dashboard.index"))


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
        revenue = {
            "available": False,
            "error_code": "DASHBOARD_REVENUE_ERROR",
            "scope": {},
            "funnel": {},
        }

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
        bridge_ok=specialist_accounting_invoice_reader.is_available(),
        can_reconcile_finance=has_permission(Permission.OPERATIONAL_HEALTH_VIEW),
        upcoming=upcoming,
        projection_policy="UNIFIED_EVENT_AWARE_V1",
    )
