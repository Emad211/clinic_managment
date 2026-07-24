"""Authenticated UI/API boundary for explicit collection reconciliation."""
from __future__ import annotations

from flask import (
    Blueprint,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from src.adapters.sqlite.clinical_data_conflict_repo import (
    ClinicalDataConflictStale,
)
from src.adapters.sqlite.patients_repo import PatientRepository
from src.api.auth import permission_required
from src.domain.clinical_engine.data_conflicts import (
    ClinicalDataConflictError,
)
from src.security.permissions import Permission
from src.services.activity_logger import log_activity
from src.services.clinical_data_conflict_service import (
    ClinicalDataConflictService,
)
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
    from src.api.patient_mutation_guards import install

    install(state.app)


def _patient_or_none(pid: int):
    return PatientRepository().get_by_id(pid)


def _anchor(collection_key: str) -> str:
    return "#meds" if collection_key == "medications" else "#record"


@bp.get("/<int:pid>/reconciliation")
@permission_required(Permission.PATIENT_VIEW)
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
@permission_required(Permission.PATIENT_VIEW)
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
@permission_required(Permission.CLINICAL_RECONCILE)
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


@bp.post("/<int:pid>/reconciliation/<collection_key>/conflicts/resolve")
@permission_required(Permission.CLINICAL_CONFLICT_RESOLVE)
def resolve_conflict(pid: int, collection_key: str):
    if not _patient_or_none(pid):
        flash("بیمار یافت نشد", "error")
        return redirect(url_for("patients.list_patients"))
    expected_event_raw = (request.form.get("expected_current_event_id") or "").strip()
    try:
        expected_event_id = int(expected_event_raw) if expected_event_raw else None
    except ValueError:
        flash("resolution ثبت نشد: شناسهٔ وضعیت جاری معتبر نیست.", "error")
        return redirect(
            url_for("clinical_reconciliation.workspace", pid=pid)
            + f"#{collection_key}"
        )
    selected = request.form.getlist("candidate_keys")
    single = (request.form.get("selected_candidate_key") or "").strip()
    if single and single not in selected:
        selected.append(single)
    try:
        event = ClinicalDataConflictService().resolve(
            patient_link_id=pid,
            collection_key=collection_key,
            conflict_group_key=(request.form.get("conflict_group_key") or "").strip(),
            method=(request.form.get("resolution_method") or "").strip(),
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            expected_candidate_set_hash=(
                request.form.get("expected_candidate_set_hash") or ""
            ).strip(),
            expected_current_event_id=expected_event_id,
            selected_candidate_keys=selected,
            note=request.form.get("note"),
        )
    except ClinicalDataConflictStale as exc:
        flash(f"resolution ثبت نشد؛ داده تغییر کرده است: {exc}", "error")
    except (ClinicalDataConflictError, ValueError, LookupError) as exc:
        flash(f"resolution ثبت نشد: {exc}", "error")
    else:
        log_activity(
            "clinical_data_conflict_resolve",
            (
                f"{collection_key} group={event['conflict_group_key']} "
                f"method={event['resolution_method']} event={event['id']}"
            ),
            patient_link_id=pid,
        )
        flash(
            "resolution تعارض ثبت شد؛ برای تأیید کامل، فهرست را دوباره مرور کنید.",
            "success",
        )
    return redirect(
        url_for("clinical_reconciliation.workspace", pid=pid)
        + f"#{collection_key}"
    )
