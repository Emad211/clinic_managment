"""Structured patient-record aggregate for Halqe.

This service is a faithful PostgreSQL port of the descriptive record owned by
``specialist_clinic``: chronic conditions, medications and medication events,
typed clinical flags, medical/surgical history, free-text record notes, labs,
appointments, follow-ups and prescription history.

Safety invariants
-----------------
* every query is explicitly ``tenant_id`` + ``patient_link_id`` scoped;
* the tenant GUC is set before ORM access so PostgreSQL RLS is active;
* multi-row writes use ``transaction.atomic`` and ``select_for_update``;
* medication state and its timeline event commit or roll back together;
* partial flag updates touch only submitted keys; a blank date never erases a
  stored date unless that key is listed in ``clear_keys``;
* every state change appends a best-effort clinical audit row after the main
  transaction has committed, so an audit failure cannot poison the transaction.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional

from django.db import connection, transaction
from django.utils import timezone

from clinical.audit import log_activity
from clinical.models import (
    Appointment,
    Condition,
    FollowupTask,
    LabResult,
    PatientCondition,
    PatientFlag,
    PatientLink,
    PatientMedication,
    Prescription,
    PrescriptionItem,
)
from clinical.record_models import (
    ClinicalNote,
    DrugCatalog,
    DrugClass,
    FlagCatalog,
    LabTestCatalog,
    MedicalHistory,
    MedicationEvent,
    SurgeryHistory,
)
from platform_core.tenant_context import set_tenant_guc


# ---------------------------------------------------------------------------
# Stable domain errors — the API maps these to 404 / 409 / 422.
# ---------------------------------------------------------------------------
class PatientRecordError(Exception):
    pass


class PatientRecordValidationError(PatientRecordError):
    pass


class PatientRecordNotFound(PatientRecordError):
    pass


class PatientRecordConflict(PatientRecordError):
    pass


ALLOWED_REFILL_INTERVALS = frozenset({15, 30, 60, 90})
ALLOWED_FLAG_TYPES = frozenset({"bool", "enum", "date", "text"})


def _clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_text(value: Any, label: str) -> str:
    text = _clean(value)
    if not text:
        raise PatientRecordValidationError(f"{label} الزامی است.")
    return text


def _actor_fields(actor_username: Optional[str], actor_id: Optional[int]):
    return actor_username or "unknown", actor_id


def _set_scope(tenant_id: int) -> None:
    if not isinstance(tenant_id, int) or tenant_id <= 0:
        raise PatientRecordValidationError("tenant_id نامعتبر است.")
    set_tenant_guc(tenant_id)


def _ensure_patient(*, tenant_id: int, patient_link_id: int) -> PatientLink:
    try:
        return PatientLink.objects.get(
            tenant_id=tenant_id,
            id=patient_link_id,
            is_active=True,
        )
    except PatientLink.DoesNotExist as exc:
        raise PatientRecordNotFound("پروندهٔ بالینی بیمار پیدا نشد.") from exc


def _audit(
    *,
    tenant_id: int,
    patient_link_id: int,
    actor_username: Optional[str],
    actor_id: Optional[int],
    action_type: str,
    target_table: str,
    target_id: Optional[int],
    description: Optional[str] = None,
) -> None:
    """Audit after the state transaction, preventing a failed audit from aborting it."""
    log_activity(
        tenant_id=tenant_id,
        user_id=actor_id,
        username=actor_username,
        action_type=action_type,
        action_category="patient_record",
        description=description,
        target_table=target_table,
        target_id=target_id,
        patient_link_id=patient_link_id,
    )


def _parse_options(raw: Optional[str]) -> list[dict[str, str]]:
    """Parse legacy ``value|label,value|label`` flag options faithfully."""
    result: list[dict[str, str]] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        value, separator, label = part.partition("|")
        value = value.strip()
        label = label.strip() if separator else value
        if value:
            result.append({"value": value, "label": label or value})
    return result


def _parse_doses(raw: Optional[str]) -> list[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def _decimal_to_text(value: Optional[Decimal]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.normalize()
    return format(normalized, "f")


def _legacy_prescription_items(raw: Any) -> list[dict[str, Any]]:
    """Normalize the legacy JSONB snapshot into the structured output shape."""
    if not raw:
        return []
    if isinstance(raw, dict):
        candidates = raw.get("items") if isinstance(raw.get("items"), list) else [raw]
    elif isinstance(raw, list):
        candidates = raw
    else:
        return []
    result = []
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        name = _clean(item.get("drug_name") or item.get("name"))
        if not name:
            continue
        result.append(
            {
                "id": None,
                "drug_name": name,
                "drug_class": _clean(item.get("drug_class")),
                "dose_value": _clean(item.get("dose_value") or item.get("dose")),
                "dose_unit": _clean(item.get("dose_unit")),
                "frequency": _clean(item.get("frequency") or item.get("schedule")),
                "route": _clean(item.get("route")),
                "quantity": item.get("quantity"),
                "duration_days": item.get("duration_days"),
                "instructions": _clean(item.get("instructions")),
                "source": "legacy_json",
            }
        )
    return result


def _suggested_lab_keys(
    *, tenant_id: int, condition_codes: Iterable[str]
) -> set[str]:
    codes = sorted({code for code in condition_codes if code})
    if not codes:
        return set()
    # condition_lab_tests has a composite natural PK and no surrogate id, so this
    # focused read uses SQL rather than inventing an unsafe ORM primary key.
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT lab_test_key
            FROM clinical.condition_lab_tests
            WHERE tenant_id=%s AND condition_code=ANY(%s)
            ORDER BY display_order, lab_test_key
            """,
            [tenant_id, codes],
        )
        return {row[0] for row in cursor.fetchall()}


# ---------------------------------------------------------------------------
# Read aggregate
# ---------------------------------------------------------------------------
def get_structured_record(
    *, tenant_id: int, patient_link_id: int
) -> dict[str, Any]:
    _set_scope(tenant_id)
    _ensure_patient(tenant_id=tenant_id, patient_link_id=patient_link_id)

    condition_catalog = list(
        Condition.objects.filter(tenant_id=tenant_id, is_active=True).order_by(
            "display_order", "id"
        )
    )
    condition_map = {row.id: row for row in condition_catalog}
    patient_conditions = list(
        PatientCondition.objects.filter(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
        ).order_by("-is_active", "-diagnosed_at", "-id")
    )
    active_codes = {
        condition_map[row.condition_id].code
        for row in patient_conditions
        if row.is_active
        and row.condition_id in condition_map
        and condition_map[row.condition_id].code
    }

    medications = list(
        PatientMedication.objects.filter(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
        ).order_by("-is_active", "-created_at", "-id")
    )
    medication_events = list(
        MedicationEvent.objects.filter(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
        ).order_by("-event_date", "-id")
    )
    events_by_medication: dict[int, list[dict[str, Any]]] = defaultdict(list)
    orphan_events: list[dict[str, Any]] = []
    for event in medication_events:
        payload = {
            "id": event.id,
            "medication_id": event.medication_id,
            "drug_name": event.drug_name,
            "event_type": event.event_type,
            "dose": event.dose,
            "event_date": event.event_date,
            "note": event.note,
            "created_by": event.created_by,
            "created_at": event.created_at,
        }
        if event.medication_id is None:
            orphan_events.append(payload)
        else:
            events_by_medication[int(event.medication_id)].append(payload)

    catalog_flags = list(
        FlagCatalog.objects.filter(tenant_id=tenant_id, is_active=True).order_by(
            "record_section", "display_order", "id"
        )
    )
    value_map = {
        row.flag_key: row
        for row in PatientFlag.objects.filter(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
        )
    }
    flags = []
    for item in catalog_flags:
        value_row = value_map.get(item.flag_key)
        flags.append(
            {
                "id": item.id,
                "flag_key": item.flag_key,
                "label": item.label,
                "flag_type": item.flag_type,
                "options": _parse_options(item.options),
                "category": item.category,
                "record_section": item.record_section or "general",
                "display_order": item.display_order,
                "notes": item.notes,
                "value": value_row.value if value_row else None,
                "recorded_by": value_row.recorded_by if value_row else None,
                "updated_at": value_row.updated_at if value_row else None,
            }
        )

    surgeries = list(
        SurgeryHistory.objects.filter(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
        )
    )
    history = list(
        MedicalHistory.objects.filter(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
        )
    )
    notes = list(
        ClinicalNote.objects.filter(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
        )
    )

    labs = list(
        LabResult.objects.filter(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
        ).order_by("-taken_at", "-id")[:200]
    )
    suggested_keys = _suggested_lab_keys(
        tenant_id=tenant_id,
        condition_codes=active_codes,
    )
    lab_catalog = list(
        LabTestCatalog.objects.filter(tenant_id=tenant_id, is_active=True).order_by(
            "display_order", "id"
        )
    )

    appointments = list(
        Appointment.objects.filter(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
        ).order_by("-scheduled_at", "-id")[:100]
    )
    followups = list(
        FollowupTask.objects.filter(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
        ).order_by("status", "due_date", "-created_at", "-id")[:200]
    )

    prescriptions = list(
        Prescription.objects.filter(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
        ).order_by("-issued_at", "-id")[:100]
    )
    prescription_ids = [row.id for row in prescriptions]
    prescription_items: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if prescription_ids:
        for item in PrescriptionItem.objects.filter(
            tenant_id=tenant_id,
            prescription_id__in=prescription_ids,
        ).order_by("prescription_id", "id"):
            prescription_items[int(item.prescription_id)].append(
                {
                    "id": item.id,
                    "drug_name": item.drug_name,
                    "drug_class": item.drug_class,
                    "dose_value": _decimal_to_text(item.dose_value),
                    "dose_unit": item.dose_unit,
                    "frequency": item.frequency,
                    "route": item.route,
                    "quantity": item.quantity,
                    "duration_days": item.duration_days,
                    "instructions": item.instructions,
                    "source": "structured",
                }
            )

    drug_classes = list(
        DrugClass.objects.filter(tenant_id=tenant_id, is_active=True).order_by(
            "display_order", "id"
        )
    )
    drug_catalog = list(
        DrugCatalog.objects.filter(tenant_id=tenant_id, is_active=True).order_by(
            "generic_fa", "id"
        )
    )

    return {
        "patient_link_id": patient_link_id,
        "condition_catalog": [
            {
                "id": row.id,
                "name": row.name,
                "code": row.code,
                "description": row.description,
                "icon": row.icon,
                "color": row.color,
                "display_order": row.display_order,
            }
            for row in condition_catalog
        ],
        "conditions": [
            {
                "id": row.id,
                "condition_id": row.condition_id,
                "condition_name": (
                    condition_map[row.condition_id].name
                    if row.condition_id in condition_map
                    else None
                ),
                "condition_code": (
                    condition_map[row.condition_id].code
                    if row.condition_id in condition_map
                    else None
                ),
                "stage": row.stage,
                "onset_date": row.onset_date,
                "notes": row.notes,
                "is_active": row.is_active,
                "diagnosed_at": row.diagnosed_at,
            }
            for row in patient_conditions
        ],
        "medications": [
            {
                "id": row.id,
                "drug_name": row.drug_name,
                "dose": row.dose,
                "schedule": row.schedule,
                "start_date": row.start_date,
                "refill_due_date": row.refill_due_date,
                "end_date": row.end_date,
                "drug_class": row.drug_class,
                "is_active": row.is_active,
                "notes": row.notes,
                "created_at": row.created_at,
                "events": events_by_medication.get(row.id, []),
            }
            for row in medications
        ],
        "orphan_medication_events": orphan_events,
        "flag_catalog": flags,
        "surgeries": [
            {
                "id": row.id,
                "title": row.title,
                "performed_on": row.performed_on,
                "note": row.note,
                "created_at": row.created_at,
            }
            for row in surgeries
        ],
        "medical_history": [
            {
                "id": row.id,
                "title": row.title,
                "since": row.since,
                "note": row.note,
                "created_at": row.created_at,
            }
            for row in history
        ],
        "clinical_notes": [
            {
                "id": row.id,
                "kind": row.kind,
                "body": row.body,
                "recorded_at": row.recorded_at,
                "recorded_by": row.recorded_by,
            }
            for row in notes
        ],
        "labs": [
            {
                "id": row.id,
                "encounter_id": row.encounter_id,
                "test_name": row.test_name,
                "test_key": row.test_key,
                "value": row.value,
                "unit": row.unit,
                "ref_low": row.ref_low,
                "ref_high": row.ref_high,
                "taken_at": row.taken_at,
                "notes": row.notes,
                "recorded_by": row.recorded_by,
            }
            for row in labs
        ],
        "lab_catalog": [
            {
                "id": row.id,
                "test_key": row.test_key,
                "name_fa": row.name_fa,
                "unit": row.unit,
                "ref_low": row.ref_low,
                "ref_high": row.ref_high,
                "category": row.category,
                "display_order": row.display_order,
                "suggested": row.test_key in suggested_keys,
            }
            for row in lab_catalog
        ],
        "appointments": [
            {
                "id": row.id,
                "scheduled_at": row.scheduled_at,
                "appt_type": row.appt_type,
                "status": row.status,
                "recurrence_months": row.recurrence_months,
                "reminder_sent": row.reminder_sent,
                "notes": row.notes,
                "doctor_id": row.doctor_id,
                "chief_complaint": row.chief_complaint,
            }
            for row in appointments
        ],
        "followups": [
            {
                "id": row.id,
                "due_date": row.due_date,
                "reason": row.reason,
                "detail": row.detail,
                "status": row.status,
                "assigned_to": row.assigned_to,
                "call_log": row.call_log,
                "source_rule": row.source_rule,
                "source_event": row.source_event,
                "appointment_id": row.appointment_id,
                "fulfillment": row.fulfillment,
                "created_at": row.created_at,
                "resolved_at": row.resolved_at,
            }
            for row in followups
        ],
        "prescriptions": [
            {
                "id": row.id,
                "kind": row.kind,
                "mode": row.mode,
                "insurer": row.insurer,
                "portal_rx_id": row.portal_rx_id,
                "prescriber_user_id": row.prescriber_user_id,
                "followup_task_id": row.followup_task_id,
                "encounter_id": row.encounter_id,
                "issued_at": row.issued_at,
                "items": (
                    prescription_items.get(row.id)
                    or _legacy_prescription_items(row.items)
                ),
            }
            for row in prescriptions
        ],
        "drug_classes": [
            {
                "id": row.id,
                "class_key": row.class_key,
                "label": row.label,
                "glucose_lowering": row.glucose_lowering,
                "display_order": row.display_order,
            }
            for row in drug_classes
        ],
        "drug_catalog": [
            {
                "id": row.id,
                "generic_fa": row.generic_fa,
                "drug_class_key": row.drug_class_key,
                "standard_doses": _parse_doses(row.standard_doses),
            }
            for row in drug_catalog
        ],
    }


# ---------------------------------------------------------------------------
# Chronic conditions
# ---------------------------------------------------------------------------
def add_condition(
    *,
    tenant_id: int,
    patient_link_id: int,
    condition_id: int,
    stage: Optional[str] = None,
    onset_date: Optional[date] = None,
    notes: Optional[str] = None,
    actor_username: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> PatientCondition:
    _set_scope(tenant_id)
    with transaction.atomic():
        _ensure_patient(tenant_id=tenant_id, patient_link_id=patient_link_id)
        try:
            condition = Condition.objects.get(
                tenant_id=tenant_id,
                id=condition_id,
                is_active=True,
            )
        except Condition.DoesNotExist as exc:
            raise PatientRecordValidationError(
                "بیماری انتخاب‌شده فعال یا معتبر نیست."
            ) from exc
        if PatientCondition.objects.filter(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
            condition_id=condition_id,
            is_active=True,
        ).exists():
            raise PatientRecordConflict("این بیماری قبلاً برای بیمار فعال است.")
        row = PatientCondition.objects.create(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
            condition_id=condition_id,
            stage=_clean(stage),
            onset_date=onset_date,
            notes=_clean(notes),
            is_active=True,
            diagnosed_at=timezone.now(),
        )
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor_username=actor_username,
        actor_id=actor_id,
        action_type="condition_added",
        target_table="patient_conditions",
        target_id=row.id,
        description=f"condition={condition.code or condition.name}",
    )
    return row


def deactivate_condition(
    *,
    tenant_id: int,
    patient_link_id: int,
    patient_condition_id: int,
    actor_username: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> int:
    _set_scope(tenant_id)
    with transaction.atomic():
        try:
            row = PatientCondition.objects.select_for_update().get(
                tenant_id=tenant_id,
                patient_link_id=patient_link_id,
                id=patient_condition_id,
                is_active=True,
            )
        except PatientCondition.DoesNotExist as exc:
            raise PatientRecordNotFound("تشخیص فعال برای این بیمار پیدا نشد.") from exc
        row.is_active = False
        row.save(update_fields=["is_active"])
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor_username=actor_username,
        actor_id=actor_id,
        action_type="condition_deactivated",
        target_table="patient_conditions",
        target_id=patient_condition_id,
    )
    return patient_condition_id


# ---------------------------------------------------------------------------
# Medication state + append-style timeline
# ---------------------------------------------------------------------------
def add_medication(
    *,
    tenant_id: int,
    patient_link_id: int,
    drug_name: str,
    dose: Optional[str] = None,
    schedule: Optional[str] = None,
    start_date: Optional[date] = None,
    refill_due_date: Optional[date] = None,
    refill_interval_days: Optional[int] = None,
    notes: Optional[str] = None,
    drug_class: Optional[str] = None,
    actor_username: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> PatientMedication:
    _set_scope(tenant_id)
    name = _required_text(drug_name, "نام دارو")
    start = start_date or timezone.localdate()
    interval = refill_interval_days
    if interval is not None:
        try:
            interval = int(interval)
        except (TypeError, ValueError) as exc:
            raise PatientRecordValidationError("بازهٔ تجدید نسخه نامعتبر است.") from exc
        if interval not in ALLOWED_REFILL_INTERVALS:
            raise PatientRecordValidationError(
                "بازهٔ تجدید نسخه باید یکی از ۱۵، ۳۰، ۶۰ یا ۹۰ روز باشد."
            )
    due = refill_due_date or (start + timedelta(days=interval) if interval else None)
    clean_class = _clean(drug_class)

    with transaction.atomic():
        _ensure_patient(tenant_id=tenant_id, patient_link_id=patient_link_id)
        if clean_class and not DrugClass.objects.filter(
            tenant_id=tenant_id,
            class_key=clean_class,
            is_active=True,
        ).exists():
            raise PatientRecordValidationError("کلاس دارویی فعال یا معتبر نیست.")
        medication = PatientMedication.objects.create(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
            drug_name=name,
            dose=_clean(dose),
            schedule=_clean(schedule),
            start_date=start,
            refill_due_date=due,
            end_date=None,
            drug_class=clean_class,
            is_active=True,
            notes=_clean(notes),
            created_at=timezone.now(),
        )
        MedicationEvent.objects.create(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
            medication_id=medication.id,
            drug_name=name,
            event_type="start",
            dose=medication.dose,
            event_date=start,
            note=medication.notes,
            created_by=actor_username,
        )
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor_username=actor_username,
        actor_id=actor_id,
        action_type="medication_added",
        target_table="patient_medications",
        target_id=medication.id,
        description=f"drug={name}, dose={medication.dose or ''}",
    )
    return medication


def stop_medication(
    *,
    tenant_id: int,
    patient_link_id: int,
    medication_id: int,
    end_date: Optional[date] = None,
    note: Optional[str] = None,
    actor_username: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> PatientMedication:
    _set_scope(tenant_id)
    stopped_on = end_date or timezone.localdate()
    with transaction.atomic():
        try:
            medication = PatientMedication.objects.select_for_update().get(
                tenant_id=tenant_id,
                patient_link_id=patient_link_id,
                id=medication_id,
                is_active=True,
            )
        except PatientMedication.DoesNotExist as exc:
            raise PatientRecordNotFound("داروی فعال برای این بیمار پیدا نشد.") from exc
        if medication.start_date and stopped_on < medication.start_date:
            raise PatientRecordValidationError(
                "تاریخ قطع نمی‌تواند قبل از تاریخ شروع دارو باشد."
            )
        medication.is_active = False
        medication.end_date = stopped_on
        medication.save(update_fields=["is_active", "end_date"])
        MedicationEvent.objects.create(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
            medication_id=medication.id,
            drug_name=medication.drug_name,
            event_type="stop",
            dose=medication.dose,
            event_date=stopped_on,
            note=_clean(note),
            created_by=actor_username,
        )
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor_username=actor_username,
        actor_id=actor_id,
        action_type="medication_stopped",
        target_table="patient_medications",
        target_id=medication.id,
        description=f"drug={medication.drug_name}, end_date={stopped_on}",
    )
    return medication


def change_medication_dose(
    *,
    tenant_id: int,
    patient_link_id: int,
    medication_id: int,
    new_dose: str,
    change_date: Optional[date] = None,
    note: Optional[str] = None,
    actor_username: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> PatientMedication:
    _set_scope(tenant_id)
    dose = _required_text(new_dose, "دوز جدید")
    changed_on = change_date or timezone.localdate()
    with transaction.atomic():
        try:
            medication = PatientMedication.objects.select_for_update().get(
                tenant_id=tenant_id,
                patient_link_id=patient_link_id,
                id=medication_id,
                is_active=True,
            )
        except PatientMedication.DoesNotExist as exc:
            raise PatientRecordNotFound("داروی فعال برای این بیمار پیدا نشد.") from exc
        old_dose = medication.dose
        medication.dose = dose
        medication.save(update_fields=["dose"])
        MedicationEvent.objects.create(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
            medication_id=medication.id,
            drug_name=medication.drug_name,
            event_type="dose_change",
            dose=dose,
            event_date=changed_on,
            note=_clean(note),
            created_by=actor_username,
        )
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor_username=actor_username,
        actor_id=actor_id,
        action_type="medication_dose_changed",
        target_table="patient_medications",
        target_id=medication.id,
        description=f"old={old_dose or ''}, new={dose}",
    )
    return medication


# ---------------------------------------------------------------------------
# Typed partial-safe flags
# ---------------------------------------------------------------------------
def _normalize_flag_value(catalog: FlagCatalog, value: Any) -> str:
    flag_type = catalog.flag_type
    if flag_type not in ALLOWED_FLAG_TYPES:
        raise PatientRecordValidationError(
            f"نوع فلگ {catalog.flag_key} در کاتالوگ نامعتبر است."
        )
    if flag_type == "bool":
        if isinstance(value, bool):
            return "1" if value else ""
        normalized = (_clean(value) or "").lower()
        return "1" if normalized in {"1", "true", "yes", "on"} else ""
    text = _clean(value) or ""
    if flag_type == "enum" and text:
        allowed = {item["value"] for item in _parse_options(catalog.options)}
        if text not in allowed:
            raise PatientRecordValidationError(
                f"مقدار {text!r} برای {catalog.label} مجاز نیست."
            )
    if flag_type == "date" and text:
        try:
            date.fromisoformat(text)
        except ValueError as exc:
            raise PatientRecordValidationError(
                f"تاریخ {catalog.label} باید YYYY-MM-DD باشد."
            ) from exc
    return text


def patch_flags(
    *,
    tenant_id: int,
    patient_link_id: int,
    values: Mapping[str, Any],
    clear_keys: Iterable[str] = (),
    actor_username: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> list[PatientFlag]:
    _set_scope(tenant_id)
    clear = {str(key).strip() for key in clear_keys if str(key).strip()}
    submitted = {str(key).strip(): value for key, value in values.items() if str(key).strip()}
    managed_keys = set(submitted) | clear
    if not managed_keys:
        raise PatientRecordValidationError("هیچ فلگی برای به‌روزرسانی ارسال نشده است.")

    with transaction.atomic():
        _ensure_patient(tenant_id=tenant_id, patient_link_id=patient_link_id)
        catalog_rows = {
            row.flag_key: row
            for row in FlagCatalog.objects.filter(
                tenant_id=tenant_id,
                flag_key__in=managed_keys,
                is_active=True,
            )
        }
        unknown = sorted(managed_keys - set(catalog_rows))
        if unknown:
            raise PatientRecordValidationError(
                "فلگ‌های ناشناخته: " + "، ".join(unknown)
            )

        changed: list[PatientFlag] = []
        for key in sorted(managed_keys):
            catalog = catalog_rows[key]
            if key in clear:
                normalized = ""
            else:
                raw_value = submitted[key]
                # Legacy partial-safe date behavior: an empty date input does not
                # wipe an existing value. Explicit clearing requires clear_keys.
                if catalog.flag_type == "date" and not _clean(raw_value):
                    continue
                normalized = _normalize_flag_value(catalog, raw_value)
            row, _created = PatientFlag.objects.update_or_create(
                tenant_id=tenant_id,
                patient_link_id=patient_link_id,
                flag_key=key,
                defaults={
                    "value": normalized,
                    "recorded_by": actor_username,
                },
            )
            changed.append(row)
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor_username=actor_username,
        actor_id=actor_id,
        action_type="patient_flags_updated",
        target_table="patient_flags",
        target_id=None,
        description="keys=" + ",".join(sorted(managed_keys)),
    )
    return changed


# ---------------------------------------------------------------------------
# Medical/surgical history and clinical notes
# ---------------------------------------------------------------------------
def add_surgery(
    *,
    tenant_id: int,
    patient_link_id: int,
    title: str,
    performed_on: Optional[date] = None,
    note: Optional[str] = None,
    actor_username: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> SurgeryHistory:
    _set_scope(tenant_id)
    clean_title = _required_text(title, "عنوان جراحی")
    with transaction.atomic():
        _ensure_patient(tenant_id=tenant_id, patient_link_id=patient_link_id)
        row = SurgeryHistory.objects.create(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
            title=clean_title,
            performed_on=performed_on,
            note=_clean(note),
        )
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor_username=actor_username,
        actor_id=actor_id,
        action_type="surgery_history_added",
        target_table="surgery_history",
        target_id=row.id,
        description=clean_title,
    )
    return row


def delete_surgery(
    *,
    tenant_id: int,
    patient_link_id: int,
    surgery_id: int,
    actor_username: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> int:
    _set_scope(tenant_id)
    with transaction.atomic():
        try:
            row = SurgeryHistory.objects.select_for_update().get(
                tenant_id=tenant_id,
                patient_link_id=patient_link_id,
                id=surgery_id,
            )
        except SurgeryHistory.DoesNotExist as exc:
            raise PatientRecordNotFound("سابقهٔ جراحی برای این بیمار پیدا نشد.") from exc
        title = row.title
        row.delete()
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor_username=actor_username,
        actor_id=actor_id,
        action_type="surgery_history_deleted",
        target_table="surgery_history",
        target_id=surgery_id,
        description=title,
    )
    return surgery_id


def add_medical_history(
    *,
    tenant_id: int,
    patient_link_id: int,
    title: str,
    since: Optional[date] = None,
    note: Optional[str] = None,
    actor_username: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> MedicalHistory:
    _set_scope(tenant_id)
    clean_title = _required_text(title, "عنوان سابقهٔ پزشکی")
    with transaction.atomic():
        _ensure_patient(tenant_id=tenant_id, patient_link_id=patient_link_id)
        row = MedicalHistory.objects.create(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
            title=clean_title,
            since=since,
            note=_clean(note),
        )
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor_username=actor_username,
        actor_id=actor_id,
        action_type="medical_history_added",
        target_table="medical_history",
        target_id=row.id,
        description=clean_title,
    )
    return row


def delete_medical_history(
    *,
    tenant_id: int,
    patient_link_id: int,
    history_id: int,
    actor_username: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> int:
    _set_scope(tenant_id)
    with transaction.atomic():
        try:
            row = MedicalHistory.objects.select_for_update().get(
                tenant_id=tenant_id,
                patient_link_id=patient_link_id,
                id=history_id,
            )
        except MedicalHistory.DoesNotExist as exc:
            raise PatientRecordNotFound("سابقهٔ پزشکی برای این بیمار پیدا نشد.") from exc
        title = row.title
        row.delete()
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor_username=actor_username,
        actor_id=actor_id,
        action_type="medical_history_deleted",
        target_table="medical_history",
        target_id=history_id,
        description=title,
    )
    return history_id


def add_clinical_note(
    *,
    tenant_id: int,
    patient_link_id: int,
    kind: str,
    body: str,
    actor_username: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> ClinicalNote:
    _set_scope(tenant_id)
    normalized_kind = (_clean(kind) or "").lower()
    if normalized_kind not in ClinicalNote.ALLOWED_KINDS:
        raise PatientRecordValidationError("نوع یادداشت بالینی نامعتبر است.")
    clean_body = _required_text(body, "متن یادداشت")
    with transaction.atomic():
        _ensure_patient(tenant_id=tenant_id, patient_link_id=patient_link_id)
        row = ClinicalNote.objects.create(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
            kind=normalized_kind,
            body=clean_body,
            recorded_by=actor_username,
        )
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor_username=actor_username,
        actor_id=actor_id,
        action_type="clinical_note_added",
        target_table="clinical_notes",
        target_id=row.id,
        description=f"kind={normalized_kind}",
    )
    return row


def delete_clinical_note(
    *,
    tenant_id: int,
    patient_link_id: int,
    note_id: int,
    actor_username: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> int:
    _set_scope(tenant_id)
    with transaction.atomic():
        try:
            row = ClinicalNote.objects.select_for_update().get(
                tenant_id=tenant_id,
                patient_link_id=patient_link_id,
                id=note_id,
            )
        except ClinicalNote.DoesNotExist as exc:
            raise PatientRecordNotFound("یادداشت برای این بیمار پیدا نشد.") from exc
        row.delete()
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor_username=actor_username,
        actor_id=actor_id,
        action_type="clinical_note_deleted",
        target_table="clinical_notes",
        target_id=note_id,
    )
    return note_id


# ---------------------------------------------------------------------------
# Standalone lab rows (encounter-bound lab writes remain in encounter_service)
# ---------------------------------------------------------------------------
def add_lab_result(
    *,
    tenant_id: int,
    patient_link_id: int,
    test_key: Optional[str] = None,
    test_name: Optional[str] = None,
    value: Optional[float] = None,
    unit: Optional[str] = None,
    ref_low: Optional[float] = None,
    ref_high: Optional[float] = None,
    taken_at: Optional[datetime] = None,
    notes: Optional[str] = None,
    actor_username: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> LabResult:
    _set_scope(tenant_id)
    normalized_key = _clean(test_key)
    normalized_name = _clean(test_name)
    with transaction.atomic():
        _ensure_patient(tenant_id=tenant_id, patient_link_id=patient_link_id)
        catalog = None
        if normalized_key:
            try:
                catalog = LabTestCatalog.objects.get(
                    tenant_id=tenant_id,
                    test_key=normalized_key,
                    is_active=True,
                )
            except LabTestCatalog.DoesNotExist as exc:
                raise PatientRecordValidationError(
                    "آزمایش انتخاب‌شده در کاتالوگ فعال نیست."
                ) from exc
            normalized_name = normalized_name or catalog.name_fa
            unit = _clean(unit) or catalog.unit
            ref_low = catalog.ref_low if ref_low is None else ref_low
            ref_high = catalog.ref_high if ref_high is None else ref_high
        if not normalized_name:
            raise PatientRecordValidationError(
                "برای آزمایش آزاد، نام آزمایش الزامی است."
            )
        row = LabResult.objects.create(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
            encounter_id=None,
            test_name=normalized_name,
            test_key=normalized_key,
            value=value,
            unit=_clean(unit),
            ref_low=ref_low,
            ref_high=ref_high,
            taken_at=taken_at or timezone.now(),
            notes=_clean(notes),
            recorded_by=actor_username,
        )
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor_username=actor_username,
        actor_id=actor_id,
        action_type="lab_result_added",
        target_table="lab_results",
        target_id=row.id,
        description=f"test={normalized_key or normalized_name}",
    )
    return row


def delete_lab_result(
    *,
    tenant_id: int,
    patient_link_id: int,
    lab_id: int,
    actor_username: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> int:
    _set_scope(tenant_id)
    with transaction.atomic():
        try:
            row = LabResult.objects.select_for_update().get(
                tenant_id=tenant_id,
                patient_link_id=patient_link_id,
                id=lab_id,
            )
        except LabResult.DoesNotExist as exc:
            raise PatientRecordNotFound("نتیجهٔ آزمایش برای این بیمار پیدا نشد.") from exc
        test_name = row.test_name
        row.delete()
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor_username=actor_username,
        actor_id=actor_id,
        action_type="lab_result_deleted",
        target_table="lab_results",
        target_id=lab_id,
        description=test_name,
    )
    return lab_id
