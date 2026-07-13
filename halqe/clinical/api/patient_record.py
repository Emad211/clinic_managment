"""Typed JWT API for the structured patient-record aggregate."""
from __future__ import annotations

import uuid as uuid_module
from datetime import date, datetime
from typing import Any, Optional

from ninja import Router, Schema
from pydantic import Field

from clinical.api._shared import _resolve_patient_link_for_tenant
from clinical.models import Condition
from clinical.patient_record_service import (
    PatientRecordConflict,
    PatientRecordNotFound,
    PatientRecordValidationError,
    add_clinical_note,
    add_condition,
    add_lab_result,
    add_medical_history,
    add_medication,
    add_surgery,
    change_medication_dose,
    deactivate_condition,
    delete_clinical_note,
    delete_lab_result,
    delete_medical_history,
    delete_surgery,
    get_structured_record,
    patch_flags,
    stop_medication,
)
from config.api_base import _jwt_auth
from config.errors import ErrorSchema, error_response

router = Router()


# ---------------------------------------------------------------------------
# Output contracts
# ---------------------------------------------------------------------------
class CatalogConditionDTO(Schema):
    id: int
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    display_order: int


class RecordConditionDTO(Schema):
    id: int
    condition_id: int
    condition_name: Optional[str] = None
    condition_code: Optional[str] = None
    stage: Optional[str] = None
    onset_date: Optional[date] = None
    notes: Optional[str] = None
    is_active: bool
    diagnosed_at: datetime


class MedicationEventDTO(Schema):
    id: int
    medication_id: Optional[int] = None
    drug_name: str
    event_type: str
    dose: Optional[str] = None
    event_date: Optional[date] = None
    note: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime


class RecordMedicationDTO(Schema):
    id: int
    drug_name: str
    dose: Optional[str] = None
    schedule: Optional[str] = None
    start_date: Optional[date] = None
    refill_due_date: Optional[date] = None
    end_date: Optional[date] = None
    drug_class: Optional[str] = None
    is_active: bool
    notes: Optional[str] = None
    created_at: datetime
    events: list[MedicationEventDTO] = Field(default_factory=list)


class FlagOptionDTO(Schema):
    value: str
    label: str


class RecordFlagDTO(Schema):
    id: int
    flag_key: str
    label: str
    flag_type: str
    options: list[FlagOptionDTO] = Field(default_factory=list)
    category: str
    record_section: str
    display_order: int
    notes: Optional[str] = None
    value: Optional[str] = None
    recorded_by: Optional[str] = None
    updated_at: Optional[datetime] = None


class SurgeryDTO(Schema):
    id: int
    title: str
    performed_on: Optional[date] = None
    note: Optional[str] = None
    created_at: datetime


class MedicalHistoryDTO(Schema):
    id: int
    title: str
    since: Optional[date] = None
    note: Optional[str] = None
    created_at: datetime


class ClinicalNoteDTO(Schema):
    id: int
    kind: str
    body: Optional[str] = None
    recorded_at: datetime
    recorded_by: Optional[str] = None


class LabResultDTO(Schema):
    id: int
    encounter_id: Optional[int] = None
    test_name: str
    test_key: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    taken_at: datetime
    notes: Optional[str] = None
    recorded_by: Optional[str] = None


class LabCatalogDTO(Schema):
    id: int
    test_key: str
    name_fa: str
    unit: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    category: Optional[str] = None
    display_order: int
    suggested: bool


class AppointmentDTO(Schema):
    id: int
    scheduled_at: datetime
    appt_type: Optional[str] = None
    status: str
    recurrence_months: Optional[int] = None
    reminder_sent: bool
    notes: Optional[str] = None
    doctor_id: Optional[int] = None
    chief_complaint: Optional[str] = None


class FollowupDTO(Schema):
    id: int
    due_date: Optional[date] = None
    reason: Optional[str] = None
    detail: Optional[str] = None
    status: str
    assigned_to: Optional[str] = None
    call_log: Optional[str] = None
    source_rule: Optional[str] = None
    source_event: Optional[str] = None
    appointment_id: Optional[int] = None
    fulfillment: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None


class PrescriptionItemDTO(Schema):
    id: Optional[int] = None
    drug_name: str
    drug_class: Optional[str] = None
    dose_value: Optional[str] = None
    dose_unit: Optional[str] = None
    frequency: Optional[str] = None
    route: Optional[str] = None
    quantity: Optional[int] = None
    duration_days: Optional[int] = None
    instructions: Optional[str] = None
    source: str


class PrescriptionDTO(Schema):
    id: int
    kind: str
    mode: str
    insurer: Optional[str] = None
    portal_rx_id: Optional[str] = None
    prescriber_user_id: Optional[int] = None
    followup_task_id: Optional[int] = None
    encounter_id: Optional[int] = None
    issued_at: datetime
    items: list[PrescriptionItemDTO] = Field(default_factory=list)


class DrugClassDTO(Schema):
    id: int
    class_key: str
    label: str
    glucose_lowering: bool
    display_order: int


class DrugCatalogDTO(Schema):
    id: int
    generic_fa: str
    drug_class_key: Optional[str] = None
    standard_doses: list[str] = Field(default_factory=list)


class StructuredRecordDTO(Schema):
    patient_link_id: int
    condition_catalog: list[CatalogConditionDTO]
    conditions: list[RecordConditionDTO]
    medications: list[RecordMedicationDTO]
    orphan_medication_events: list[MedicationEventDTO]
    flag_catalog: list[RecordFlagDTO]
    surgeries: list[SurgeryDTO]
    medical_history: list[MedicalHistoryDTO]
    clinical_notes: list[ClinicalNoteDTO]
    labs: list[LabResultDTO]
    lab_catalog: list[LabCatalogDTO]
    appointments: list[AppointmentDTO]
    followups: list[FollowupDTO]
    prescriptions: list[PrescriptionDTO]
    drug_classes: list[DrugClassDTO]
    drug_catalog: list[DrugCatalogDTO]


class DeleteOut(Schema):
    deleted: bool
    id: int


# ---------------------------------------------------------------------------
# Input contracts
# ---------------------------------------------------------------------------
class ConditionIn(Schema):
    condition_id: int
    stage: Optional[str] = None
    onset_date: Optional[date] = None
    notes: Optional[str] = None


class MedicationIn(Schema):
    drug_name: str
    dose: Optional[str] = None
    schedule: Optional[str] = None
    start_date: Optional[date] = None
    refill_due_date: Optional[date] = None
    refill_interval_days: Optional[int] = None
    notes: Optional[str] = None
    drug_class: Optional[str] = None


class MedicationStopIn(Schema):
    end_date: Optional[date] = None
    note: Optional[str] = None


class MedicationDoseIn(Schema):
    dose: str
    change_date: Optional[date] = None
    note: Optional[str] = None


class FlagsPatchIn(Schema):
    values: dict[str, Any] = Field(default_factory=dict)
    clear_keys: list[str] = Field(default_factory=list)


class SurgeryIn(Schema):
    title: str
    performed_on: Optional[date] = None
    note: Optional[str] = None


class MedicalHistoryIn(Schema):
    title: str
    since: Optional[date] = None
    note: Optional[str] = None


class ClinicalNoteIn(Schema):
    kind: str
    body: str


class LabResultIn(Schema):
    test_key: Optional[str] = None
    test_name: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    taken_at: Optional[datetime] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _actor(request) -> tuple[str, Optional[int]]:
    return (
        getattr(request.auth, "username", None) or "unknown",
        getattr(request.auth, "pk", None),
    )


def _error(exc: Exception):
    if isinstance(exc, PatientRecordNotFound):
        return 404, error_response(str(exc), "not_found")
    if isinstance(exc, PatientRecordConflict):
        return 409, error_response(str(exc), "conflict")
    return 422, error_response(str(exc), "validation_error")


def _link(request, patient_uuid: uuid_module.UUID):
    return _resolve_patient_link_for_tenant(patient_uuid, request.tenant_id)


def _medication_dto(row) -> RecordMedicationDTO:
    return RecordMedicationDTO(
        id=row.id,
        drug_name=row.drug_name,
        dose=row.dose,
        schedule=row.schedule,
        start_date=row.start_date,
        refill_due_date=row.refill_due_date,
        end_date=row.end_date,
        drug_class=row.drug_class,
        is_active=row.is_active,
        notes=row.notes,
        created_at=row.created_at,
        events=[],
    )


# ---------------------------------------------------------------------------
# Aggregate read
# ---------------------------------------------------------------------------
@router.get(
    "/patients/{patient_uuid}/record/structured",
    response=StructuredRecordDTO,
    auth=_jwt_auth,
    tags=["patient-record"],
)
def structured_record(request, patient_uuid: uuid_module.UUID):
    link = _link(request, patient_uuid)
    return get_structured_record(
        tenant_id=request.tenant_id,
        patient_link_id=link.id,
    )


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------
@router.post(
    "/patients/{patient_uuid}/record/conditions",
    response={201: RecordConditionDTO, 404: ErrorSchema, 409: ErrorSchema, 422: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def create_condition(request, patient_uuid: uuid_module.UUID, payload: ConditionIn):
    link = _link(request, patient_uuid)
    username, user_id = _actor(request)
    try:
        row = add_condition(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            condition_id=payload.condition_id,
            stage=payload.stage,
            onset_date=payload.onset_date,
            notes=payload.notes,
            actor_username=username,
            actor_id=user_id,
        )
    except (PatientRecordNotFound, PatientRecordConflict, PatientRecordValidationError) as exc:
        return _error(exc)
    condition = Condition.objects.filter(
        tenant_id=request.tenant_id,
        id=row.condition_id,
    ).first()
    return 201, RecordConditionDTO(
        id=row.id,
        condition_id=row.condition_id,
        condition_name=condition.name if condition else None,
        condition_code=condition.code if condition else None,
        stage=row.stage,
        onset_date=row.onset_date,
        notes=row.notes,
        is_active=row.is_active,
        diagnosed_at=row.diagnosed_at,
    )


@router.delete(
    "/patients/{patient_uuid}/record/conditions/{patient_condition_id}",
    response={200: DeleteOut, 404: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def remove_condition(request, patient_uuid: uuid_module.UUID, patient_condition_id: int):
    link = _link(request, patient_uuid)
    username, user_id = _actor(request)
    try:
        row_id = deactivate_condition(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            patient_condition_id=patient_condition_id,
            actor_username=username,
            actor_id=user_id,
        )
    except PatientRecordNotFound as exc:
        return _error(exc)
    return DeleteOut(deleted=True, id=row_id)


# ---------------------------------------------------------------------------
# Medications
# ---------------------------------------------------------------------------
@router.post(
    "/patients/{patient_uuid}/record/medications",
    response={201: RecordMedicationDTO, 404: ErrorSchema, 422: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def create_medication(request, patient_uuid: uuid_module.UUID, payload: MedicationIn):
    link = _link(request, patient_uuid)
    username, user_id = _actor(request)
    try:
        row = add_medication(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            actor_username=username,
            actor_id=user_id,
            **payload.model_dump(),
        )
    except (PatientRecordNotFound, PatientRecordValidationError) as exc:
        return _error(exc)
    return 201, _medication_dto(row)


@router.post(
    "/patients/{patient_uuid}/record/medications/{medication_id}/stop",
    response={200: RecordMedicationDTO, 404: ErrorSchema, 422: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def stop_medication_endpoint(
    request,
    patient_uuid: uuid_module.UUID,
    medication_id: int,
    payload: MedicationStopIn,
):
    link = _link(request, patient_uuid)
    username, user_id = _actor(request)
    try:
        row = stop_medication(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            medication_id=medication_id,
            end_date=payload.end_date,
            note=payload.note,
            actor_username=username,
            actor_id=user_id,
        )
    except (PatientRecordNotFound, PatientRecordValidationError) as exc:
        return _error(exc)
    return _medication_dto(row)


@router.post(
    "/patients/{patient_uuid}/record/medications/{medication_id}/dose",
    response={200: RecordMedicationDTO, 404: ErrorSchema, 422: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def change_dose_endpoint(
    request,
    patient_uuid: uuid_module.UUID,
    medication_id: int,
    payload: MedicationDoseIn,
):
    link = _link(request, patient_uuid)
    username, user_id = _actor(request)
    try:
        row = change_medication_dose(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            medication_id=medication_id,
            new_dose=payload.dose,
            change_date=payload.change_date,
            note=payload.note,
            actor_username=username,
            actor_id=user_id,
        )
    except (PatientRecordNotFound, PatientRecordValidationError) as exc:
        return _error(exc)
    return _medication_dto(row)


# ---------------------------------------------------------------------------
# Typed, partial-safe flags
# ---------------------------------------------------------------------------
@router.patch(
    "/patients/{patient_uuid}/record/flags",
    response={200: list[RecordFlagDTO], 404: ErrorSchema, 422: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def update_flags(request, patient_uuid: uuid_module.UUID, payload: FlagsPatchIn):
    link = _link(request, patient_uuid)
    username, user_id = _actor(request)
    try:
        patch_flags(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            values=payload.values,
            clear_keys=payload.clear_keys,
            actor_username=username,
            actor_id=user_id,
        )
    except (PatientRecordNotFound, PatientRecordValidationError) as exc:
        return _error(exc)
    aggregate = get_structured_record(
        tenant_id=request.tenant_id,
        patient_link_id=link.id,
    )
    changed = set(payload.values) | set(payload.clear_keys)
    return [row for row in aggregate["flag_catalog"] if row["flag_key"] in changed]


# ---------------------------------------------------------------------------
# Medical/surgical history and record notes
# ---------------------------------------------------------------------------
@router.post(
    "/patients/{patient_uuid}/record/surgeries",
    response={201: SurgeryDTO, 404: ErrorSchema, 422: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def create_surgery(request, patient_uuid: uuid_module.UUID, payload: SurgeryIn):
    link = _link(request, patient_uuid)
    username, user_id = _actor(request)
    try:
        row = add_surgery(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            title=payload.title,
            performed_on=payload.performed_on,
            note=payload.note,
            actor_username=username,
            actor_id=user_id,
        )
    except (PatientRecordNotFound, PatientRecordValidationError) as exc:
        return _error(exc)
    return 201, SurgeryDTO(
        id=row.id,
        title=row.title,
        performed_on=row.performed_on,
        note=row.note,
        created_at=row.created_at,
    )


@router.delete(
    "/patients/{patient_uuid}/record/surgeries/{surgery_id}",
    response={200: DeleteOut, 404: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def remove_surgery(request, patient_uuid: uuid_module.UUID, surgery_id: int):
    link = _link(request, patient_uuid)
    username, user_id = _actor(request)
    try:
        deleted_id = delete_surgery(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            surgery_id=surgery_id,
            actor_username=username,
            actor_id=user_id,
        )
    except PatientRecordNotFound as exc:
        return _error(exc)
    return DeleteOut(deleted=True, id=deleted_id)


@router.post(
    "/patients/{patient_uuid}/record/medical-history",
    response={201: MedicalHistoryDTO, 404: ErrorSchema, 422: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def create_medical_history_endpoint(
    request,
    patient_uuid: uuid_module.UUID,
    payload: MedicalHistoryIn,
):
    link = _link(request, patient_uuid)
    username, user_id = _actor(request)
    try:
        row = add_medical_history(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            title=payload.title,
            since=payload.since,
            note=payload.note,
            actor_username=username,
            actor_id=user_id,
        )
    except (PatientRecordNotFound, PatientRecordValidationError) as exc:
        return _error(exc)
    return 201, MedicalHistoryDTO(
        id=row.id,
        title=row.title,
        since=row.since,
        note=row.note,
        created_at=row.created_at,
    )


@router.delete(
    "/patients/{patient_uuid}/record/medical-history/{history_id}",
    response={200: DeleteOut, 404: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def remove_medical_history(request, patient_uuid: uuid_module.UUID, history_id: int):
    link = _link(request, patient_uuid)
    username, user_id = _actor(request)
    try:
        deleted_id = delete_medical_history(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            history_id=history_id,
            actor_username=username,
            actor_id=user_id,
        )
    except PatientRecordNotFound as exc:
        return _error(exc)
    return DeleteOut(deleted=True, id=deleted_id)


@router.post(
    "/patients/{patient_uuid}/record/notes",
    response={201: ClinicalNoteDTO, 404: ErrorSchema, 422: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def create_note(request, patient_uuid: uuid_module.UUID, payload: ClinicalNoteIn):
    link = _link(request, patient_uuid)
    username, user_id = _actor(request)
    try:
        row = add_clinical_note(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            kind=payload.kind,
            body=payload.body,
            actor_username=username,
            actor_id=user_id,
        )
    except (PatientRecordNotFound, PatientRecordValidationError) as exc:
        return _error(exc)
    return 201, ClinicalNoteDTO(
        id=row.id,
        kind=row.kind,
        body=row.body,
        recorded_at=row.recorded_at,
        recorded_by=row.recorded_by,
    )


@router.delete(
    "/patients/{patient_uuid}/record/notes/{note_id}",
    response={200: DeleteOut, 404: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def remove_note(request, patient_uuid: uuid_module.UUID, note_id: int):
    link = _link(request, patient_uuid)
    username, user_id = _actor(request)
    try:
        deleted_id = delete_clinical_note(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            note_id=note_id,
            actor_username=username,
            actor_id=user_id,
        )
    except PatientRecordNotFound as exc:
        return _error(exc)
    return DeleteOut(deleted=True, id=deleted_id)


# ---------------------------------------------------------------------------
# Standalone labs
# ---------------------------------------------------------------------------
@router.post(
    "/patients/{patient_uuid}/record/labs",
    response={201: LabResultDTO, 404: ErrorSchema, 422: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def create_lab(request, patient_uuid: uuid_module.UUID, payload: LabResultIn):
    link = _link(request, patient_uuid)
    username, user_id = _actor(request)
    try:
        row = add_lab_result(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            actor_username=username,
            actor_id=user_id,
            **payload.model_dump(),
        )
    except (PatientRecordNotFound, PatientRecordValidationError) as exc:
        return _error(exc)
    return 201, LabResultDTO(
        id=row.id,
        encounter_id=row.encounter_id,
        test_name=row.test_name,
        test_key=row.test_key,
        value=row.value,
        unit=row.unit,
        ref_low=row.ref_low,
        ref_high=row.ref_high,
        taken_at=row.taken_at,
        notes=row.notes,
        recorded_by=row.recorded_by,
    )


@router.delete(
    "/patients/{patient_uuid}/record/labs/{lab_id}",
    response={200: DeleteOut, 404: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def remove_lab(request, patient_uuid: uuid_module.UUID, lab_id: int):
    link = _link(request, patient_uuid)
    username, user_id = _actor(request)
    try:
        deleted_id = delete_lab_result(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            lab_id=lab_id,
            actor_username=username,
            actor_id=user_id,
        )
    except PatientRecordNotFound as exc:
        return _error(exc)
    return DeleteOut(deleted=True, id=deleted_id)
