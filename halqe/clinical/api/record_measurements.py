"""Read projection for the complete vital history in the specialist record."""
from __future__ import annotations

import uuid as uuid_module
from datetime import datetime
from typing import Optional

from ninja import Router, Schema

from clinical.api._shared import _resolve_patient_link_for_tenant
from clinical.record_repository import RecordRepository
from config.api_base import _jwt_auth


router = Router()


class RecordVitalDTO(Schema):
    id: int
    type: str
    value: float
    unit: Optional[str] = None
    measured_at: datetime
    source: Optional[str] = None
    notes: Optional[str] = None
    recorded_by: Optional[str] = None
    verified: bool
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    encounter_id: Optional[int] = None


@router.get(
    "/patients/{patient_uuid}/record/vitals",
    response=list[RecordVitalDTO],
    auth=_jwt_auth,
    tags=["patient-record"],
)
def list_record_vitals(request, patient_uuid: uuid_module.UUID):
    link = _resolve_patient_link_for_tenant(patient_uuid, request.tenant_id)
    rows = RecordRepository().list_vitals(
        tenant_id=request.tenant_id,
        patient_link_id=link.id,
        limit=200,
    )
    return [
        RecordVitalDTO(
            id=row.id,
            type=row.type,
            value=row.value,
            unit=row.unit,
            measured_at=row.measured_at,
            source=row.source,
            notes=row.notes,
            recorded_by=row.recorded_by,
            verified=row.verified,
            verified_by=row.verified_by,
            verified_at=row.verified_at,
            rejected_by=row.rejected_by,
            rejected_at=row.rejected_at,
            encounter_id=row.encounter_id,
        )
        for row in rows
    ]
