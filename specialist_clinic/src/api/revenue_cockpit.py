"""Manager revenue & operational-value cockpit (read-only presentation).

This surface computes nothing financial itself. `RevenueService` stays the single
authority for money — its completed-Encounter scope, freshness ceiling and
unavailability contract — and `RevenueCockpitService` only composes that projection
with count-only operational aggregates so a manager can see which work turns into
provable revenue. The route is therefore GET-only and never mutates anything, and it
is gated on the same manager-only permission as the finance review surface.
"""
from __future__ import annotations

from flask import Blueprint, render_template

from src.security.permissions import Permission, permission_required
from src.services.revenue_cockpit_service import RevenueCockpitService


bp = Blueprint("revenue_cockpit", __name__, url_prefix="/revenue-cockpit")


@bp.get("/")
@permission_required(Permission.FINANCIAL_REVIEW_VIEW)
def index():
    # `permission_required` already redirects an unauthenticated request to the
    # login page, so no separate login gate is needed here.
    cockpit = RevenueCockpitService().cockpit()
    return render_template(
        "revenue_cockpit/index.html",
        active_page="revenue_cockpit",
        cockpit=cockpit,
    )
