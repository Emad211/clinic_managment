"""Per-request tenant isolation middleware (PostgreSQL RLS).

Sets ``app.current_clinic`` for the duration of each request so that every
query the view issues is automatically filtered to the authenticated user's
clinic by RLS policies (docs/DATA_MODEL.md §3).

Implementation note: ``SET LOCAL`` must run inside a transaction, and the view
must run inside the *same* transaction for the value to apply. We therefore wrap
``get_response`` in ``transaction.atomic()`` and set the GUC at the top of that
block. (This intentionally couples request handling to a DB transaction; revisit
if/when long-running / streaming responses need to opt out.)

How the clinic id is resolved is deliberately pluggable: today it reads
``request.session['clinic_id']``; once AppUser is wired into auth it will read
``request.user.clinic_id``. Until then, unauthenticated / context-less requests
get NO tenant set -> RLS returns zero rows (fail-closed), which is the safe
default.
"""

from django.db import transaction
from django.utils.deprecation import MiddlewareMixin  # noqa: F401  (reserved)

from .tenant import set_current_clinic


def _resolve_clinic_id(request):
    # Phase-1 placeholder resolution order; AppUser-auth integration is a
    # follow-up (see platform/README.md "Open scaffold decisions").
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        clinic_id = getattr(user, "clinic_id", None)
        if clinic_id:
            return clinic_id
    session = getattr(request, "session", None)
    if session is not None:
        return session.get("clinic_id")
    return None


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        clinic_id = _resolve_clinic_id(request)
        if not clinic_id:
            # Fail-closed: no tenant context -> RLS yields zero rows.
            return self.get_response(request)
        with transaction.atomic():
            set_current_clinic(clinic_id)
            return self.get_response(request)
