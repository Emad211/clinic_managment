"""Operational lead pipeline for patient acquisition and conversion."""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.leads_repo import LeadRepository
from src.common.utils import jalali_to_gregorian_str
from src.security.permissions import Permission, permission_required
from src.services.activity_logger import log_activity
from src.services.lead_pipeline_service import (
    LEAD_INTERESTS,
    LEAD_LOST_REASONS,
    LEAD_SOURCES,
    LEAD_STATUS_LABELS,
    LeadPipelineError,
    LeadPipelineService,
)


bp = Blueprint("leads", __name__, url_prefix="/leads")


def _datetime_from_form(prefix: str) -> str | None:
    date_value = str(request.form.get(f"{prefix}_date") or "").strip()
    time_value = str(request.form.get(f"{prefix}_time") or "").strip() or "09:00"
    if not date_value:
        return None
    converted = jalali_to_gregorian_str(date_value)
    if not converted:
        raise LeadPipelineError("تاریخ واردشده معتبر نیست.")
    try:
        normalized_time = datetime.strptime(time_value, "%H:%M").strftime("%H:%M")
    except ValueError as exc:
        raise LeadPipelineError("ساعت واردشده معتبر نیست.") from exc
    return f"{converted} {normalized_time}:00"


def _active_users() -> list[dict]:
    return [
        dict(row)
        for row in get_db().execute(
            """SELECT username,full_name,role FROM users
               WHERE is_active=1 ORDER BY full_name,username"""
        ).fetchall()
    ]


def _index_context(*, form_state=None, errors=None) -> dict:
    status = str(request.args.get("status") or "").strip().upper() or None
    if status and status not in LEAD_STATUS_LABELS:
        status = None
    owner = str(request.args.get("owner") or "").strip() or None
    query = str(request.args.get("q") or "").strip() or None
    data = LeadPipelineService(get_db()).dashboard(
        status=status,
        owner_username=owner,
        query=query,
    )
    return {
        **data,
        "status_filter": status or "",
        "owner_filter": owner or "",
        "query": query or "",
        "sources": LEAD_SOURCES,
        "interests": LEAD_INTERESTS,
        "status_labels": LEAD_STATUS_LABELS,
        "lost_reasons": LEAD_LOST_REASONS,
        "users": _active_users(),
        "form_state": form_state or {},
        "form_errors": errors or [],
        "active_page": "leads",
    }


@bp.get("/")
@permission_required(Permission.PATIENT_VIEW)
def index():
    return render_template("leads/index.html", **_index_context())


@bp.post("/")
@permission_required(Permission.PATIENT_EDIT)
def create():
    state = {
        "full_name": str(request.form.get("full_name") or "").strip(),
        "phone_number": str(request.form.get("phone_number") or "").strip(),
        "national_id": str(request.form.get("national_id") or "").strip(),
        "source_code": str(request.form.get("source_code") or "").strip(),
        "source_detail": str(request.form.get("source_detail") or "").strip(),
        "referrer_name": str(request.form.get("referrer_name") or "").strip(),
        "interest_code": str(request.form.get("interest_code") or "").strip(),
        "owner_username": str(request.form.get("owner_username") or "").strip(),
        "next_action_date": str(request.form.get("next_action_date") or "").strip(),
        "next_action_time": str(request.form.get("next_action_time") or "").strip(),
        "notes": str(request.form.get("notes") or "").strip(),
    }
    try:
        lead = LeadPipelineService(get_db()).create(
            full_name=state["full_name"],
            phone_number=state["phone_number"],
            national_id=state["national_id"] or None,
            source_code=state["source_code"],
            source_detail=state["source_detail"] or None,
            referrer_name=state["referrer_name"] or None,
            interest_code=state["interest_code"] or None,
            owner_username=state["owner_username"] or str(g.user["username"]),
            next_action_at=_datetime_from_form("next_action"),
            notes=state["notes"] or None,
            actor_username=str(g.user["username"]),
        )
    except LeadPipelineError as exc:
        return (
            render_template(
                "leads/index.html",
                **_index_context(form_state=state, errors=[str(exc)]),
            ),
            422,
        )

    if lead.get("duplicate"):
        flash("این شماره یک سرنخ باز دارد؛ همان پرونده باز شد.", "warning")
    else:
        log_activity(
            "lead_create",
            f"lead={lead['id']} source={lead['source_code']}",
        )
        flash("سرنخ ثبت شد و موعد پیگیری برای آن ساخته شد.", "success")
    return redirect(url_for("leads.detail", lead_id=int(lead["id"])))


@bp.get("/<int:lead_id>")
@permission_required(Permission.PATIENT_VIEW)
def detail(lead_id: int):
    repository = LeadRepository(get_db())
    lead = repository.get(lead_id)
    if not lead:
        flash("سرنخ پیدا نشد.", "error")
        return redirect(url_for("leads.index"))
    return render_template(
        "leads/detail.html",
        lead=lead,
        events=repository.list_events(lead_id),
        sources=LEAD_SOURCES,
        interests=LEAD_INTERESTS,
        status_labels=LEAD_STATUS_LABELS,
        lost_reasons=LEAD_LOST_REASONS,
        users=_active_users(),
        active_page="leads",
    )


@bp.post("/<int:lead_id>/transition")
@permission_required(Permission.PATIENT_EDIT)
def transition(lead_id: int):
    target = str(request.form.get("to_status") or "").strip().upper()
    try:
        lead = LeadPipelineService(get_db()).transition(
            lead_id,
            to_status=target,
            actor_username=str(g.user["username"]),
            next_action_at=_datetime_from_form("next_action"),
            appointment_at=_datetime_from_form("appointment"),
            lost_reason=request.form.get("lost_reason") or None,
            note=request.form.get("note") or None,
            owner_username=request.form.get("owner_username") or None,
        )
    except LeadPipelineError as exc:
        flash(str(exc), "error")
        return redirect(url_for("leads.detail", lead_id=lead_id))

    log_activity(
        "lead_transition",
        f"lead={lead_id} status={lead['status']}",
    )
    flash("مرحله سرنخ و اقدام بعدی ثبت شد.", "success")
    return redirect(url_for("leads.detail", lead_id=lead_id))


@bp.post("/<int:lead_id>/convert")
@permission_required(Permission.PATIENT_EDIT)
def convert(lead_id: int):
    try:
        result = LeadPipelineService(get_db()).convert(
            lead_id,
            actor_username=str(g.user["username"]),
        )
    except LeadPipelineError as exc:
        flash(str(exc), "error")
        return redirect(url_for("leads.detail", lead_id=lead_id))

    log_activity(
        "lead_convert",
        f"lead={lead_id} patient={result['patient_link_id']}",
        patient_link_id=int(result["patient_link_id"]),
    )
    flash("سرنخ به بیمار تبدیل شد و سابقه منبع جذب حفظ شد.", "success")
    return redirect(
        url_for(
            "patient_workspace.detail",
            pid=int(result["patient_link_id"]),
            tab="summary",
        )
    )


def lead_context() -> dict:
    if not getattr(g, "user", None):
        return {"lead_open_count": 0, "lead_due_count": 0}
    try:
        service = LeadPipelineService(get_db())
        data = service.dashboard()
    except Exception:
        return {"lead_open_count": 0, "lead_due_count": 0}
    return {
        "lead_open_count": int(data["counts"].get("OPEN", 0)),
        "lead_due_count": int(data["due_count"]),
    }


__all__ = ["bp", "lead_context"]
