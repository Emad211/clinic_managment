"""
فاز ۱ کاکپیت — تست‌های endpointهای حساسیت (clinical.allergies).

Coverage matrix (tenant-1، JWT-authenticated مگر جایی که ذکر شود):

  1.  POST /patients/{uuid}/allergies → 201 + AllergyDTO (shape درست).
  2.  GET  /patients/{uuid}/allergies → allergyِ تازه‌ساخته را برمی‌گرداند.
  3.  POST با severity نامعتبر → 422 validation_error (CHECKِ DB آینه شده).
  4.  POST با severity خالی/حذف‌شده → 201 و severity=None.
  5.  POST با substance خالی → 422 validation_error.
  6.  DELETE /patients/{uuid}/allergies/{id} → 200 deleted، سپس از فهرست حذف.
  7.  DELETE ردیفِ ناموجود → 404 not_found.
  8.  هر سه endpoint بدونِ JWT → 401.
  9.  Tenant isolation: توکنِ tenant-2 روی بیمارِ tenant-1 → 404 (هر سه).
  10. Tenant isolation (data): allergyِ tenant-1 در فهرستِ tenant-2 (بیمارِ خودش) دیده نمی‌شود.
  11. Audit: allergy_added و allergy_deleted در clinical.activity_logs ثبت می‌شوند.

هیچ نوشتنی روی accounting.*. NullProvider (بدونِ SMS واقعی). RLS: GUC via JWTBearer.
تست‌ها روی DBِ throwaway (halqe_app_test) با sliceهای اعمال‌شده اجرا می‌شوند.
"""
import os

import pytest
import psycopg
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


def _su_conn():
    conninfo = (
        f"host='{os.environ.get('PG_HOST', 'localhost')}' "
        f"port='{os.environ.get('PG_PORT', '55432')}' "
        f"user='{os.environ.get('PG_USER', 'postgres')}' "
        f"password='{os.environ.get('PG_PASSWORD', 'validate_only')}' "
        f"dbname='{os.environ.get('PG_TEST_DB', 'halqe_app_test')}'"
    )
    return psycopg.connect(conninfo, autocommit=True)


def _assert_error_contract(body: dict, expected_code: str) -> None:
    assert "detail" in body and isinstance(body["detail"], str) and body["detail"], body
    assert body.get("code") == expected_code, (
        f"Expected code={expected_code!r}, got {body.get('code')!r}"
    )


def _assert_allergy_shape(body: dict) -> None:
    # قراردادِ حداقلیِ فرانت: {id, substance, severity, note}
    for field in ("id", "substance", "severity", "note", "created_at"):
        assert field in body, f"AllergyDTO missing '{field}': {body}"
    assert isinstance(body["id"], int)
    assert isinstance(body["substance"], str)


# ─── 1 + 2. create then list ─────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_create_and_list_allergy(seed_clinical_data):
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])
    client = _client()

    resp = client.post(
        f"/patients/{uuid}/allergies",
        json={"substance": "پنی‌سیلین", "severity": "severe", "note": "کهیر شدید"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    body = resp.json()
    _assert_allergy_shape(body)
    assert body["substance"] == "پنی‌سیلین"
    assert body["severity"] == "severe"
    assert body["note"] == "کهیر شدید"
    new_id = body["id"]

    # list shows it
    list_resp = client.get(f"/patients/{uuid}/allergies", headers=_auth(token))
    assert list_resp.status_code == 200, list_resp.text
    items = list_resp.json()
    assert isinstance(items, list)
    ids = [a["id"] for a in items]
    assert new_id in ids, f"created allergy {new_id} not in list {ids}"


# ─── 3. invalid severity → 422 ───────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_create_allergy_invalid_severity_422(seed_clinical_data):
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])

    resp = _client().post(
        f"/patients/{uuid}/allergies",
        json={"substance": "آسپرین", "severity": "fatal"},  # not in CHECK set
        headers=_auth(token),
    )
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    _assert_error_contract(resp.json(), "validation_error")


# ─── 4. empty severity → 201 + null ──────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_create_allergy_null_severity(seed_clinical_data):
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])

    resp = _client().post(
        f"/patients/{uuid}/allergies",
        json={"substance": "گرده گیاهان"},  # no severity, no note
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["severity"] is None
    assert body["note"] is None


# ─── 5. empty substance → 422 ────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_create_allergy_empty_substance_422(seed_clinical_data):
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])

    resp = _client().post(
        f"/patients/{uuid}/allergies",
        json={"substance": "   "},  # whitespace-only
        headers=_auth(token),
    )
    assert resp.status_code == 422, resp.text
    _assert_error_contract(resp.json(), "validation_error")


# ─── 6. delete → 200 then gone ───────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_delete_allergy(seed_clinical_data):
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])
    client = _client()

    create = client.post(
        f"/patients/{uuid}/allergies",
        json={"substance": "لاتکس", "severity": "moderate"},
        headers=_auth(token),
    )
    assert create.status_code == 201
    aid = create.json()["id"]

    dele = client.delete(f"/patients/{uuid}/allergies/{aid}", headers=_auth(token))
    assert dele.status_code == 200, dele.text
    assert dele.json() == {"deleted": True, "id": aid}

    # gone from list
    items = client.get(f"/patients/{uuid}/allergies", headers=_auth(token)).json()
    assert aid not in [a["id"] for a in items]


# ─── 7. delete missing → 404 ─────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_delete_missing_allergy_404(seed_clinical_data):
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])

    resp = _client().delete(
        f"/patients/{uuid}/allergies/99999999", headers=_auth(token)
    )
    assert resp.status_code == 404, resp.text
    _assert_error_contract(resp.json(), "not_found")


# ─── 8. no JWT → 401 (all three verbs) ───────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_allergies_require_jwt(seed_clinical_data):
    uuid = str(seed_clinical_data["patient_uuid"])
    client = _client()

    assert client.get(f"/patients/{uuid}/allergies").status_code == 401
    assert client.post(
        f"/patients/{uuid}/allergies", json={"substance": "x"}
    ).status_code == 401
    assert client.delete(f"/patients/{uuid}/allergies/1").status_code == 401


# ─── 9 + 10. tenant isolation ────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_allergy_tenant_isolation(seed_clinical_data):
    """
    توکنِ tenant-2 نباید به بیمارِ tenant-1 دسترسی داشته باشد (404 در هر سه)،
    و allergyِ tenant-1 نباید در فهرستِ tenant-2 (روی بیمارِ خودِ tenant-2) دیده شود.
    """
    import bcrypt

    # testuser_t2 برای tenant 2
    t2_password = "t2_alg_pass"
    pw_hash = bcrypt.hashpw(t2_password.encode(), bcrypt.gensalt())
    with _su_conn() as conn:
        conn.execute("""
            INSERT INTO platform.users
                (tenant_id, username, password_hash, role, app, is_active, failed_attempts)
            VALUES (2, 'testuser_t2_alg', %s, 'staff', 'platform', TRUE, 0)
            ON CONFLICT (tenant_id, username) DO UPDATE
                SET password_hash = EXCLUDED.password_hash,
                    is_active = TRUE, failed_attempts = 0, locked_until = NULL
        """, (pw_hash,))

    client = _client()

    # tenant-1: create an allergy on its own patient
    t1_token = _get_token(seed_clinical_data)
    t1_uuid = str(seed_clinical_data["patient_uuid"])
    created = client.post(
        f"/patients/{t1_uuid}/allergies",
        json={"substance": "سولفونامید", "severity": "mild"},
        headers=_auth(t1_token),
    )
    assert created.status_code == 201
    t1_allergy_id = created.json()["id"]

    # tenant-2 token
    t2_login = client.post(
        "/auth/login",
        json={"username": "testuser_t2_alg", "password": t2_password},
    )
    assert t2_login.status_code == 200, t2_login.text
    t2_token = t2_login.json()["token"]

    # (9) tenant-2 hitting tenant-1's patient uuid → 404 on all three verbs.
    #     _resolve_patient_link_for_tenant fails (no enrollment for tenant 2).
    r_get = client.get(f"/patients/{t1_uuid}/allergies", headers=_auth(t2_token))
    assert r_get.status_code == 404, r_get.text
    r_post = client.post(
        f"/patients/{t1_uuid}/allergies",
        json={"substance": "hack"},
        headers=_auth(t2_token),
    )
    assert r_post.status_code == 404, r_post.text
    r_del = client.delete(
        f"/patients/{t1_uuid}/allergies/{t1_allergy_id}", headers=_auth(t2_token)
    )
    assert r_del.status_code == 404, r_del.text

    # (10) tenant-2 listing ITS OWN patient must not see tenant-1's allergy.
    t2_patient_uuid = str(seed_clinical_data["tenant2_patient_uuid"])
    t2_list = client.get(
        f"/patients/{t2_patient_uuid}/allergies", headers=_auth(t2_token)
    )
    assert t2_list.status_code == 200, t2_list.text
    t2_ids = [a["id"] for a in t2_list.json()]
    assert t1_allergy_id not in t2_ids, (
        "RLS leak: tenant-1 allergy visible in tenant-2 listing"
    )

    # the tenant-1 allergy is still there for tenant-1 (not deleted by t2 attempt)
    t1_list = client.get(f"/patients/{t1_uuid}/allergies", headers=_auth(t1_token))
    assert t1_allergy_id in [a["id"] for a in t1_list.json()]


# ─── 11. audit trail on add + delete ─────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_allergy_writes_are_audited(seed_clinical_data):
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])
    client = _client()

    created = client.post(
        f"/patients/{uuid}/allergies",
        json={"substance": "کدئین", "severity": "severe"},
        headers=_auth(token),
    )
    assert created.status_code == 201
    aid = created.json()["id"]

    client.delete(f"/patients/{uuid}/allergies/{aid}", headers=_auth(token))

    # verify both audit rows exist (superuser read — RLS bypassed for assertion)
    with _su_conn() as conn:
        added = conn.execute("""
            SELECT count(*) FROM clinical.activity_logs
            WHERE action_type='allergy_added' AND target_table='allergies'
              AND target_id=%s AND tenant_id=1
        """, (aid,)).fetchone()[0]
        deleted = conn.execute("""
            SELECT count(*) FROM clinical.activity_logs
            WHERE action_type='allergy_deleted' AND target_table='allergies'
              AND target_id=%s AND tenant_id=1
        """, (aid,)).fetchone()[0]

    assert added == 1, f"expected 1 allergy_added audit row, got {added}"
    assert deleted == 1, f"expected 1 allergy_deleted audit row, got {deleted}"
