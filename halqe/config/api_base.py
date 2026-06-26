"""
Shared API base for the Halqe Platform API (cleanup step 3 — god-file split).

This module owns the cross-domain primitives that every domain router needs:
  - the single ``NinjaAPI`` instance (``api``)
  - the shared JWT auth dependency (``_jwt_auth``)
  - the global Http404 → uniform-error exception handler
  - ``SYSTEM_TENANT_ID`` sentinel for tenant-less audit rows

It must NOT import any domain router module (``config.api`` or anything under
``clinical.api``).  Routers import FROM here; nothing here imports a router.
That one-way dependency keeps the package free of import cycles: domain routers
depend on ``api_base``; ``config.api`` wires the routers onto ``api`` at the end.

Other shared pieces already live in their own modules and are imported directly
by the routers that need them:
  - ``config.errors``     — ``ErrorSchema`` + ``error_response`` (uniform error shape)
  - ``config.pagination`` — ``paginate`` (standard {items,total,limit,offset} envelope)
"""
from django.http import Http404, JsonResponse

from ninja import NinjaAPI

from config.errors import error_response
from platform_core.auth_bearer import JWTBearer

# ---------------------------------------------------------------------------
# System sentinel for audit rows where no real tenant can be resolved.
#
# Used ONLY for failed-login audit rows when the supplied username does not
# exist in the DB (User.DoesNotExist or ambiguous multi-tenant collision).
# In those cases there is no user object to extract a real tenant_id from.
#
# We use 1 rather than 0 because clinical.activity_logs.tenant_id has a
# FOREIGN KEY REFERENCES platform.tenants(id), and the schema seeds tenant 1
# as the "پیش‌فرض" (default) tenant (slice0.sql).  Using 0 would violate the
# FK unless a system tenant row is inserted — a schema change deferred to a
# future step.  The constant name makes the intent explicit and distinguishable
# from any accidental hardcoded literal '1' elsewhere.
#
# When real tenant routing (subdomain / host-based) is implemented in a future
# step, these audit rows should carry the resolved tenant or be stored in a
# dedicated "platform audit" table without the FK constraint.
# ---------------------------------------------------------------------------
SYSTEM_TENANT_ID: int = 1

api = NinjaAPI(title="Halqe Platform API", version="0.1.0")

_jwt_auth = JWTBearer()


# ---------------------------------------------------------------------------
# Global exception handler — Http404 → uniform error contract
#
# django-ninja converts Http404 to {"detail": "Not Found"} by default,
# which lacks the `code` field the contract requires.  By registering a
# handler here, every `raise Http404(...)` in any endpoint of *this* API
# returns the standard ErrorSchema shape, so the web client still reads
# `detail` and new consumers can branch on `code`.
# ---------------------------------------------------------------------------
@api.exception_handler(Http404)
def _handle_404(request, exc):
    return JsonResponse(
        error_response(str(exc) or "Not Found", "not_found"),
        status=404,
    )
