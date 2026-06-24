"""
Tests for the patient-list + clinical-record read slice.

Coverage:
  1. GET /patients  — list enrolled patients (with demographics)
  2. GET /patients  — pagination: limit/offset + total
  3. GET /patients/{uuid}/record — conditions (active only), active meds, recent vitals
  4. GET /patients/{uuid}/record — only ACTIVE medications returned
  5. Both endpoints return 401 without JWT
  6. Both endpoints return 200 with valid JWT
  7. Tenant isolation: a patient enrolled under tenant-2 is NOT visible to tenant-1 token

Architecture notes:
  - list_patients: N+1-avoidance via get_patients_by_ids (one batch accounting query per page)
  - Both endpoints: tenant_id scoped from JWT claims (request.tenant_id set by JWTBearer)
  - Clinical reads on 'default'; demographics reads on 'accounting_read'
"""
import pytest
from ninja.testing import TestClient

from config.api import api


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client() -> TestClient:
    return TestClient(api)


def _get_token(seed_data, username: str = "testuser") -> str:
    """Obtain a JWT for testuser (tenant 1) via POST /auth/login."""
    resp = _client().post(
        "/auth/login",
        json={"username": username, "password": seed_data["test_password"]},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["token"]


# ---------------------------------------------------------------------------
# 1. Patient list — basic
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_list_patients_returns_enrolled_patient_with_demographics(seed_clinical_data):
    """
    GET /patients → 200.
    The seeded tenant-1 patient must appear in the list with correct demographics.
    """
    token = _get_token(seed_clinical_data)
    resp = _client().get(
        "/patients",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert "items" in data
    assert "total" in data
    assert data["total"] >= 1

    # Find our test patient by uuid
    patient_uuid = str(seed_clinical_data["patient_uuid"])
    found = next(
        (item for item in data["items"] if item["patient_uuid"] == patient_uuid),
        None,
    )
    assert found is not None, f"Test patient not in list. items={data['items']}"
    assert found["full_name"] == "علی رضایی"
    assert found["national_id"] == "1234567890"
    assert found["phone_number"] == "09120000001"
    assert found["is_active"] is True


# ---------------------------------------------------------------------------
# 2. Patient list — pagination (limit / offset)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_list_patients_pagination(seed_clinical_data):
    """
    GET /patients?limit=1&offset=0 → 1 item, total >= 1.
    GET /patients?limit=1&offset=9999 → 0 items, total unchanged.
    """
    token = _get_token(seed_clinical_data)
    client = _client()
    headers = {"Authorization": f"Bearer {token}"}

    # First page — 1 item
    resp = client.get("/patients?limit=1&offset=0", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["limit"] == 1
    assert data["offset"] == 0
    total = data["total"]
    assert total >= 1

    # Out-of-range offset — 0 items but total still correct
    resp2 = client.get("/patients?limit=1&offset=9999", headers=headers)
    assert resp2.status_code == 200, resp2.text
    data2 = resp2.json()
    assert len(data2["items"]) == 0
    assert data2["total"] == total


# ---------------------------------------------------------------------------
# 3. Clinical record — full structure
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_get_patient_record_returns_conditions_and_meds_and_vitals(seed_clinical_data):
    """
    GET /patients/{uuid}/record → 200.
    - demographics present
    - active conditions (diabetes + hypertension)
    - active medications only (2 active; 1 inactive excluded)
    - recent vitals (newest first, ≤10)
    """
    token = _get_token(seed_clinical_data)
    patient_uuid = seed_clinical_data["patient_uuid"]
    resp = _client().get(
        f"/patients/{patient_uuid}/record",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Demographics
    assert data["demographics"]["full_name"] == "علی رضایی"
    assert data["demographics"]["national_id"] == "1234567890"

    # Active conditions — at least diabetes and hypertension
    cond_codes = [c["condition_code"] for c in data["active_conditions"]]
    assert "diabetes" in cond_codes, f"diabetes missing from {cond_codes}"
    assert "hypertension" in cond_codes, f"hypertension missing from {cond_codes}"
    # All returned conditions must be active
    for cond in data["active_conditions"]:
        assert cond["is_active"] is True

    # Active medications: exactly 2 (متفورمین + آملودیپین); گلیبنکلامید is inactive
    assert len(data["active_medications"]) == 2, (
        f"Expected 2 active meds, got {len(data['active_medications'])}: "
        f"{[m['drug_name'] for m in data['active_medications']]}"
    )
    active_drug_names = {m["drug_name"] for m in data["active_medications"]}
    assert "متفورمین" in active_drug_names
    assert "آملودیپین" in active_drug_names
    assert "گلیبنکلامید" not in active_drug_names

    # Recent vitals — has items, newest first
    vitals = data["recent_vitals"]
    assert len(vitals) >= 1
    assert len(vitals) <= 10
    if len(vitals) > 1:
        # Confirm descending order
        for i in range(len(vitals) - 1):
            assert vitals[i]["measured_at"] >= vitals[i + 1]["measured_at"], (
                "Vitals must be returned newest-first"
            )


# ---------------------------------------------------------------------------
# 4. Clinical record — ONLY active medications returned
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_record_excludes_inactive_medications(seed_clinical_data):
    """
    The inactive medication (گلیبنکلامید, is_active=False) must NOT appear
    in the record's active_medications list.
    """
    token = _get_token(seed_clinical_data)
    patient_uuid = seed_clinical_data["patient_uuid"]
    resp = _client().get(
        f"/patients/{patient_uuid}/record",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    meds = resp.json()["active_medications"]
    drug_names = [m["drug_name"] for m in meds]
    assert "گلیبنکلامید" not in drug_names, (
        "Inactive medication must not appear in active_medications"
    )


# ---------------------------------------------------------------------------
# 5. Both endpoints return 401 without JWT
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_list_patients_requires_jwt(seed_clinical_data):
    """GET /patients without token → 401."""
    resp = _client().get("/patients")
    assert resp.status_code == 401, resp.text


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_get_record_requires_jwt(seed_clinical_data):
    """GET /patients/{uuid}/record without token → 401."""
    patient_uuid = seed_clinical_data["patient_uuid"]
    resp = _client().get(f"/patients/{patient_uuid}/record")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# 6. Both endpoints return 200 with valid JWT
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_list_patients_with_valid_token_returns_200(seed_clinical_data):
    """GET /patients with valid token → 200."""
    token = _get_token(seed_clinical_data)
    resp = _client().get(
        "/patients",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_get_record_with_valid_token_returns_200(seed_clinical_data):
    """GET /patients/{uuid}/record with valid token → 200."""
    token = _get_token(seed_clinical_data)
    patient_uuid = seed_clinical_data["patient_uuid"]
    resp = _client().get(
        f"/patients/{patient_uuid}/record",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# 7. Tenant isolation — tenant-2 patient NOT visible to tenant-1 token
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_tenant_isolation_list_does_not_show_other_tenant_patient(seed_clinical_data):
    """
    Tenant-1 token must NOT see the tenant-2 patient in the list.

    The tenant-2 patient (uuid=11111111-...) is enrolled under tenant_id=2.
    A tenant-1 token has tenant_id=1 → only tenant_id=1 patient_links are returned.
    """
    token = _get_token(seed_clinical_data)
    resp = _client().get(
        "/patients",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    tenant2_uuid = str(seed_clinical_data["tenant2_patient_uuid"])
    in_list = any(item["patient_uuid"] == tenant2_uuid for item in data["items"])
    assert not in_list, (
        f"Tenant-2 patient ({tenant2_uuid}) must NOT appear in tenant-1 response"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_tenant_isolation_record_404_for_other_tenant_patient(seed_clinical_data):
    """
    GET /patients/{uuid}/record for tenant-2 patient with tenant-1 token → 404.

    The accounting patient exists (uuid resolves), but there is no
    patient_link with tenant_id=1, so the endpoint must 404.
    """
    token = _get_token(seed_clinical_data)
    tenant2_uuid = seed_clinical_data["tenant2_patient_uuid"]
    resp = _client().get(
        f"/patients/{tenant2_uuid}/record",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404, (
        f"Expected 404 for cross-tenant record access, got {resp.status_code}: {resp.text}"
    )
