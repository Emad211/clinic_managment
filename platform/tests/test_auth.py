import bcrypt
import pytest

from apps.common.tenant import tenant_context
from apps.identity.services import AuthError, MAX_FAILED_ATTEMPTS, authenticate


def test_login_success(manager):
    with tenant_context(manager.clinic_id):
        u = authenticate(manager.clinic, "mgr", "secret")
    assert u.id == manager.id
    u.refresh_from_db()
    assert u.failed_attempts == 0 and u.last_login is not None


def test_login_wrong_password(manager):
    with tenant_context(manager.clinic_id):
        with pytest.raises(AuthError) as e:
            authenticate(manager.clinic, "mgr", "WRONG")
    assert e.value.code == "invalid_credentials"


def test_lockout_after_max_attempts(manager):
    with tenant_context(manager.clinic_id):
        for _ in range(MAX_FAILED_ATTEMPTS):
            with pytest.raises(AuthError):
                authenticate(manager.clinic, "mgr", "x")
        # even with the correct password, the account is now locked
        with pytest.raises(AuthError) as e:
            authenticate(manager.clinic, "mgr", "secret")
    assert e.value.code == "locked"


def test_api_login_flow(auth_client, manager):
    r = auth_client.get("/api/auth/me")
    assert r.status_code == 200 and r.json()["username"] == "mgr"
    auth_client.post("/api/auth/logout")
    assert auth_client.get("/api/auth/me").status_code == 401
