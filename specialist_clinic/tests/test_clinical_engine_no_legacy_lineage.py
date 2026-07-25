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


def _clean_app(tmp_path, filename: str):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    return create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / filename),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "no-legacy-lineage-test",
        }
    )


def _remove_legacy_schema(db):
    from src.adapters.sqlite.clinical_engine_legacy_cleanup_schema import (
        cleanup_legacy_clinical_schema,
    )

    cleanup_legacy_clinical_schema(db)


def _columns(db, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in db.execute(f"PRAGMA table_info({table})").fetchall()
    }


def test_rule_version_persists_after_physical_lineage_cleanup(tmp_path):
    from src.adapters.sqlite import core

    app = _clean_app(tmp_path, "no-legacy-rule-lineage.db")
    try:
        with app.app_context():
            db = core.get_db()
            _remove_legacy_schema(db)

            compiled = RuleCompiler().compile(valid_rule())
            assert not hasattr(compiled.definition, "legacy_rule_id")
            rule_id = ClinicalEngineRulesRepository().create_rule_version(
                compiled,
                created_by="pytest",
            )

            assert "source_legacy_rule_id" not in _columns(
                db, "clinical_rule_versions"
            )
            row = db.execute(
                "SELECT rule_code, version FROM clinical_rule_versions "
                "WHERE id=?",
                (rule_id,),
            ).fetchone()
            assert row["rule_code"] == valid_rule()["rule_code"]
            assert row["version"] == valid_rule()["version"]
    finally:
        core._initialized = False


def test_decision_audit_persists_and_projects_after_lineage_cleanup(tmp_path):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.clinical_engine_audit_repo import (
        ClinicalEngineAuditRepository,
    )
    from src.domain.clinical_engine import (
        ClinicalDecision,
        RecommendationEventType,
        RunStatus,
    )

    app = _clean_app(tmp_path, "no-legacy-decision-lineage.db")
    try:
        with app.app_context():
            db = core.get_db()
            _remove_legacy_schema(db)
            patient_id = int(
                db.execute(
                    """INSERT INTO patient_links
                       (national_id, full_name, enrolled_by)
                       VALUES ('LINEAGE01', 'Lineage Free Patient', 'pytest')"""
                ).lastrowid
            )
            db.commit()

            audit = ClinicalEngineAuditRepository()
            run_id = audit.start_run(
                patient_link_id=patient_id,
                as_of_at="2026-07-23 09:00:00",
                engine_version="lineage-free-test",
                fact_snapshot={
                    "schema_version": "2.0",
                    "patient_link_id": patient_id,
                    "clinical_data_revision": 0,
                    "facts": [],
                },
            )
            recommendation_id = audit.append_recommendation_event(
                run_id=run_id,
                recommendation_key="lineage-free:test",
                action_type="educate",
                event_type=RecommendationEventType.CREATED,
                payload={"suggestion_only": True},
            )
            audit.complete_run(run_id, status=RunStatus.COMPLETED)
            decision_id = audit.append_decision(
                recommendation_event_id=recommendation_id,
                patient_link_id=patient_id,
                decision=ClinicalDecision.ACCEPTED,
                actor_username="physician",
            )

            assert "legacy_source_suggestion_log_id" not in _columns(
                db, "clinical_decision_events"
            )
            stored = db.execute(
                "SELECT decision, actor_username "
                "FROM clinical_decision_events WHERE id=?",
                (decision_id,),
            ).fetchone()
            assert dict(stored) == {
                "decision": "ACCEPTED",
                "actor_username": "physician",
            }
            projected = audit.recommendation_context(
                recommendation_id,
                patient_link_id=patient_id,
            )
            assert projected["current_decision"]["id"] == decision_id
            assert all(
                "legacy" not in key
                for key in projected["current_decision"]
            )
    finally:
        core._initialized = False
