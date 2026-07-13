"""Application service for the complete specialist patient record.

Every mutation is tenant-scoped, atomic, validated before persistence, and
audited without copying sensitive free text into the audit description.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Optional

from django.db import IntegrityError, transaction
from django.utils import timezone

from accounting_port.record import get_patient_visit_history
from clinical.audit import log_activity
from clinical.models import PatientCondition, PatientMedication
from clinical.record_catalog_defaults import (
    ALLOWED_REFILL_INTERVALS,
    NOTE_KINDS,
)
from clinical.record_repository import (
    CATEGORY_LABELS,
    RecordRepository,
    parse_flag_options,
    parse_standard_doses,
)
from platform_core.tenant_context import set_tenant_guc


class RecordServiceError(Exception):
    status = 400
    code = "record_error"

    def __init__(self, detail: str, code: Optional[str] = None):
        super().__init__(detail)
        if code:
            self.code = code


class RecordValidationError(RecordServiceError):
    status = 422
    code = "validation_error"


class RecordNotFound(RecordServiceError):
    status = 404
    code = "not_found"


class RecordConflict(RecordServiceError):
    status = 409
    code = "conflict"


def _clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _actor_fields(actor: Any) -> tuple[Optional[int], str]:
    actor_id = getattr(actor, "pk", None) or getattr(actor, "id", None)
    username = _clean(getattr(actor, "username", None)) or "unknown"
    return actor_id, username


def _audit(
    *,
    tenant_id: int,
    patient_link_id: int,
    actor: Any,
    action_type: str,
    target_table: str,
    target_id: Optional[int] = None,
    description: Optional[str] = None,
) -> None:
    actor_id, username = _actor_fields(actor)
    log_activity(
        tenant_id=tenant_id,
        user_id=actor_id,
        username=username,
        action_type=action_type,
        action_category="clinical_record",
        target_table=target_table,
        target_id=target_id,
        patient_link_id=patient_link_id,
        description=description,
    )


def _iso_date(value: Any, *, field: str) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise RecordValidationError(
            f"{field} باید تاریخ میلادی معتبر با قالب YYYY-MM-DD باشد.",
            "invalid_date",
        ) from exc


def _aware_datetime(value: Optional[datetime]) -> datetime:
    result = value or timezone.now()
    if timezone.is_naive(result):
        result = timezone.make_aware(result, timezone.get_current_timezone())
    return result


def _finite_number(value: Any, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RecordValidationError(f"{field} باید عدد باشد.", "invalid_number") from exc
    if not math.isfinite(number):
        raise RecordValidationError(
            f"{field} باید عدد متناهی باشد.", "invalid_number"
        )
    return number


def _condition_out(row, condition_map: Mapping[int, Any]) -> dict[str, Any]:
    condition = condition_map.get(row.condition_id)
    return {
        "id": int(row.id),
        "condition_id": int(row.condition_id),
        "condition_name": condition.name if condition else None,
        "condition_code": condition.code if condition else None,
        "stage": row.stage,
        "onset_date": row.onset_date,
        "notes": row.notes,
        "is_active": bool(row.is_active),
        "diagnosed_at": row.diagnosed_at,
    }


def _medication_out(row) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "drug_name": row.drug_name,
        "dose": row.dose,
        "schedule": row.schedule,
        "start_date": row.start_date,
        "refill_due_date": row.refill_due_date,
        "end_date": row.end_date,
        "drug_class": row.drug_class,
        "is_active": bool(row.is_active),
        "notes": row.notes,
        "created_at": row.created_at,
    }


def get_record_data(
    *, tenant_id: int, patient_link_id: int, accounting_patient_id: int
) -> dict[str, Any]:
    """Return the complete editable record projection in bounded query batches."""
    set_tenant_guc(tenant_id)
    repo = RecordRepository()

    conditions = repo.list_condition_catalog(tenant_id=tenant_id)
    condition_map = {row.id: row for row in conditions}
    patient_conditions = repo.list_patient_conditions(
        tenant_id=tenant_id, patient_link_id=patient_link_id
    )
    active_codes = [
        condition_map[row.condition_id].code
        for row in patient_conditions
        if row.is_active
        and row.condition_id in condition_map
        and condition_map[row.condition_id].code
    ]

    flags = repo.list_patient_flags(
        tenant_id=tenant_id, patient_link_id=patient_link_id
    )
    flag_catalog = repo.list_flag_catalog(tenant_id=tenant_id)

    labs = repo.list_labs(tenant_id=tenant_id, patient_link_id=patient_link_id)
    lab_catalog = repo.list_lab_catalog(tenant_id=tenant_id)
    medications = repo.list_medications(
        tenant_id=tenant_id, patient_link_id=patient_link_id
    )

    prescriptions = []
    for row in repo.list_prescriptions(
        tenant_id=tenant_id, patient_link_id=patient_link_id
    ):
        items = row.items
        if isinstance(items, list):
            item_count = len(items)
        elif isinstance(items, dict):
            item_count = len(items)
        else:
            item_count = 0
        prescriptions.append(
            {
                "id": int(row.id),
                "kind": row.kind,
                "mode": row.mode,
                "insurer": row.insurer,
                "portal_rx_id": row.portal_rx_id,
                "issued_at": row.issued_at,
                "item_count": item_count,
                "items": items,
            }
        )

    visit_history = get_patient_visit_history(
        accounting_patient_id=accounting_patient_id,
        tenant_id=tenant_id,
        limit=100,
    )

    return {
        "condition_catalog": [
            {
                "id": int(row.id),
                "name": row.name,
                "code": row.code,
                "description": row.description,
                "icon": row.icon,
                "color": row.color,
                "display_order": row.display_order,
            }
            for row in conditions
        ],
        "conditions": [
            _condition_out(row, condition_map) for row in patient_conditions
        ],
        "surgeries": [
            {
                "id": int(row.id),
                "title": row.title,
                "performed_on": row.performed_on,
                "note": row.note,
                "created_at": row.created_at,
            }
            for row in repo.list_surgeries(
                tenant_id=tenant_id, patient_link_id=patient_link_id
            )
        ],
        "medical_history": [
            {
                "id": int(row.id),
                "title": row.title,
                "since": row.since,
                "note": row.note,
                "created_at": row.created_at,
            }
            for row in repo.list_medical_history(
                tenant_id=tenant_id, patient_link_id=patient_link_id
            )
        ],
        "notes": [
            {
                "id": int(row.id),
                "kind": row.kind,
                "body": row.body or "",
                "recorded_at": row.recorded_at,
                "recorded_by": row.recorded_by,
            }
            for row in repo.list_notes(
                tenant_id=tenant_id, patient_link_id=patient_link_id
            )
        ],
        "flag_catalog": [
            {
                "flag_key": row.flag_key,
                "label": row.label,
                "flag_type": row.flag_type,
                "options": parse_flag_options(row.options),
                "category": row.category,
                "category_label": CATEGORY_LABELS.get(row.category, row.category),
                "record_section": row.record_section or "general",
                "display_order": row.display_order,
            }
            for row in flag_catalog
        ],
        "patient_flags": {row.flag_key: row.value for row in flags},
        "lab_catalog": [
            {
                "id": int(row.id),
                "test_key": row.test_key,
                "name_fa": row.name_fa,
                "unit": row.unit,
                "ref_low": row.ref_low,
                "ref_high": row.ref_high,
                "category": row.category,
                "display_order": row.display_order or 100,
            }
            for row in lab_catalog
        ],
        "suggested_labs": repo.suggested_labs(
            tenant_id=tenant_id, condition_codes=active_codes
        ),
        "labs": [
            {
                "id": int(row.id),
                "test_name": row.test_name,
                "test_key": row.test_key,
                "value": row.value,
                "unit": row.unit,
                "ref_low": row.ref_low,
                "ref_high": row.ref_high,
                "taken_at": row.taken_at,
                "notes": row.notes,
                "recorded_by": row.recorded_by,
                "encounter_id": row.encounter_id,
            }
            for row in labs
        ],
        "indicator_catalog": [
            {
                "key": row.key,
                "label": row.label,
                "unit": row.unit,
                "category": row.category,
                "display_order": row.display_order,
            }
            for row in repo.list_indicators(tenant_id=tenant_id)
        ],
        "drug_classes": [
            {
                "class_key": row.class_key,
                "label": row.label,
                "glucose_lowering": bool(row.glucose_lowering),
                "display_order": row.display_order,
            }
            for row in repo.list_drug_classes(tenant_id=tenant_id)
        ],
        "drug_catalog": [
            {
                "id": int(row.id),
                "generic_fa": row.generic_fa,
                "drug_class_key": row.drug_class_key,
                "doses": parse_standard_doses(row.standard_doses),
            }
            for row in repo.list_drug_catalog(tenant_id=tenant_id)
        ],
        "medications": [_medication_out(row) for row in medications],
        "medication_events": [
            {
                "id": int(row.id),
                "medication_id": (
                    int(row.medication_id)
                    if row.medication_id is not None
                    else None
                ),
                "drug_name": row.drug_name,
                "event_type": row.event_type,
                "dose": row.dose,
                "event_date": row.event_date,
                "note": row.note,
                "created_by": row.created_by,
                "created_at": row.created_at,
            }
            for row in repo.list_medication_events(
                tenant_id=tenant_id, patient_link_id=patient_link_id
            )
        ],
        "appointments": [
            {
                "id": int(row.id),
                "scheduled_at": row.scheduled_at,
                "appt_type": row.appt_type,
                "status": row.status,
                "notes": row.notes,
                "chief_complaint": row.chief_complaint,
                "doctor_id": row.doctor_id,
            }
            for row in repo.list_appointments(
                tenant_id=tenant_id, patient_link_id=patient_link_id
            )
        ],
        "prescriptions": prescriptions,
        "accounting_visit_history": [
            item.model_dump() for item in visit_history
        ],
    }


@transaction.atomic
def add_surgery(
    *,
    tenant_id: int,
    patient_link_id: int,
    title: str,
    performed_on: Any = None,
    note: Optional[str] = None,
    actor: Any,
):
    set_tenant_guc(tenant_id)
    clean_title = _clean(title)
    if not clean_title:
        raise RecordValidationError("عنوان جراحی الزامی است.", "title_required")
    row = RecordRepository().create_surgery(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        title=clean_title,
        performed_on=_iso_date(performed_on, field="تاریخ جراحی"),
        note=_clean(note),
    )
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor=actor,
        action_type="record_surgery_added",
        target_table="surgery_history",
        target_id=row.id,
    )
    return row


@transaction.atomic
def delete_surgery(
    *, tenant_id: int, patient_link_id: int, row_id: int, actor: Any
) -> None:
    set_tenant_guc(tenant_id)
    row = RecordRepository().get_surgery(
        tenant_id=tenant_id, patient_link_id=patient_link_id, row_id=row_id
    )
    if row is None:
        raise RecordNotFound("سابقهٔ جراحی پیدا نشد.")
    row.delete()
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor=actor,
        action_type="record_surgery_deleted",
        target_table="surgery_history",
        target_id=row_id,
    )


@transaction.atomic
def add_medical_history(
    *,
    tenant_id: int,
    patient_link_id: int,
    title: str,
    since: Any = None,
    note: Optional[str] = None,
    actor: Any,
):
    set_tenant_guc(tenant_id)
    clean_title = _clean(title)
    if not clean_title:
        raise RecordValidationError("عنوان سابقهٔ پزشکی الزامی است.", "title_required")
    row = RecordRepository().create_medical_history(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        title=clean_title,
        since=_iso_date(since, field="تاریخ شروع سابقه"),
        note=_clean(note),
    )
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor=actor,
        action_type="record_history_added",
        target_table="medical_history",
        target_id=row.id,
    )
    return row


@transaction.atomic
def delete_medical_history(
    *, tenant_id: int, patient_link_id: int, row_id: int, actor: Any
) -> None:
    set_tenant_guc(tenant_id)
    row = RecordRepository().get_medical_history(
        tenant_id=tenant_id, patient_link_id=patient_link_id, row_id=row_id
    )
    if row is None:
        raise RecordNotFound("سابقهٔ پزشکی پیدا نشد.")
    row.delete()
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor=actor,
        action_type="record_history_deleted",
        target_table="medical_history",
        target_id=row_id,
    )


@transaction.atomic
def add_note(
    *,
    tenant_id: int,
    patient_link_id: int,
    kind: str,
    body: str,
    actor: Any,
):
    set_tenant_guc(tenant_id)
    clean_kind = _clean(kind)
    clean_body = _clean(body)
    if clean_kind not in NOTE_KINDS:
        raise RecordValidationError("نوع یادداشت نامعتبر است.", "invalid_note_kind")
    if not clean_body:
        raise RecordValidationError("متن یادداشت الزامی است.", "body_required")
    _actor_id, username = _actor_fields(actor)
    row = RecordRepository().create_note(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        kind=clean_kind,
        body=clean_body,
        recorded_by=username,
    )
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor=actor,
        action_type="record_note_added",
        target_table="clinical_notes",
        target_id=row.id,
        description=f"kind={clean_kind}",
    )
    return row


@transaction.atomic
def delete_note(
    *, tenant_id: int, patient_link_id: int, row_id: int, actor: Any
) -> None:
    set_tenant_guc(tenant_id)
    row = RecordRepository().get_note(
        tenant_id=tenant_id, patient_link_id=patient_link_id, row_id=row_id
    )
    if row is None:
        raise RecordNotFound("یادداشت پیدا نشد.")
    kind = row.kind
    row.delete()
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor=actor,
        action_type="record_note_deleted",
        target_table="clinical_notes",
        target_id=row_id,
        description=f"kind={kind}",
    )


def _normalise_bool(value: Any) -> bool:
    if value in (True, 1, "1", "true", "True", "on", "yes"):
        return True
    if value in (False, 0, "0", "false", "False", "off", "no", "", None):
        return False
    raise RecordValidationError("مقدار فلگ بله/خیر نامعتبر است.", "invalid_flag_value")


@transaction.atomic
def update_flags(
    *,
    tenant_id: int,
    patient_link_id: int,
    managed_keys: list[str],
    values: Mapping[str, Any],
    actor: Any,
) -> dict[str, Optional[str]]:
    """Partially update only explicitly managed keys.

    Date flags intentionally preserve their prior value when submitted blank,
    matching the specialist record's Jalali date picker semantics.
    """
    set_tenant_guc(tenant_id)
    keys = list(dict.fromkeys(_clean(key) for key in managed_keys))
    keys = [key for key in keys if key]
    if not keys:
        raise RecordValidationError("حداقل یک کلید فلگ لازم است.", "flag_keys_required")
    if len(keys) > 100:
        raise RecordValidationError("تعداد فلگ‌ها بیش از حد مجاز است.")

    repo = RecordRepository()
    catalog = repo.get_flags_by_keys(tenant_id=tenant_id, keys=keys)
    missing = sorted(set(keys) - set(catalog))
    if missing:
        raise RecordValidationError(
            "فلگ نامعتبر: " + ", ".join(missing), "invalid_flag_key"
        )

    _actor_id, username = _actor_fields(actor)
    changed: list[str] = []
    for key in keys:
        definition = catalog[key]
        provided = key in values
        raw = values.get(key)

        if definition.flag_type == "bool":
            if _normalise_bool(raw if provided else False):
                repo.set_flag(
                    tenant_id=tenant_id,
                    patient_link_id=patient_link_id,
                    flag_key=key,
                    value="1",
                    recorded_by=username,
                )
            else:
                repo.clear_flag(
                    tenant_id=tenant_id,
                    patient_link_id=patient_link_id,
                    flag_key=key,
                )
            changed.append(key)
            continue

        clean_value = _clean(raw) if provided else None
        if definition.flag_type == "date" and not clean_value:
            continue

        if not clean_value:
            repo.clear_flag(
                tenant_id=tenant_id,
                patient_link_id=patient_link_id,
                flag_key=key,
            )
            changed.append(key)
            continue

        if definition.flag_type == "enum":
            allowed = {option["value"] for option in parse_flag_options(definition.options)}
            if clean_value not in allowed:
                raise RecordValidationError(
                    f"مقدار فلگ {key} خارج از گزینه‌های مجاز است.",
                    "invalid_flag_value",
                )
        elif definition.flag_type == "date":
            clean_value = _iso_date(clean_value, field=definition.label).isoformat()

        repo.set_flag(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
            flag_key=key,
            value=clean_value,
            recorded_by=username,
        )
        changed.append(key)

    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor=actor,
        action_type="record_flags_updated",
        target_table="patient_flags",
        description="keys=" + ",".join(changed),
    )
    return {
        row.flag_key: row.value
        for row in repo.list_patient_flags(
            tenant_id=tenant_id, patient_link_id=patient_link_id
        )
    }


@transaction.atomic
def add_condition(
    *,
    tenant_id: int,
    patient_link_id: int,
    condition_id: int,
    stage: Optional[str],
    onset_date: Any,
    notes: Optional[str],
    actor: Any,
) -> PatientCondition:
    set_tenant_guc(tenant_id)
    repo = RecordRepository()
    condition = repo.get_condition(tenant_id=tenant_id, condition_id=condition_id)
    if condition is None:
        raise RecordValidationError("بیماری انتخاب‌شده معتبر نیست.", "invalid_condition")

    existing = repo.find_condition_assignment(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        condition_id=condition_id,
    )
    parsed_onset = _iso_date(onset_date, field="تاریخ شروع بیماری")
    if existing and existing.is_active:
        raise RecordConflict("این بیماری قبلاً برای بیمار فعال شده است.", "duplicate_condition")
    if existing:
        existing.stage = _clean(stage)
        existing.onset_date = parsed_onset
        existing.notes = _clean(notes)
        existing.is_active = True
        existing.diagnosed_at = timezone.now()
        existing.save(
            update_fields=[
                "stage",
                "onset_date",
                "notes",
                "is_active",
                "diagnosed_at",
            ]
        )
        row = existing
    else:
        row = repo.create_patient_condition(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
            condition_id=condition_id,
            stage=_clean(stage),
            onset_date=parsed_onset,
            notes=_clean(notes),
            is_active=True,
            diagnosed_at=timezone.now(),
        )

    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor=actor,
        action_type="record_condition_added",
        target_table="patient_conditions",
        target_id=row.id,
        description=f"condition_id={condition_id}",
    )
    return row


@transaction.atomic
def remove_condition(
    *,
    tenant_id: int,
    patient_link_id: int,
    patient_condition_id: int,
    actor: Any,
) -> None:
    set_tenant_guc(tenant_id)
    row = RecordRepository().get_patient_condition(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        row_id=patient_condition_id,
    )
    if row is None or not row.is_active:
        raise RecordNotFound("بیماری فعال پیدا نشد.")
    row.is_active = False
    row.save(update_fields=["is_active"])
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor=actor,
        action_type="record_condition_removed",
        target_table="patient_conditions",
        target_id=patient_condition_id,
        description=f"condition_id={row.condition_id}",
    )


@transaction.atomic
def add_medication(
    *,
    tenant_id: int,
    patient_link_id: int,
    actor: Any,
    drug_id: Optional[int] = None,
    drug_name: Optional[str] = None,
    drug_class: Optional[str] = None,
    dose: Optional[str] = None,
    schedule: Optional[str] = None,
    start_date: Any = None,
    refill_interval_days: Optional[int] = None,
    notes: Optional[str] = None,
) -> PatientMedication:
    set_tenant_guc(tenant_id)
    repo = RecordRepository()

    if drug_id is not None:
        catalog_drug = repo.get_drug(tenant_id=tenant_id, drug_id=drug_id)
        if catalog_drug is None:
            raise RecordValidationError("داروی کاتالوگی معتبر نیست.", "invalid_drug")
        clean_name = catalog_drug.generic_fa
        clean_class = catalog_drug.drug_class_key
    else:
        clean_name = _clean(drug_name)
        clean_class = _clean(drug_class)
        if not clean_name:
            raise RecordValidationError("نام دارو الزامی است.", "drug_name_required")
        if clean_class and repo.get_drug_class(
            tenant_id=tenant_id, class_key=clean_class
        ) is None:
            raise RecordValidationError("کلاس دارویی معتبر نیست.", "invalid_drug_class")

    start = _iso_date(start_date, field="تاریخ شروع دارو") or timezone.localdate()
    refill_due = None
    if refill_interval_days is not None:
        interval = int(refill_interval_days)
        if interval not in ALLOWED_REFILL_INTERVALS:
            raise RecordValidationError(
                "فاصلهٔ تجدید نسخه باید یکی از ۱۵، ۳۰، ۶۰ یا ۹۰ روز باشد.",
                "invalid_refill_interval",
            )
        refill_due = start + timedelta(days=interval)

    _actor_id, username = _actor_fields(actor)
    row = repo.create_medication(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        drug_name=clean_name,
        dose=_clean(dose),
        schedule=_clean(schedule),
        start_date=start,
        refill_due_date=refill_due,
        end_date=None,
        drug_class=clean_class,
        is_active=True,
        notes=_clean(notes),
        created_at=timezone.now(),
    )
    repo.create_medication_event(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        medication_id=row.id,
        drug_name=row.drug_name,
        event_type="start",
        dose=row.dose,
        event_date=start,
        created_by=username,
    )
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor=actor,
        action_type="record_medication_added",
        target_table="patient_medications",
        target_id=row.id,
    )
    return row


@transaction.atomic
def change_medication_dose(
    *,
    tenant_id: int,
    patient_link_id: int,
    medication_id: int,
    new_dose: str,
    change_date: Any,
    note: Optional[str],
    actor: Any,
) -> PatientMedication:
    set_tenant_guc(tenant_id)
    clean_dose = _clean(new_dose)
    if not clean_dose:
        raise RecordValidationError("دوز جدید الزامی است.", "dose_required")
    repo = RecordRepository()
    row = repo.get_medication_for_update(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        medication_id=medication_id,
    )
    if row is None:
        raise RecordNotFound("دارو پیدا نشد.")
    if not row.is_active:
        raise RecordConflict("دوز داروی قطع‌شده قابل تغییر نیست.", "medication_inactive")

    event_date = _iso_date(change_date, field="تاریخ تغییر دوز") or timezone.localdate()
    row.dose = clean_dose
    row.save(update_fields=["dose"])
    _actor_id, username = _actor_fields(actor)
    repo.create_medication_event(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        medication_id=row.id,
        drug_name=row.drug_name,
        event_type="dose_change",
        dose=clean_dose,
        event_date=event_date,
        note=_clean(note),
        created_by=username,
    )
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor=actor,
        action_type="record_medication_dose_changed",
        target_table="patient_medications",
        target_id=row.id,
    )
    return row


@transaction.atomic
def stop_medication(
    *,
    tenant_id: int,
    patient_link_id: int,
    medication_id: int,
    end_date: Any,
    note: Optional[str],
    actor: Any,
) -> PatientMedication:
    set_tenant_guc(tenant_id)
    repo = RecordRepository()
    row = repo.get_medication_for_update(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        medication_id=medication_id,
    )
    if row is None:
        raise RecordNotFound("دارو پیدا نشد.")
    if not row.is_active:
        raise RecordConflict("این دارو قبلاً قطع شده است.", "medication_inactive")

    stop_date = _iso_date(end_date, field="تاریخ قطع دارو") or timezone.localdate()
    if row.start_date and stop_date < row.start_date:
        raise RecordValidationError(
            "تاریخ قطع نمی‌تواند قبل از تاریخ شروع باشد.", "invalid_end_date"
        )
    row.is_active = False
    row.end_date = stop_date
    row.save(update_fields=["is_active", "end_date"])
    _actor_id, username = _actor_fields(actor)
    repo.create_medication_event(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        medication_id=row.id,
        drug_name=row.drug_name,
        event_type="stop",
        dose=row.dose,
        event_date=stop_date,
        note=_clean(note),
        created_by=username,
    )
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor=actor,
        action_type="record_medication_stopped",
        target_table="patient_medications",
        target_id=row.id,
    )
    return row


@transaction.atomic
def add_labs(
    *,
    tenant_id: int,
    patient_link_id: int,
    items: list[Mapping[str, Any]],
    taken_at: Optional[datetime],
    actor: Any,
) -> list[Any]:
    set_tenant_guc(tenant_id)
    if not items:
        raise RecordValidationError("حداقل یک آزمایش لازم است.", "lab_items_required")
    if len(items) > 50:
        raise RecordValidationError("حداکثر ۵۰ آزمایش در یک ثبت مجاز است.")

    keys = [_clean(item.get("test_key")) for item in items]
    if any(key is None for key in keys):
        raise RecordValidationError("test_key هر آزمایش الزامی است.", "test_key_required")
    if len(set(keys)) != len(keys):
        raise RecordValidationError(
            "یک آزمایش در یک درخواست دوبار تکرار شده است.", "duplicate_test_key"
        )

    repo = RecordRepository()
    catalog = repo.get_labs_by_keys(tenant_id=tenant_id, keys=keys)
    missing = sorted(set(keys) - set(catalog))
    if missing:
        raise RecordValidationError(
            "آزمایش کاتالوگی نامعتبر: " + ", ".join(missing),
            "invalid_lab_test",
        )

    _actor_id, username = _actor_fields(actor)
    timestamp = _aware_datetime(taken_at)
    validated = [
        (
            catalog[key],
            _finite_number(item.get("value"), field=catalog[key].name_fa),
            _clean(item.get("notes")),
        )
        for key, item in zip(keys, items)
    ]

    created = []
    try:
        for definition, value, note in validated:
            created.append(
                repo.create_lab(
                    tenant_id=tenant_id,
                    patient_link_id=patient_link_id,
                    test_name=definition.name_fa,
                    test_key=definition.test_key,
                    value=value,
                    unit=definition.unit,
                    ref_low=definition.ref_low,
                    ref_high=definition.ref_high,
                    taken_at=timestamp,
                    notes=note,
                    recorded_by=username,
                    encounter_id=None,
                )
            )
    except IntegrityError as exc:
        raise RecordConflict(
            "ثبت آزمایش‌ها با یک دادهٔ موجود تعارض دارد.", "duplicate_lab"
        ) from exc

    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor=actor,
        action_type="record_labs_added",
        target_table="lab_results",
        description=f"count={len(created)};keys={','.join(keys)}",
    )
    return created


@transaction.atomic
def delete_lab(
    *, tenant_id: int, patient_link_id: int, lab_id: int, actor: Any
) -> None:
    set_tenant_guc(tenant_id)
    row = RecordRepository().get_lab(
        tenant_id=tenant_id, patient_link_id=patient_link_id, lab_id=lab_id
    )
    if row is None:
        raise RecordNotFound("آزمایش پیدا نشد.")
    row.delete()
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor=actor,
        action_type="record_lab_deleted",
        target_table="lab_results",
        target_id=lab_id,
    )


@transaction.atomic
def add_vitals(
    *,
    tenant_id: int,
    patient_link_id: int,
    items: list[Mapping[str, Any]],
    measured_at: Optional[datetime],
    actor: Any,
) -> list[Any]:
    set_tenant_guc(tenant_id)
    if not items:
        raise RecordValidationError("حداقل یک شاخص لازم است.", "vital_items_required")
    if len(items) > 30:
        raise RecordValidationError("حداکثر ۳۰ شاخص در یک ثبت مجاز است.")

    keys = [_clean(item.get("type")) for item in items]
    if any(key is None for key in keys):
        raise RecordValidationError("نوع هر شاخص الزامی است.", "vital_type_required")
    if len(set(keys)) != len(keys):
        raise RecordValidationError(
            "یک شاخص در یک درخواست دوبار تکرار شده است.", "duplicate_vital_type"
        )

    repo = RecordRepository()
    indicators = {
        row.key: row for row in repo.list_indicators(tenant_id=tenant_id)
    }
    missing = sorted(set(keys) - set(indicators))
    if missing:
        raise RecordValidationError(
            "شاخص نامعتبر: " + ", ".join(missing), "invalid_vital_type"
        )

    timestamp = _aware_datetime(measured_at)
    _actor_id, username = _actor_fields(actor)
    validated = [
        (
            key,
            _finite_number(item.get("value"), field=indicators[key].label),
            _clean(item.get("notes")),
        )
        for key, item in zip(keys, items)
    ]
    created = []
    try:
        for key, value, note in validated:
            created.append(
                repo.create_vital(
                    tenant_id=tenant_id,
                    patient_link_id=patient_link_id,
                    type=key,
                    value=value,
                    unit=indicators[key].unit,
                    measured_at=timestamp,
                    source="clinic",
                    notes=note,
                    recorded_by=username,
                    encounter_id=None,
                    verified=True,
                )
            )
    except IntegrityError as exc:
        raise RecordConflict(
            "ثبت شاخص‌ها با یک اندازه‌گیری موجود تعارض دارد.", "duplicate_vital"
        ) from exc

    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor=actor,
        action_type="record_vitals_added",
        target_table="vital_readings",
        description=f"count={len(created)};types={','.join(keys)}",
    )
    return created


@transaction.atomic
def delete_vital(
    *, tenant_id: int, patient_link_id: int, vital_id: int, actor: Any
) -> None:
    set_tenant_guc(tenant_id)
    row = RecordRepository().get_vital(
        tenant_id=tenant_id, patient_link_id=patient_link_id, vital_id=vital_id
    )
    if row is None:
        raise RecordNotFound("شاخص پیدا نشد.")
    if row.source in {"patient_self", "self"}:
        raise RecordConflict(
            "دادهٔ خوداظهاری برای حفظ سابقهٔ بازبینی حذف نمی‌شود.",
            "self_report_delete_blocked",
        )
    row.delete()
    _audit(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        actor=actor,
        action_type="record_vital_deleted",
        target_table="vital_readings",
        target_id=vital_id,
    )
