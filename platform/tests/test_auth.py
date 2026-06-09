import bcrypt
import pytest
from django.core.exceptions import ValidationError

from apps.common.tenant import tenant_context
from apps.identity.models import AppUser
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


# ── clinical licensing gate (REGULATORY §1/§6) ──────────────────────────────

def test_licensed_doctor_can_practice(doctor):
    assert doctor.is_licensed and doctor.can_practice_clinically()


def test_unlicensed_manager_cannot_practice(manager):
    assert not manager.is_licensed and not manager.can_practice_clinically()


def test_clinical_role_requires_license_no(clinic):
    """A doctor/nurse account with no license number fails model validation."""
    u = AppUser(clinic=clinic, username="d2", role="doctor", password_hash=b"x")
    with pytest.raises(ValidationError) as e:
        u.full_clean()
    assert "medical_license_no" in e.value.message_dict


def test_inactive_licensed_user_cannot_practice(doctor):
    doctor.is_active = False
    assert not doctor.can_practice_clinically()
