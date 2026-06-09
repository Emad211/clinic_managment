"""Template context processors for the web frontend.

``current_app_user`` exposes the logged-in AppUser to every template so the nav
can show role-gated links (e.g. the manager-only audit log) and the username,
without each view threading it through manually. Runs inside the request's tenant
context (TenantMiddleware), so the RLS-protected app_user read is correct.
"""

from apps.identity.models import AppUser


def current_app_user(request):
    uid = request.session.get("user_id")
    if not uid:
        return {"current_app_user": None}
    return {"current_app_user": AppUser.objects.filter(id=uid).first()}
