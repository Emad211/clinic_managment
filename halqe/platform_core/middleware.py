"""
TenantGucMiddleware — Step 2 of halqe platform hardening.

Clears the `app.current_tenant` GUC at the START of every request.

WHY this middleware exists:
  Django (and most WSGI servers) reuse persistent DB connections across
  requests on the same thread. A GUC set with is_local=false on a connection
  survives across transaction boundaries — it persists on the connection until
  explicitly cleared or the connection is closed.

  Without this middleware, an authenticated request that sets
  `app.current_tenant=42` could leak that value into the next request on the
  same connection IF that next request does not authenticate (e.g. an
  unauthenticated OPTIONS preflight, a health-check, or a login attempt).

FLOW (for every request):
  1. TenantGucMiddleware.process_request() → clear_tenant_guc()  ['' GUC]
  2. JWTBearer.authenticate() (only for auth-protected endpoints)
        → set_tenant_guc(user.tenant_id)           [correct tenant]
  3. View queries run — GUC reflects the authenticated tenant, or '' if none.

RLS Step 19 will read current_setting('app.current_tenant', true) in POLICY
expressions. An empty string is the fail-safe: no tenant → no rows visible.

MIDDLEWARE ORDER in settings.py:
  TenantGucMiddleware should come BEFORE CommonMiddleware and any view
  middleware, so the GUC is cleared before any view code runs.
"""
from __future__ import annotations

from platform_core.tenant_context import clear_tenant_guc


class TenantGucMiddleware:
    """
    Django middleware that clears the `app.current_tenant` Postgres GUC
    at the start of every request.

    This is a defense-in-depth measure against connection-pool GUC leakage.
    The authenticated flow re-sets the GUC in JWTBearer.authenticate().
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Clear GUC before the view runs — fail-safe for unauthenticated paths.
        clear_tenant_guc()
        response = self.get_response(request)
        return response
