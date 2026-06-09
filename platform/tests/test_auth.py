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
        # even with the correct password, the account is now locked — and the
        # error is the SAME generic code as any other failure (no state oracle)
        with pytest.raises(AuthError) as e:
            authenticate(manager.clinic, "mgr", "secret")
    assert e.value.code == "invalid_credentials"
    manager.refresh_from_db()
    assert manager.locked_until is not None  # lockout is enforced internally


def test_login_failures_are_indistinguishable(clinic, manager):
    """Wrong-user, wrong-password, and inactive all return the same code/message
    so login can't be used to enumerate usernames or probe account state."""
    import bcrypt as _bcrypt
    from apps.identity.models import AppUser

    inactive = AppUser.objects.create(
        clinic=clinic, username="ghost", role="reception",
        password_hash=_bcrypt.hashpw(b"secret", _bcrypt.gensalt()), is_active=False,
    )
    with tenant_context(clinic.id):
        errs = []
        for uname, pw in [("nobody", "x"), ("mgr", "WRONG"), ("ghost", "secret")]:
            with pytest.raises(AuthError) as e:
                authenticate(clinic, uname, pw)
            errs.append((e.value.code, e.value.message))
    assert len({c for c, _ in errs}) == 1   # one code for every failure mode
    assert len({m for _, m in errs}) == 1   # one message too


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
