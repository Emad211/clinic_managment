"""Explicit acquisition attribution for patients without a converted Lead."""
from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.patient_acquisition_schema import (
    ensure_patient_acquisition_storage,
)
from src.api.auth import login_required
from src.common.utils import iran_now
from src.services.activity_logger import log_activity
from src.services.lead_pipeline_service import LEAD_SOURCES
from src.services.patient_data_quality_service import PatientDataQualityService
from src.services.patient_workspace_service import PatientWorkspaceService, WORKSPACE_TABS


bp = Blueprint("patient_acquisition", __name__, url_prefix="/patients")


def _render_error(pid: int, errors: list[str], state: dict):
    workspace = PatientWorkspaceService().build(pid)
    if workspace is None:
        flash("بیمار یافت نشد.", "error")
        return redirect(url_for("patients.list_patients"))
    workspace["data_quality"] = PatientDataQualityService(get_db()).build(pid)
    return (
        render_template(
            "patients/workspace.html",
            active_page="patients",
            active_tab="summary",
            workspace_tabs=WORKSPACE_TABS,
            legacy_url=url_for("patients.detail", pid=pid, legacy=1),
            workspace_form_errors=errors,
            workspace_form_state={"acquisition": state},
            acquisition_sources=LEAD_SOURCES,
            **workspace,
        ),
        422,
    )


def _now_text() -> str:
    current = iran_now()
    if current.tzinfo is not None:
        current = current.replace(tzinfo=None)
    return current.replace(microsecond=0).isoformat(sep=" ", timespec="seconds")


@bp.post("/<int:pid>/workspace/acquisition")
@login_required
def update(pid: int):
    db = get_db()
    ensure_patient_acquisition_storage(db)
    state = {
        "source_code": str(request.form.get("source_code") or "").strip().upper(),
        "source_detail": str(request.form.get("source_detail") or "").strip(),
        "referrer_patient_link_id": str(
            request.form.get("referrer_patient_link_id") or ""
        ).strip(),
        "referrer_name": str(request.form.get("referrer_name") or "").strip(),
    }
    errors: list[str] = []
    source = state["source_code"]
    if source not in LEAD_SOURCES:
        errors.append("منبع جذب معتبر نیست.")

    referrer_id = None
    referrer_name = state["referrer_name"] or None
    if source == "PATIENT_REFERRAL":
        try:
            referrer_id = int(state["referrer_patient_link_id"])
        except (TypeError, ValueError):
            referrer_id = None
        if not referrer_id:
            errors.append("بیمار معرف را انتخاب کنید.")
        elif referrer_id == int(pid):
            errors.append("بیمار نمی‌تواند معرف خودش باشد.")
        else:
            referrer = db.execute(
                """SELECT id,full_name FROM patient_links
                   WHERE id=? AND is_active=1""",
                (referrer_id,),
            ).fetchone()
            if not referrer:
                errors.append("بیمار معرف فعال پیدا نشد.")
            else:
                referrer_name = str(referrer["full_name"])
    elif source == "DOCTOR_REFERRAL" and not referrer_name:
        errors.append("نام پزشک معرف را وارد کنید.")
    else:
        referrer_id = None

    patient = db.execute(
        "SELECT id FROM patient_links WHERE id=? AND is_active=1",
        (int(pid),),
    ).fetchone()
    if not patient:
        errors.append("بیمار فعال پیدا نشد.")

    if errors:
        return _render_error(pid, errors, state)

    db.execute(
        """INSERT INTO growth_patient_acquisition
           (patient_link_id,source_code,source_detail,
            referrer_patient_link_id,referrer_name,recorded_at,recorded_by)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(patient_link_id) DO UPDATE SET
             source_code=excluded.source_code,
             source_detail=excluded.source_detail,
             referrer_patient_link_id=excluded.referrer_patient_link_id,
             referrer_name=excluded.referrer_name,
             recorded_at=excluded.recorded_at,
             recorded_by=excluded.recorded_by""",
        (
            int(pid),
            source,
            state["source_detail"] or None,
            referrer_id,
            referrer_name,
            _now_text(),
            str(g.user["username"]),
        ),
    )
    db.commit()
    log_activity(
        "patient_acquisition_update",
        f"source={source} referrer_patient={referrer_id or ''}",
        patient_link_id=pid,
    )
    flash("منبع جذب بیمار ثبت شد.", "success")
    return redirect(
        url_for("patient_workspace.detail", pid=pid, tab="summary")
        + "#workspace-acquisition-editor"
    )


__all__ = ["bp"]
