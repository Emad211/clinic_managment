"""
django-ninja API — halqe platform v1.

Endpoints:
  GET /api/v1/patients/{uuid}               → PatientDTO (via AccountingReadPort)
  GET /api/v1/patients/{uuid}/vitals/latest → list[VitalReadingDTO] (latest per type)

No auth in this vertical slice — the boundary proof and data-correctness tests
are the deliverable.
"""
import uuid as uuid_module
from typing import Optional
from datetime import date, datetime

from ninja import NinjaAPI, Schema
from django.http import Http404

from accounting_port.port import get_patient_by_uuid, PatientDTO
from clinical.models import VitalReading, PatientLink

api = NinjaAPI(title="Halqe Platform API", version="0.1.0")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class VitalReadingDTO(Schema):
    id: int
    patient_link_id: int
    type: str
    value: float
    unit: Optional[str]
    measured_at: datetime
    source: Optional[str]
    notes: Optional[str]


# ---------------------------------------------------------------------------
# Patient endpoint
# ---------------------------------------------------------------------------

@api.get("/patients/{patient_uuid}", response=PatientDTO, tags=["patients"])
def get_patient(request, patient_uuid: uuid_module.UUID):
    """Return patient demographics from accounting schema (read-only)."""
    dto = get_patient_by_uuid(patient_uuid)
    if dto is None:
        raise Http404(f"Patient with uuid={patient_uuid} not found.")
    return dto


# ---------------------------------------------------------------------------
# Vitals endpoint
# ---------------------------------------------------------------------------

@api.get(
    "/patients/{patient_uuid}/vitals/latest",
    response=list[VitalReadingDTO],
    tags=["vitals"],
)
def get_latest_vitals(request, patient_uuid: uuid_module.UUID):
    """
    Return the most recent VitalReading for each type for this patient.

    Lookup chain: accounting.patients(uuid) → clinical.patient_links → vital_readings.
    Raises 404 if the patient or the clinical enrollment doesn't exist.
    """
    # 1. Resolve uuid → accounting patient id (read-only)
    patient_dto = get_patient_by_uuid(patient_uuid)
    if patient_dto is None:
        raise Http404(f"Patient with uuid={patient_uuid} not found.")

    # 2. Find the clinical patient_link
    try:
        link = PatientLink.objects.get(patient_id=patient_dto.id, is_active=True)
    except PatientLink.DoesNotExist:
        raise Http404(f"Patient uuid={patient_uuid} has no active clinical enrollment.")

    # 3. Latest reading per type — one subquery per ORM idiom for portability
    from django.db.models import Max
    from django.db.models import OuterRef, Subquery

    latest_per_type = (
        VitalReading.objects.filter(patient_link_id=link.id)
        .order_by("type", "-measured_at")
        .distinct("type")
    )

    return list(latest_per_type)
