"""
tests/test_observability.py — Step 28: health probes + request-id middleware.

Coverage:
  1. GET /healthz → 200 {"status": "ok"}  (no DB, no auth)
  2. GET /readyz  → 200 {"status": "ready"} when DB is up
  3. GET /readyz  → 503 {"status": "not_ready"} when DB SELECT 1 raises
  4. Request-ID: response always carries X-Request-ID header
  5. Request-ID: client-supplied valid X-Request-ID is echoed back
  6. Request-ID: client-supplied invalid/too-long header is replaced by uuid4
  7. Request-ID: invalid charset replaced by uuid4
  8. Logging Filter: RequestIdFilter injects request_id into log records
     (unit-tested without HTTP round-trip)
"""
from __future__ import annotations

import logging
import re
import uuid
from unittest.mock import MagicMock, patch

import pytest
from django.test import RequestFactory

# ---------------------------------------------------------------------------
# Module-level import of the views so we can call them directly too.
# ---------------------------------------------------------------------------
from platform_core.health import healthz, readyz
from platform_core.request_id import (
    RequestIdFilter,
    RequestIdMiddleware,
    _request_id_ctx_var,
    get_request_id,
)

# ---------------------------------------------------------------------------
# UUID4 pattern — used to verify generated IDs look like UUIDs.
# ---------------------------------------------------------------------------
UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _get(client, url, **kwargs):
    """Thin wrapper so test lines stay short."""
    return client.get(url, **kwargs)


# ===========================================================================
# 1. /healthz — liveness probe
# ===========================================================================

class TestHealthz:
    """GET /healthz → always 200 {"status":"ok"}, no auth, no DB."""

    @pytest.mark.django_db
    def test_healthz_returns_200(self, client):
        response = _get(client, "/healthz")
        assert response.status_code == 200

    @pytest.mark.django_db
    def test_healthz_body(self, client):
        response = _get(client, "/healthz")
        data = response.json()
        assert data == {"status": "ok"}

    def test_healthz_no_db_needed(self):
        """
        healthz view must return 200 even without a live DB.
        We call it directly via RequestFactory — no DB, no middleware.
        """
        factory = RequestFactory()
        request = factory.get("/healthz")
        response = healthz(request)
        assert response.status_code == 200
        import json
        assert json.loads(response.content) == {"status": "ok"}


# ===========================================================================
# 2. /readyz — readiness probe, DB up
# ===========================================================================

class TestReadyzOk:
    """GET /readyz → 200 when DB SELECT 1 succeeds."""

    @pytest.mark.django_db
    def test_readyz_200_when_db_up(self, client):
        response = _get(client, "/readyz")
        assert response.status_code == 200

    @pytest.mark.django_db
    def test_readyz_body_when_up(self, client):
        response = _get(client, "/readyz")
        data = response.json()
        assert data["status"] == "ready"


# ===========================================================================
# 3. /readyz — 503 when DB SELECT 1 raises
# ===========================================================================

class TestReadyzFailure:
    """GET /readyz → 503 when the default DB cursor raises."""

    def test_readyz_503_on_db_error(self):
        """
        Patch django.db.connections to raise on cursor().__enter__.
        Must return 503 {"status":"not_ready"} — no DB exception leaks.

        We patch 'platform_core.health.connections' because health.py
        imports `connections` at module level from django.db — that bound
        name in the health module's namespace is what we intercept.
        """
        factory = RequestFactory()
        request = factory.get("/readyz")

        # Build a mock connection whose cursor().__enter__ raises.
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(
            side_effect=Exception("connection refused")
        )
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_connections = MagicMock()
        mock_connections.__getitem__ = MagicMock(return_value=mock_conn)

        with patch("platform_core.health.connections", mock_connections):
            response = readyz(request)

        assert response.status_code == 503
        import json
        data = json.loads(response.content)
        assert data["status"] == "not_ready"
        # Must NOT leak internal error text to caller
        assert "connection refused" not in str(data)
        assert "Exception" not in str(data)

    def test_readyz_not_ready_has_reason_field(self):
        """503 body includes a 'reason' field (generic, PII-free)."""
        factory = RequestFactory()
        request = factory.get("/readyz")

        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = Exception("timeout")

        mock_connections = MagicMock()
        mock_connections.__getitem__ = MagicMock(return_value=mock_conn)

        with patch("platform_core.health.connections", mock_connections):
            response = readyz(request)

        import json
        data = json.loads(response.content)
        assert "reason" in data
        # The reason must be a non-empty generic string
        assert isinstance(data["reason"], str)
        assert len(data["reason"]) > 0


# ===========================================================================
# 4–7. Request-ID middleware
# ===========================================================================

class TestRequestIdMiddleware:
    """
    Tests for platform_core.request_id.RequestIdMiddleware.

    We test via the Django test client (which runs full middleware stack)
    AND directly via RequestFactory (for edge cases).
    """

    # 4. Response always has X-Request-ID
    @pytest.mark.django_db
    def test_response_has_request_id_header(self, client):
        response = _get(client, "/healthz")
        assert "X-Request-ID" in response

    @pytest.mark.django_db
    def test_request_id_is_uuid4_when_not_supplied(self, client):
        response = _get(client, "/healthz")
        rid = response["X-Request-ID"]
        assert UUID4_RE.match(rid), f"Expected UUID4, got: {rid!r}"

    # 5. Client-supplied valid X-Request-ID is echoed back unchanged
    @pytest.mark.django_db
    def test_valid_client_request_id_is_echoed(self, client):
        supplied = "my-stable-trace-id-123"
        response = _get(client, "/healthz", HTTP_X_REQUEST_ID=supplied)
        assert response["X-Request-ID"] == supplied

    @pytest.mark.django_db
    def test_valid_uuid_request_id_echoed(self, client):
        supplied = str(uuid.uuid4())
        # UUIDs have hyphens — valid charset
        response = _get(client, "/healthz", HTTP_X_REQUEST_ID=supplied)
        assert response["X-Request-ID"] == supplied

    # 6. Too-long header (>64 chars) triggers fresh uuid4
    @pytest.mark.django_db
    def test_too_long_request_id_replaced(self, client):
        too_long = "a" * 65
        response = _get(client, "/healthz", HTTP_X_REQUEST_ID=too_long)
        rid = response["X-Request-ID"]
        # Must NOT echo the too-long value
        assert rid != too_long
        # Must be a valid UUID4
        assert UUID4_RE.match(rid), f"Expected UUID4, got: {rid!r}"

    # 7. Invalid charset (spaces, slash) → replaced by uuid4
    @pytest.mark.django_db
    def test_invalid_charset_replaced(self, client):
        bad = "has space/slash"
        response = _get(client, "/healthz", HTTP_X_REQUEST_ID=bad)
        rid = response["X-Request-ID"]
        assert rid != bad
        assert UUID4_RE.match(rid), f"Expected UUID4, got: {rid!r}"

    @pytest.mark.django_db
    def test_empty_request_id_generates_uuid(self, client):
        """Empty string header is treated as absent → generates UUID4."""
        response = _get(client, "/healthz", HTTP_X_REQUEST_ID="")
        rid = response["X-Request-ID"]
        assert UUID4_RE.match(rid), f"Expected UUID4, got: {rid!r}"

    # Direct RequestFactory test — middleware call without full stack
    def test_middleware_sets_request_attribute(self):
        """request.request_id is set by the middleware."""
        factory = RequestFactory()
        request = factory.get("/healthz")
        # Simulate middleware calling get_response
        captured = {}
        def fake_response(req):
            captured["request_id"] = req.request_id
            from django.http import HttpResponse
            return HttpResponse()
        mw = RequestIdMiddleware(fake_response)
        mw(request)
        assert captured["request_id"]  # non-empty
        assert UUID4_RE.match(captured["request_id"])

    def test_middleware_resets_contextvar_after_response(self):
        """Contextvar is reset after the response so threads don't leak state."""
        factory = RequestFactory()
        request = factory.get("/healthz")
        request.META["HTTP_X_REQUEST_ID"] = "trace-abc"

        def fake_response(req):
            # Inside the request the contextvar must be set
            assert get_request_id() == "trace-abc"
            from django.http import HttpResponse
            return HttpResponse()

        mw = RequestIdMiddleware(fake_response)
        mw(request)

        # After the call the contextvar must be reset (to '' default)
        assert get_request_id() == ""

    def test_request_id_echoed_in_response_header_directly(self):
        """Response X-Request-ID matches the supplied valid header."""
        factory = RequestFactory()
        request = factory.get("/healthz")
        request.META["HTTP_X_REQUEST_ID"] = "my-id-42"

        def fake_response(req):
            from django.http import HttpResponse
            return HttpResponse()

        mw = RequestIdMiddleware(fake_response)
        response = mw(request)
        assert response["X-Request-ID"] == "my-id-42"


# ===========================================================================
# 8. RequestIdFilter — logging filter unit test
# ===========================================================================

class TestRequestIdFilter:
    """Unit tests for RequestIdFilter (no HTTP round-trip needed)."""

    def test_filter_injects_request_id_from_contextvar(self):
        """When contextvar is set, record.request_id matches."""
        token = _request_id_ctx_var.set("test-req-id-xyz")
        try:
            f = RequestIdFilter()
            record = logging.LogRecord(
                name="test", level=logging.INFO,
                pathname="", lineno=0, msg="hello",
                args=(), exc_info=None,
            )
            f.filter(record)
            assert record.request_id == "test-req-id-xyz"
        finally:
            _request_id_ctx_var.reset(token)

    def test_filter_defaults_to_dash_outside_request(self):
        """When contextvar is empty (no active request), request_id = '-'."""
        # Ensure contextvar is empty
        token = _request_id_ctx_var.set("")
        try:
            f = RequestIdFilter()
            record = logging.LogRecord(
                name="test", level=logging.WARNING,
                pathname="", lineno=0, msg="no request",
                args=(), exc_info=None,
            )
            f.filter(record)
            assert record.request_id == "-"
        finally:
            _request_id_ctx_var.reset(token)

    def test_filter_always_returns_true(self):
        """Filter must never suppress log records."""
        f = RequestIdFilter()
        record = logging.LogRecord(
            name="test", level=logging.DEBUG,
            pathname="", lineno=0, msg="debug",
            args=(), exc_info=None,
        )
        assert f.filter(record) is True

    def test_filter_in_logger_handler(self, caplog):
        """End-to-end: a logger with the filter emits request_id in the record."""
        token = _request_id_ctx_var.set("e2e-test-id")
        try:
            logger = logging.getLogger("platform_core.health")
            f = RequestIdFilter()
            logger.addFilter(f)
            try:
                with caplog.at_level(logging.INFO, logger="platform_core.health"):
                    logger.info("probe called")
                # At least one record should have the request_id attribute set
                records_with_rid = [
                    r for r in caplog.records
                    if getattr(r, "request_id", None) == "e2e-test-id"
                ]
                assert records_with_rid, (
                    "Expected at least one log record with request_id='e2e-test-id'"
                )
            finally:
                logger.removeFilter(f)
        finally:
            _request_id_ctx_var.reset(token)
