"""Authenticated UI/API boundary for explicit collection reconciliation."""
from __future__ import annotations

from flask import Blueprint, flash, g, jsonify, redirect, request, url_for

from src.adapters.sqlite.patients_repo import PatientRepository
from src.api.auth import login_required
from src.services.activity_logger import log_activity
from src.services.clinical_reconciliation_service import (
    ClinicalReconciliationService,
)


bp = Blueprint(
    "clinical_reconciliation",
    __name__,
    url_prefix="/patients",
)


def _patient_or_none(pid: int):
    return PatientRepository().get_by_id(pid)


def _anchor(collection_key: str) -> str:
    return "#meds" if collection_key == "medications" else "#record"


@bp.get("/<int:pid>/reconciliation/status")
@login_required
def status(pid: int):
    if not _patient_or_none(pid):
        return jsonify({"error": "patient_not_found"}), 404
    statuses = ClinicalReconciliationService().patient_status(pid)
    return jsonify({
        "patient_link_id": pid,
        "collections": statuses,
        "review_url_template": url_for(
            "clinical_reconciliation.review",
            pid=pid,
            collection_key="__COLLECTION__",
        ),
    })


@bp.post("/<int:pid>/reconciliation/<collection_key>")
@login_required
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
                request.form.get("patient_confirmed") in {"yes", "on", "1"}
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
    return redirect(url_for("patients.detail", pid=pid) + _anchor(collection_key))
