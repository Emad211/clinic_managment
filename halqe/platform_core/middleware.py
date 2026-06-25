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
  1. TenantGucMiddleware.__call__() → clear_tenant_guc()  ['' GUC, start]
  2. JWTBearer.authenticate() (only for auth-protected endpoints)
        → set_tenant_guc(user.tenant_id)           [correct tenant]
  3. View queries run — GUC reflects the authenticated tenant, or '' if none.
  4. After response (finally) → clear_tenant_guc() again  [defense-in-depth]

RLS (slice5) reads current_setting('app.current_tenant', true) in POLICY
expressions. An empty string is the fail-safe: no tenant → no rows visible.

DEFENSE-IN-DEPTH — post-response clear (step 4):
  With CONN_MAX_AGE=0 (the current invariant per ADR-0008), the connection
  is closed after each request and the GUC dies anyway.  The post-response
  clear is therefore a no-op under the invariant — but it costs nothing and
  ensures correctness if CONN_MAX_AGE is ever raised (with the explicit ACK
  described in ADR-0008): in that case the connection is reused, so clearing
  after the response is the last line of defense before the next request's
  leading clear runs.
  Note: clear_tenant_guc() never raises (it catches and logs all exceptions).

MIDDLEWARE ORDER in settings.py:
  TenantGucMiddleware should come BEFORE CommonMiddleware and any view
  middleware, so the GUC is cleared before any view code runs.
"""
from __future__ import annotations

from platform_core.tenant_context import clear_tenant_guc


class TenantGucMiddleware:
    """
    Django middleware that clears the `app.current_tenant` Postgres GUC
    at the start AND end of every request.

    Leading clear (start):  prevents a stale GUC from a prior request on the
                            same connection from leaking into this request.
    Trailing clear (finally): defense-in-depth for persistent connections
                              (CONN_MAX_AGE > 0, session-mode pooler only —
                              see ADR-0008); no-op with CONN_MAX_AGE=0.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Leading clear: GUC → '' before any view code runs.
        clear_tenant_guc()
        try:
            response = self.get_response(request)
        finally:
            # Trailing clear: ensure the connection is GUC-clean after the
            # request completes (whether by normal return or exception).
            # With CONN_MAX_AGE=0 this is a no-op (connection is closed).
            # With CONN_MAX_AGE>0 + session-mode pooler this is the safety net.
            clear_tenant_guc()
        return response
