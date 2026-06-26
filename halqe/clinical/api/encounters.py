"""
Encounters domain router (cleanup step 7 — god-file split).

Migrated verbatim out of the ``config/api.py`` god-file (Step 10 encounter
write-path + Step 11 free-mode prescription write-path). All JWT, all
tenant-scoped:

  POST /patients/{uuid}/encounters                  → 201 EncounterOut (status=open)
  GET  /patients/{uuid}/encounters                  → paginated encounter list
  POST /encounters/{id}/vitals                      → add list of vitals
  POST /encounters/{id}/labs                        → add list of labs
  POST /encounters/{id}/complete                    → open → completed
  POST /encounters/{id}/cancel                      → open → cancelled
  POST /encounters/{id}/prescriptions               → free-mode prescription

URLs are preserved byte-for-byte: ``config.api`` wires this router with
``api.add_router("", encounters_router)`` and the routes carry their full short
paths, so ``/api/v1`` (urls.py) + the path == the same full paths as before.

BLOCKED TRACK (preserved verbatim): only ``mode='free'`` prescriptions are
supported. ``mode='insurance'`` returns 422 — the insurance/MV3 bridge track is
blocked pending owner live access. Do NOT add mode='insurance' support here.

This module imports FROM ``config.api_base`` (shared ``_jwt_auth``) and
``clinical.api._shared`` (``_resolve_patient_link_for_tenant``); nothing in
either imports a router, so the package stays free of cycles.
"""
from __future__ import annotations

import uuid as uuid_module
from typing import Optional, List as _List
from datetime import datetime

from ninja import Router, Schema, Query

from config.api_base import _jwt_auth
from config.errors import ErrorSchema, error_response
from config.pagination import paginate
from clinical.api._shared import _resolve_patient_link_for_tenant

from clinical.models import (
    Encounter as _Encounter,
    Prescription as _Prescription,
    PrescriptionItem as _PrescriptionItem,
)
from clinical.encounter_service import (
    create_encounter as _create_encounter,
    add_vital_to_encounter as _add_vital_to_encounter,
    add_lab_to_encounter as _add_lab_to_encounter,
    complete_encounter as _complete_encounter,
    cancel_encounter as _cancel_encounter,
    add_prescription_to_encounter as _add_prescription_to_encounter,
    EncounterNotFound as _EncounterNotFound,
    InvalidEncounterTransition as _InvalidEncounterTransition,
    EncounterSealed as _EncounterSealed,
    InvalidEncounterType as _InvalidEncounterType,
    DuplicateVitalReading as _DuplicateVitalReading,
    InsurancePrescriptionNotSupported as _InsurancePrescriptionNotSupported,
    PrescriptionItemValidationError as _PrescriptionItemValidationError,
)

router = Router()


# ===========================================================================
# Encounter write-path (Step 10)
# ===========================================================================

# ---------------------------------------------------------------------------
# Input/Output schemas
# ---------------------------------------------------------------------------

class CreateEncounterIn(Schema):
    """Body for POST /patients/{uuid}/encounters."""
    encounter_type: str = "visit"
    encounter_at: Optional[datetime] = None
    chief_complaint: Optional[str] = None
    doctor_id: Optional[int] = None
    appointment_id: Optional[int] = None


class EncounterOut(Schema):
    """Encounter representation returned from all encounter endpoints."""
    id: int
    tenant_id: int
    patient_link_id: int
    encounter_type: str
    encounter_at: datetime
    status: str
    chief_complaint: Optional[str] = None
    doctor_id: Optional[int] = None
    appointment_id: Optional[int] = None
    accounting_invoice_id: Optional[int] = None
    completed_at: Optional[datetime] = None
    summary_note: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class EncounterListResponse(Schema):
    items: list[EncounterOut]
    total: int
    limit: int
    offset: int


class VitalIn(Schema):
    """One vital reading to add under an encounter."""
    type: str
    value: float
    unit: Optional[str] = None
    source: str = "clinic"
    measured_at: Optional[datetime] = None


class VitalReadingCreatedDTO(Schema):
    """A created vital reading."""
    id: int
    patient_link_id: int
    type: str
    value: float
    unit: Optional[str] = None
    source: Optional[str] = None
    measured_at: datetime
    recorded_by: Optional[str] = None


class LabIn(Schema):
    """
    One lab result to add under an encounter.

    test_key is a soft FK to lab_test_catalog.test_key — pass null if the catalog
    row does not exist yet; the LabResult will still be saved (test_name is the
    required human-readable label).
    """
    test_name: str
    test_key: Optional[str] = None   # nullable; must match lab_test_catalog if supplied
    value: Optional[float] = None
    unit: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    taken_at: Optional[datetime] = None


class LabResultCreatedDTO(Schema):
    """A created lab result."""
    id: int
    patient_link_id: int
    encounter_id: Optional[int] = None
    test_name: str
    test_key: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    taken_at: datetime
    recorded_by: Optional[str] = None


class VitalsAddedResponse(Schema):
    """Response from POST /encounters/{id}/vitals (list add)."""
    count: int
    vitals: list[VitalReadingCreatedDTO]


class LabsAddedResponse(Schema):
    """Response from POST /encounters/{id}/labs (list add)."""
    count: int
    labs: list[LabResultCreatedDTO]


class CompleteEncounterIn(Schema):
    summary_note: Optional[str] = None


class CancelEncounterIn(Schema):
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _encounter_to_out(enc: _Encounter) -> EncounterOut:
    return EncounterOut(
        id=enc.id,
        tenant_id=enc.tenant_id,
        patient_link_id=enc.patient_link_id,
        encounter_type=enc.encounter_type,
        encounter_at=enc.encounter_at,
        status=enc.status,
        chief_complaint=enc.chief_complaint,
        doctor_id=enc.doctor_id,
        appointment_id=enc.appointment_id,
        accounting_invoice_id=enc.accounting_invoice_id,
        completed_at=enc.completed_at,
        summary_note=enc.summary_note,
        created_by=enc.created_by,
        created_at=enc.created_at,
        updated_at=enc.updated_at,
    )


# ---------------------------------------------------------------------------
# POST /patients/{uuid}/encounters — create encounter
# ---------------------------------------------------------------------------

@router.post(
    "/patients/{patient_uuid}/encounters",
    response={
        201: EncounterOut,
        404: ErrorSchema,
        422: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["encounters"],
)
def create_encounter_endpoint(
    request,
    patient_uuid: uuid_module.UUID,
    body: CreateEncounterIn,
):
    """
    Create a new encounter (status=open) for an enrolled patient.

    encounter_type: 'visit' (default) | 'follow_up' | 'phone' | 'remote'.
    doctor_id / appointment_id / accounting_invoice_id are stored id snapshots —
    they reference existing rows but are NEVER accounting writes.
    Returns 201 on success, 404 if patient/enrollment not found,
    422 if encounter_type is invalid.
    """
    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"

    link = _resolve_patient_link_for_tenant(patient_uuid, tenant_id)

    try:
        enc = _create_encounter(
            patient_link_id=link.id,
            tenant_id=tenant_id,
            encounter_type=body.encounter_type,
            encounter_at=body.encounter_at,
            chief_complaint=body.chief_complaint,
            doctor_id=body.doctor_id,
            appointment_id=body.appointment_id,
            created_by=actor,
        )
    except _InvalidEncounterType as exc:
        return 422, error_response(str(exc), "validation_error")

    return 201, _encounter_to_out(enc)


# ---------------------------------------------------------------------------
# GET /patients/{uuid}/encounters — paginated list
# ---------------------------------------------------------------------------

@router.get(
    "/patients/{patient_uuid}/encounters",
    response=EncounterListResponse,
    auth=_jwt_auth,
    tags=["encounters"],
)
def list_encounters(
    request,
    patient_uuid: uuid_module.UUID,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """
    Paginated list of encounters for one enrolled patient, newest first.

    Tenant-scoped: 404 if no enrollment for this uuid in this tenant.
    """
    tenant_id = request.tenant_id
    link = _resolve_patient_link_for_tenant(patient_uuid, tenant_id)

    qs = _Encounter.objects.filter(
        patient_link_id=link.id,
        tenant_id=tenant_id,
    )
    total = qs.count()
    page = list(qs.order_by("-encounter_at")[offset: offset + limit])

    return EncounterListResponse(
        **paginate(total, [_encounter_to_out(e) for e in page], limit, offset)
    )


# ---------------------------------------------------------------------------
# POST /encounters/{encounter_id}/vitals — add list of vitals
# ---------------------------------------------------------------------------

@router.post(
    "/encounters/{encounter_id}/vitals",
    response={
        200: VitalsAddedResponse,
        404: ErrorSchema,
        409: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["encounters"],
)
def add_vitals(
    request,
    encounter_id: int,
    body: _List[VitalIn],
):
    """
    Add one or more vital readings to an open encounter.

    Accepts a JSON array of VitalIn objects.
    Returns 409 with code='encounter_sealed' if the encounter is not open.
    Returns 409 with code='duplicate_vital' if any vital would violate the UNIQUE key.
    The service is called per item; on error after partial success the already-written
    items remain (each item is individually audited by the service).

    Note: test_key for each vital is NOT a lab field here — VitalIn.type is the
    vital_readings.type value (e.g. 'bp_systolic', 'hba1c').
    """
    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"

    created = []
    try:
        for item in body:
            reading = _add_vital_to_encounter(
                encounter_id,
                tenant_id,
                type=item.type,
                value=item.value,
                unit=item.unit,
                source=item.source,
                measured_at=item.measured_at,
                recorded_by=actor,
            )
            created.append(
                VitalReadingCreatedDTO(
                    id=reading.id,
                    patient_link_id=reading.patient_link_id,
                    type=reading.type,
                    value=reading.value,
                    unit=reading.unit,
                    source=reading.source,
                    measured_at=reading.measured_at,
                    recorded_by=reading.recorded_by,
                )
            )
    except _EncounterNotFound as exc:
        return 404, error_response(str(exc), "not_found")
    except _EncounterSealed as exc:
        return 409, error_response(str(exc), "encounter_sealed")
    except _DuplicateVitalReading as exc:
        return 409, error_response(str(exc), "duplicate_vital")

    return 200, VitalsAddedResponse(count=len(created), vitals=created)


# ---------------------------------------------------------------------------
# POST /encounters/{encounter_id}/labs — add list of labs
# ---------------------------------------------------------------------------

@router.post(
    "/encounters/{encounter_id}/labs",
    response={
        200: LabsAddedResponse,
        404: ErrorSchema,
        409: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["encounters"],
)
def add_labs(
    request,
    encounter_id: int,
    body: _List[LabIn],
):
    """
    Add one or more lab results to an open encounter.

    Accepts a JSON array of LabIn objects.
    test_key is a soft FK to lab_test_catalog.test_key — if non-null, the
    catalog row must already exist (the DB will reject it otherwise).
    Returns 409 with code='encounter_sealed' if encounter is not open.
    """
    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"

    created = []
    try:
        for item in body:
            lab = _add_lab_to_encounter(
                encounter_id,
                tenant_id,
                test_name=item.test_name,
                test_key=item.test_key,
                value=item.value,
                unit=item.unit,
                ref_low=item.ref_low,
                ref_high=item.ref_high,
                taken_at=item.taken_at,
                recorded_by=actor,
            )
            created.append(
                LabResultCreatedDTO(
                    id=lab.id,
                    patient_link_id=lab.patient_link_id,
                    encounter_id=lab.encounter_id,
                    test_name=lab.test_name,
                    test_key=lab.test_key,
                    value=lab.value,
                    unit=lab.unit,
                    ref_low=lab.ref_low,
                    ref_high=lab.ref_high,
                    taken_at=lab.taken_at,
                    recorded_by=lab.recorded_by,
                )
            )
    except _EncounterNotFound as exc:
        return 404, error_response(str(exc), "not_found")
    except _EncounterSealed as exc:
        return 409, error_response(str(exc), "encounter_sealed")

    return 200, LabsAddedResponse(count=len(created), labs=created)


# ---------------------------------------------------------------------------
# POST /encounters/{encounter_id}/complete — complete an open encounter
# ---------------------------------------------------------------------------

@router.post(
    "/encounters/{encounter_id}/complete",
    response={
        200: EncounterOut,
        404: ErrorSchema,
        409: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["encounters"],
)
def complete_encounter_endpoint(
    request,
    encounter_id: int,
    body: CompleteEncounterIn,
):
    """
    Transition an open encounter to 'completed'.

    Returns 409 with code='invalid_transition' if the encounter is not open.
    Returns 404 with code='not_found' if the encounter does not exist for this tenant.
    """
    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"

    try:
        enc = _complete_encounter(
            encounter_id,
            tenant_id,
            summary_note=body.summary_note,
            completed_by=actor,
        )
    except _EncounterNotFound as exc:
        return 404, error_response(str(exc), "not_found")
    except _InvalidEncounterTransition as exc:
        return 409, error_response(str(exc), "invalid_transition")

    return 200, _encounter_to_out(enc)


# ---------------------------------------------------------------------------
# POST /encounters/{encounter_id}/cancel — cancel an open encounter
# ---------------------------------------------------------------------------

@router.post(
    "/encounters/{encounter_id}/cancel",
    response={
        200: EncounterOut,
        404: ErrorSchema,
        409: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["encounters"],
)
def cancel_encounter_endpoint(
    request,
    encounter_id: int,
    body: CancelEncounterIn,
):
    """
    Transition an open encounter to 'cancelled'.

    reason is stored in summary_note (no dedicated cancel_reason column).
    Returns 409 with code='invalid_transition' if the encounter is not open.
    Returns 404 with code='not_found' if not found for this tenant.
    """
    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"

    try:
        enc = _cancel_encounter(
            encounter_id,
            tenant_id,
            reason=body.reason,
            cancelled_by=actor,
        )
    except _EncounterNotFound as exc:
        return 404, error_response(str(exc), "not_found")
    except _InvalidEncounterTransition as exc:
        return 409, error_response(str(exc), "invalid_transition")

    return 200, _encounter_to_out(enc)


# ===========================================================================
# Prescription write-path (Step 11) — mode='free' only
# Insurance/MV3 bridge is BLOCKED — do NOT add mode='insurance' support here.
# ===========================================================================

# ---------------------------------------------------------------------------
# Prescription schemas
# ---------------------------------------------------------------------------

class PrescriptionItemIn(Schema):
    """
    One prescription item.

    drug_name is required; all other fields are optional.
    frequency must be one of: od, bid, tid, qid, qod, weekly, monthly, prn,
      with_meal, bedtime, other (or omitted).
    route must be one of: oral, sublingual, sc, im, iv, topical, inhaled, other
      (or omitted).
    quantity and duration_days must be > 0 if provided.
    """
    drug_name: str
    drug_class: Optional[str] = None
    dose_value: Optional[float] = None         # NUMERIC(10,3) — float in API, Decimal in DB
    dose_unit: Optional[str] = None
    frequency: Optional[str] = None            # validated by service against allowed set
    route: Optional[str] = None                # validated by service against allowed set
    quantity: Optional[int] = None             # > 0
    duration_days: Optional[int] = None        # > 0
    instructions: Optional[str] = None


class CreatePrescriptionIn(Schema):
    """Body for POST /encounters/{encounter_id}/prescriptions."""
    kind: str
    items: list[PrescriptionItemIn]
    mode: str = "free"                         # default free; 'insurance' is rejected


class PrescriptionItemOut(Schema):
    """One created prescription item."""
    id: int
    tenant_id: int
    prescription_id: int
    drug_name: str
    drug_class: Optional[str] = None
    dose_value: Optional[float] = None
    dose_unit: Optional[str] = None
    frequency: Optional[str] = None
    route: Optional[str] = None
    quantity: Optional[int] = None
    duration_days: Optional[int] = None
    instructions: Optional[str] = None


class PrescriptionOut(Schema):
    """Created prescription header + items."""
    id: int
    tenant_id: int
    patient_link_id: int
    encounter_id: Optional[int] = None
    kind: str
    mode: str
    prescriber_user_id: Optional[int] = None
    followup_task_id: Optional[int] = None
    issued_at: datetime
    items_structured: list[PrescriptionItemOut]


# ---------------------------------------------------------------------------
# Helper — build PrescriptionOut from ORM objects
# ---------------------------------------------------------------------------

def _prescription_to_out(
    rx: "_Prescription",
    item_rows: "list[_PrescriptionItem]",
) -> PrescriptionOut:
    return PrescriptionOut(
        id=rx.id,
        tenant_id=rx.tenant_id,
        patient_link_id=rx.patient_link_id,
        encounter_id=rx.encounter_id,
        kind=rx.kind,
        mode=rx.mode,
        prescriber_user_id=rx.prescriber_user_id,
        followup_task_id=rx.followup_task_id,
        issued_at=rx.issued_at,
        items_structured=[
            PrescriptionItemOut(
                id=item.id,
                tenant_id=item.tenant_id,
                prescription_id=item.prescription_id,
                drug_name=item.drug_name,
                drug_class=item.drug_class,
                dose_value=float(item.dose_value) if item.dose_value is not None else None,
                dose_unit=item.dose_unit,
                frequency=item.frequency,
                route=item.route,
                quantity=item.quantity,
                duration_days=item.duration_days,
                instructions=item.instructions,
            )
            for item in item_rows
        ],
    )


# ---------------------------------------------------------------------------
# POST /encounters/{encounter_id}/prescriptions — create free prescription
# ---------------------------------------------------------------------------

@router.post(
    "/encounters/{encounter_id}/prescriptions",
    response={
        201: PrescriptionOut,
        400: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
        422: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["encounters"],
)
def create_prescription(
    request,
    encounter_id: int,
    body: CreatePrescriptionIn,
):
    """
    Add a free-mode prescription (header + structured items) to an open encounter.

    Only mode='free' is supported. Passing mode='insurance' returns 422
    (insurance_prescription_not_supported) — the insurance/MV3 bridge track
    is blocked pending owner live access.

    The prescription header and all items are created in a single transaction:
    either all items are saved or none (no orphaned header on item failure).

    Returns 201 with the created prescription + items on success.
    Returns 404 if the encounter does not exist for this tenant.
    Returns 409 (encounter_sealed) if the encounter is not open.
    Returns 422 for mode='insurance' or item validation errors (bad frequency,
    bad route, quantity/duration_days <= 0, empty drug_name).
    """
    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"
    user_id = getattr(request.auth, "pk", None)

    # Convert Pydantic schema list to plain dicts for the service layer
    items_dicts = [item.dict() for item in body.items]

    try:
        rx = _add_prescription_to_encounter(
            encounter_id,
            tenant_id,
            kind=body.kind,
            items=items_dicts,
            mode=body.mode,
            prescriber_user_id=user_id,
            created_by=actor,
        )
    except _EncounterNotFound as exc:
        return 404, error_response(str(exc), "not_found")
    except _EncounterSealed as exc:
        return 409, error_response(str(exc), "encounter_sealed")
    except _InsurancePrescriptionNotSupported as exc:
        return 422, error_response(str(exc), "insurance_prescription_not_supported")
    except _PrescriptionItemValidationError as exc:
        return 422, error_response(str(exc), "validation_error")

    # Fetch created items (single query, ordered by id)
    item_rows = list(
        _PrescriptionItem.objects.filter(
            prescription_id=rx.id,
            tenant_id=tenant_id,
        ).order_by("id")
    )

    return 201, _prescription_to_out(rx, item_rows)
