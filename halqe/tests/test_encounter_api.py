"""
Step 10 — encounter API endpoint tests.

Coverage matrix (all tenant-1, JWT-authenticated unless noted):

  1.  POST /patients/{uuid}/encounters → 201 + EncounterOut (status=open).
  2.  GET  /patients/{uuid}/encounters → list shows the just-created encounter.
  3.  POST /encounters/{id}/vitals (list body) → 200 + VitalsAddedResponse.
  4.  After adding vitals, GET /patients/{uuid}/record shows them in recent_vitals.
  5.  POST /encounters/{id}/labs (list body) → 200 + LabsAddedResponse.
  6.  POST /encounters/{id}/complete → 200 + EncounterOut (status=completed).
  7.  POST /encounters/{id}/vitals after complete → 409 encounter_sealed.
  8.  POST /encounters/{id}/complete again → 409 invalid_transition.
  9.  POST /patients/{uuid}/encounters then POST /encounters/{id}/cancel → 200 cancelled.
  10. POST /patients/{uuid}/encounters with bad encounter_type → 422 validation_error.
  11. All six endpoints return 401 without JWT.
  12. Tenant isolation: encounter of another tenant → 404 not_found.
  13. Duplicate vital (same natural key) → 409 duplicate_vital.
  14. GET /patients/{uuid}/encounters → pagination total/limit/offset.
  15. POST /encounters/{id}/labs with encounter_sealed → 409 encounter_sealed.
  16. Error bodies always carry {detail (str), code (str)}.

All tests use @pytest.mark.django_db(transaction=True) — they see session-seeded data.
Never writes to accounting.*; doctor_id/accounting_invoice_id never set.
NullProvider: no real SMS (scheduler disabled by TESTING flag).
"""
import pytest
from ninja.testing import TestClient

from config.api import api

# ─── helpers ─────────────────────────────────────────────────────────────────

def _client() -> TestClient:
    return TestClient(api)


def _get_token(seed) -> str:
    resp = _client().post(
        "/auth/login",
        json={"username": "testuser", "password": seed["test_password"]},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _assert_error_contract(body: dict, expected_code: str) -> None:
    """Every error body must have {detail: non-empty str, code: expected_code}."""
    assert "detail" in body, f"Missing 'detail' in error body: {body}"
    assert isinstance(body["detail"], str) and body["detail"], (
        f"'detail' must be non-empty string, got: {body['detail']!r}"
    )
    assert "code" in body, f"Missing 'code' in error body: {body}"
    assert body["code"] == expected_code, (
        f"Expected code={expected_code!r}, got {body['code']!r}"
    )


def _assert_encounter_out(body: dict) -> None:
    """EncounterOut shape: required fields present and typed correctly."""
    for field in ("id", "tenant_id", "patient_link_id", "encounter_type",
                  "encounter_at", "status", "created_at", "updated_at"):
        assert field in body, f"EncounterOut missing field '{field}': {body}"
    assert isinstance(body["id"], int)
    assert isinstance(body["status"], str)
    assert isinstance(body["encounter_type"], str)


# ─── 1. POST /patients/{uuid}/encounters → 201 ────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_create_encounter_returns_201(seed_clinical_data):
    """POST /patients/{uuid}/encounters with valid body → 201 + EncounterOut."""
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])

    resp = _client().post(
        f"/patients/{uuid}/encounters",
        json={"encounter_type": "visit", "chief_complaint": "سرگیجه"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    body = resp.json()
    _assert_encounter_out(body)
    assert body["status"] == "open"
    assert body["encounter_type"] == "visit"
    assert body["chief_complaint"] == "سرگیجه"
    assert body["tenant_id"] == 1
    assert body["completed_at"] is None


# ─── 2. GET /patients/{uuid}/encounters → list shows created encounter ─────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_list_encounters_shows_created(seed_clinical_data):
    """
    POST creates an encounter; GET list returns it.
    total >= 1; the created encounter appears in items.
    """
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])
    client = _client()

    create_resp = client.post(
        f"/patients/{uuid}/encounters",
        json={"encounter_type": "phone"},
        headers=_auth(token),
    )
    assert create_resp.status_code == 201
    enc_id = create_resp.json()["id"]

    list_resp = client.get(
        f"/patients/{uuid}/encounters",
        headers=_auth(token),
    )
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert "items" in body and "total" in body and "limit" in body and "offset" in body
    assert body["total"] >= 1
    ids = [item["id"] for item in body["items"]]
    assert enc_id in ids, f"Created encounter {enc_id} not found in list: {ids}"


# ─── 3. POST /encounters/{id}/vitals → 200 + VitalsAddedResponse ──────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_add_vitals_to_encounter(seed_clinical_data):
    """
    POST /encounters/{id}/vitals with a list body → 200.
    Response: {count, vitals:[VitalReadingCreatedDTO]}.
    Vitals carry correct patient_link_id.
    """
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])
    link_id = seed_clinical_data["link_id"]
    client = _client()

    enc_resp = client.post(
        f"/patients/{uuid}/encounters",
        json={"encounter_type": "visit"},
        headers=_auth(token),
    )
    assert enc_resp.status_code == 201
    enc_id = enc_resp.json()["id"]

    vitals_resp = client.post(
        f"/encounters/{enc_id}/vitals",
        json=[
            {"type": "bp_systolic", "value": 135.0, "unit": "mmHg"},
            {"type": "bp_diastolic", "value": 88.0, "unit": "mmHg"},
        ],
        headers=_auth(token),
    )
    assert vitals_resp.status_code == 200, f"Expected 200: {vitals_resp.text}"
    body = vitals_resp.json()
    assert body["count"] == 2
    assert len(body["vitals"]) == 2
    types_returned = {v["type"] for v in body["vitals"]}
    assert "bp_systolic" in types_returned
    assert "bp_diastolic" in types_returned
    # All vitals should carry the correct patient_link_id
    for v in body["vitals"]:
        assert v["patient_link_id"] == link_id
        assert isinstance(v["id"], int)


# ─── 4. Vitals appear in GET /patients/{uuid}/record ──────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_vitals_appear_in_record(seed_clinical_data):
    """
    After adding a vital through POST /encounters/{id}/vitals,
    GET /patients/{uuid}/record recent_vitals includes it (by type).
    """
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])
    client = _client()

    enc_resp = client.post(
        f"/patients/{uuid}/encounters",
        json={"encounter_type": "visit"},
        headers=_auth(token),
    )
    assert enc_resp.status_code == 201
    enc_id = enc_resp.json()["id"]

    # Use a distinctive type to avoid clashing with seed_clinical_data vitals
    client.post(
        f"/encounters/{enc_id}/vitals",
        json=[{"type": "heart_rate", "value": 75.0, "unit": "bpm"}],
        headers=_auth(token),
    )

    record_resp = client.get(
        f"/patients/{uuid}/record",
        headers=_auth(token),
    )
    assert record_resp.status_code == 200
    recent_types = [v["type"] for v in record_resp.json()["recent_vitals"]]
    assert "heart_rate" in recent_types, (
        f"heart_rate not found in recent_vitals: {recent_types}"
    )


# ─── 5. POST /encounters/{id}/labs → 200 + LabsAddedResponse ──────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_add_labs_to_encounter(seed_clinical_data):
    """
    POST /encounters/{id}/labs with a list body → 200.
    Response: {count, labs:[LabResultCreatedDTO]}.
    encounter_id is set on each lab row.
    """
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])
    link_id = seed_clinical_data["link_id"]
    client = _client()

    enc_resp = client.post(
        f"/patients/{uuid}/encounters",
        json={"encounter_type": "visit"},
        headers=_auth(token),
    )
    assert enc_resp.status_code == 201
    enc_id = enc_resp.json()["id"]

    labs_resp = client.post(
        f"/encounters/{enc_id}/labs",
        json=[
            {"test_name": "HbA1c", "value": 7.4, "unit": "%"},
            {"test_name": "eGFR", "value": 68.0, "unit": "mL/min", "ref_low": 60.0},
        ],
        headers=_auth(token),
    )
    assert labs_resp.status_code == 200, f"Expected 200: {labs_resp.text}"
    body = labs_resp.json()
    assert body["count"] == 2
    assert len(body["labs"]) == 2
    test_names = {lab["test_name"] for lab in body["labs"]}
    assert "HbA1c" in test_names
    assert "eGFR" in test_names
    for lab in body["labs"]:
        assert lab["encounter_id"] == enc_id, "encounter_id must be set on each lab"
        assert lab["patient_link_id"] == link_id


# ─── 6. POST /encounters/{id}/complete → 200 + status=completed ──────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_complete_encounter_endpoint(seed_clinical_data):
    """
    POST /encounters/{id}/complete → 200 + EncounterOut with status=completed.
    completed_at is set; summary_note is stored.
    """
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])
    client = _client()

    enc_resp = client.post(
        f"/patients/{uuid}/encounters",
        json={"encounter_type": "visit"},
        headers=_auth(token),
    )
    assert enc_resp.status_code == 201
    enc_id = enc_resp.json()["id"]

    complete_resp = client.post(
        f"/encounters/{enc_id}/complete",
        json={"summary_note": "مرخص با نسخه"},
        headers=_auth(token),
    )
    assert complete_resp.status_code == 200, f"Expected 200: {complete_resp.text}"
    body = complete_resp.json()
    assert body["status"] == "completed"
    assert body["completed_at"] is not None
    assert body["summary_note"] == "مرخص با نسخه"
    _assert_encounter_out(body)


# ─── 7. POST /encounters/{id}/vitals after complete → 409 encounter_sealed ────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_add_vital_to_completed_encounter_is_409_sealed(seed_clinical_data):
    """
    After completing an encounter, POST /encounters/{id}/vitals returns
    409 with code='encounter_sealed'.
    """
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])
    client = _client()

    enc_resp = client.post(
        f"/patients/{uuid}/encounters",
        json={"encounter_type": "follow_up"},
        headers=_auth(token),
    )
    assert enc_resp.status_code == 201
    enc_id = enc_resp.json()["id"]

    client.post(f"/encounters/{enc_id}/complete", json={}, headers=_auth(token))

    sealed_resp = client.post(
        f"/encounters/{enc_id}/vitals",
        json=[{"type": "weight", "value": 80.0}],
        headers=_auth(token),
    )
    assert sealed_resp.status_code == 409, f"Expected 409: {sealed_resp.text}"
    _assert_error_contract(sealed_resp.json(), "encounter_sealed")


# ─── 8. POST /encounters/{id}/complete again → 409 invalid_transition ─────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_double_complete_returns_409_invalid_transition(seed_clinical_data):
    """
    Calling complete twice on the same encounter → 409 invalid_transition.
    """
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])
    client = _client()

    enc_resp = client.post(
        f"/patients/{uuid}/encounters",
        json={"encounter_type": "visit"},
        headers=_auth(token),
    )
    assert enc_resp.status_code == 201
    enc_id = enc_resp.json()["id"]

    client.post(f"/encounters/{enc_id}/complete", json={}, headers=_auth(token))

    again = client.post(
        f"/encounters/{enc_id}/complete", json={}, headers=_auth(token)
    )
    assert again.status_code == 409, f"Expected 409: {again.text}"
    _assert_error_contract(again.json(), "invalid_transition")


# ─── 9. POST /encounters/{id}/cancel → 200 cancelled ─────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_cancel_encounter_endpoint(seed_clinical_data):
    """
    POST /encounters/{id}/cancel on an open encounter → 200 + status=cancelled.
    reason stored in summary_note.
    """
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])
    client = _client()

    enc_resp = client.post(
        f"/patients/{uuid}/encounters",
        json={"encounter_type": "remote"},
        headers=_auth(token),
    )
    assert enc_resp.status_code == 201
    enc_id = enc_resp.json()["id"]

    cancel_resp = client.post(
        f"/encounters/{enc_id}/cancel",
        json={"reason": "بیمار انصراف داد"},
        headers=_auth(token),
    )
    assert cancel_resp.status_code == 200, f"Expected 200: {cancel_resp.text}"
    body = cancel_resp.json()
    assert body["status"] == "cancelled"
    assert body["summary_note"] == "بیمار انصراف داد"
    _assert_encounter_out(body)


# ─── 10. Bad encounter_type → 422 validation_error ────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_create_encounter_bad_type_returns_422(seed_clinical_data):
    """
    POST /patients/{uuid}/encounters with encounter_type='bogus' → 422 validation_error.
    """
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])

    resp = _client().post(
        f"/patients/{uuid}/encounters",
        json={"encounter_type": "bogus_type"},
        headers=_auth(token),
    )
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    _assert_error_contract(resp.json(), "validation_error")


# ─── 11. All endpoints → 401 without JWT ──────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_all_encounter_endpoints_require_jwt(seed_clinical_data):
    """
    All six encounter endpoints return 401 when called without a JWT.
    """
    uuid = str(seed_clinical_data["patient_uuid"])
    client = _client()

    endpoints = [
        ("POST", f"/patients/{uuid}/encounters", {"encounter_type": "visit"}),
        ("GET",  f"/patients/{uuid}/encounters", None),
        ("POST", "/encounters/999/vitals", [{"type": "weight", "value": 80.0}]),
        ("POST", "/encounters/999/labs", [{"test_name": "HbA1c", "value": 7.0}]),
        ("POST", "/encounters/999/complete", {}),
        ("POST", "/encounters/999/cancel", {}),
    ]

    for method, path, body in endpoints:
        if method == "GET":
            resp = client.get(path)
        elif body is None:
            resp = client.post(path)
        elif isinstance(body, list):
            resp = client.post(path, json=body)
        else:
            resp = client.post(path, json=body)
        assert resp.status_code == 401, (
            f"Expected 401 without JWT for {method} {path}, "
            f"got {resp.status_code}: {resp.text}"
        )


# ─── 12. Tenant isolation ─────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_encounter_tenant_isolation(seed_clinical_data):
    """
    An encounter created under tenant 1 is not accessible via tenant 2's token.

    Strategy:
      - seed_clinical_data has a tenant-2 patient (tenant2_patient_uuid).
      - We create a testuser2 for tenant 2 and get their JWT.
      - We create an encounter as tenant-1's testuser.
      - We call /encounters/{id}/complete as tenant-2's user → 404 not_found.
    """
    import os
    import bcrypt
    import psycopg

    PG_HOST = os.environ.get("PG_HOST", "localhost")
    PG_PORT = os.environ.get("PG_PORT", "55432")
    PG_SU_USER = os.environ.get("PG_USER", "postgres")
    PG_SU_PASSWORD = os.environ.get("PG_PASSWORD", "validate_only")
    TEST_DB_NAME = os.environ.get("PG_TEST_DB", "halqe_app_test")

    conninfo = (
        f"host='{PG_HOST}' port='{PG_PORT}' "
        f"user='{PG_SU_USER}' password='{PG_SU_PASSWORD}' dbname='{TEST_DB_NAME}'"
    )
    t2_password = "t2_pass_abc"
    pw_hash = bcrypt.hashpw(t2_password.encode(), bcrypt.gensalt())

    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute("""
            INSERT INTO platform.users
                (tenant_id, username, password_hash, role, app, is_active, failed_attempts)
            VALUES (2, 'testuser_t2', %s, 'staff', 'platform', TRUE, 0)
            ON CONFLICT (tenant_id, username) DO UPDATE
                SET password_hash = EXCLUDED.password_hash,
                    is_active = TRUE, failed_attempts = 0, locked_until = NULL
        """, (pw_hash,))

    client = _client()

    # Tenant-1 creates an encounter
    t1_token = _get_token(seed_clinical_data)
    t1_uuid = str(seed_clinical_data["patient_uuid"])
    enc_resp = client.post(
        f"/patients/{t1_uuid}/encounters",
        json={"encounter_type": "visit"},
        headers=_auth(t1_token),
    )
    assert enc_resp.status_code == 201
    enc_id = enc_resp.json()["id"]

    # Tenant-2 token
    t2_login = client.post(
        "/auth/login",
        json={"username": "testuser_t2", "password": t2_password},
    )
    assert t2_login.status_code == 200, f"T2 login failed: {t2_login.text}"
    t2_token = t2_login.json()["token"]

    # Tenant-2 tries to complete tenant-1's encounter → 404
    isolation_resp = client.post(
        f"/encounters/{enc_id}/complete",
        json={},
        headers=_auth(t2_token),
    )
    assert isolation_resp.status_code == 404, (
        f"Expected 404 for cross-tenant access, got {isolation_resp.status_code}: "
        f"{isolation_resp.text}"
    )
    _assert_error_contract(isolation_resp.json(), "not_found")


# ─── 13. Duplicate vital → 409 duplicate_vital ────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_duplicate_vital_returns_409_duplicate_vital(seed_clinical_data):
    """
    Adding the same vital twice (same type+measured_at+source) → 409 duplicate_vital.
    The service raises DuplicateVitalReading which the endpoint maps to 409.
    """
    from django.utils import timezone

    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])
    client = _client()

    enc_resp = client.post(
        f"/patients/{uuid}/encounters",
        json={"encounter_type": "visit"},
        headers=_auth(token),
    )
    assert enc_resp.status_code == 201
    enc_id = enc_resp.json()["id"]

    # First add: a vital with a fixed measured_at (so the natural key is deterministic)
    fixed_ts = timezone.now().replace(microsecond=0).isoformat()

    first = client.post(
        f"/encounters/{enc_id}/vitals",
        json=[{"type": "temperature", "value": 37.2, "unit": "C",
               "source": "clinic", "measured_at": fixed_ts}],
        headers=_auth(token),
    )
    assert first.status_code == 200, f"First vital add failed: {first.text}"

    # Second add: identical natural key → 409
    second = client.post(
        f"/encounters/{enc_id}/vitals",
        json=[{"type": "temperature", "value": 37.5, "unit": "C",
               "source": "clinic", "measured_at": fixed_ts}],
        headers=_auth(token),
    )
    assert second.status_code == 409, f"Expected 409 duplicate, got {second.status_code}: {second.text}"
    _assert_error_contract(second.json(), "duplicate_vital")


# ─── 14. Pagination: total/limit/offset ───────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_list_encounters_pagination(seed_clinical_data):
    """
    Create 3 encounters, then assert pagination fields (total >= 3, limit, offset).
    limit=1 should return exactly 1 item; offset=0 vs offset=1 returns different items.
    """
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])
    client = _client()

    for _ in range(3):
        r = client.post(
            f"/patients/{uuid}/encounters",
            json={"encounter_type": "visit"},
            headers=_auth(token),
        )
        assert r.status_code == 201

    # Fetch with limit=1, offset=0
    resp0 = client.get(
        f"/patients/{uuid}/encounters?limit=1&offset=0",
        headers=_auth(token),
    )
    assert resp0.status_code == 200
    body0 = resp0.json()
    assert body0["limit"] == 1
    assert body0["offset"] == 0
    assert body0["total"] >= 3
    assert len(body0["items"]) == 1

    # Fetch with limit=1, offset=1 — different item
    resp1 = client.get(
        f"/patients/{uuid}/encounters?limit=1&offset=1",
        headers=_auth(token),
    )
    assert resp1.status_code == 200
    body1 = resp1.json()
    assert len(body1["items"]) == 1
    # The two pages should have different encounter ids
    assert body0["items"][0]["id"] != body1["items"][0]["id"]


# ─── 15. POST /encounters/{id}/labs after complete → 409 encounter_sealed ─────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_add_lab_to_completed_encounter_is_409_sealed(seed_clinical_data):
    """
    POST /encounters/{id}/labs on a completed encounter → 409 encounter_sealed.
    """
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])
    client = _client()

    enc_resp = client.post(
        f"/patients/{uuid}/encounters",
        json={"encounter_type": "visit"},
        headers=_auth(token),
    )
    assert enc_resp.status_code == 201
    enc_id = enc_resp.json()["id"]

    client.post(f"/encounters/{enc_id}/complete", json={}, headers=_auth(token))

    sealed_resp = client.post(
        f"/encounters/{enc_id}/labs",
        json=[{"test_name": "Creatinine", "value": 1.2}],
        headers=_auth(token),
    )
    assert sealed_resp.status_code == 409, f"Expected 409: {sealed_resp.text}"
    _assert_error_contract(sealed_resp.json(), "encounter_sealed")


# ─── 16. Error bodies carry {detail, code} for all error paths ────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_error_bodies_contract_all_paths(seed_clinical_data):
    """
    Verify every documented error path returns ErrorSchema {detail: str, code: str}.

    Paths tested:
      - 404 not_found (non-existent encounter)
      - 409 invalid_transition (double-complete)
      - 409 encounter_sealed (add vital to completed)
      - 422 validation_error (bad encounter_type)
    """
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])
    client = _client()

    # 404 not_found — complete a non-existent encounter
    r1 = client.post("/encounters/999999/complete", json={}, headers=_auth(token))
    assert r1.status_code == 404
    _assert_error_contract(r1.json(), "not_found")

    # 409 invalid_transition — double complete
    enc_resp = client.post(
        f"/patients/{uuid}/encounters",
        json={"encounter_type": "visit"},
        headers=_auth(token),
    )
    assert enc_resp.status_code == 201
    enc_id = enc_resp.json()["id"]
    client.post(f"/encounters/{enc_id}/complete", json={}, headers=_auth(token))
    r2 = client.post(f"/encounters/{enc_id}/complete", json={}, headers=_auth(token))
    assert r2.status_code == 409
    _assert_error_contract(r2.json(), "invalid_transition")

    # 409 encounter_sealed — add vital after complete
    r3 = client.post(
        f"/encounters/{enc_id}/vitals",
        json=[{"type": "bmi", "value": 24.5}],
        headers=_auth(token),
    )
    assert r3.status_code == 409
    _assert_error_contract(r3.json(), "encounter_sealed")

    # 422 validation_error — bad encounter_type
    r4 = client.post(
        f"/patients/{uuid}/encounters",
        json={"encounter_type": "invalid_type"},
        headers=_auth(token),
    )
    assert r4.status_code == 422
    _assert_error_contract(r4.json(), "validation_error")
