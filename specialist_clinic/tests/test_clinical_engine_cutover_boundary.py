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


def test_blueprint_never_owns_persistent_schema_cleanup():
    boundary = _source("api/clinical_reconciliation.py")

    assert "ensure_v1_schema_cutover" not in boundary
    assert "install_v1_request_projection" in boundary


def test_cutover_verifies_its_postcondition():
    cutover = _source("adapters/sqlite/clinical_engine_v1_cutover.py")

    assert 'if _cleanup_needed(db):' in cutover
    assert (
        "retired Clinical Engine v1 storage remained after schema cutover"
        in cutover
    )
