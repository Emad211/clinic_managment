"""Complete patient-record API ported from ``specialist_clinic``.

The existing ``/patients/{uuid}/record`` safety cockpit remains backward
compatible.  This router adds the structured editable record projection and
tenant-safe mutation endpoints used by the Record and Medications tabs.
"""
from __future__ import annotations

import uuid as uuid_module
from datetime import date, datetime
from typing import Any, Optional

from ninja import Router, Schema

from clinical.api._shared import _resolve_patient_link_and_demo_for_tenant
from clinical.record_service import (
    RecordServiceError,
    add_condition,
    add_labs,
    add_medical_history,
    add_medication,
    add_note,
    add_surgery,
    add_vitals,
    change_medication_dose,
    delete_lab,
    delete_medical_history,
    delete_note,
    delete_surgery,
    delete_vital,
    get_record_data,
    remove_condition,
    stop_medication,
    update_flags,
)
from config.api_base import _jwt_auth
from config.errors import ErrorSchema, error_response


router = Router()


class ConditionCatalogDTO(Schema):
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
    body: str
    recorded_at: datetime
    recorded_by: Optional[str] = None


class FlagOptionDTO(Schema):
    value: str
    label: str


class FlagCatalogDTO(Schema):
    flag_key: str
    label: str
    flag_type: str
    options: list[FlagOptionDTO]
    category: str
    category_label: str
    record_section: str
    display_order: int


class LabCatalogDTO(Schema):
    id: int
    test_key: str
    name_fa: str
    unit: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    category: Optional[str] = None
    display_order: int


class LabResultDTO(Schema):
    id: int
    test_name: str
    test_key: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    taken_at: datetime
    notes: Optional[str] = None
    recorded_by: Optional[str] = None
    encounter_id: Optional[int] = None


class IndicatorCatalogDTO(Schema):
    key: str
    label: str
    unit: Optional[str] = None
    category: str
    display_order: int


class DrugClassDTO(Schema):
    class_key: str
    label: str
    glucose_lowering: bool
    display_order: int


class DrugCatalogDTO(Schema):
    id: int
    generic_fa: str
    drug_class_key: Optional[str] = None
    doses: list[str]


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


class AppointmentDTO(Schema):
    id: int
    scheduled_at: datetime
    appt_type: Optional[str] = None
    status: str
    notes: Optional[str] = None
    chief_complaint: Optional[str] = None
    doctor_id: Optional[int] = None


class PrescriptionSummaryDTO(Schema):
    id: int
    kind: str
    mode: Optional[str] = None
    insurer: Optional[str] = None
    portal_rx_id: Optional[str] = None
    issued_at: datetime
    item_count: int
    items: Any = None


class AccountingVisitHistoryDTO(Schema):
    visit_id: int
    invoice_id: Optional[int] = None
    visit_date: datetime
    work_date: Optional[date] = None
    doctor_name: Optional[str] = None
    price: int
    status: Optional[str] = None


class RecordDataDTO(Schema):
    condition_catalog: list[ConditionCatalogDTO]
    conditions: list[RecordConditionDTO]
    surgeries: list[SurgeryDTO]
    medical_history: list[MedicalHistoryDTO]
    notes: list[ClinicalNoteDTO]
    flag_catalog: list[FlagCatalogDTO]
    patient_flags: dict[str, Optional[str]]
    lab_catalog: list[LabCatalogDTO]
    suggested_labs: list[LabCatalogDTO]
    labs: list[LabResultDTO]
    indicator_catalog: list[IndicatorCatalogDTO]
    drug_classes: list[DrugClassDTO]
    drug_catalog: list[DrugCatalogDTO]
    medications: list[RecordMedicationDTO]
    medication_events: list[MedicationEventDTO]
    appointments: list[AppointmentDTO]
    prescriptions: list[PrescriptionSummaryDTO]
    accounting_visit_history: list[AccountingVisitHistoryDTO]


class RecordMutationOut(Schema):
    id: int
    changed: bool = True


class DeleteOut(Schema):
    deleted: bool
    id: int


class FlagsOut(Schema):
    values: dict[str, Optional[str]]


class BulkCreatedOut(Schema):
    count: int
    ids: list[int]


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


class FlagsIn(Schema):
    managed_keys: list[str]
    values: dict[str, Any]


class ConditionIn(Schema):
    condition_id: int
    stage: Optional[str] = None
    onset_date: Optional[date] = None
    notes: Optional[str] = None


class MedicationIn(Schema):
    drug_id: Optional[int] = None
    drug_name: Optional[str] = None
    drug_class: Optional[str] = None
    dose: Optional[str] = None
    schedule: Optional[str] = None
    start_date: Optional[date] = None
    refill_interval_days: Optional[int] = None
    notes: Optional[str] = None


class DoseChangeIn(Schema):
    new_dose: str
    change_date: Optional[date] = None
    note: Optional[str] = None


class StopMedicationIn(Schema):
    end_date: Optional[date] = None
    note: Optional[str] = None


class LabEntryIn(Schema):
    test_key: str
    value: float
    notes: Optional[str] = None


class BulkLabsIn(Schema):
    items: list[LabEntryIn]
    taken_at: Optional[datetime] = None


class VitalEntryIn(Schema):
    type: str
    value: float
    notes: Optional[str] = None


class BulkVitalsIn(Schema):
    items: list[VitalEntryIn]
    measured_at: Optional[datetime] = None


def _error(exc: RecordServiceError):
    return exc.status, error_response(str(exc), exc.code)


def _actor(request):
    return request.auth


def _medication_to_dto(row) -> RecordMedicationDTO:
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
    )


def _resolve(request, patient_uuid):
    return _resolve_patient_link_and_demo_for_tenant(
        patient_uuid, request.tenant_id
    )


@router.get(
    "/patients/{patient_uuid}/record-data",
    response=RecordDataDTO,
    auth=_jwt_auth,
    tags=["patient-record"],
)
def record_data(request, patient_uuid: uuid_module.UUID):
    link, demo = _resolve(request, patient_uuid)
    return get_record_data(
        tenant_id=request.tenant_id,
        patient_link_id=link.id,
        accounting_patient_id=demo.id,
    )


@router.post(
    "/patients/{patient_uuid}/record/conditions",
    response={201: RecordMutationOut, 404: ErrorSchema, 409: ErrorSchema, 422: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def create_condition(request, patient_uuid: uuid_module.UUID, payload: ConditionIn):
    link, _demo = _resolve(request, patient_uuid)
    try:
        row = add_condition(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            condition_id=payload.condition_id,
            stage=payload.stage,
            onset_date=payload.onset_date,
            notes=payload.notes,
            actor=_actor(request),
        )
    except RecordServiceError as exc:
        return _error(exc)
    return 201, RecordMutationOut(id=row.id)


@router.delete(
    "/patients/{patient_uuid}/record/conditions/{row_id}",
    response={200: DeleteOut, 404: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def delete_condition(request, patient_uuid: uuid_module.UUID, row_id: int):
    link, _demo = _resolve(request, patient_uuid)
    try:
        remove_condition(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            patient_condition_id=row_id,
            actor=_actor(request),
        )
    except RecordServiceError as exc:
        return _error(exc)
    return DeleteOut(deleted=True, id=row_id)


@router.post(
    "/patients/{patient_uuid}/record/surgeries",
    response={201: SurgeryDTO, 404: ErrorSchema, 422: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def create_surgery(request, patient_uuid: uuid_module.UUID, payload: SurgeryIn):
    link, _demo = _resolve(request, patient_uuid)
    try:
        row = add_surgery(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            title=payload.title,
            performed_on=payload.performed_on,
            note=payload.note,
            actor=_actor(request),
        )
    except RecordServiceError as exc:
        return _error(exc)
    return 201, SurgeryDTO(
        id=row.id,
        title=row.title,
        performed_on=row.performed_on,
        note=row.note,
        created_at=row.created_at,
    )


@router.delete(
    "/patients/{patient_uuid}/record/surgeries/{row_id}",
    response={200: DeleteOut, 404: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def remove_surgery_endpoint(request, patient_uuid: uuid_module.UUID, row_id: int):
    link, _demo = _resolve(request, patient_uuid)
    try:
        delete_surgery(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            row_id=row_id,
            actor=_actor(request),
        )
    except RecordServiceError as exc:
        return _error(exc)
    return DeleteOut(deleted=True, id=row_id)


@router.post(
    "/patients/{patient_uuid}/record/medical-history",
    response={201: MedicalHistoryDTO, 404: ErrorSchema, 422: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def create_history(
    request, patient_uuid: uuid_module.UUID, payload: MedicalHistoryIn
):
    link, _demo = _resolve(request, patient_uuid)
    try:
        row = add_medical_history(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            title=payload.title,
            since=payload.since,
            note=payload.note,
            actor=_actor(request),
        )
    except RecordServiceError as exc:
        return _error(exc)
    return 201, MedicalHistoryDTO(
        id=row.id,
        title=row.title,
        since=row.since,
        note=row.note,
        created_at=row.created_at,
    )


@router.delete(
    "/patients/{patient_uuid}/record/medical-history/{row_id}",
    response={200: DeleteOut, 404: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def remove_history_endpoint(request, patient_uuid: uuid_module.UUID, row_id: int):
    link, _demo = _resolve(request, patient_uuid)
    try:
        delete_medical_history(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            row_id=row_id,
            actor=_actor(request),
        )
    except RecordServiceError as exc:
        return _error(exc)
    return DeleteOut(deleted=True, id=row_id)


@router.post(
    "/patients/{patient_uuid}/record/notes",
    response={201: ClinicalNoteDTO, 404: ErrorSchema, 422: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def create_note_endpoint(
    request, patient_uuid: uuid_module.UUID, payload: ClinicalNoteIn
):
    link, _demo = _resolve(request, patient_uuid)
    try:
        row = add_note(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            kind=payload.kind,
            body=payload.body,
            actor=_actor(request),
        )
    except RecordServiceError as exc:
        return _error(exc)
    return 201, ClinicalNoteDTO(
        id=row.id,
        kind=row.kind,
        body=row.body or "",
        recorded_at=row.recorded_at,
        recorded_by=row.recorded_by,
    )


@router.delete(
    "/patients/{patient_uuid}/record/notes/{row_id}",
    response={200: DeleteOut, 404: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def remove_note_endpoint(request, patient_uuid: uuid_module.UUID, row_id: int):
    link, _demo = _resolve(request, patient_uuid)
    try:
        delete_note(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            row_id=row_id,
            actor=_actor(request),
        )
    except RecordServiceError as exc:
        return _error(exc)
    return DeleteOut(deleted=True, id=row_id)


@router.put(
    "/patients/{patient_uuid}/record/flags",
    response={200: FlagsOut, 404: ErrorSchema, 422: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def save_flags(request, patient_uuid: uuid_module.UUID, payload: FlagsIn):
    link, _demo = _resolve(request, patient_uuid)
    try:
        values = update_flags(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            managed_keys=payload.managed_keys,
            values=payload.values,
            actor=_actor(request),
        )
    except RecordServiceError as exc:
        return _error(exc)
    return FlagsOut(values=values)


@router.post(
    "/patients/{patient_uuid}/record/medications",
    response={201: RecordMedicationDTO, 404: ErrorSchema, 422: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def create_medication(
    request, patient_uuid: uuid_module.UUID, payload: MedicationIn
):
    link, _demo = _resolve(request, patient_uuid)
    try:
        row = add_medication(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            actor=_actor(request),
            **payload.model_dump(),
        )
    except RecordServiceError as exc:
        return _error(exc)
    return 201, _medication_to_dto(row)


@router.post(
    "/patients/{patient_uuid}/record/medications/{medication_id}/dose",
    response={200: RecordMedicationDTO, 404: ErrorSchema, 409: ErrorSchema, 422: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def update_medication_dose(
    request,
    patient_uuid: uuid_module.UUID,
    medication_id: int,
    payload: DoseChangeIn,
):
    link, _demo = _resolve(request, patient_uuid)
    try:
        row = change_medication_dose(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            medication_id=medication_id,
            new_dose=payload.new_dose,
            change_date=payload.change_date,
            note=payload.note,
            actor=_actor(request),
        )
    except RecordServiceError as exc:
        return _error(exc)
    return _medication_to_dto(row)


@router.post(
    "/patients/{patient_uuid}/record/medications/{medication_id}/stop",
    response={200: RecordMedicationDTO, 404: ErrorSchema, 409: ErrorSchema, 422: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def stop_medication_endpoint(
    request,
    patient_uuid: uuid_module.UUID,
    medication_id: int,
    payload: StopMedicationIn,
):
    link, _demo = _resolve(request, patient_uuid)
    try:
        row = stop_medication(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            medication_id=medication_id,
            end_date=payload.end_date,
            note=payload.note,
            actor=_actor(request),
        )
    except RecordServiceError as exc:
        return _error(exc)
    return _medication_to_dto(row)


@router.post(
    "/patients/{patient_uuid}/record/labs",
    response={201: BulkCreatedOut, 404: ErrorSchema, 409: ErrorSchema, 422: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def create_labs(request, patient_uuid: uuid_module.UUID, payload: BulkLabsIn):
    link, _demo = _resolve(request, patient_uuid)
    try:
        rows = add_labs(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            items=[item.model_dump() for item in payload.items],
            taken_at=payload.taken_at,
            actor=_actor(request),
        )
    except RecordServiceError as exc:
        return _error(exc)
    return 201, BulkCreatedOut(count=len(rows), ids=[row.id for row in rows])


@router.delete(
    "/patients/{patient_uuid}/record/labs/{lab_id}",
    response={200: DeleteOut, 404: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def remove_lab_endpoint(request, patient_uuid: uuid_module.UUID, lab_id: int):
    link, _demo = _resolve(request, patient_uuid)
    try:
        delete_lab(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            lab_id=lab_id,
            actor=_actor(request),
        )
    except RecordServiceError as exc:
        return _error(exc)
    return DeleteOut(deleted=True, id=lab_id)


@router.post(
    "/patients/{patient_uuid}/record/vitals",
    response={201: BulkCreatedOut, 404: ErrorSchema, 409: ErrorSchema, 422: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def create_vitals(request, patient_uuid: uuid_module.UUID, payload: BulkVitalsIn):
    link, _demo = _resolve(request, patient_uuid)
    try:
        rows = add_vitals(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            items=[item.model_dump() for item in payload.items],
            measured_at=payload.measured_at,
            actor=_actor(request),
        )
    except RecordServiceError as exc:
        return _error(exc)
    return 201, BulkCreatedOut(count=len(rows), ids=[row.id for row in rows])


@router.delete(
    "/patients/{patient_uuid}/record/vitals/{vital_id}",
    response={200: DeleteOut, 404: ErrorSchema, 409: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-record"],
)
def remove_vital_endpoint(request, patient_uuid: uuid_module.UUID, vital_id: int):
    link, _demo = _resolve(request, patient_uuid)
    try:
        delete_vital(
            tenant_id=request.tenant_id,
            patient_link_id=link.id,
            vital_id=vital_id,
            actor=_actor(request),
        )
    except RecordServiceError as exc:
        return _error(exc)
    return DeleteOut(deleted=True, id=vital_id)
