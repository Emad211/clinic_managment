"""
JWT HttpBearer auth for django-ninja.

Attach `auth=JWTBearer()` to any endpoint that requires a valid token.
The authenticated User object is available via request.auth.
"""
from ninja.security import HttpBearer

from platform_core.auth_service import get_user_from_token


class JWTBearer(HttpBearer):
    """
    Validates 'Authorization: Bearer <token>' on every protected request.

    Returns the User object on success; returns None (→ 401) on any failure.
    django-ninja will return HTTP 401 automatically when None is returned.
    """

    def authenticate(self, request, token: str):
        user = get_user_from_token(token)
        if user is None:
            return None
        # Attach tenant_id for downstream handler convenience
        request.tenant_id = user.tenant_id
        return user
