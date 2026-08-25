"""Root redirect to the doctor queue; clinical interpretation belongs to Engine v2."""
from flask import Blueprint, flash, redirect, url_for

from src.api.auth import login_required
from src.security.permissions import Permission, permission_required
from src.services.activity_logger import log_activity
from src.services.specialist_financial_reconciliation_service import (
    SpecialistFinancialReconciliationService,
)


bp = Blueprint("dashboard", __name__)


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
    """The daily home is the doctor queue; this route only forwards to it."""
    return redirect(url_for("doctor_queue.index"))
