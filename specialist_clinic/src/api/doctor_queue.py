"""Physician visit queue backed by read-only accounting invoices.

Only the accounting invoice ID and optional local appointment ID cross the HTTP boundary.
Patient identity, work date, ownership and specialist enrollment are resolved server-side.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from src.api.auth import login_required
from src.security.permissions import Permission, has_permission
from src.services.doctor_queue_service import (
    DoctorQueueIdentityError,
    DoctorQueueService,
)
from src.services.activity_logger import log_activity
from src.common.utils import jalali_to_gregorian_str, today_str

bp = Blueprint("doctor_queue", __name__, url_prefix="/doctor-queue")
VISIT_INVITE_EVENTS = {"lab_consult_invite", "bp_glucose_invite"}


def _snapshot(invoice_id: int) -> dict:
    return {"accounting_invoice_id": int(invoice_id)}


def _queue_error(exc: Exception) -> None:
    labels = {
        "ACCOUNTING_BRIDGE_UNAVAILABLE": "اتصال خواندنی حسابداری در دسترس نیست.",
        "ACCOUNTING_INVOICE_NOT_FOUND": "فاکتور حسابداری پیدا نشد.",
        "ACCOUNTING_INVOICE_NOT_OPEN": "فاکتور دیگر باز نیست.",
        "ACCOUNTING_INVOICE_OUTSIDE_ACTIVE_DAY": "فاکتور متعلق به روز فعال صف نیست.",
        "SPECIALIST_ENROLLMENT_REQUIRED": "بیمار هنوز وارد برنامهٔ تخصصی نشده است.",
        "SPECIALIST_VISIT_NOT_STARTED": "ابتدا ویزیت را از صف شروع کنید.",
        "SPECIALIST_VISIT_NOT_ACTIVE": "این Encounter دیگر فعال نیست.",
        "SPECIALIST_APPOINTMENT_NOT_FOUND": "نوبت انتخاب‌شده پیدا نشد.",
        "SPECIALIST_APPOINTMENT_PATIENT_MISMATCH": "نوبت انتخاب‌شده متعلق به این بیمار نیست.",
        "SPECIALIST_APPOINTMENT_NOT_SCHEDULED": "نوبت انتخاب‌شده دیگر در وضعیت برنامه‌ریزی‌شده نیست.",
        "SPECIALIST_APPOINTMENT_DATE_MISMATCH": "نوبت انتخاب‌شده متعلق به روز فعال صف نیست.",
        "ENCOUNTER_ALREADY_LINKED_TO_ANOTHER_APPOINTMENT": "این Encounter قبلاً به نوبت دیگری متصل شده است.",
        "APPOINTMENT_ALREADY_LINKED_TO_ANOTHER_ENCOUNTER": "این نوبت قبلاً به Encounter دیگری متصل شده است.",
        "journey attribution requires a positive response event": "پاسخ انتخاب‌شده مثبت و معتبر نیست.",
        "journey attribution requires the latest campaign response": "پاسخ انتخاب‌شده آخرین پاسخ بیمار نیست.",
        "campaign journey patient mismatch": "پاسخ کمپین متعلق به این بیمار نیست.",
        "campaign response is already attributed to another journey": "این پاسخ قبلاً به Journey دیگری متصل شده است.",
    }
    flash(labels.get(str(exc), f"عملیات متوقف شد: {exc}"), "error")


@bp.route("/")
@login_required
def index():
    data = DoctorQueueService().queue()
    return render_template(
        "doctor_queue/queue.html", active_page="doctor_queue", **data
    )


@bp.route("/<int:invoice_id>/start", methods=["POST"])
@login_required
def start(invoice_id):
    try:
        response_event_id = request.form.get(
            "campaign_response_event_id", type=int
        )
        if response_event_id and not has_permission(
            Permission.SMS_CAMPAIGN_ATTRIBUTION_RECORD
        ):
            raise DoctorQueueIdentityError(
                "مجوز ثبت انتساب کمپین برای این کاربر وجود ندارد."
            )
        visit = DoctorQueueService().start(
            _snapshot(invoice_id),
            actor_username=g.user["username"],
            appointment_id=request.form.get("appointment_id", type=int),
            campaign_response_event_id=response_event_id,
        )
        appointment_text = (
            f" appointment={visit['appointment_id']}"
            if visit.get("appointment_id")
            else " walk-in"
        )
        response_text = (
            f" campaign_response={visit['campaign_response_event_id']}"
            if visit.get("campaign_response_event_id") else ""
        )
        log_activity(
            "visit_start",
            f"شروع ویزیت فاکتور #{invoice_id}{appointment_text}{response_text}",
            patient_link_id=visit.get("patient_link_id"),
        )
        return redirect(url_for("doctor_queue.visit", invoice_id=invoice_id))
    except Exception as exc:
        _queue_error(exc)
        return redirect(url_for("doctor_queue.index"))


@bp.route("/<int:invoice_id>/done", methods=["POST"])
@login_required
def done(invoice_id):
    try:
        visit = DoctorQueueService().end_visit(
            _snapshot(invoice_id),
            g.user["username"],
            notes=request.form.get("notes") or None,
        )
        log_activity(
            "visit_done",
            f"پایان ویزیت فاکتور #{invoice_id} encounter={visit.get('encounter_id')}",
            patient_link_id=visit.get("patient_link_id"),
        )
    except Exception as exc:
        _queue_error(exc)
    return redirect(url_for("doctor_queue.index"))


@bp.route("/<int:invoice_id>/invite", methods=["POST"])
@login_required
def invite(invoice_id):
    event_key = request.form.get("event_key") or ""
    if event_key not in VISIT_INVITE_EVENTS:
        flash("نوع دعوت نامعتبر است.", "error")
        return redirect(url_for("doctor_queue.index"))
    try:
        snapshot = DoctorQueueService().active_visit_snapshot(invoice_id)
    except Exception as exc:
        _queue_error(exc)
        return redirect(url_for("doctor_queue.index"))

    from src.services.engagement_service import EngagementService

    aid = EngagementService().enqueue_event_for_patient(
        snapshot["patient_link_id"],
        event_key,
        period_key=f"{event_key}:{today_str()}:{invoice_id}",
    )
    if aid:
        log_activity(
            "visit_invite_event",
            f"دعوت «{event_key}» از Encounter فاکتور #{invoice_id}",
            patient_link_id=snapshot["patient_link_id"],
        )
        flash("دعوت در صف تأیید پیامک ثبت شد.", "success")
    else:
        flash(
            "دعوت ثبت نشد؛ وضعیت شماره، انصراف، تکرار یا cooldown را بررسی کنید.",
            "warning",
        )
    return redirect(url_for("doctor_queue.visit", invoice_id=invoice_id))


@bp.route("/<int:invoice_id>/visit")
@login_required
def visit(invoice_id):
    try:
        snapshot = DoctorQueueService().active_visit_snapshot(invoice_id)
    except Exception as exc:
        _queue_error(exc)
        return redirect(url_for("doctor_queue.index"))

    pid = snapshot["patient_link_id"]
    from src.services.patient_service import PatientService
    from src.adapters.sqlite.vitals_repo import VitalsRepository, VITAL_TYPES
    from src.adapters.sqlite.record_repo import RecordRepository
    from src.adapters.sqlite.followups_repo import FollowupRepository
    from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository

    profile = PatientService().get_full_profile(pid)
    rules = ClinicalRulesRepository()
    codes = [
        condition.get("condition_code")
        for condition in profile["conditions"]
        if condition.get("condition_code")
    ]
    entry_indicators = [
        indicator for indicator in rules.for_conditions(codes)
        if indicator.get("is_vital")
    ]
    indicator_labels = {
        indicator["key"]: indicator
        for indicator in rules.all_indicators(active_only=False)
    }
    recent_vitals = VitalsRepository().get_readings(pid, limit=8)
    for vital in recent_vitals:
        metadata = indicator_labels.get(vital["type"]) or VITAL_TYPES.get(
            vital["type"], {}
        )
        vital["type_label"] = metadata.get("label", vital["type"])
    notes = RecordRepository().list_notes(pid, "exam")
    open_followups = [
        task for task in FollowupRepository().list_for_patient(pid)
        if task.get("status") == "open"
    ]
    return render_template(
        "doctor_queue/visit_quick.html",
        active_page="doctor_queue",
        invoice_id=invoice_id,
        nid=snapshot.get("national_id"),
        pid=pid,
        work_date=snapshot["work_date"],
        encounter_id=snapshot["encounter_id"],
        journey_id=snapshot["journey_id"],
        appointment_id=snapshot.get("appointment_id"),
        patient=profile["patient"],
        conditions=profile["conditions"],
        medications=profile["medications"],
        allergies=profile["allergies"],
        entry_indicators=entry_indicators,
        recent_vitals=recent_vitals,
        last_note=(notes[0] if notes else None),
        open_followups=open_followups,
    )


@bp.route("/<int:invoice_id>/save", methods=["POST"])
@login_required
def save(invoice_id):
    try:
        snapshot = DoctorQueueService().active_visit_snapshot(invoice_id)
    except Exception as exc:
        _queue_error(exc)
        return redirect(url_for("doctor_queue.index"))

    pid = snapshot["patient_link_id"]
    from src.adapters.sqlite.vitals_repo import VitalsRepository, VITAL_TYPES
    from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository
    from src.adapters.sqlite.record_repo import RecordRepository

    measured = jalali_to_gregorian_str(request.form.get("measured_date", ""))
    measured_at = f"{measured} 12:00:00" if measured else None
    indicators = ClinicalRulesRepository().as_map()
    keys = set(indicators) | set(VITAL_TYPES)
    parsed: list[tuple[str, float, str | None]] = []
    invalid: list[str] = []
    for vital_type in keys:
        raw = (request.form.get(vital_type, "") or "").strip()
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            invalid.append(vital_type)
            continue
        unit = (indicators.get(vital_type) or {}).get("unit") or (
            VITAL_TYPES.get(vital_type, {}).get("unit")
        )
        parsed.append((vital_type, value, unit))
    if invalid:
        flash(
            "مقادیر نامعتبر ثبت نشدند: " + "، ".join(sorted(invalid)),
            "error",
        )
        return redirect(url_for("doctor_queue.visit", invoice_id=invoice_id))

    vitals = VitalsRepository()
    for vital_type, value, unit in parsed:
        vitals.add_reading(
            pid,
            vtype=vital_type,
            value=value,
            unit=unit,
            measured_at=measured_at,
            recorded_by=g.user["username"],
        )
    note = (request.form.get("note") or "").strip()
    if note:
        RecordRepository().add_note(
            pid, "exam", note, recorded_by=g.user["username"]
        )
    if parsed or note:
        log_activity(
            "visit_save",
            f"ثبت {len(parsed)} شاخص + یادداشت Encounter",
            patient_link_id=pid,
        )
        flash("اطلاعات ویزیت ثبت شد.", "success")
    return redirect(url_for("doctor_queue.visit", invoice_id=invoice_id))
