"""Canonical exception-first home for clinic daily operation."""
from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.patient_acquisition_schema import (
    ensure_patient_acquisition_storage,
)
from src.api.auth import login_required
from src.services.operations_home_service import OperationsHomeService


bp = Blueprint("operations_home", __name__, url_prefix="/home")


@bp.get("/")
@login_required
def index():
    db = get_db()
    ensure_patient_acquisition_storage(db)
    return render_template(
        "home/operations.html",
        active_page="home",
        **OperationsHomeService(db).build(),
    )


def install_home_compatibility(app) -> None:
    """Make the action-oriented home canonical while retaining a legacy fallback."""
    if app.extensions.get("operations_home_compatibility_v1"):
        return
    app.extensions["operations_home_compatibility_v1"] = True

    @app.before_request
    def redirect_legacy_dashboard():
        if request.endpoint != "dashboard.index":
            return None
        if request.args.get("legacy") == "1":
            return None
        return redirect(url_for("operations_home.index"))


__all__ = ["bp", "install_home_compatibility"]
