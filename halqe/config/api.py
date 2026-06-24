"""
django-ninja API — halqe platform v1.

Endpoints:
  POST /api/v1/auth/login                   → JWT token
  GET  /api/v1/patients/{uuid}               → PatientDTO (requires JWT)
  GET  /api/v1/patients/{uuid}/vitals/latest → list[VitalReadingDTO] (requires JWT)
"""
import uuid as uuid_module
from typing import Optional
from datetime import datetime

from ninja import NinjaAPI, Schema
from django.http import Http404

from accounting_port.port import get_patient_by_uuid, PatientDTO
from clinical.models import VitalReading, PatientLink
from platform_core.auth_bearer import JWTBearer
from platform_core.auth_service import (
    login,
    InvalidCredentials,
    AccountLocked,
    AccountInactive,
)

api = NinjaAPI(title="Halqe Platform API", version="0.1.0")

_jwt_auth = JWTBearer()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LoginRequest(Schema):
    username: str
    password: str


class TokenResponse(Schema):
    token: str


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
# Auth endpoint — POST /auth/login
# ---------------------------------------------------------------------------

@api.post("/auth/login", response={200: TokenResponse, 401: dict, 423: dict}, auth=None, tags=["auth"])
def auth_login(request, body: LoginRequest):
    """
    Verify credentials against platform.users (bcrypt).
    Returns a signed JWT (8h) on success.
    401 on wrong credentials or inactive account.
    423 on locked account.
    """
    try:
        token = login(body.username, body.password)
        return 200, {"token": token}
    except AccountLocked as exc:
        return 423, {"detail": str(exc)}
    except (InvalidCredentials, AccountInactive) as exc:
        return 401, {"detail": str(exc)}


# ---------------------------------------------------------------------------
# Patient endpoint — requires JWT
# ---------------------------------------------------------------------------

@api.get("/patients/{patient_uuid}", response=PatientDTO, auth=_jwt_auth, tags=["patients"])
def get_patient(request, patient_uuid: uuid_module.UUID):
    """Return patient demographics from accounting schema (read-only). Requires JWT."""
    dto = get_patient_by_uuid(patient_uuid)
    if dto is None:
        raise Http404(f"Patient with uuid={patient_uuid} not found.")
    return dto


# ---------------------------------------------------------------------------
# Vitals endpoint — requires JWT
# ---------------------------------------------------------------------------

@api.get(
    "/patients/{patient_uuid}/vitals/latest",
    response=list[VitalReadingDTO],
    auth=_jwt_auth,
    tags=["vitals"],
)
def get_latest_vitals(request, patient_uuid: uuid_module.UUID):
    """
    Return the most recent VitalReading for each type for this patient. Requires JWT.

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

    # 3. Latest reading per type
    latest_per_type = (
        VitalReading.objects.filter(patient_link_id=link.id)
        .order_by("type", "-measured_at")
        .distinct("type")
    )

    return list(latest_per_type)
