"""
tests/test_openapi_contract.py — API contract drift guard.

The committed ``docs/openapi.json`` is the locked API contract. These tests are
the silent-drift tripwire: additive v1 changes must update the operation/path
counts and regenerate the snapshot; breaking changes require a new API version.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.conf import settings

from config.api import api

# The structured patient-record migration adds fifteen additive operations across
# fifteen new paths under /api/v1. No existing path, method or response contract
# was removed or renamed.
EXPECTED_OPERATION_COUNT = 62
EXPECTED_PATH_COUNT = 59
EXPECTED_API_VERSION = "0.1.0"

_HTTP_VERBS = ("get", "post", "put", "patch", "delete")

# Representative spine — one path per bounded domain plus the new structured
# patient-record aggregate. Losing any of these indicates router drift.
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


class TestOpenApiSurface:
    def test_operation_count_is_locked(self):
        schema = _live_schema()
        actual = _count_operations(schema)
        assert actual == EXPECTED_OPERATION_COUNT, (
            f"API operation count changed: expected {EXPECTED_OPERATION_COUNT}, "
            f"got {actual}. If this is an intentional ADDITIVE change within "
            f"/api/v1, update EXPECTED_OPERATION_COUNT and regenerate "
            f"docs/openapi.json. Breaking changes require /api/v2 "
            f"(see docs/api_versioning.md)."
        )

    def test_path_count_is_locked(self):
        schema = _live_schema()
        actual = len(schema.get("paths", {}))
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
            f"Found path(s) NOT under /api/v1: {rogue}. v1 is the only mounted "
            f"version; a v2 surface must be a separate NinjaAPI mount."
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
        paths = _live_schema().get("paths", {})
        assert "get" in paths["/api/v1/card/{token}"]

    def test_patient_report_is_post(self):
        paths = _live_schema().get("paths", {})
        assert "post" in paths["/api/v1/patient-report/{token}"]


class TestCommittedSnapshot:
    def _snapshot_path(self) -> Path:
        return Path(settings.BASE_DIR) / "docs" / "openapi.json"

    def test_snapshot_file_exists(self):
        assert self._snapshot_path().exists(), (
            "docs/openapi.json missing — run `python manage.py dump_openapi`."
        )

    def test_snapshot_matches_live_schema(self):
        snap_path = self._snapshot_path()
        if not snap_path.exists():
            pytest.skip("snapshot missing; covered by test_snapshot_file_exists")
        committed = json.loads(snap_path.read_text(encoding="utf-8"))
        live = json.loads(json.dumps(_live_schema()))
        assert committed == live, (
            "docs/openapi.json is STALE vs the live API schema. Run "
            "`python manage.py dump_openapi` and commit the result."
        )

    def test_snapshot_operation_count(self):
        snap_path = self._snapshot_path()
        if not snap_path.exists():
            pytest.skip("snapshot missing; covered by test_snapshot_file_exists")
        committed = json.loads(snap_path.read_text(encoding="utf-8"))
        assert _count_operations(committed) == EXPECTED_OPERATION_COUNT
