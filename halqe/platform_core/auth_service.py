"""
Auth service — halqe platform.

Mirrors the security model of specialist_clinic and webapp:
  - bcrypt password verification (stored as BYTEA in platform.users)
  - 5 bad attempts → locked_until = now + 15 min
  - On success: reset failed_attempts, set last_login, issue JWT (8h)
  - JWT claims: user_id, tenant_id, role, exp

No Django contrib.auth involved (not installed). All state written to
platform.users (via platform_app role → write access on platform schema).
"""
from __future__ import annotations

import datetime
from typing import Optional

import bcrypt
import jwt
from django.conf import settings
from django.utils import timezone

from platform_core.models import User

_LOCKOUT_ATTEMPTS = 5
_LOCKOUT_MINUTES = 15
_JWT_EXPIRY_HOURS = 8


class AuthError(Exception):
    """
    Base auth error — subclasses carry HTTP status hints.

    tenant_id attribute (optional, set by callers):
      When the user WAS found in the DB but auth failed (wrong password,
      locked, inactive), the caller attaches the resolved user's tenant_id
      so the audit row records the REAL tenant rather than a sentinel.
      When the user was NOT found (DoesNotExist / ambiguous username),
      tenant_id is None — the audit layer must use SYSTEM_TENANT_ID instead.
    """
    http_status = 500
    tenant_id: Optional[int] = None    # set after construction when user is known


class InvalidCredentials(AuthError):
    http_status = 401


class AccountLocked(AuthError):
    http_status = 423


class AccountInactive(AuthError):
    http_status = 401


def login(username: str, password: str) -> str:
    """
    Verify credentials and return a signed JWT on success.

    Tenant resolution: looks up the user by username ONLY (no tenant filter).
    Real tenant routing (subdomain / host header) is a future step — platform.tenants
    currently has NO subdomain column, so we cannot derive tenant from the host.
    For single-tenant deployments this is correct. For multi-tenant, the correct
    tenant will be derived automatically from the resolved user's tenant_id.

    MultipleObjectsReturned (username exists in two tenants): treated as auth
    failure with InvalidCredentials — ambiguous login is not allowed without a
    tenant discriminator.  This is the safe, conservative choice until host-based
    routing is implemented.

    Raises:
        InvalidCredentials — user not found, wrong password, or ambiguous (multi-tenant collision)
        AccountLocked      — locked_until is in the future
        AccountInactive    — is_active = False
    """
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        raise InvalidCredentials("نام کاربری یا رمز اشتباه است")
    except User.MultipleObjectsReturned:
        # Username exists in multiple tenants.  Without a tenant discriminator
        # (subdomain / host-header routing — deferred to a future step) we
        # cannot safely choose one.  Treat as auth failure: ambiguous identity.
        raise InvalidCredentials("نام کاربری یا رمز اشتباه است")

    if not user.is_active:
        exc = AccountInactive("حساب غیرفعال است")
        exc.tenant_id = user.tenant_id  # user was found → real tenant known
        raise exc

    now = timezone.now()
    if user.locked_until and user.locked_until > now:
        exc = AccountLocked(f"حساب تا {user.locked_until.isoformat()} قفل است")
        exc.tenant_id = user.tenant_id  # user was found → real tenant known
        raise exc

    # Verify bcrypt — password_hash is memoryview/bytes from BinaryField
    pw_hash: bytes = bytes(user.password_hash)
    if not bcrypt.checkpw(password.encode(), pw_hash):
        _record_bad_attempt(user, now)
        exc = InvalidCredentials("نام کاربری یا رمز اشتباه است")
        exc.tenant_id = user.tenant_id  # user was found → real tenant known
        raise exc

    # Success — reset counter, record last_login
    User.objects.filter(pk=user.pk).update(
        failed_attempts=0,
        locked_until=None,
        last_login=now,
    )

    return _make_jwt(user)


def _record_bad_attempt(user: User, now: datetime.datetime) -> None:
    new_attempts = user.failed_attempts + 1
    locked_until = None
    if new_attempts >= _LOCKOUT_ATTEMPTS:
        locked_until = now + datetime.timedelta(minutes=_LOCKOUT_MINUTES)
    User.objects.filter(pk=user.pk).update(
        failed_attempts=new_attempts,
        locked_until=locked_until,
    )


def _make_jwt(user: User) -> str:
    exp = timezone.now() + datetime.timedelta(hours=_JWT_EXPIRY_HOURS)
    payload = {
        "user_id": user.pk,
        "tenant_id": user.tenant_id,
        "role": user.role,
        "exp": exp,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_jwt(token: str) -> dict:
    """
    Decode and validate a JWT. Raises jwt.PyJWTError on any failure
    (expired, bad signature, malformed).
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])


def get_user_from_token(token: str) -> Optional[User]:
    """
    Full validation: decode JWT, load the User, check is_active + not locked.
    Returns None if any check fails (caller should return 401).
    """
    try:
        claims = decode_jwt(token)
    except Exception:
        return None

    try:
        user = User.objects.get(pk=claims["user_id"])
    except (User.DoesNotExist, KeyError):
        return None

    now = timezone.now()
    if not user.is_active:
        return None
    if user.locked_until and user.locked_until > now:
        return None

    return user
