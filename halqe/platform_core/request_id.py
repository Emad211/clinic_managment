"""
platform_core/request_id.py — Request-ID middleware + contextvar helper.

PURPOSE
-------
Assigns a stable, opaque correlation ID to every HTTP request so that all log
lines from a single request can be joined by a single field.

FLOW
----
1. RequestIdMiddleware runs BEFORE TenantGucMiddleware (see settings.py).
2. It reads X-Request-ID from the incoming request headers.
3. The value is sanitized (length + charset).  If absent or invalid, a new
   UUID4 is generated.
4. The clean ID is stored on:
   - request.request_id   — readable by views / error handlers
   - _request_id_ctx_var  — contextvar readable by the logging Filter without
     threading through the request object.
5. The same ID is echoed back in the X-Request-ID response header.

SECURITY
--------
- The header value is sanitized: max 64 chars, only [a-zA-Z0-9-_] allowed.
  Any other character triggers a fresh UUID4 (not a 400 — health probes that
  send garbage should still get a 200/503).
- The original header value is NEVER propagated to logs without sanitization.
- No body content is ever logged (PII-free).

ORDERING IN MIDDLEWARE STACK (settings.py)
------------------------------------------
RequestIdMiddleware must come FIRST — even before TenantGucMiddleware — so
that the contextvar is populated before any other middleware logs anything.

    MIDDLEWARE = [
        "platform_core.request_id.RequestIdMiddleware",   # ← first
        "platform_core.middleware.TenantGucMiddleware",
        ...
    ]
"""
from __future__ import annotations

import re
import uuid
import logging
from contextvars import ContextVar
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Contextvar — readable by RequestIdFilter in the logging stack.
# Lives at module level so it is shared across all imports.
# ---------------------------------------------------------------------------
_request_id_ctx_var: ContextVar[str] = ContextVar("request_id", default="")

# Sanitization: only alphanumeric, dash, underscore — max 64 chars.
_SAFE_RE = re.compile(r"^[a-zA-Z0-9\-_]{1,64}$")


def _sanitize(raw: str) -> Optional[str]:
    """
    Return the sanitized value or None if it is unacceptable.

    Acceptable: 1–64 chars, only [a-zA-Z0-9-_].
    """
    if raw and _SAFE_RE.match(raw):
        return raw
    return None


def get_request_id() -> str:
    """
    Return the current request's ID from the contextvar.

    Returns '' when called outside a request context (e.g. management commands,
    background threads started before the first request).
    """
    return _request_id_ctx_var.get()


class RequestIdFilter(logging.Filter):
    """
    Python logging Filter that injects request_id into every LogRecord.

    Reads from the contextvar set by RequestIdMiddleware.  When called
    outside a request context (management commands, background threads,
    test collection) the field defaults to '-' so log lines are always
    well-formed.

    Usage in settings.py LOGGING dict:
        "filters": {
            "request_id": {
                "()": "platform_core.request_id.RequestIdFilter",
            },
        },
    Then add "filters": ["request_id"] to each handler.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.request_id = _request_id_ctx_var.get() or "-"
        return True  # always pass the record through


class RequestIdMiddleware:
    """
    Django WSGI middleware that assigns a request-scoped correlation ID.

    Must be the outermost middleware in MIDDLEWARE (first in the list) so that
    every downstream layer — including TenantGucMiddleware and all views — sees
    a populated contextvar and all log lines are tagged.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. Extract incoming header (case-insensitive HTTP header lookup via META)
        raw = request.META.get("HTTP_X_REQUEST_ID", "")

        # 2. Sanitize or generate
        request_id = _sanitize(raw) or str(uuid.uuid4())

        # 3. Store on request object and contextvar
        request.request_id = request_id
        token = _request_id_ctx_var.set(request_id)

        try:
            response = self.get_response(request)
        finally:
            # Reset contextvar — defense against connection/thread reuse.
            _request_id_ctx_var.reset(token)

        # 4. Echo back on response header
        response["X-Request-ID"] = request_id
        return response
