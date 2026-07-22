"""Legacy v1 identifiers cannot enter new Clinical Engine v2 artefacts."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SPECIALIST_ROOT.parent
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))
if str(SPECIALIST_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT / "tests"))

from test_clinical_engine_v2_compiler import valid_rule
from src.adapters.sqlite.clinical_engine_rules_repo import (
    ClinicalEngineRulesRepository,
)
from src.domain.clinical_engine import RuleCompilationError
from src.services.clinical_engine.compiler import RuleCompiler


RUNTIME_SCHEMA = (
    SPECIALIST_ROOT
    / "src"
    / "domain"
    / "clinical_engine"
    / "schemas"
    / "clinical-rule.schema.json"
)
RESEARCH_SCHEMA = (
    REPOSITORY_ROOT
    / "clinical_engine_v2_research"
    / "clinical-rule.schema.json"
)
ARTEFACT_ROOT = (
    SPECIALIST_ROOT
    / "src"
    / "domain"
    / "clinical_engine"
    / "rule_artifacts"
)


def test_runtime_and_research_rule_schemas_reject_legacy_identity():
    for path in (RUNTIME_SCHEMA, RESEARCH_SCHEMA):
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert "legacy_rule_id" not in schema["properties"]
        assert schema["additionalProperties"] is False


def test_compiler_fails_closed_when_legacy_rule_id_is_supplied():
    raw = valid_rule()
    raw["legacy_rule_id"] = 42
    compiler = RuleCompiler()

    diagnostics = compiler.validate(raw)

    assert diagnostics
    assert {item.code for item in diagnostics} == {
        "SCHEMA_VALIDATION_ERROR"
    }
    with pytest.raises(RuleCompilationError):
        compiler.compile(raw)


def test_bundled_rule_packages_contain_no_legacy_identifier():
    documents = []
    for path in sorted(ARTEFACT_ROOT.rglob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if path.name == "manifest.json":
            continue
        documents.append(payload)
        assert "legacy_rule_id" not in payload, path
    assert documents


def test_rule_version_persists_after_physical_lineage_cleanup(tmp_path):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.clinical_engine_legacy_cleanup_schema import (
        cleanup_legacy_clinical_schema,
    )
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "no-legacy-lineage.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "no-legacy-lineage-test",
        }
    )
    try:
        with app.app_context():
            db = core.get_db()
            cleanup_legacy_clinical_schema(db)

            compiled = RuleCompiler().compile(valid_rule())
            assert not hasattr(compiled.definition, "legacy_rule_id")
            rule_id = ClinicalEngineRulesRepository().create_rule_version(
                compiled,
                created_by="pytest",
            )

            columns = {
                str(row["name"])
                for row in db.execute(
                    "PRAGMA table_info(clinical_rule_versions)"
                ).fetchall()
            }
            assert "source_legacy_rule_id" not in columns
            row = db.execute(
                "SELECT rule_code, version FROM clinical_rule_versions "
                "WHERE id=?",
                (rule_id,),
            ).fetchone()
            assert row["rule_code"] == valid_rule()["rule_code"]
            assert row["version"] == valid_rule()["version"]
    finally:
        core._initialized = False
