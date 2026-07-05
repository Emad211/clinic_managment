"""
tests/test_openapi_contract.py — Step 56 (cluster M): API contract drift guard.

PURPOSE
-------
The committed ``docs/openapi.json`` is the locked API contract. These tests are
the silent-drift tripwire: if a router is added/removed, an endpoint's verb or
path changes, or the operation surface otherwise shifts, one of these assertions
fails BEFORE the change reaches a consumer (web client, future mobile app).

DESIGN
------
* No DB needed. ``api.get_openapi_schema()`` is pure schema introspection over
  the wired NinjaAPI — these tests run even without PG_TEST_DSN, so the contract
  guard is always exercised by the suite.
* We assert *invariants* (operation count, presence of core paths, public-route
  semantics, the version field), NOT the entire blob — a brittle full-blob equal
  would break on every harmless schema-description tweak and teach reviewers to
  ignore it. The byte-for-byte lock is the separate ``dump_openapi --check``
  CI step; here we assert the load-bearing shape.
* The committed snapshot is cross-checked against the live schema so the two
  cannot silently diverge.

If you intentionally change the surface (an ADDITIVE change within /api/v1 — see
docs/api_versioning.md), update EXPECTED_OPERATION_COUNT here and regenerate the
snapshot with ``python manage.py dump_openapi``. A *breaking* change is not
allowed in v1 — it requires a new /api/v2 mount.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.conf import settings

from config.api import api

# ---------------------------------------------------------------------------
# Locked invariants. As of step 56 the surface was 44 operations across 42 paths.
# فاز ۱ کاکپیت (allergies domain) additively added the allergies sub-resource:
#   GET/POST /patients/{uuid}/allergies + DELETE /patients/{uuid}/allergies/{id}
#   → +3 operations, +2 paths (all within /api/v1, no breaking change).
# New verified count: 47 operations across 44 paths.
# ---------------------------------------------------------------------------
EXPECTED_OPERATION_COUNT = 47
EXPECTED_PATH_COUNT = 44
EXPECTED_API_VERSION = "0.1.0"

_HTTP_VERBS = ("get", "post", "put", "patch", "delete")

# A representative spine of the contract — one path per domain router. If any of
# these vanishes or moves, a domain was dropped or re-prefixed by accident.
CORE_PATHS = [
    "/api/v1/auth/login",
    "/api/v1/patients",
    "/api/v1/patients/{patient_uuid}",
    "/api/v1/patients/{patient_uuid}/record",
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

# Public (auth=None) routes are a deliberate, sacred part of the contract.
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
    """Invariants over the LIVE schema (no committed file involved)."""

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
        missing = [p for p in CORE_PATHS if p not in paths]
        assert not missing, f"Core contract paths missing from schema: {missing}"

    def test_all_paths_under_api_v1(self):
        """Every operation lives under /api/v1 — the v1 mount boundary."""
        paths = _live_schema().get("paths", {})
        rogue = [p for p in paths if not p.startswith("/api/v1/")]
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
    """
    The two one-time-token public routes must stay present. (Whether they are
    auth-free is asserted behaviourally in the patient-card / self-report test
    modules; here we lock that they remain part of the published surface.)
    """

    def test_public_paths_present(self):
        paths = _live_schema().get("paths", {})
        missing = [p for p in PUBLIC_PATHS if p not in paths]
        assert not missing, f"Public contract path(s) missing: {missing}"

    def test_card_token_is_get(self):
        paths = _live_schema().get("paths", {})
        assert "get" in paths["/api/v1/card/{token}"]

    def test_patient_report_is_post(self):
        paths = _live_schema().get("paths", {})
        assert "post" in paths["/api/v1/patient-report/{token}"]


class TestCommittedSnapshot:
    """
    The committed docs/openapi.json must match the live schema (drift lock).

    This is the in-suite mirror of `manage.py dump_openapi --check`: if the
    snapshot is stale, this fails with an actionable message instead of leaving
    the contract lock to rot.
    """

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
        live = json.loads(json.dumps(_live_schema()))  # normalize types
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
