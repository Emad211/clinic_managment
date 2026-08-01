"""Manager-side read-only monitor for hypoglycemia shadow aggregates."""
from __future__ import annotations

from flask import Blueprint, make_response, render_template

from src.security.permissions import Permission, permission_required
from src.services.hypoglycemia_shadow_observability import (
    HypoglycemiaShadowObservability,
)


bp = Blueprint(
    "hypoglycemia_shadow_monitor",
    __name__,
    url_prefix="/manager/hypoglycemia-shadow",
)


@bp.get("/")
@permission_required(Permission.OPERATIONAL_HEALTH_VIEW)
def index():
    """Render identifier-free internal counts without adding any write surface."""
    response = make_response(
        render_template(
            "manager/hypoglycemia_shadow_monitor.html",
            shadow=HypoglycemiaShadowObservability().snapshot(),
            active_page="manager",
        )
    )
    # Low-cell internal health counts must not be cached or indexed even though
    # direct patient/event/source identifiers are absent from the payload.
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response
