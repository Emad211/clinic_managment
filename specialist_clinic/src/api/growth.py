"""Manager-facing growth, revenue and low-risk automation surfaces."""
from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from src.adapters.sqlite.core import get_db
from src.security.permissions import Permission, permission_required
from src.services.activity_logger import log_activity
from src.services.growth_automation_service import GrowthAutomationService
from src.services.growth_revenue_cockpit_service import (
    GrowthRevenueCockpitService,
)


bp = Blueprint("growth", __name__, url_prefix="/growth")


def _active_users() -> list[dict]:
    return [
        dict(row)
        for row in get_db().execute(
            """SELECT username,full_name FROM users
               WHERE is_active=1 ORDER BY full_name,username"""
        ).fetchall()
    ]


@bp.get("/")
@permission_required(Permission.FINANCIAL_REVIEW_VIEW)
def cockpit():
    return render_template(
        "growth/cockpit.html",
        active_page="growth",
        **GrowthRevenueCockpitService().build(),
    )


@bp.get("/automation")
@permission_required(Permission.FOLLOWUP_ADMIN_MANAGE)
def automation():
    inactive_days = request.args.get("inactive_days", type=int) or 180
    service = GrowthAutomationService(get_db())
    return render_template(
        "growth/automation.html",
        active_page="growth",
        preview=service.preview(inactive_days=inactive_days),
        inactive_days=max(inactive_days, 30),
        users=_active_users(),
    )


@bp.post("/automation/run")
@permission_required(Permission.FOLLOWUP_ADMIN_MANAGE)
def run_automation():
    inactive_days = request.form.get("inactive_days", type=int) or 180
    assigned_to = str(request.form.get("assigned_to") or "").strip() or None
    result = GrowthAutomationService(get_db()).run_all(
        inactive_days=inactive_days,
        assigned_to=assigned_to,
    )
    created = sum(
        int(result[key].get("created") or 0)
        for key in ("no_show", "cancelled", "inactive")
    )
    log_activity(
        "growth_automation_run",
        (
            f"created={created} no_show={result['no_show']['created']} "
            f"cancelled={result['cancelled']['created']} "
            f"inactive={result['inactive']['created']}"
        ),
    )
    if created:
        flash(f"{created} کار رشد و بازیابی وارد مرکز کارها شد.", "success")
    else:
        flash("مورد جدیدی برای ساخت کار وجود نداشت.", "info")
    return redirect(
        url_for("growth.automation", inactive_days=max(inactive_days, 30))
    )


__all__ = ["bp"]
