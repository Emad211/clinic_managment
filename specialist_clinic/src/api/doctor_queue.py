"""Physician visit queue backed by read-only accounting invoices.

Only the accounting invoice ID and optional local appointment ID cross the HTTP boundary.
Patient identity, work date, ownership and specialist enrollment are resolved server-side.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from src.api.auth import login_required
from src.security.permissions import (
    Permission,
    has_permission,
    permission_required,
)
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


def _commitments_from_form() -> list[dict]:
    keys = request.form.getlist("commitment_client_key")
    kinds = request.form.getlist("commitment_type")
    instructions = request.form.getlist("commitment_instruction")
    dates = request.form.getlist("commitment_due_date")
    times = request.form.getlist("commitment_due_time")
    fulfillments = request.form.getlist("commitment_fulfillment")
    assignees = request.form.getlist("commitment_assigned_to")
    width = max(
        len(keys), len(kinds), len(instructions), len(dates), len(times),
        len(fulfillments), len(assignees), 0,
    )
    output: list[dict] = []
    for index in range(width):
        def at(values, default=""):
            return values[index] if index < len(values) else default
        raw = {
            "client_key": at(keys).strip(),
            "commitment_type": at(kinds).strip(),
            "instruction": at(instructions).strip(),
            "due_date": at(dates).strip(),
            "due_time": at(times, "09:00").strip() or "09:00",
            "fulfillment": at(fulfillments, "remote").strip() or "remote",
            "assigned_to": at(assignees).strip(),
        }
        if not any(
            raw[field]
            for field in ("client_key", "commitment_type", "instruction", "due_date", "assigned_to")
        ):
            continue
        if not all(
            raw[field]
            for field in ("client_key", "commitment_type", "instruction", "due_date")
        ):
            raise ValueError(
                f"ردیف تعهد {index + 1} ناقص است؛ نوع، دستور و موعد الزامی‌اند."
            )
        due_day = jalali_to_gregorian_str(raw["due_date"])
        if not due_day:
            raise ValueError(f"تاریخ تعهد {index + 1} نامعتبر است.")
        try:
            from datetime import datetime
            due = datetime.fromisoformat(f"{due_day} {raw['due_time']}:00")
        except ValueError as exc:
            raise ValueError(f"زمان تعهد {index + 1} نامعتبر است.") from exc
        output.append(
            {
                "client_key": raw["client_key"],
                "commitment_type": raw["commitment_type"],
                "instruction": raw["instruction"],
                "due_at": due.isoformat(sep=" ", timespec="seconds"),
                "fulfillment": raw["fulfillment"],
                "assigned_to": raw["assigned_to"] or None,
            }
        )
    return output


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
        "SIGNED_ENCOUNTER_DOCUMENT_REQUIRED": "برای پایان ویزیت، ابتدا سند Encounter را کامل و امضا کنید.",
        "ENCOUNTER_NOT_ACTIVE_FOR_DOCUMENTATION": "Encounter برای ثبت یا امضای سند فعال نیست.",
        "ENCOUNTER_NOT_COMPLETED_FOR_AMENDMENT": "اصلاح سند فقط پس از تکمیل Encounter مجاز است.",
        "STALE_ENCOUNTER_DOCUMENT": "نسخه سند تغییر کرده است؛ صفحه را تازه کنید.",
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
            require_documentation=True,
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
    from src.adapters.sqlite.encounter_documentation_repo import (
        EncounterDocumentationRepository,
    )
    document_repository = EncounterDocumentationRepository()
    current_document = document_repository.current_document(
        snapshot["encounter_id"]
    )
    document_history = document_repository.history(snapshot["encounter_id"])
    if current_document:
        import json
        current_document["problems"] = json.loads(
            current_document.get("problems_json") or "[]"
        )
        current_document["commitments"] = json.loads(
            current_document.get("commitments_json") or "[]"
        )
    outcome_labels = {
        "STABLE_CONTINUE": "پایدار؛ ادامه برنامه فعلی",
        "PLAN_CHANGED": "برنامه درمانی تغییر کرد",
        "FOLLOWUP_REQUIRED": "پیگیری لازم است",
        "REFERRED": "ارجاع انجام شد",
        "URGENT_ESCALATION": "اقدام یا ارجاع فوری",
        "OTHER": "سایر",
    }
    import uuid
    document_request_id = uuid.uuid4().hex
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
        current_document=current_document,
        document_history=document_history,
        outcome_labels=outcome_labels,
        document_request_id=document_request_id,
    )


@bp.route("/<int:invoice_id>/save", methods=["POST"])
@permission_required(Permission.CLINICAL_DOCUMENT_WRITE)
def save(invoice_id):
    import uuid
    from src.adapters.sqlite.vitals_repo import VITAL_TYPES
    from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository
    from src.adapters.sqlite.encounter_documentation_repo import (
        EncounterDocumentationConflict,
        EncounterDocumentationValidationError,
    )
    from src.services.encounter_documentation_service import (
        EncounterDocumentationService,
        EncounterDocumentationStateError,
    )

    requested_action = str(request.form.get("action") or "draft").lower()
    requested_id = request.form.get("document_request_id") or ""
    try:
        snapshot = DoctorQueueService().active_visit_snapshot(invoice_id)
    except Exception as exc:
        if requested_action == "sign" and requested_id:
            from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
            from src.adapters.sqlite.encounter_documentation_repo import (
                EncounterDocumentationRepository,
            )
            encounter = CareJourneyRepository().encounter_for_invoice(invoice_id)
            existing = (
                EncounterDocumentationRepository().document_by_idempotency(
                    f"encounter-document:sign:{encounter['encounter_id']}:{requested_id}"
                )
                if encounter else None
            )
            current = (
                CareJourneyRepository().current_encounter_event(
                    encounter["encounter_id"]
                )
                if encounter else None
            )
            if (
                existing and existing["document_status"] == "SIGNED"
                and current and current["event_type"] == "COMPLETED"
            ):
                flash("این درخواست قبلاً با موفقیت امضا و تکمیل شده است.", "success")
                return redirect(url_for("doctor_queue.index"))
        _queue_error(exc)
        return redirect(url_for("doctor_queue.index"))

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

    document = {
        "chief_complaint": request.form.get("chief_complaint"),
        "objective_findings": request.form.get("objective_findings"),
        "assessment": request.form.get("assessment"),
        "plan": request.form.get("plan"),
        "followup_instructions": request.form.get("followup_instructions"),
        "problems": request.form.get("problems"),
        "outcome_code": request.form.get("outcome_code"),
        "commitments": _commitments_from_form(),
    }
    action = str(request.form.get("action") or "draft").lower()
    request_id = (
        request.form.get("document_request_id") or uuid.uuid4().hex
    )
    expected = request.form.get("expected_current_event_id", type=int)
    service = EncounterDocumentationService()
    try:
        if action == "sign":
            result = service.sign_and_complete(
                visit_snapshot=snapshot,
                document=document,
                readings=parsed,
                measured_at=measured_at,
                actor_username=g.user["username"],
                actor_user_id=int(g.user["id"]),
                idempotency_key=(
                    f"encounter-document:sign:{snapshot['encounter_id']}:{request_id}"
                ),
                expected_current_event_id=expected,
            )
            log_activity(
                "encounter_document_sign",
                f"signed document={result['document']['id']} encounter={snapshot['encounter_id']}",
                patient_link_id=snapshot["patient_link_id"],
            )
            flash("سند Encounter امضا و ویزیت تکمیل شد.", "success")
            return redirect(url_for("doctor_queue.index"))
        result = service.save_draft_with_vitals(
            visit_snapshot=snapshot,
            document=document,
            readings=parsed,
            measured_at=measured_at,
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            idempotency_key=(
                f"encounter-document:draft:{snapshot['encounter_id']}:{request_id}"
            ),
            expected_current_event_id=expected,
        )
        log_activity(
            "encounter_document_draft",
            f"draft document={result['document']['id']} encounter={snapshot['encounter_id']}",
            patient_link_id=snapshot["patient_link_id"],
        )
        flash("پیش‌نویس سند و شاخص‌ها به‌صورت اتمیک ذخیره شد.", "success")
    except (
        EncounterDocumentationConflict,
        EncounterDocumentationValidationError,
        EncounterDocumentationStateError,
        ValueError,
        LookupError,
    ) as exc:
        _queue_error(exc)
    return redirect(url_for("doctor_queue.visit", invoice_id=invoice_id))


@bp.get("/<int:invoice_id>/document")
@login_required
def document_detail(invoice_id: int):
    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.adapters.sqlite.encounter_documentation_repo import (
        EncounterDocumentationRepository,
    )

    try:
        snapshot = DoctorQueueService().canonical_snapshot(invoice_id)
        encounter = CareJourneyRepository().encounter_for_invoice(invoice_id)
        if not encounter:
            raise LookupError("encounter not found")
        repository = EncounterDocumentationRepository()
        current = repository.current_document(encounter["encounter_id"])
        if not current:
            raise LookupError("encounter document not found")
        import json
        current["problems"] = json.loads(current.get("problems_json") or "[]")
        current["commitments"] = json.loads(
            current.get("commitments_json") or "[]"
        )
        history = repository.history(encounter["encounter_id"])
    except Exception as exc:
        _queue_error(exc)
        return redirect(url_for("doctor_queue.index"))
    return render_template(
        "doctor_queue/document_detail.html",
        active_page="doctor_queue",
        invoice_id=invoice_id,
        snapshot=snapshot,
        encounter=encounter,
        document=current,
        history=history,
        outcome_labels={
            "STABLE_CONTINUE": "پایدار؛ ادامه برنامه فعلی",
            "PLAN_CHANGED": "برنامه درمانی تغییر کرد",
            "FOLLOWUP_REQUIRED": "پیگیری لازم است",
            "REFERRED": "ارجاع انجام شد",
            "URGENT_ESCALATION": "اقدام یا ارجاع فوری",
            "OTHER": "سایر",
        },
    )


@bp.post("/<int:invoice_id>/document/amend")
@permission_required(Permission.CLINICAL_DOCUMENT_AMEND)
def amend_document(invoice_id: int):
    import uuid
    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.adapters.sqlite.encounter_documentation_repo import (
        EncounterDocumentationConflict,
        EncounterDocumentationValidationError,
    )
    from src.services.encounter_documentation_service import (
        EncounterDocumentationService,
        EncounterDocumentationStateError,
    )

    encounter = CareJourneyRepository().encounter_for_invoice(invoice_id)
    if not encounter:
        flash("Encounter یافت نشد.", "error")
        return redirect(url_for("doctor_queue.index"))
    document = {
        "chief_complaint": request.form.get("chief_complaint"),
        "objective_findings": request.form.get("objective_findings"),
        "assessment": request.form.get("assessment"),
        "plan": request.form.get("plan"),
        "followup_instructions": request.form.get("followup_instructions"),
        "problems": request.form.get("problems"),
        "outcome_code": request.form.get("outcome_code"),
    }
    try:
        event = EncounterDocumentationService().amend_completed_document(
            encounter_id=encounter["encounter_id"],
            document=document,
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            idempotency_key=(
                request.form.get("idempotency_key")
                or f"encounter-document:amend:{encounter['encounter_id']}:{uuid.uuid4().hex}"
            ),
            expected_current_event_id=request.form.get(
                "expected_current_event_id", type=int
            ),
            amendment_reason=request.form.get("amendment_reason") or "",
        )
    except (
        EncounterDocumentationConflict,
        EncounterDocumentationValidationError,
        EncounterDocumentationStateError,
        ValueError,
        LookupError,
    ) as exc:
        _queue_error(exc)
    else:
        log_activity(
            "encounter_document_amend",
            f"amended document={event['id']} encounter={encounter['encounter_id']}",
            patient_link_id=encounter["patient_link_id"],
        )
        flash("اصلاحیهٔ سند با حفظ نسخه‌های قبلی ثبت شد.", "success")
    return redirect(url_for("doctor_queue.document_detail", invoice_id=invoice_id))
