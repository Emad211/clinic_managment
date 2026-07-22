"""Authenticated UI/API boundary for explicit collection reconciliation."""
from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from src.adapters.sqlite.clinical_engine_v1_cutover import (
    ensure_v1_schema_cutover,
    install_v1_request_projection,
)
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.patients_repo import PatientRepository
from src.api.auth import login_required, manager_required
from src.services.activity_logger import log_activity
from src.services.clinical_reconciliation_service import (
    ClinicalReconciliationService,
)
from src.services.patient_service import PatientService


bp = Blueprint(
    "clinical_reconciliation",
    __name__,
    url_prefix="/patients",
)


@bp.record_once
def install_patient_mutation_guards(state):
    # The patients blueprint is registered first. Replace only the four legacy
    # endpoint callables that need patient-row ownership checks while preserving
    # every public URL and endpoint name.
    from src.api.patient_mutation_guards import install

    install(state.app)


@bp.record
def enforce_file_backed_v1_cutover(state):
    # ``record`` (not ``record_once``) is deliberate: test processes and desktop
    # relaunches may construct more than one Flask application from the same
    # imported Blueprint object. Every application must be clean before serving.
    if (state.app.config.get("DATABASE_PATH") or "") != ":memory:":
        with state.app.app_context():
            ensure_v1_schema_cutover(get_db())


@bp.before_app_request
def install_request_local_v2_rule_projection():
    """Install only connection-local read compatibility required by one route."""
    db = get_db()
    # An in-memory database belongs to this exact request connection, so its
    # bootstrap cleanup must occur here. It cannot alter any persistent file.
    if (current_app.config.get("DATABASE_PATH") or "") == ":memory:":
        ensure_v1_schema_cutover(db)
    install_v1_request_projection(
        db,
        endpoint=request.endpoint,
    )


def _patient_or_none(pid: int):
    return PatientRepository().get_by_id(pid)


def _anchor(collection_key: str) -> str:
    return "#meds" if collection_key == "medications" else "#record"


@bp.get("/<int:pid>/reconciliation")
@login_required
def workspace(pid: int):
    profile = PatientService().get_full_profile(pid)
    if not profile:
        flash("بیمار یافت نشد", "error")
        return redirect(url_for("patients.list_patients"))
    return render_template(
        "patients/reconciliation.html",
        active_page="patients",
        patient=profile["patient"],
        conditions=profile["conditions"],
        medications=[
            medication
            for medication in profile["medications"]
            if medication.get("is_active")
        ],
        allergies=profile["allergies"],
        reconciliation=profile["reconciliation"],
    )


@bp.get("/<int:pid>/reconciliation/status")
@login_required
def status(pid: int):
    if not _patient_or_none(pid):
        return jsonify({"error": "patient_not_found"}), 404
    statuses = ClinicalReconciliationService().patient_status(pid)
    return jsonify(
        {
            "patient_link_id": pid,
            "collections": statuses,
            "workspace_url": url_for(
                "clinical_reconciliation.workspace", pid=pid
            ),
            "review_url_template": url_for(
                "clinical_reconciliation.review",
                pid=pid,
                collection_key="__COLLECTION__",
            ),
        }
    )


@bp.post("/<int:pid>/reconciliation/<collection_key>")
@manager_required
def review(pid: int, collection_key: str):
    if not _patient_or_none(pid):
        flash("بیمار یافت نشد", "error")
        return redirect(url_for("patients.list_patients"))
    try:
        event = ClinicalReconciliationService().record(
            patient_link_id=pid,
            collection_key=collection_key,
            completeness=(request.form.get("completeness") or "").strip(),
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            attested=request.form.get("attested") in {"yes", "on", "1"},
            patient_confirmed=(
                request.form.get("patient_confirmed")
                in {"yes", "on", "1"}
            ),
            note=request.form.get("note"),
        )
    except (ValueError, LookupError) as exc:
        flash(f"مرور فهرست ثبت نشد: {exc}", "error")
    else:
        log_activity(
            "clinical_collection_reconcile",
            (
                f"{collection_key} {event['completeness']} "
                f"items={event['item_count']} event={event['id']}"
            ),
            patient_link_id=pid,
        )
        flash(
            "مرور فهرست ثبت شد؛ هر تغییر بعدی نیازمند مرور دوباره است.",
            "success",
        )
    if request.form.get("return_to") == "workspace":
        return redirect(
            url_for("clinical_reconciliation.workspace", pid=pid)
            + f"#{collection_key}"
        )
    return redirect(
        url_for("patients.detail", pid=pid) + _anchor(collection_key)
    )
