"""
Auth tests — halqe platform.

Coverage:
  1. POST /auth/login with correct credentials → 200 + JWT token
  2. POST /auth/login with wrong password → 401 + failed_attempts increments
  3. Lockout after 5 consecutive failed attempts → 423
  4. Protected endpoint without token → 401
  5. Protected endpoint with valid token → 200
  6. Protected endpoint with garbage token → 401
  7. Protected endpoint with expired token → 401
"""
import datetime
import uuid
import pytest
import jwt

from django.conf import settings
from ninja.testing import TestClient
from config.api import api


def _client():
    return TestClient(api)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(username="testuser", password="secret123"):
    client = _client()
    return client.post("/auth/login", json={"username": username, "password": password})


def _reset_user(seed_data):
    """Reset testuser's failed_attempts and locked_until after lockout tests."""
    import psycopg
    import os

    db_name = os.environ.get("PG_TEST_DB", "halqe_app_test")
    conninfo = (
        f"host='localhost' port='55432' user='postgres' "
        f"password='validate_only' dbname='{db_name}'"
    )
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute(
            "UPDATE platform.users SET failed_attempts=0, locked_until=NULL "
            "WHERE tenant_id=1 AND username='testuser'"
        )


# ---------------------------------------------------------------------------
# Test 1 — login success → token
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_login_success_returns_token(seed_data):
    """POST /auth/login با رمزِ درست → ۲۰۰ + توکنِ JWT معتبر."""
    resp = _login(password=seed_data["test_password"])
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "token" in data

    # توکن باید قابلِ decode باشد
    claims = jwt.decode(data["token"], settings.SECRET_KEY, algorithms=["HS256"])
    assert claims["user_id"] == seed_data["user_id"]
    assert claims["tenant_id"] == 1
    assert "exp" in claims


# ---------------------------------------------------------------------------
# Test 2 — wrong password → 401 + failed_attempts increments
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_wrong_password_returns_401_and_increments_attempts(seed_data):
    """رمزِ اشتباه → ۴۰۱ و failed_attempts افزایش می‌یابد."""
    # اطمینان از شروع با حساب پاک
    _reset_user(seed_data)

    from platform_core.models import User
    user_before = User.objects.get(pk=seed_data["user_id"])
    attempts_before = user_before.failed_attempts

    resp = _login(password="wrong_password")
    assert resp.status_code == 401, resp.text

    user_after = User.objects.get(pk=seed_data["user_id"])
    assert user_after.failed_attempts == attempts_before + 1

    # تمیزکاری
    _reset_user(seed_data)


# ---------------------------------------------------------------------------
# Test 3 — lockout after 5 failures → 423
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_lockout_after_5_failures(seed_data):
    """۵ بار رمزِ اشتباه → قفل‌شدن و ۴۲۳ برای تلاشِ بعدی."""
    _reset_user(seed_data)

    for i in range(5):
        resp = _login(password="bad_pw")
        # اولین ۴ بار ۴۰۱، بار پنجم هم ۴۰۱ (قفل در همین لحظه می‌شود)
        assert resp.status_code == 401, f"attempt {i+1}: expected 401, got {resp.status_code}"

    # حالا باید ۴۲۳ بدهد
    resp = _login(password="bad_pw")
    assert resp.status_code == 423, f"پس از ۵ تلاش باید ۴۲۳ بدهد؛ گرفت: {resp.status_code}"

    # پس از تست، حساب را بازنشانی کن
    _reset_user(seed_data)


# ---------------------------------------------------------------------------
# Test 4 — protected endpoint without token → 401
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_protected_endpoint_without_token_returns_401(seed_data):
    """GET /patients/{uuid} بدونِ توکن → ۴۰۱."""
    client = _client()
    patient_uuid = seed_data["patient_uuid"]
    resp = client.get(f"/patients/{patient_uuid}")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# Test 5 — protected endpoint with valid token → 200
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_protected_endpoint_with_valid_token_returns_200(seed_data):
    """GET /patients/{uuid} با توکنِ معتبر → ۲۰۰."""
    login_resp = _login(password=seed_data["test_password"])
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]

    client = _client()
    patient_uuid = seed_data["patient_uuid"]
    resp = client.get(
        f"/patients/{patient_uuid}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["uuid"] == str(patient_uuid)


# ---------------------------------------------------------------------------
# Test 6 — protected endpoint with garbage token → 401
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_protected_endpoint_with_garbage_token_returns_401(seed_data):
    """GET /patients/{uuid} با توکنِ نامعتبر → ۴۰۱."""
    client = _client()
    patient_uuid = seed_data["patient_uuid"]
    resp = client.get(
        f"/patients/{patient_uuid}",
        headers={"Authorization": "Bearer this.is.garbage"},
    )
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# Test 7 — protected endpoint with expired token → 401
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_protected_endpoint_with_expired_token_returns_401(seed_data):
    """GET /patients/{uuid} با توکنِ منقضی‌شده → ۴۰۱."""
    # ساختِ توکنِ از قبل منقضی‌شده
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    expired_token = jwt.encode(
        {
            "user_id": seed_data["user_id"],
            "tenant_id": 1,
            "role": "staff",
            "exp": past,
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )

    client = _client()
    patient_uuid = seed_data["patient_uuid"]
    resp = client.get(
        f"/patients/{patient_uuid}",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert resp.status_code == 401, resp.text
