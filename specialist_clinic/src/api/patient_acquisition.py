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


def _active_referrers(pid: int) -> list[dict]:
    return [
        dict(row)
        for row in get_db().execute(
            """SELECT id,full_name,phone_number,national_id
               FROM patient_links
               WHERE is_active=1 AND id<>?
               ORDER BY full_name,id LIMIT 1000""",
            (int(pid),),
        ).fetchall()
    ]


def _current_summary(pid: int, fallback: dict) -> dict:
    db = get_db()
    ensure_patient_acquisition_storage(db)
    row = db.execute(
        """SELECT acquisition.*,referrer.full_name AS referrer_patient_name
           FROM growth_patient_acquisition acquisition
           LEFT JOIN patient_links referrer
             ON referrer.id=acquisition.referrer_patient_link_id
           WHERE acquisition.patient_link_id=?""",
        (int(pid),),
    ).fetchone()
    if not row:
        return {**fallback, "attribution_source": "ENROLLMENT_FALLBACK"}
    item = dict(row)
    source = str(item.get("source_code") or "OTHER")
    referrer = (
        str(item.get("referrer_patient_name") or "").strip()
        or str(item.get("referrer_name") or "").strip()
        or None
    )
    return {
        "source_code": source,
        "source_label": LEAD_SOURCES.get(source, source),
        "source_detail": item.get("source_detail"),
        "enrolled_by": item.get("recorded_by") or fallback.get("enrolled_by"),
        "enrolled_at": item.get("recorded_at") or fallback.get("enrolled_at"),
        "referrer": referrer,
        "referrer_patient_link_id": item.get("referrer_patient_link_id"),
        "referrer_label": referrer or "ثبت نشده",
        "attribution_source": "EXPLICIT_PATIENT_ATTRIBUTION",
    }


def _render_error(pid: int, errors: list[str], state: dict):
    workspace = PatientWorkspaceService().build(pid)
    if workspace is None:
        flash("بیمار یافت نشد.", "error")
        return redirect(url_for("patients.list_patients"))
    workspace["enrollment_summary"] = _current_summary(
        pid,
        workspace.get("enrollment_summary") or {},
    )
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
            acquisition_patients=_active_referrers(pid),
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
