"""django-ninja auth dependency: session-based principal resolution.

Returns the logged-in AppUser (loaded inside its clinic's tenant context) or
None — ninja turns None into a 401. Attach to routers that require a logged-in
user; leave /auth/login + /health open.

``require_role`` is a helper for endpoint-level RBAC (follows the Flask apps'
inline ``if g.user['role'] != ...`` pattern rather than a decorator).
"""

from ninja.errors import HttpError

from apps.common.tenant import tenant_context


class SessionAuth:
    def __call__(self, request):
        user_id = request.session.get("user_id")
        clinic_id = request.session.get("clinic_id")
        if not user_id or not clinic_id:
            return None
        from apps.identity.models import AppUser  # lazy to avoid import cycle

        with tenant_context(clinic_id):
            try:
                user = AppUser.objects.get(id=user_id, is_active=True)
            except AppUser.DoesNotExist:
                return None
        # expose for downstream handlers / RBAC
        request.app_user = user
        return user


session_auth = SessionAuth()


def require_role(request, *roles):
    """Raise 403 unless the authenticated user has one of ``roles``."""
    user = getattr(request, "app_user", None)
    if user is None or user.role not in roles:
        raise HttpError(403, "دسترسی مجاز نیست.")
    return user


def require_clinical_license(request):
    """Raise 403 unless the authenticated user may SIGN a clinical decision
    (holds a نظام‌پزشکی license). The shield for "the physician decides" actions —
    acknowledging an ADA suggestion, issuing an e-prescription. REGULATORY §1/§6."""
    user = getattr(request, "app_user", None)
    if user is None or not user.can_practice_clinically():
        raise HttpError(403, "این اقدام بالینی نیازمند کاربر دارای پروانهٔ نظام‌پزشکی است.")
    return user
