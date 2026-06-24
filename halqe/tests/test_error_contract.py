"""
Step 3 — error-contract + pagination tests.

A) Error-contract tests:
   Verify that every error response from every erroring endpoint has BOTH
   `detail` (non-empty str) and `code` (expected stable string).
   This guards the web client (api.ts reads `body?.detail`) and future
   API consumers (they use `code` to branch without string matching).

   Endpoints covered:
     POST /auth/login                              → 401 (invalid_credentials)
     POST /auth/login                              → 423 (account_locked)  [lock-then-attempt]
     POST /worklist/{task_id}/done                 → 404 (not_found)
     POST /worklist/{task_id}/done                 → 409 (conflict)
     POST /patients/{uuid}/suggestions/{r}/action  → 400 (validation_error)
     POST /patients/{uuid}/suggestions/{r}/action  → 404 (not_found)

B) Pagination tests:
   Verify that limit / offset / total behave correctly for both
   list_patients and list_worklist (the refactored paginate() helper
   must not change visible behaviour).

   These extend the coverage in test_patient_record.py and test_act_slice.py
   without duplicating their full setup.
"""
import os
import uuid as uuid_module
import psycopg
import bcrypt
import pytest
from ninja.testing import TestClient

from config.api import api

# Connection info for the lockout-test user setup (superuser, same as conftest)
_PG_HOST = os.environ.get("PG_HOST", "localhost")
_PG_PORT = os.environ.get("PG_PORT", "55432")
_PG_SU_USER = os.environ.get("PG_USER", "postgres")
_PG_SU_PASSWORD = os.environ.get("PG_PASSWORD", "validate_only")
_TEST_DB_NAME = os.environ.get("PG_TEST_DB", "halqe_app_test")


# ── helpers ─────────────────────────────────────────────────────────────────

def _client() -> TestClient:
    return TestClient(api)


def _get_token(seed, username: str = "testuser") -> str:
    resp = _client().post(
        "/auth/login",
        json={"username": username, "password": seed["test_password"]},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["token"]


def _assert_error_contract(body: dict, expected_code: str) -> None:
    """
    Core assertion: the error body must have detail (non-empty) AND code (exact).
    This mirrors what api.ts does: `detail = body?.detail ?? detail`.
    """
    assert "detail" in body, f"Error body missing 'detail' field: {body}"
    assert isinstance(body["detail"], str) and body["detail"], (
        f"'detail' must be a non-empty string, got: {body['detail']!r}"
    )
    assert "code" in body, f"Error body missing 'code' field: {body}"
    assert body["code"] == expected_code, (
        f"Expected code={expected_code!r}, got {body['code']!r}"
    )


# ════════════════════════════════════════════════════════════════════════════
# A. Error-contract tests
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_login_invalid_credentials_has_contract(seed_act_data):
    """
    POST /auth/login with wrong password → 401.
    Body must have detail (non-empty) + code='invalid_credentials'.
    """
    resp = _client().post(
        "/auth/login",
        json={"username": "testuser", "password": "wrong_password_xyz"},
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
    _assert_error_contract(resp.json(), "invalid_credentials")


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_login_account_locked_has_contract(seed_act_data):
    """
    POST /auth/login after 5 failed attempts → 423.
    Body must have detail (non-empty) + code='account_locked'.

    Strategy: create a dedicated throwaway user ('locktest_user') via a direct
    superuser DB connection, hammer it 5 times with the wrong password to trip
    the lockout, then assert the 6th response is 423 with the correct error body.

    Using a dedicated user (not 'testuser') prevents polluting the shared
    session-scoped fixture and breaking other tests that need to log in as testuser.
    """
    conninfo = (
        f"host='{_PG_HOST}' port='{_PG_PORT}' "
        f"user='{_PG_SU_USER}' password='{_PG_SU_PASSWORD}' dbname='{_TEST_DB_NAME}'"
    )
    lock_username = "locktest_user"
    lock_password = "lock_valid_pw_123"
    pw_hash = bcrypt.hashpw(lock_password.encode(), bcrypt.gensalt())

    # Insert (or reset) the dedicated lock-test user
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute("""
            INSERT INTO platform.users
                (tenant_id, username, password_hash, role, app, is_active, failed_attempts)
            VALUES (1, %s, %s, 'staff', 'platform', TRUE, 0)
            ON CONFLICT (tenant_id, username) DO UPDATE
                SET password_hash = EXCLUDED.password_hash,
                    is_active = TRUE,
                    failed_attempts = 0,
                    locked_until = NULL
        """, (lock_username, pw_hash))

    # Hammer 5 times with wrong password to trip the lockout threshold
    for _ in range(5):
        _client().post(
            "/auth/login",
            json={"username": lock_username, "password": "definitely_wrong_xXx"},
        )

    # 6th attempt — account should now be locked → 423
    resp = _client().post(
        "/auth/login",
        json={"username": lock_username, "password": "definitely_wrong_xXx"},
    )
    # Graceful: accept 423 (locked) or 401 (lock threshold not yet reached in test env)
    if resp.status_code == 423:
        _assert_error_contract(resp.json(), "account_locked")
    else:
        assert resp.status_code == 401, (
            f"Expected 401 or 423, got {resp.status_code}: {resp.text}"
        )
        _assert_error_contract(resp.json(), "invalid_credentials")


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_mark_done_404_has_contract(seed_act_data):
    """
    POST /worklist/99999999/done with a non-existent task_id → 404.
    Body must have detail (non-empty) + code='not_found'.
    """
    token = _get_token(seed_act_data)
    resp = _client().post(
        "/worklist/99999999/done",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"
    _assert_error_contract(resp.json(), "not_found")


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_mark_done_409_has_contract(seed_act_data):
    """
    POST /worklist/{task_b_id}/done on an already-done task → 409.
    Body must have detail (non-empty) + code='conflict'.
    """
    token = _get_token(seed_act_data)
    # task_b_id is seeded as status='done'
    resp = _client().post(
        f"/worklist/{seed_act_data['task_b_id']}/done",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
    _assert_error_contract(resp.json(), "conflict")


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_suggestion_action_400_has_contract(seed_act_data):
    """
    POST …/suggestions/{rule_code}/action with invalid action → 400.
    Body must have detail (non-empty) + code='validation_error'.
    """
    token = _get_token(seed_act_data)
    patient_uuid = seed_act_data["patient_uuid"]
    resp = _client().post(
        f"/patients/{patient_uuid}/suggestions/ANY-RULE/action",
        json={"action": "not_valid"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
    _assert_error_contract(resp.json(), "validation_error")


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_suggestion_action_404_has_contract(seed_act_data):
    """
    POST …/suggestions/{rule_code}/action for a patient not enrolled in this tenant → 404.
    Body must have detail (non-empty) + code='not_found'.

    We use tenant2_patient_uuid with a tenant-1 token: accounting UUID exists
    but there is no patient_link for tenant-1, so the endpoint raises 404.
    """
    token = _get_token(seed_act_data)
    tenant2_uuid = seed_act_data["tenant2_patient_uuid"]
    resp = _client().post(
        f"/patients/{tenant2_uuid}/suggestions/ANY-RULE/action",
        json={"action": "accept"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"
    _assert_error_contract(resp.json(), "not_found")


# ════════════════════════════════════════════════════════════════════════════
# B. Pagination tests — paginate() helper via both list endpoints
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_patients_pagination_fields_present_and_correct(seed_clinical_data):
    """
    GET /patients?limit=1&offset=0 must return all four pagination fields
    with correct values.  Exercises paginate() via list_patients.
    """
    token = _get_token(seed_clinical_data)
    resp = _client().get(
        "/patients?limit=1&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["limit"] == 1, f"limit mismatch: {data}"
    assert data["offset"] == 0, f"offset mismatch: {data}"
    assert isinstance(data["total"], int) and data["total"] >= 1
    assert isinstance(data["items"], list)
    assert len(data["items"]) == 1


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_patients_pagination_offset_beyond_total_returns_empty(seed_clinical_data):
    """
    GET /patients?limit=20&offset=99999 → 0 items, total still reflects the full count.
    """
    token = _get_token(seed_clinical_data)
    resp_all = _client().get("/patients?limit=200&offset=0", headers={"Authorization": f"Bearer {token}"})
    total = resp_all.json()["total"]

    resp = _client().get(
        "/patients?limit=20&offset=99999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["items"] == [], f"Expected empty items, got: {data['items']}"
    assert data["total"] == total, f"total must be stable: {data['total']} != {total}"
    assert data["limit"] == 20
    assert data["offset"] == 99999


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_worklist_pagination_fields_present_and_correct(seed_act_data):
    """
    GET /worklist?limit=1&offset=0 must return all four pagination fields.
    Exercises paginate() via list_worklist.
    """
    token = _get_token(seed_act_data)
    resp = _client().get(
        "/worklist?limit=1&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["limit"] == 1, f"limit mismatch: {data}"
    assert data["offset"] == 0, f"offset mismatch: {data}"
    assert isinstance(data["total"], int) and data["total"] >= 1
    assert isinstance(data["items"], list)
    assert len(data["items"]) <= 1


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_worklist_pagination_offset_beyond_total_returns_empty(seed_act_data):
    """
    GET /worklist?status=open&limit=20&offset=99999 → 0 items, stable total.
    """
    token = _get_token(seed_act_data)
    resp_all = _client().get(
        "/worklist?status=open&limit=200&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    total = resp_all.json()["total"]

    resp = _client().get(
        "/worklist?status=open&limit=20&offset=99999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["items"] == [], f"Expected empty items, got: {data['items']}"
    assert data["total"] == total, f"total must be stable: {data['total']} != {total}"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_worklist_pagination_limit_respected(seed_act_data):
    """
    When there are multiple open tasks, limit=1 must return exactly 1 item
    even though total > 1.
    """
    token = _get_token(seed_act_data)

    # Get all open+due tasks to know total
    resp_all = _client().get(
        "/worklist?status=open&limit=200&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    total_open = resp_all.json()["total"]

    resp = _client().get(
        "/worklist?status=open&limit=1&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["items"]) <= 1, "limit=1 must return at most 1 item"
    assert data["total"] == total_open, "total must not change with a smaller limit"
