"""Appointment waitlist and cancellation-slot fill routes."""
from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from src.adapters.sqlite.core import get_db
from src.common.utils import jalali_to_gregorian_str
from src.security.permissions import Permission, permission_required
from src.services.activity_logger import log_activity
from src.services.growth_waitlist_service import (
    GrowthWaitlistError,
    GrowthWaitlistService,
    TIME_WINDOWS,
    WAITLIST_STATUS_LABELS,
)


bp = Blueprint("growth_waitlist", __name__, url_prefix="/growth/waitlist")


def _patients() -> list[dict]:
    return [
        dict(row)
        for row in get_db().execute(
            """SELECT id,full_name,phone_number,national_id
               FROM patient_links WHERE is_active=1
               ORDER BY full_name,id LIMIT 1000"""
        ).fetchall()
    ]


def _users() -> list[dict]:
    return [
        dict(row)
        for row in get_db().execute(
            """SELECT username,full_name FROM users
               WHERE is_active=1 ORDER BY full_name,username"""
        ).fetchall()
    ]


@bp.get("/")
@permission_required(Permission.PATIENT_VIEW)
def index():
    status = str(request.args.get("status") or "").strip().upper() or None
    if status and status not in WAITLIST_STATUS_LABELS:
        status = None
    patient_id = request.args.get("patient_id", type=int)
    service = GrowthWaitlistService(get_db())
    return render_template(
        "growth/waitlist.html",
        active_page="growth",
        selected_patient_id=patient_id,
        status_filter=status or "",
        patients=_patients(),
        users=_users(),
        time_windows=TIME_WINDOWS,
        status_labels=WAITLIST_STATUS_LABELS,
        **service.dashboard(status=status),
    )


@bp.post("/")
@permission_required(Permission.PATIENT_EDIT)
def create():
    patient_id = request.form.get("patient_link_id", type=int)
    start_raw = str(request.form.get("date_from") or "").strip()
    end_raw = str(request.form.get("date_to") or "").strip()
    try:
        entry = GrowthWaitlistService(get_db()).create_entry(
            patient_link_id=int(patient_id or 0),
            appt_type=request.form.get("appt_type") or "visit",
            date_from=jalali_to_gregorian_str(start_raw) if start_raw else None,
            date_to=jalali_to_gregorian_str(end_raw) if end_raw else None,
            time_window=request.form.get("time_window") or "ANY",
            auto_fill=request.form.get("auto_fill") == "1",
            priority=request.form.get("priority", type=int) or 100,
            notes=request.form.get("notes") or None,
            created_by=str(g.user["username"]),
        )
    except (GrowthWaitlistError, ValueError) as exc:
        flash(str(exc), "error")
        return redirect(
            url_for("growth_waitlist.index", patient_id=patient_id or None)
        )
    if entry.get("duplicate"):
        flash("این بیمار از قبل ورودی فعال در صف انتظار دارد.", "warning")
    else:
        log_activity(
            "waitlist_add",
            f"entry={entry['id']} patient={entry['patient_link_id']}",
            patient_link_id=int(entry["patient_link_id"]),
        )
        flash("بیمار به صف انتظار افزوده شد.", "success")
    return redirect(url_for("growth_waitlist.index"))


@bp.post("/fill")
@permission_required(Permission.FOLLOWUP_ADMIN_MANAGE)
def fill_slots():
    assigned_to = str(request.form.get("assigned_to") or "").strip() or None
    result = GrowthWaitlistService(get_db()).fill_cancelled_slots(
        actor_username=str(g.user["username"]),
        assigned_to=assigned_to,
    )
    log_activity(
        "waitlist_fill_slots",
        (
            f"auto={result['auto_booked']} offers={result['offers']} "
            f"unmatched={result['unmatched']}"
        ),
    )
    flash(
        (
            f"{result['auto_booked']} نوبت خودکار ثبت و "
            f"{result['offers']} پیشنهاد برای تماس ساخته شد."
        ),
        "success" if result["auto_booked"] or result["offers"] else "info",
    )
    return redirect(url_for("growth_waitlist.index"))


@bp.post("/<int:entry_id>/book")
@permission_required(Permission.FOLLOWUP_BOOK_APPOINTMENT)
def book_offer(entry_id: int):
    try:
        result = GrowthWaitlistService(get_db()).book_offered_entry(
            entry_id,
            actor_username=str(g.user["username"]),
        )
    except GrowthWaitlistError as exc:
        flash(str(exc), "error")
        return redirect(url_for("growth_waitlist.index"))
    log_activity(
        "waitlist_offer_booked",
        f"entry={entry_id} appointment={result['appointment_id']}",
        patient_link_id=int(result["patient_link_id"]),
    )
    flash("Slot پیشنهادی به نوبت قطعی تبدیل شد.", "success")
    return redirect(
        url_for(
            "patient_workspace.detail",
            pid=int(result["patient_link_id"]),
            tab="encounters",
        )
    )


@bp.post("/<int:entry_id>/cancel")
@permission_required(Permission.PATIENT_EDIT)
def cancel(entry_id: int):
    try:
        GrowthWaitlistService(get_db()).cancel_entry(entry_id)
    except GrowthWaitlistError as exc:
        flash(str(exc), "error")
    else:
        flash("ورودی صف انتظار لغو شد.", "success")
    return redirect(url_for("growth_waitlist.index"))


__all__ = ["bp"]
