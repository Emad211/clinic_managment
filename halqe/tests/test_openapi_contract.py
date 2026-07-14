"""Compact exact OpenAPI guard for the unified platform."""
import json
from pathlib import Path

from django.conf import settings

from config.api import api
from platform_core.management.commands.dump_openapi import _render_schema, _schema_lock


EXPECTED_PATHS = 95
EXPECTED_OPERATIONS = 99
REQUIRED = {
    "/api/v1/auth/login": "post",
    "/api/v1/patients/{patient_uuid}/record/structured": "get",
    "/api/v1/accounting/invoices/{invoice_id}/detail": "get",
    "/api/v1/accounting/admin/config": "get",
    "/api/v1/accounting/reports/overview": "get",
    "/api/v1/accounting/reports/invoices": "get",
    "/api/v1/accounting/reports/services": "get",
    "/api/v1/accounting/reports/payroll": "get",
    "/api/v1/control-room": "get",
}


def test_unified_openapi_surface_and_version():
    schema = api.get_openapi_schema()
    paths = schema["paths"]
    verbs = {"get", "post", "put", "patch", "delete"}
    operations = sum(
        1 for methods in paths.values() for verb in methods if verb.lower() in verbs
    )
    assert len(paths) == EXPECTED_PATHS
    assert operations == EXPECTED_OPERATIONS
    assert schema["info"]["version"] == "0.1.0"
    assert schema["openapi"].startswith("3.")
    assert all(path.startswith("/api/v1/") for path in paths)
    for path, method in REQUIRED.items():
        assert method in paths[path]


def test_committed_lock_matches_complete_schema():
    lock_path = Path(settings.BASE_DIR) / "docs" / "openapi.lock.json"
    committed = json.loads(lock_path.read_text(encoding="utf-8"))
    live = _schema_lock(_render_schema())
    assert committed == live
    assert committed["paths"] == EXPECTED_PATHS
    assert committed["operations"] == EXPECTED_OPERATIONS
    assert len(committed["sha256_words"]) == 4
