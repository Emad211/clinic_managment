"""Source guards for the one authoritative Clinical Engine v1 cutover boundary."""
from __future__ import annotations

from pathlib import Path


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
SRC = SPECIALIST_ROOT / "src"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def test_migration_pass_owns_persistent_v1_cutover():
    core = _source("adapters/sqlite/core.py")
    migrations = core.split("def _run_migrations(db):", 1)[1].split(
        "def _ensure_default_admin", 1
    )[0]

    assert "ensure_v1_schema_cutover" in migrations
    assert "ensure_v1_schema_cutover(db)" in migrations
    assert migrations.index("ensure_v1_schema_cutover(db)") > migrations.index(
        "seed_drug_catalog(db)"
    )


def test_blueprint_has_no_schema_or_compatibility_projection():
    boundary = _source("api/clinical_reconciliation.py")

    assert "ensure_v1_schema_cutover" not in boundary
    assert "install_v1_request_projection" not in boundary
    assert "before_app_request" not in boundary
    assert "TEMP VIEW clinical_rules" not in _source(
        "adapters/sqlite/clinical_engine_v1_cutover.py"
    )


def test_cutover_verifies_its_postcondition():
    cutover = _source("adapters/sqlite/clinical_engine_v1_cutover.py")

    assert 'if _cleanup_needed(db):' in cutover
    assert (
        "retired Clinical Engine v1 storage remained after schema cutover"
        in cutover
    )


def test_canonical_schema_never_defines_v1_objects():
    schema = (SRC / "adapters/sqlite/schema.sql").read_text(encoding="utf-8")
    core = _source("adapters/sqlite/core.py")

    assert "CREATE TABLE IF NOT EXISTS clinical_rules (" not in schema
    assert "CREATE TABLE IF NOT EXISTS suggestion_log" not in schema
    assert "source_legacy_rule_id" not in schema
    assert "legacy_source_suggestion_log_id" not in schema
    assert '"clinical_rules", "condition_code"' not in core
    assert "seed_clinical_rules" not in core


def test_app_factory_does_not_duplicate_migration_cutover_policy():
    app_source = _source("app.py")

    assert "ensure_v1_schema_cutover" not in app_source
