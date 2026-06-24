"""
AccountingReadPort — the ONLY legitimate read path into accounting.patients
from the clinical side.

Contract:
  - Always uses 'accounting_read' db alias (enforced by router, double-checked here).
  - NEVER calls .using('default') for accounting models.
  - Returns a Pydantic PatientDTO or None (not the ORM object — no leaking
    of the ORM model across the boundary).
  - Raises PermissionError on misuse (direct write attempt caught by router).
  - Fail-loud: raises on unexpected DB errors; returns None only when the
    patient genuinely doesn't exist.

Usage:
  from accounting_port.port import get_patient_by_uuid, PatientDTO
  dto = get_patient_by_uuid(some_uuid)
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
