"""
AccountingReadPort — the ONLY legitimate read path into accounting.patients
from the clinical side.

Contract:
  - Always uses 'accounting_read' db alias (enforced by router, double-checked here).
  - NEVER calls .using('default') for accounting models.
  - Returns Pydantic DTO(s) or None/[] (not ORM objects — no leaking of the
    ORM model across the boundary).
  - Raises PermissionError on misuse (direct write attempt caught by router).
  - Fail-loud: raises on unexpected DB errors; returns None/[] only when the
    patient genuinely doesn't exist.

Usage:
  from accounting_port.port import get_patient_by_uuid, get_patients_by_ids, PatientDTO
  dto = get_patient_by_uuid(some_uuid)
  dtos = get_patients_by_ids([1, 2, 3])   # N+1-avoidance: batch fetch
"""
import uuid as uuid_module
from datetime import date
from typing import Optional

from pydantic import BaseModel

from accounting.models import Patient


class PatientDTO(BaseModel):
    """Read-only patient demographics from accounting.patients."""

    model_config = {"from_attributes": True}  # allow Pydantic V2 to read from ORM objects

    id: int
    uuid: uuid_module.UUID
    name: str
    family_name: str
    full_name: str          # GENERATED ALWAYS STORED in DB; read-only
    national_id: Optional[str] = None
    phone_number: Optional[str] = None
    birthdate: Optional[date] = None
    gender: Optional[str] = None


def get_patient_by_uuid(patient_uuid: uuid_module.UUID) -> Optional[PatientDTO]:
    """
    Look up a patient in accounting.patients by their external UUID.

    Returns PatientDTO or None (patient not found).
    Explicitly uses .using('accounting_read') as a guard — the router also
    enforces this, but belt-and-suspenders for misuse detection.
    Raises PermissionError if somehow called with .using('default').
    """
    try:
        patient = (
            Patient.objects
            .using("accounting_read")   # explicit + router both enforce read-only
            .only(
                "id", "uuid", "name", "family_name", "full_name",
                "national_id", "phone_number", "birthdate", "gender",
            )
            .get(uuid=patient_uuid)
        )
    except Patient.DoesNotExist:
        return None

    return PatientDTO.model_validate(patient)


def get_patients_by_ids(patient_ids: list[int]) -> list[PatientDTO]:
    """
    Batch-fetch demographics for a list of accounting.patients.id values.

    Used by the patient-list endpoint to avoid N+1: page patient_links first,
    then call this once for the whole page.

    Returns list[PatientDTO] — only the patients that were found.
    Order is not guaranteed (callers should re-index by id if needed).
    Empty list if patient_ids is empty (no DB round-trip).
    """
    if not patient_ids:
        return []

    patients = (
        Patient.objects
        .using("accounting_read")
        .only(
            "id", "uuid", "name", "family_name", "full_name",
            "national_id", "phone_number", "birthdate", "gender",
        )
        .filter(id__in=patient_ids)
    )
    return [PatientDTO.model_validate(p) for p in patients]
