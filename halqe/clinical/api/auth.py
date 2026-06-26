"""
Auth domain router — POST /api/v1/auth/login.

Migrated out of the ``config/api.py`` god-file in cleanup step 3.

Full URL is preserved byte-for-byte: ``config.api`` wires this router with
``api.add_router("", auth_router)`` and the route below is ``"/auth/login"``,
so ``/api/v1`` (from ``urls.py``) + ``""`` (prefix) + ``"/auth/login"`` ==
``/api/v1/auth/login`` — identical to before.

The endpoint is public (``auth=None``): it issues the token, so it cannot
itself require one.
"""
from typing import Optional

from ninja import Router, Schema

from config.api_base import SYSTEM_TENANT_ID
from config.errors import ErrorSchema, error_response
from clinical.audit import log_activity
from platform_core.auth_service import (
    login,
    InvalidCredentials,
    AccountLocked,
    AccountInactive,
)

router = Router()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LoginRequest(Schema):
    username: str
    password: str


class TokenResponse(Schema):
    token: str


# ---------------------------------------------------------------------------
# POST /auth/login  →  /api/v1/auth/login
# ---------------------------------------------------------------------------

@router.post(
    "/auth/login",
    response={200: TokenResponse, 401: ErrorSchema, 423: ErrorSchema},
    auth=None,
    tags=["auth"],
)
def auth_login(request, body: LoginRequest):
    """
    Verify credentials against platform.users (bcrypt).
    Returns a signed JWT (8h) on success.
    401 on wrong credentials or inactive account.
    423 on locked account.
    """
    try:
        token = login(body.username, body.password)
        # Resolve user_id from the token claims for the audit row.
        # We decode here rather than issuing a second DB query — the JWT was
        # just signed by auth_service.login so it is guaranteed valid.
        from platform_core.auth_service import decode_jwt
        claims = decode_jwt(token)
        log_activity(
            tenant_id=claims.get("tenant_id", SYSTEM_TENANT_ID),
            user_id=claims.get("user_id"),
            username=body.username,
            action_type="login",
            action_category="auth",
            description="successful login",
        )
        return 200, {"token": token}
    except AccountLocked as exc:
        # exc.tenant_id is set when the user WAS found (wrong password triggers
        # lockout after 5 attempts — user object was resolved before the lock).
        # Falls back to SYSTEM_TENANT_ID only if tenant is truly unknown.
        audit_tenant = exc.tenant_id if exc.tenant_id is not None else SYSTEM_TENANT_ID
        log_activity(
            tenant_id=audit_tenant,
            user_id=None,
            username=body.username,
            action_type="login_failed",
            action_category="auth",
            description="account locked",
        )
        return 423, error_response(str(exc), "account_locked")
    except (InvalidCredentials, AccountInactive) as exc:
        # exc.tenant_id is set when the user WAS found (wrong password case).
        # It is None when the username does not exist or is ambiguous (multi-tenant).
        audit_tenant = exc.tenant_id if exc.tenant_id is not None else SYSTEM_TENANT_ID
        log_activity(
            tenant_id=audit_tenant,
            user_id=None,
            username=body.username,
            action_type="login_failed",
            action_category="auth",
            description=str(exc),
        )
        return 401, error_response(str(exc), "invalid_credentials")
