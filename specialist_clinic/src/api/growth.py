"""Manager-facing growth and attributable revenue cockpit."""
from flask import Blueprint, render_template

from src.security.permissions import Permission, permission_required
from src.services.growth_revenue_cockpit_service import (
    GrowthRevenueCockpitService,
)


bp = Blueprint("growth", __name__, url_prefix="/growth")


@bp.get("/")
@permission_required(Permission.FINANCIAL_REVIEW_VIEW)
def cockpit():
    return render_template(
        "growth/cockpit.html",
        active_page="growth",
        **GrowthRevenueCockpitService().build(),
    )


__all__ = ["bp"]
