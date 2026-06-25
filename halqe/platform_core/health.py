"""
platform_core/health.py — Liveness and readiness probes.

GET /healthz  (liveness)
  Always returns 200 {"status": "ok"}.
  No auth, no DB — just confirms the Python process is alive.
  Safe to be called by load-balancer TCP/HTTP probes every few seconds.

GET /readyz   (readiness)
  Checks only the 'default' (primary) DB connection with SELECT 1.
  Returns 200 {"status": "ready"} when the check passes.
  Returns 503 {"status": "not_ready", "reason": "<generic message>"} on failure.
  No auth required — the endpoint is open to load-balancer probes.

DESIGN DECISIONS
----------------
- accounting_read is NOT checked: it is an optional, read-only bridge.
  The app can still serve clinical writes even if the accounting schema
  is momentarily unreachable.
- Error details are NOT leaked: only a generic "reason" string is returned
  on 503. Internal exception text is logged (server-side) but never sent
  to the caller.
- SELECT 1 does not touch any tenant table, so it is safe to run without
  setting app.current_tenant GUC — it works with RLS fail-closed.
- These views are plain Django HttpResponse views (no ninja/JWT overhead)
  so they never block on middleware that requires a DB connection.
"""
from __future__ import annotations

import logging

from django.db import connections
from django.http import JsonResponse

logger = logging.getLogger(__name__)


def healthz(request):
    """
    Liveness probe — always 200.

    Confirms the Python process accepted the connection and can run a view.
    No database interaction whatsoever.
    """
    return JsonResponse({"status": "ok"})


def readyz(request):
    """
    Readiness probe — checks the primary ('default') DB connection only.

    Returns 200 {"status": "ready"} when SELECT 1 succeeds.
    Returns 503 {"status": "not_ready", "reason": "..."} on any DB error.

    The 'accounting_read' alias is intentionally NOT checked — it is an
    optional read-only bridge; its unavailability must not block clinical writes.
    """
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return JsonResponse({"status": "ready"})
    except Exception as exc:  # noqa: BLE001
        # Log server-side for ops debugging; do NOT leak the exception text
        # to the caller (may contain internal DB hostnames / passwords).
        logger.error(
            "readyz: primary DB check failed",
            exc_info=exc,
        )
        return JsonResponse(
            {"status": "not_ready", "reason": "primary database unavailable"},
            status=503,
        )
