"""
JWT HttpBearer auth for django-ninja.

Attach `auth=JWTBearer()` to any endpoint that requires a valid token.
The authenticated User object is available via request.auth.
"""
from ninja.security import HttpBearer

from platform_core.auth_service import get_user_from_token
from platform_core.tenant_context import set_tenant_guc


class JWTBearer(HttpBearer):
    """
    Validates 'Authorization: Bearer <token>' on every protected request.

    Returns the User object on success; returns None (→ 401) on any failure.
    django-ninja will return HTTP 401 automatically when None is returned.

    GUC flow (Step 2):
      TenantGucMiddleware already cleared app.current_tenant to '' before
      this method runs.  Once the user is resolved we SET it to the user's
      real tenant_id so every subsequent query on this request's connection
      sees the correct value.  RLS policies (Step 19) will rely on this GUC.
    """

    def authenticate(self, request, token: str):
        user = get_user_from_token(token)
        if user is None:
            return None
        # Attach tenant_id for downstream handler convenience
        request.tenant_id = user.tenant_id
        # Set the GUC so all queries on this connection are tenant-scoped.
        # This runs AFTER TenantGucMiddleware cleared it, so the value is
        # always correct for the current request.
        set_tenant_guc(user.tenant_id)
        return user
