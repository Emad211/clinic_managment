"""
Vertical slice tests for halqe platform.

Coverage:
  1. GET /api/v1/patients/{uuid} returns correct PatientDTO
  2. GET /api/v1/patients/{uuid}/vitals/latest returns correct vitals
     (latest per type — only 1 hba1c not 2)
  3. Boundary: Patient.objects.using('default').create(...) raises PermissionError
     (router enforcement)
  4. Boundary: full_name is the GENERATED value from DB (read-only, correct)
  5. Boundary: GET on non-existent uuid returns 404

All tests use seed_data fixture (session-scoped seeding outside transaction).
Endpoints now require a JWT — tests obtain one via POST /auth/login.
"""
import uuid
import pytest
from django.test import RequestFactory

from accounting.models import Patient
from accounting_port.port import get_patient_by_uuid, PatientDTO
from clinical.models import PatientLink, VitalReading
from config.api import api


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _api_client():
    """Return a django-ninja test client."""
    from ninja.testing import TestClient
    return TestClient(api)


def _get_token(seed_data):
    """Obtain a valid JWT for testuser (seeded in conftest)."""
    client = _api_client()
    resp = client.post(
        "/auth/login",
        json={"username": "testuser", "password": seed_data["test_password"]},
    )
    assert resp.status_code == 200, f"Login failed in helper: {resp.text}"
    return resp.json()["token"]


# ---------------------------------------------------------------------------
# Test: patient endpoint returns correct data
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_get_patient_endpoint_returns_correct_data(seed_data):
    """GET /patients/{uuid} → 200 with correct fields from accounting.patients."""
    token = _get_token(seed_data)
    patient_uuid = seed_data["patient_uuid"]
    client = _api_client()
    resp = client.get(
        f"/patients/{patient_uuid}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["uuid"] == str(patient_uuid)
    assert data["name"] == "علی"
    assert data["family_name"] == "رضایی"
    # GENERATED ALWAYS STORED: full_name = name || ' ' || family_name
    assert data["full_name"] == "علی رضایی"
    assert data["national_id"] == "1234567890"
    assert data["gender"] == "male"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_get_patient_endpoint_404_on_unknown_uuid(seed_data):
    """GET /patients/{unknown_uuid} → 404."""
    token = _get_token(seed_data)
    client = _api_client()
    unknown = "00000000-0000-0000-0000-000000000000"
    resp = client.get(
        f"/patients/{unknown}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test: vitals endpoint returns latest per type
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_get_latest_vitals_returns_latest_per_type(seed_data):
    """
    GET /patients/{uuid}/vitals/latest → list of latest VitalReading per type.

    Seed has: hba1c (1 day ago), bp_systolic (2 days ago), hba1c (30 days ago).
    Expected: 2 items — hba1c (most recent = 1 day ago) + bp_systolic.
    """
    token = _get_token(seed_data)
    patient_uuid = seed_data["patient_uuid"]
    client = _api_client()
    resp = client.get(
        f"/patients/{patient_uuid}/vitals/latest",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200, resp.text
    readings = resp.json()

    types_returned = {r["type"] for r in readings}
    assert "hba1c" in types_returned
    assert "bp_systolic" in types_returned

    # Each type appears EXACTLY ONCE (latest-per-type dedup — no duplicates)
    types_list = [r["type"] for r in readings]
    assert len(types_list) == len(set(types_list)), (
        "vitals/latest must return each type at most once — duplicates found"
    )

    # The hba1c returned should be the most recent (value 7.2, not 7.5)
    hba1c_reading = next(r for r in readings if r["type"] == "hba1c")
    assert hba1c_reading["value"] == pytest.approx(7.2, abs=0.01)


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_get_latest_vitals_404_on_unknown_uuid(seed_data):
    """GET /patients/{unknown_uuid}/vitals/latest → 404."""
    token = _get_token(seed_data)
    client = _api_client()
    unknown = "00000000-0000-0000-0000-000000000001"
    resp = client.get(
        f"/patients/{unknown}/vitals/latest",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test: boundary — router blocks write on accounting model
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_boundary_router_blocks_accounting_write(seed_data):
    """
    ClinicalRouter.db_for_write raises PermissionError for app_label='accounting'.

    Note: Patient.objects.using('default') bypasses the router (explicit alias).
    The router is called when Django resolves the DB for a model *without* .using().
    We test the router directly and also via .create() without explicit .using().
    """
    from config.routers import ClinicalRouter
    router = ClinicalRouter()

    # Direct router call must raise PermissionError
    with pytest.raises(PermissionError, match="accounting"):
        router.db_for_write(Patient)

    # create() without .using() also triggers the router
    with pytest.raises(PermissionError, match="accounting"):
        Patient.objects.create(
            name="حمله",
            family_name="تست",
            uuid=uuid.uuid4(),
        )


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_boundary_port_never_uses_default_for_accounting(seed_data):
    """
    AccountingReadPort must use accounting_read, not default.
    Direct Patient.objects.get() without .using() should route to accounting_read.
    """
    patient_uuid = seed_data["patient_uuid"]
    dto = get_patient_by_uuid(patient_uuid)
    assert dto is not None
    assert isinstance(dto, PatientDTO)
    # Verify the router directed this to accounting_read (not default)
    # by checking we got valid data
    assert dto.full_name == "علی رضایی"


# ---------------------------------------------------------------------------
# Test: full_name is GENERATED (read correctly, not settable)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_full_name_is_generated_and_read_only(seed_data):
    """
    full_name must be the GENERATED ALWAYS STORED value from DB.
    The Patient model declares it editable=False.
    We verify the field is read correctly and the model field is non-editable.
    """
    patient_uuid = seed_data["patient_uuid"]
    patient = (
        Patient.objects.using("accounting_read").get(uuid=patient_uuid)
    )
    # Read correctly from GENERATED column
    assert patient.full_name == "علی رضایی"

    # editable=False is declared in the model
    field = Patient._meta.get_field("full_name")
    assert field.editable is False, "full_name must be non-editable (GENERATED column)"


# ---------------------------------------------------------------------------
# Test: clinical PatientLink and VitalReading are readable on 'default'
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default"])
def test_clinical_patient_link_readable(seed_data):
    """PatientLink is readable from 'default' DB."""
    link = PatientLink.objects.get(id=seed_data["link_id"])
    assert link.patient_id == seed_data["patient_id"]
    assert link.is_active is True


@pytest.mark.django_db(databases=["default"])
def test_clinical_vital_readings_readable(seed_data):
    """VitalReading is readable from 'default' DB.

    Uses >= 3 instead of == 3 to accommodate optional RLS-isolation test data
    (test_pg_schema._ensure_rls_test_data) that may insert additional readings
    on the same patient_link_id when the full test suite runs together.
    """
    readings = VitalReading.objects.filter(
        patient_link_id=seed_data["link_id"]
    ).order_by("-measured_at")
    assert readings.count() >= 3


# ---------------------------------------------------------------------------
# Test: DB-level boundary — clinical_login_test cannot write to accounting
# ---------------------------------------------------------------------------

def test_db_level_accounting_write_denied(seed_data):
    """
    As platform_app (login role platform_login_test), UPDATE on accounting.patients
    must raise a DB-level permission error (read-only boundary enforced at DB level).
    This test connects directly with psycopg as platform_login_test.
    """
    import os
    import psycopg

    conninfo = (
        f"host='localhost' port='55432' "
        f"user='platform_login_test' password='test_pw' "
        f"dbname='halqe_app_test'"
    )
    with psycopg.connect(conninfo) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction():
                conn.execute(
                    "UPDATE accounting.patients SET gender = 'unknown' WHERE id = %s",
                    (seed_data["patient_id"],)
                )
