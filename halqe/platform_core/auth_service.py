"""
Auth service — halqe platform.

Mirrors the security model of specialist_clinic and webapp:
  - bcrypt password verification (stored as BYTEA in platform.users)
  - 5 bad attempts → locked_until = now + 15 min
  - On success: reset failed_attempts, set last_login, issue JWT (8h)
  - JWT claims: user_id, tenant_id, role, exp

No Django contrib.auth involved (not installed). All state written to
platform.users via SECURITY DEFINER functions (auth_lookup_user /
auth_record_attempt) — NOT via raw ORM queries that hit RLS.

WHY SECURITY DEFINER functions instead of User.objects.get/filter:
  login() must look up a user by username WITHOUT knowing tenant_id
  (chicken-and-egg: you need the user to know the tenant, need the
  tenant to scope RLS). With slice5 RLS active, a direct ORM query
  runs under the app role (platform_login_test / platform_app) and
  the GUC is empty at login time → RLS makes the UPDATE return 0 rows.

  platform.auth_lookup_user(username):
    SECURITY DEFINER (owner=superuser → BYPASSRLS).
    Returns exactly the 8 columns needed for auth; no api_token_hash
    (least-privilege — login path doesn't need it).
    No LIMIT → caller detects ambiguous (>1 row) safely.

  platform.auth_record_attempt(user_id, success, threshold, minutes):
    SECURITY DEFINER → UPDATE succeeds without a GUC.
    Threshold params passed from Python so SQL never hardcodes them.

get_user_from_token() (line ~157) is intentionally left as an ORM
query: it runs after JWTBearer sets the GUC → the query is correctly
tenant-scoped. Do not touch it.
"""
from __future__ import annotations

import datetime
from collections import namedtuple
from typing import Optional

import bcrypt
import jwt
from django.conf import settings
from django.db import connection
from django.utils import timezone

from platform_core.models import User

_LOCKOUT_ATTEMPTS = 5
_LOCKOUT_MINUTES = 15
_JWT_EXPIRY_HOURS = 8

# Lightweight stand-in for a User ORM object — only the fields auth_service
# needs after auth_lookup_user returns.  Keeps the rest of the logic identical
# to before without pulling in a full ORM model (which would trigger RLS).
_AuthUser = namedtuple(
    "_AuthUser",
    ["pk", "tenant_id", "username", "password_hash",
     "role", "is_active", "failed_attempts", "locked_until"],
)


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


def _lookup_user(username: str) -> _AuthUser:
    """
    Call platform.auth_lookup_user(username) via a raw cursor.

    The function is SECURITY DEFINER and bypasses RLS — safe because it
    returns only 8 columns (no api_token_hash) and is GRANT-ed only to
    platform_app.

    Raises:
        InvalidCredentials — 0 rows (not found) or >1 rows (ambiguous)
    """
    with connection.cursor() as cur:
        cur.execute(
            "SELECT * FROM platform.auth_lookup_user(%s)",
            [username],
        )
        rows = cur.fetchall()

    if len(rows) == 0:
        raise InvalidCredentials("نام کاربری یا رمز اشتباه است")
    if len(rows) > 1:
        # Username exists in multiple tenants.  Without a tenant discriminator
        # (subdomain / host-header routing — deferred to a future step) we
        # cannot safely choose one.  Treat as auth failure: ambiguous identity.
        raise InvalidCredentials("نام کاربری یا رمز اشتباه است")

    row = rows[0]
    # Row order matches the RETURNS TABLE declaration in slice7:
    # (id, tenant_id, username, password_hash, role, is_active,
    #  failed_attempts, locked_until)
    return _AuthUser(
        pk=row[0],
        tenant_id=row[1],
        username=row[2],
        password_hash=row[3],
        role=row[4],
        is_active=row[5],
        failed_attempts=row[6],
        locked_until=row[7],
    )


def _record_attempt(user_id: int, success: bool) -> None:
    """
    Call platform.auth_record_attempt() via a raw cursor.

    SECURITY DEFINER → UPDATE succeeds without GUC being set.
    Lockout threshold/minutes come from Python constants (source of truth).
    """
    with connection.cursor() as cur:
        cur.execute(
            "SELECT platform.auth_record_attempt(%s, %s, %s, %s)",
            [user_id, success, _LOCKOUT_ATTEMPTS, _LOCKOUT_MINUTES],
        )


def login(username: str, password: str) -> str:
    """
    Verify credentials and return a signed JWT on success.

    Tenant resolution: looks up the user by username ONLY (no tenant filter).
    Real tenant routing (subdomain / host header) is a future step — platform.tenants
    currently has NO subdomain column, so we cannot derive tenant from the host.
    For single-tenant deployments this is correct. For multi-tenant, the correct
    tenant will be derived automatically from the resolved user's tenant_id.

    Uses SECURITY DEFINER functions (auth_lookup_user / auth_record_attempt) to
    bypass RLS for the lookup and update steps — because GUC is empty at login time.

    Raises:
        InvalidCredentials — user not found, wrong password, or ambiguous (multi-tenant collision)
        AccountLocked      — locked_until is in the future
        AccountInactive    — is_active = False
    """
    user = _lookup_user(username)   # raises InvalidCredentials if 0 or >1 rows

    if not user.is_active:
        exc = AccountInactive("حساب غیرفعال است")
        exc.tenant_id = user.tenant_id  # user was found → real tenant known
        raise exc

    now = timezone.now()
    if user.locked_until and user.locked_until > now:
        exc = AccountLocked(f"حساب تا {user.locked_until.isoformat()} قفل است")
        exc.tenant_id = user.tenant_id  # user was found → real tenant known
        raise exc

    # Verify bcrypt — password_hash is memoryview/bytes from DB (BYTEA → psycopg3 bytes)
    pw_hash: bytes = bytes(user.password_hash)
    if not bcrypt.checkpw(password.encode(), pw_hash):
        _record_attempt(user.pk, success=False)
        exc = InvalidCredentials("نام کاربری یا رمز اشتباه است")
        exc.tenant_id = user.tenant_id  # user was found → real tenant known
        raise exc

    # Success — reset counter, record last_login
    _record_attempt(user.pk, success=True)

    return _make_jwt(user)


def _make_jwt(user: _AuthUser) -> str:
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

    Chicken-and-egg (same as login): this runs BEFORE JWTBearer sets the GUC, so
    it must set the GUC itself from the JWT's tenant_id claim before the ORM load.
    Otherwise the fully-isolated platform.users (step 34 dropped the open SELECT
    policy) hides the row under the wrong/empty tenant GUC, and every authed
    request for a non-default tenant 401s.  decode_jwt has already verified the
    signature, so the tenant_id claim is authentic — a forged tenant_id would
    fail signature verification above.
    """
    try:
        claims = decode_jwt(token)
    except Exception:
        return None

    tenant_id = claims.get("tenant_id")
    if tenant_id is None:
        return None
    # Set the GUC from the trusted (signature-verified) claim BEFORE the ORM load,
    # so the User.objects.get below is correctly tenant-scoped under RLS.
    from platform_core.tenant_context import set_tenant_guc
    set_tenant_guc(tenant_id)

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
