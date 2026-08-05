"""Low-click appointment views and booking form."""
from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlsplit

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.adapters.sqlite.patients_repo import PatientRepository
from src.api.auth import login_required
from src.common.utils import (
    format_jalali_date,
    format_jalali_datetime,
    iran_now,
    jalali_to_gregorian_str,
)
from src.services.activity_logger import log_activity
from src.services.appointment_service import AppointmentService


bp = Blueprint("appointments", __name__, url_prefix="/appointments")

APPT_TYPES = {
    "visit": "ویزیت",
    "lab": "آزمایش",
    "checkup": "چکاپ دوره‌ای",
}
STATUS_FA = {
    "scheduled": "برنامه‌ریزی‌شده",
    "done": "انجام‌شده",
    "no_show": "غیبت",
    "cancelled": "لغوشده",
}
RECURRENCE_OPTIONS = {1, 3, 6, 12}


def _safe_return_url(value: object, fallback: str) -> str:
    rendered = str(value or "").strip()
    if not rendered:
        return fallback
    parsed = urlsplit(rendered)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
        return fallback
    if not parsed.path.startswith(("/appointments", "/patients/", "/followups/unified")):
        return fallback
    return rendered


def _next_quarter_hour() -> datetime:
    current = iran_now().replace(tzinfo=None, second=0, microsecond=0)
    target = current + timedelta(minutes=15 - (current.minute % 15))
    return target.replace(second=0, microsecond=0)


def _form_defaults(source) -> dict:
    suggested = _next_quarter_hour()
    requested_type = str(source.get("appt_type") or "visit").strip().lower()
    return {
        "patient_link_id": source.get("patient_link_id", type=int),
        "date": str(
            source.get("date")
            or format_jalali_date(suggested.strftime("%Y-%m-%d"))
        ).strip(),
        "time": str(source.get("time") or suggested.strftime("%H:%M")).strip(),
        "appt_type": requested_type if requested_type in APPT_TYPES else "visit",
        "recurrence_months": str(source.get("recurrence_months") or "").strip(),
        "notes": str(source.get("notes") or "").strip(),
        "return_url": str(source.get("return_url") or "").strip(),
    }


def _render_new(*, values: dict, errors: list[str] | None = None, status: int = 200):
    patients = PatientRepository().list_patients()
    selected_patient = (
        PatientRepository().get_by_id(int(values["patient_link_id"]))
        if values.get("patient_link_id")
        else None
    )
    return (
        render_template(
            "appointments/new.html",
            patients=patients,
            appt_types=APPT_TYPES,
            recurrence_options=sorted(RECURRENCE_OPTIONS),
            form_values=values,
            selected_patient=selected_patient,
            errors=errors or [],
            active_page="appointments",
        ),
        status,
    )


@bp.get("/")
@login_required
def list_appointments():
    today = iran_now().strftime("%Y-%m-%d")
    custom_range = bool(request.args.get("from") or request.args.get("to"))
    view = str(request.args.get("view") or ("list" if custom_range else "today")).strip()
    if view not in {"today", "list"}:
        view = "today"

    if view == "today":
        date_from = date_to = today
    else:
        date_from = jalali_to_gregorian_str(request.args.get("from", "")) or today
        date_to = jalali_to_gregorian_str(request.args.get("to", "")) or (
            iran_now() + timedelta(days=30)
        ).strftime("%Y-%m-%d")

    status = request.args.get("status") or None
    if status not in STATUS_FA:
        status = None
    appointments = AppointmentRepository().list_range(date_from, date_to, status)
    for appointment in appointments:
        appointment["type_fa"] = APPT_TYPES.get(
            appointment.get("appt_type"), appointment.get("appt_type") or "—"
        )
        appointment["status_fa"] = STATUS_FA.get(
            appointment.get("status"), appointment.get("status")
        )
        appointment["scheduled_fa"] = format_jalali_datetime(
            appointment["scheduled_at"]
        )
        appointment["is_today"] = str(appointment["scheduled_at"])[:10] == today

    summary = {
        "today": sum(1 for item in appointments if item["is_today"]),
        "scheduled": sum(1 for item in appointments if item["status"] == "scheduled"),
        "done": sum(1 for item in appointments if item["status"] == "done"),
        "no_show": sum(1 for item in appointments if item["status"] == "no_show"),
        "total": len(appointments),
    }
    return render_template(
        "appointments/list.html",
        appointments=appointments,
        status_fa=STATUS_FA,
        active_page="appointments",
        summary=summary,
        active_status=status or "",
        active_view=view,
        date_from_fa=(request.args.get("from") or format_jalali_date(date_from)),
        date_to_fa=(request.args.get("to") or format_jalali_date(date_to)),
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_appointment():
    values = _form_defaults(request.form if request.method == "POST" else request.args)
    if request.method == "GET":
        return _render_new(values=values)

    errors: list[str] = []
    patient_id = values.get("patient_link_id")
    patient = PatientRepository().get_by_id(int(patient_id)) if patient_id else None
    if not patient or not bool(patient.get("is_active")):
        errors.append("بیمار فعال را انتخاب کنید.")

    date_g = jalali_to_gregorian_str(values["date"])
    if not date_g:
        errors.append("تاریخ نوبت معتبر نیست.")

    try:
        normalized_time = datetime.strptime(values["time"], "%H:%M").strftime("%H:%M")
    except ValueError:
        normalized_time = ""
        errors.append("ساعت نوبت معتبر نیست.")

    appointment_type = values["appt_type"]
    if appointment_type not in APPT_TYPES:
        errors.append("نوع نوبت معتبر نیست.")

    recurrence = None
    if values["recurrence_months"]:
        try:
            recurrence = int(values["recurrence_months"])
        except ValueError:
            recurrence = None
        if recurrence not in RECURRENCE_OPTIONS:
            errors.append("دورهٔ تکرار انتخاب‌شده معتبر نیست.")

    scheduled = None
    if date_g and normalized_time:
        scheduled = datetime.fromisoformat(f"{date_g} {normalized_time}:00")
        if scheduled <= iran_now().replace(tzinfo=None, microsecond=0):
            errors.append("زمان نوبت باید در آینده باشد.")

    if errors:
        return _render_new(values=values, errors=errors, status=400)

    appointment_id = AppointmentService().schedule(
        int(patient_id),
        scheduled_at=scheduled.isoformat(sep=" ", timespec="seconds"),
        appt_type=appointment_type,
        notes=values["notes"] or None,
        recurrence_months=recurrence,
        created_by=g.user["username"],
    )
    log_activity(
        "appointment_create",
        f"ثبت نوبت #{appointment_id}",
        patient_link_id=int(patient_id),
    )
    flash("نوبت ثبت شد؛ به مسیر قبلی برگشتید.", "success")
    fallback = url_for("appointments.list_appointments", view="today")
    return redirect(_safe_return_url(values["return_url"], fallback))


@bp.post("/<int:appt_id>/status")
@login_required
def set_status(appt_id: int):
    status = str(request.form.get("status") or "").strip()
    service = AppointmentService()
    if status == "done":
        service.mark_done(appt_id, created_by=g.user["username"])
    elif status in {"no_show", "cancelled", "scheduled"}:
        service.set_status(appt_id, status)
    else:
        flash("وضعیت نوبت معتبر نیست.", "error")
        return redirect(
            _safe_return_url(
                request.form.get("return_url"),
                url_for("appointments.list_appointments", view="today"),
            )
        )
    log_activity(
        "appointment_status",
        f"تغییر وضعیت نوبت به {STATUS_FA.get(status, status)}",
    )
    return redirect(
        _safe_return_url(
            request.form.get("return_url"),
            url_for("appointments.list_appointments", view="today"),
        )
    )
