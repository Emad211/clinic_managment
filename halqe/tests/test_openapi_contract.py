"""Exact OpenAPI drift guard for the unified Halqe platform.

The full canonical JSON is generated as a CI artifact for human review. The
committed ``docs/openapi.lock.json`` stores SHA-256 of that complete document,
plus path/operation counts. Representative clinical, accounting and manager
paths are asserted explicitly below so accidental domain removal has a readable
failure in addition to the exact byte-level hash mismatch.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings

from config.api import api
from platform_core.management.commands.dump_openapi import (
    _render_schema,
    _schema_lock,
)


EXPECTED_OPERATION_COUNT = 95
EXPECTED_PATH_COUNT = 91
EXPECTED_API_VERSION = "0.1.0"
_HTTP_VERBS = ("get", "post", "put", "patch", "delete")

# Representative spine: clinical safety/care, structured specialist record,
# accounting reception/payment/nursing/procedure/workbench/admin, and management.
CORE_PATHS = [
    "/api/v1/auth/login",
    "/api/v1/patients",
    "/api/v1/patients/{patient_uuid}",
    "/api/v1/patients/{patient_uuid}/record",
    "/api/v1/patients/{patient_uuid}/record/structured",
    "/api/v1/patients/{patient_uuid}/record/medications",
    "/api/v1/patients/{patient_uuid}/record/flags",
    "/api/v1/patients/{patient_uuid}/vitals/latest",
    "/api/v1/patients/{patient_uuid}/allergies",
    "/api/v1/patients/{patient_uuid}/suggestions",
    "/api/v1/worklist",
    "/api/v1/patients/{patient_uuid}/encounters",
    "/api/v1/accounting/patients/search",
    "/api/v1/accounting/invoices/visit",
    "/api/v1/accounting/invoices/{invoice_id}/detail",
    "/api/v1/accounting/invoices/{invoice_id}/nursing-items",
    "/api/v1/accounting/invoices/{invoice_id}/procedure-items",
    "/api/v1/accounting/invoices/{invoice_id}/financials",
    "/api/v1/accounting/admin/config",
    "/api/v1/accounting/admin/staff",
    "/api/v1/accounting/admin/insurance-schemes",
    "/api/v1/accounting/admin/visit-tariffs",
    "/api/v1/accounting/admin/payroll-settings",
    "/api/v1/manager/population-thresholds",
    "/api/v1/control-room",
    "/api/v1/doctor-queue",
    "/api/v1/engagement/approvals",
    "/api/v1/card/{token}",
    "/api/v1/patient-report/{token}",
]

PUBLIC_PATHS = ["/api/v1/card/{token}", "/api/v1/patient-report/{token}"]


def _live_schema() -> dict:
    return api.get_openapi_schema()


def _count_operations(schema: dict) -> int:
    return sum(
        1
        for methods in schema.get("paths", {}).values()
        for verb in methods
        if verb.lower() in _HTTP_VERBS
    )


def _lock_path() -> Path:
    return Path(settings.BASE_DIR) / "docs" / "openapi.lock.json"


class TestOpenApiSurface:
    def test_operation_count_is_locked(self):
        actual = _count_operations(_live_schema())
        assert actual == EXPECTED_OPERATION_COUNT, (
            f"API operation count changed: expected {EXPECTED_OPERATION_COUNT}, "
            f"got {actual}. Intentional additive v1 changes must regenerate and "
            "review docs/openapi.lock.json plus the full CI artifact."
        )

    def test_path_count_is_locked(self):
        actual = len(_live_schema().get("paths", {}))
        assert actual == EXPECTED_PATH_COUNT, (
            f"API path count changed: expected {EXPECTED_PATH_COUNT}, got {actual}."
        )

    def test_core_paths_exist(self):
        paths = _live_schema().get("paths", {})
        missing = [path for path in CORE_PATHS if path not in paths]
        assert not missing, f"Core contract paths missing from schema: {missing}"

    def test_all_paths_under_api_v1(self):
        paths = _live_schema().get("paths", {})
        rogue = [path for path in paths if not path.startswith("/api/v1/")]
        assert not rogue, (
            f"Found path(s) NOT under /api/v1: {rogue}. A breaking surface must "
            "be mounted separately as /api/v2."
        )

    def test_version_field(self):
        info = _live_schema().get("info", {})
        assert info.get("version") == EXPECTED_API_VERSION
        assert info.get("title") == "Halqe Platform API"

    def test_openapi_is_3x(self):
        assert _live_schema().get("openapi", "").startswith("3.")


class TestPublicRoutesContract:
    def test_public_paths_present(self):
        paths = _live_schema().get("paths", {})
        missing = [path for path in PUBLIC_PATHS if path not in paths]
        assert not missing, f"Public contract path(s) missing from schema: {missing}"

    def test_card_token_is_get(self):
        assert "get" in _live_schema()["paths"]["/api/v1/card/{token}"]

    def test_patient_report_is_post(self):
        assert "post" in _live_schema()["paths"]["/api/v1/patient-report/{token}"]


class TestCommittedLock:
    def test_lock_file_exists(self):
        assert _lock_path().exists(), (
            "docs/openapi.lock.json missing — run "
            "`python manage.py dump_openapi --write-lock`."
        )

    def test_lock_matches_complete_live_schema(self):
        committed = json.loads(_lock_path().read_text(encoding="utf-8"))
        live_lock = _schema_lock(_render_schema())
        assert committed == live_lock, (
            "OpenAPI lock is STALE vs the complete canonical schema. Generate "
            "the full JSON for review, then run `python manage.py dump_openapi "
            "--write-lock` for an intentional additive v1 change."
        )

    def test_lock_counts_match_constants(self):
        committed = json.loads(_lock_path().read_text(encoding="utf-8"))
        assert committed["paths"] == EXPECTED_PATH_COUNT
        assert committed["operations"] == EXPECTED_OPERATION_COUNT
        assert committed["sha256"] == _schema_lock(_render_schema())["sha256"]
