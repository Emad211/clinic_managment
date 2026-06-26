"""
Patients domain router (cleanup step 7 — god-file split).

Migrated verbatim out of the ``config/api.py`` god-file. Holds the read-side
patient endpoints (all JWT, all tenant-scoped):

  GET /patients                       → paginated enrolled patient list
  GET /patients/{uuid}                → PatientDTO (accounting demographics)
  GET /patients/{uuid}/record         → full clinical record

URLs are preserved byte-for-byte: ``config.api`` wires this router with
``api.add_router("", patients_router)`` and the routes carry their full short
paths, so ``/api/v1`` (urls.py) + the path == the same full paths as before.

The vital read DTO (``VitalReadingDTO``) is shared with the vitals domain and
lives in ``clinical.api._shared``.  The per-record threshold-level evaluation
(``_vital_level``) is single-domain (only the record endpoint uses it) and
stays here.

This module imports FROM ``config.api_base`` (shared ``_jwt_auth``) and
``clinical.api._shared``; nothing in either imports a router, so the package
stays free of cycles.
"""
from __future__ import annotations

import uuid as uuid_module
from typing import Optional
from datetime import datetime, date

from ninja import Router, Schema, Query
from django.http import Http404

from config.api_base import _jwt_auth
from config.pagination import paginate
from clinical.api._shared import VitalReadingDTO

from accounting_port.port import (
    get_patient_by_uuid,
    get_patients_by_ids,
    PatientDTO,
)
from clinical.models import (
    VitalReading,
    PatientLink,
    Condition,
    PatientCondition,
    PatientMedication,
)
from clinical.rule_engine import _evaluate_reading as _eval_reading
from clinical.models import ClinicalIndicator as _ClinicalIndicator

router = Router()


# ---------------------------------------------------------------------------
# Patient-list schemas
# ---------------------------------------------------------------------------

class EnrolledPatientDTO(Schema):
    """One item in the paginated patient list."""
    link_id: int
    patient_id: int
    is_active: bool
    enrolled_at: datetime
    # Demographics from AccountingReadPort (None if not found in accounting)
    full_name: Optional[str] = None
    national_id: Optional[str] = None
    phone_number: Optional[str] = None
    patient_uuid: Optional[str] = None


class PatientListResponse(Schema):
    items: list[EnrolledPatientDTO]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Clinical record schemas
# ---------------------------------------------------------------------------

class ConditionDTO(Schema):
    id: int
    condition_id: int
    condition_name: Optional[str] = None
    condition_code: Optional[str] = None
    stage: Optional[str] = None
    onset_date: Optional[date] = None
    notes: Optional[str] = None
    is_active: bool
    diagnosed_at: datetime


class MedicationDTO(Schema):
    id: int
    drug_name: str
    dose: Optional[str] = None
    schedule: Optional[str] = None
    start_date: Optional[date] = None
    refill_due_date: Optional[date] = None
    drug_class: Optional[str] = None
    is_active: bool
    notes: Optional[str] = None
    created_at: datetime


class ClinicalRecordDTO(Schema):
    """Full clinical record for one patient."""
    patient_link_id: int
    # Demographics via AccountingReadPort
    demographics: Optional[PatientDTO] = None
    # Active chronic conditions
    active_conditions: list[ConditionDTO]
    # Active medications only
    active_medications: list[MedicationDTO]
    # Recent vitals (last ~10, newest first)
    recent_vitals: list[VitalReadingDTO]


# ---------------------------------------------------------------------------
# Patient list — GET /patients  (requires JWT, tenant-scoped)
# ---------------------------------------------------------------------------

@router.get(
    "/patients",
    response=PatientListResponse,
    auth=_jwt_auth,
    tags=["patients"],
)
def list_patients(
    request,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """
    Paginated list of ENROLLED patients for the authenticated tenant.

    Scoped to request.tenant_id (set by JWTBearer from token claims).
    N+1-avoidance: page patient_links first, then batch-fetch demographics
    for the page via AccountingReadPort.get_patients_by_ids().
    """
    tenant_id = request.tenant_id

    # 1. Total count for this tenant
    total = PatientLink.objects.filter(
        tenant_id=tenant_id,
    ).count()

    # 2. Fetch the page (newest enrolled first)
    page_links = list(
        PatientLink.objects.filter(tenant_id=tenant_id)
        .order_by("-enrolled_at")
        [offset: offset + limit]
    )

    # 3. Batch-fetch demographics — single query, no N+1
    patient_ids = [pl.patient_id for pl in page_links]
    demos_by_id: dict[int, PatientDTO] = {
        d.id: d for d in get_patients_by_ids(patient_ids)
    }

    # 4. Build result items
    items: list[EnrolledPatientDTO] = []
    for pl in page_links:
        demo = demos_by_id.get(pl.patient_id)
        items.append(
            EnrolledPatientDTO(
                link_id=pl.id,
                patient_id=pl.patient_id,
                is_active=pl.is_active,
                enrolled_at=pl.enrolled_at,
                full_name=demo.full_name if demo else None,
                national_id=demo.national_id if demo else None,
                phone_number=demo.phone_number if demo else None,
                patient_uuid=str(demo.uuid) if demo else None,
            )
        )

    return PatientListResponse(**paginate(total, items, limit, offset))


# ---------------------------------------------------------------------------
# Clinical record — GET /patients/{uuid}/record  (requires JWT, tenant-scoped)
# ---------------------------------------------------------------------------

@router.get(
    "/patients/{patient_uuid}/record",
    response=ClinicalRecordDTO,
    auth=_jwt_auth,
    tags=["patients"],
)
def get_patient_record(request, patient_uuid: uuid_module.UUID):
    """
    Full clinical record for one patient.

    Tenant-scoped: 404 if no enrollment for this tenant.
    Returns: demographics (via Port) + active conditions + active medications
             + recent vitals (last 10, newest first).
    Reads demographics from 'accounting_read', clinical data from 'default'.
    """
    tenant_id = request.tenant_id

    # 1. Resolve uuid → accounting patient
    demo = get_patient_by_uuid(patient_uuid)
    if demo is None:
        raise Http404(f"Patient with uuid={patient_uuid} not found.")

    # 2. Find clinical enrollment for THIS tenant
    try:
        link = PatientLink.objects.get(
            tenant_id=tenant_id,
            patient_id=demo.id,
        )
    except PatientLink.DoesNotExist:
        raise Http404(
            f"Patient uuid={patient_uuid} has no enrollment for this tenant."
        )

    # 3. Active conditions with condition metadata (IN query — no N+1)
    patient_conditions = list(
        PatientCondition.objects.filter(
            patient_link_id=link.id,
            is_active=True,
        ).order_by("diagnosed_at")
    )
    # Batch-fetch condition names/codes in one query
    cond_ids = [pc.condition_id for pc in patient_conditions]
    conditions_map: dict[int, Condition] = {}
    if cond_ids:
        conditions_map = {
            c.id: c
            for c in Condition.objects.filter(id__in=cond_ids)
        }

    active_conditions = [
        ConditionDTO(
            id=pc.id,
            condition_id=pc.condition_id,
            condition_name=(
                conditions_map[pc.condition_id].name
                if pc.condition_id in conditions_map else None
            ),
            condition_code=(
                conditions_map[pc.condition_id].code
                if pc.condition_id in conditions_map else None
            ),
            stage=pc.stage,
            onset_date=pc.onset_date,
            notes=pc.notes,
            is_active=pc.is_active,
            diagnosed_at=pc.diagnosed_at,
        )
        for pc in patient_conditions
    ]

    # 4. Active medications only
    active_medications = [
        MedicationDTO(
            id=m.id,
            drug_name=m.drug_name,
            dose=m.dose,
            schedule=m.schedule,
            start_date=m.start_date,
            refill_due_date=m.refill_due_date,
            drug_class=m.drug_class,
            is_active=m.is_active,
            notes=m.notes,
            created_at=m.created_at,
        )
        for m in PatientMedication.objects.filter(
            patient_link_id=link.id,
            is_active=True,
        ).order_by("-created_at")
    ]

    # 5. Recent vitals — last 10, newest first
    recent_vitals = list(
        VitalReading.objects.filter(
            patient_link_id=link.id,
        ).order_by("-measured_at")[:10]
    )

    # 6. Build threshold indicator map once (one query) for level evaluation.
    #    Source of truth: clinical_indicators table (never hardcoded thresholds).
    #    Falls back to _evaluate_reading's own static fallback if indicator row
    #    is absent — returning 'ok' when no threshold exists (shown as level=None
    #    below for vital types with no clinical_indicators row at all).
    _indicator_map: dict = {
        row.key: row
        for row in _ClinicalIndicator.objects.filter(
            tenant_id=tenant_id, is_active=True
        )
    }

    def _vital_level(vtype: str, value: float) -> Optional[str]:
        """
        Return 'ok'|'warn'|'danger' when a clinical_indicators row exists for
        this vital type; return None when no indicator row is present (the UI
        renders the vital without a colour badge).
        """
        if vtype not in _indicator_map:
            return None
        return _eval_reading(vtype, value, _indicator_map)

    return ClinicalRecordDTO(
        patient_link_id=link.id,
        demographics=demo,
        active_conditions=active_conditions,
        active_medications=active_medications,
        recent_vitals=[
            VitalReadingDTO(
                id=v.id,
                patient_link_id=v.patient_link_id,
                type=v.type,
                value=v.value,
                unit=v.unit,
                measured_at=v.measured_at,
                source=v.source,
                notes=v.notes,
                level=_vital_level(v.type, v.value),
                # slice14: always serialise review state so UI can distinguish
                # pending / approved / rejected without extra round-trips.
                verified=v.verified,
                rejected_at=(
                    v.rejected_at.isoformat() if v.rejected_at else None
                ),
            )
            for v in recent_vitals
        ],
    )


# ---------------------------------------------------------------------------
# Patient endpoint — requires JWT
# ---------------------------------------------------------------------------

@router.get("/patients/{patient_uuid}", response=PatientDTO, auth=_jwt_auth, tags=["patients"])
def get_patient(request, patient_uuid: uuid_module.UUID):
    """Return patient demographics from accounting schema (read-only). Requires JWT."""
    dto = get_patient_by_uuid(patient_uuid)
    if dto is None:
        raise Http404(f"Patient with uuid={patient_uuid} not found.")
    return dto
