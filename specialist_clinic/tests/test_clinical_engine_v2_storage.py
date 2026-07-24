"""PR-03 tests: additive v2 storage, lifecycle gates and append-only audit."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))

from src.adapters.sqlite.clinical_engine_audit_repo import ClinicalEngineAuditRepository
from src.adapters.sqlite.clinical_engine_rules_repo import (
    ClinicalEngineRulesRepository,
    ClinicalEngineStorageConflict,
)
from src.domain.clinical_engine import (
    ClinicalDecision,
    PredicateState,
    RecommendationEventType,
    RuleOutcome,
    RunStatus,
)
from src.services.clinical_engine.compiler import RuleCompiler


V2_TABLES = {
    "clinical_rule_versions",
    "clinical_rulesets",
    "clinical_ruleset_members",
    "clinical_engine_runs",
    "clinical_rule_evaluations",
    "clinical_recommendation_events",
    "clinical_decision_events",
}
SAFETY_ARTIFACT_DIR = (
    SPECIALIST_ROOT / "src" / "domain" / "clinical_engine" /
    "rule_artifacts" / "2026.1-draft.1"
)


def _valid_rule():
    return {
        "schema_version": "2.0",
        "dsl_version": "2.0",
        "rule_code": "TEST-STORAGE-01",
        "version": "2.0.0-draft.1",
        "title": "قاعدهٔ آزمایشی ذخیره‌سازی",
        "phase": "ROUTINE",
        "action_type": "educate",
        "severity": "INFO",
        "priority": 100,
        "semantic_key": "test:storage:education",
        "scope": {
            "population": "بزرگسال سرپایی",
            "age_min": 18,
            "age_max": None,
            "sex": ["any"],
            "care_settings": ["outpatient"],
            "encounter_types": ["office_visit"],
            "condition_codes": ["diabetes"],
            "out_of_scope": [],
        },
        "required_facts": [
            {
                "key": "condition.diabetes",
                "criticality": "REQUIRED",
                "max_age_days": None,
                "minimum_verification": "CONFIRMED",
                "on_unusable": "NEEDS_DATA",
                "prompt_fa": "تشخیص دیابت باید تأیید شود.",
            }
        ],
        "eligibility": {
            "node_id": "eligibility-diabetes",
            "fact": "condition.diabetes",
            "selector": {"aggregation": "single"},
            "op": "==",
            "value": True,
            "unit": None,
        },
        "condition": {
            "node_id": "condition-diabetes",
            "fact": "condition.diabetes",
            "selector": {"aggregation": "single"},
            "op": "truthy",
            "unit": None,
        },
        "safety": {
            "redflag_exclusions": [],
            "hard_exclusions": [],
            "on_safety_error": "BLOCK_ROUTINE_OUTPUTS",
        },
        "recommendation": {
            "text_fa": "آموزش عمومی با تأیید پزشک معالج.",
            "suggestion_only": True,
            "requires_clinician_confirmation": False,
            "may_create_internal_task": False,
            "params": {},
        },
        "evidence": {
            "source_title": "Test guideline",
            "issuing_organization": "Test organization",
            "publication_date": "2026-01-01",
            "source_version": "2026",
            "source_locator": "Section 1",
            "source_url": "https://example.org/guideline",
            "evidence_certainty": "NOT_GRADED",
            "recommendation_strength": "NOT_GRADED",
            "local_validation_status": "NOT_REVIEWED",
            "local_adaptation_note": "فقط برای تست",
        },
        "governance": {
            "status": "DRAFT",
            "author": "test-suite",
            "clinical_reviewer": None,
            "technical_reviewer": None,
            "review_due_date": "2026-12-31",
            "supersedes": None,
            "change_note": "initial draft",
        },
    }


def test_pr06_safety_artefacts_compile_and_store_without_v1_storage(
    storage_app,
):
    _, _, _, _ = storage_app
    from src.adapters.sqlite.core import get_db

    db = get_db()
    assert db.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='clinical_rules'"
    ).fetchone() is None
    manifest = json.loads(
        (SAFETY_ARTIFACT_DIR / "manifest.json").read_text(encoding="utf-8")
    )
    repository = ClinicalEngineRulesRepository()
    compiler = RuleCompiler()
    members = []
    for item in manifest["rules"]:
        raw = json.loads(
            (SAFETY_ARTIFACT_DIR / item["file"]).read_text(encoding="utf-8")
        )
        assert raw["governance"]["status"] == "DRAFT"
        assert raw["evidence"]["local_validation_status"] == "NOT_REVIEWED"
        compiled = compiler.compile(raw)
        rule_version_id = repository.create_rule_version(
            compiled, created_by="pytest-pr06"
        )
        members.append({
            "rule_version_id": rule_version_id,
            "sort_order": item["sort_order"],
        })
    ruleset_id = repository.create_ruleset(
        manifest["ruleset_code"], manifest["version"], members,
        created_by="pytest-pr06",
        note="technical shadow draft; not clinically approved",
    )
    stored = repository.get_ruleset(ruleset_id)
    assert stored["status"] == "DRAFT"
    assert [item["phase"] for item in stored["members"]] == ["PREFLIGHT", "SAFETY"]
    assert db.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='clinical_rules'"
    ).fetchone() is None


@pytest.fixture()
def storage_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    db_path = tmp_path / "specialist-v2.db"
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(db_path),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "clinical-engine-storage-test",
        }
    )
    ctx = app.app_context()
    ctx.push()
    from src.adapters.sqlite.core import get_db

    db = get_db()
    cur = db.execute(
        """INSERT INTO patient_links (national_id, full_name, enrolled_by)
           VALUES ('V2STORAGE001', 'بیمار تست موتور نسخه دو', 'pytest')"""
    )
    db.commit()
    yield app, db_path, tmp_path, int(cur.lastrowid)
    ctx.pop()
    core._initialized = False


def _approved_rule_and_ruleset():
    compiled = RuleCompiler().compile(_valid_rule())
    rules = ClinicalEngineRulesRepository()
    rule_id = rules.create_rule_version(compiled, created_by="technical-reviewer")
    rules.mark_validated(rule_id, compiled)
    rules.approve_rule_version(rule_id, approved_by="clinical-reviewer")
    ruleset_id = rules.create_ruleset(
        "general-outpatient",
        "2026.1",
        [{"rule_version_id": rule_id, "sort_order": 10}],
        created_by="release-manager",
    )
    return compiled, rule_id, ruleset_id


def test_fresh_bootstrap_creates_all_tables_and_safe_off_flag(storage_app):
    from src.adapters.sqlite.core import _CLINICAL_ENGINE_V2_TRIGGERS, get_db

    db = get_db()
    tables = {
        row["name"]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert V2_TABLES <= tables
    triggers = {
        row["name"]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
    }
    assert _CLINICAL_ENGINE_V2_TRIGGERS <= triggers
    mode = db.execute(
        "SELECT value FROM settings WHERE key='clinical_engine_v2_mode'"
    ).fetchone()
    assert mode["value"] == "off"


def test_existing_database_bootstrap_is_additive_and_idempotent(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    db_path = tmp_path / "copied-existing.db"
    raw = sqlite3.connect(db_path)
    raw.executescript(core._load_schema_text())
    raw.execute("PRAGMA foreign_keys=OFF")
    for table in (
        "clinical_decision_events",
        "clinical_recommendation_events",
        "clinical_rule_evaluations",
        "clinical_engine_runs",
        "clinical_ruleset_members",
        "clinical_rulesets",
        "clinical_rule_versions",
    ):
        raw.execute(f"DROP TABLE {table}")
    raw.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('legacy-marker', 'kept')"
    )
    raw.execute("DELETE FROM settings WHERE key='clinical_engine_v2_mode'")
    raw.commit()
    raw.close()

    for _ in range(2):
        core._initialized = False
        app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": str(db_path),
                "BACKUP_FOLDER": str(tmp_path / "backups"),
                "SECRET_KEY": "migration-test",
            }
        )
        with app.app_context():
            db = core.get_db()
            tables = {
                row["name"]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert V2_TABLES <= tables
            assert db.execute(
                "SELECT value FROM settings WHERE key='legacy-marker'"
            ).fetchone()["value"] == "kept"
            assert db.execute(
                "SELECT COUNT(*) AS c FROM settings "
                "WHERE key='clinical_engine_v2_mode'"
            ).fetchone()["c"] == 1


def test_rule_versions_are_compiled_idempotent_and_content_immutable(storage_app):
    from src.adapters.sqlite.core import get_db

    compiler = RuleCompiler()
    compiled = compiler.compile(_valid_rule())
    repo = ClinicalEngineRulesRepository()
    rule_id = repo.create_rule_version(compiled, created_by="author")
    assert repo.create_rule_version(compiled, created_by="author") == rule_id

    changed = deepcopy(_valid_rule())
    changed["recommendation"]["text_fa"] = "محتوای متفاوت"
    with pytest.raises(ClinicalEngineStorageConflict):
        repo.create_rule_version(compiler.compile(changed), created_by="author")

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        get_db().execute(
            "UPDATE clinical_rule_versions SET rule_json='{}' WHERE id=?", (rule_id,)
        )


def test_ruleset_activation_requires_approved_members_and_freezes_membership(storage_app):
    compiled = RuleCompiler().compile(_valid_rule())
    repo = ClinicalEngineRulesRepository()
    rule_id = repo.create_rule_version(compiled, created_by="author")
    ruleset_id = repo.create_ruleset(
        "general-outpatient",
        "2026.1",
        [{"rule_version_id": rule_id, "sort_order": 10}],
        created_by="release-manager",
    )
    with pytest.raises(ValueError, match="APPROVED"):
        repo.activate_ruleset(ruleset_id, activated_by="release-manager")

    repo.mark_validated(rule_id, compiled)
    repo.approve_rule_version(rule_id, approved_by="physician")
    repo.activate_ruleset(ruleset_id, activated_by="release-manager", silent=True)
    active = repo.active_ruleset("general-outpatient")
    assert active["id"] == ruleset_id
    assert active["status"] == "SILENT"

    from src.adapters.sqlite.core import get_db

    with pytest.raises(sqlite3.IntegrityError, match="DRAFT"):
        get_db().execute(
            """INSERT INTO clinical_ruleset_members
               (ruleset_id, rule_version_id, phase, sort_order)
               VALUES (?, ?, 'ROUTINE', 20)""",
            (ruleset_id, rule_id),
        )


def test_audit_is_reproducible_append_only_and_survives_backup(storage_app):
    app, db_path, tmp_path, patient_id = storage_app
    _, rule_id, ruleset_id = _approved_rule_and_ruleset()
    ClinicalEngineRulesRepository().activate_ruleset(
        ruleset_id, activated_by="release-manager", silent=True
    )
    audit = ClinicalEngineAuditRepository()
    snapshot = {"facts": [{"key": "condition.diabetes", "value": True}]}
    run_id = audit.start_run(
        patient_link_id=patient_id,
        as_of_at="2026-07-21 12:00:00",
        engine_version="2.0.0",
        ruleset_id=ruleset_id,
        fact_snapshot=snapshot,
        created_by="pytest",
    )
    evaluation_id = audit.append_evaluation(
        run_id=run_id,
        rule_version_id=rule_id,
        predicate_state=PredicateState.TRUE,
        outcome=RuleOutcome.FIRED,
        trace={"node_id": "condition-diabetes", "state": "TRUE"},
        recommendation={"text_fa": "آموزش"},
        duration_ms=1.25,
    )
    recommendation_id = audit.append_recommendation_event(
        run_id=run_id,
        evaluation_id=evaluation_id,
        recommendation_key="test:storage:education",
        action_type="educate",
        event_type=RecommendationEventType.CREATED,
        payload={"text_fa": "آموزش"},
    )
    from src.adapters.sqlite.core import get_db

    db = get_db()
    with pytest.raises(sqlite3.IntegrityError, match="snapshot are immutable"):
        db.execute(
            "UPDATE clinical_engine_runs SET fact_snapshot_json='{}' WHERE run_id=?",
            (run_id,),
        )
    audit.complete_run(run_id, status=RunStatus.COMPLETED, summary={"fired": 1})
    decision_id = audit.append_decision(
        recommendation_event_id=recommendation_id,
        patient_link_id=patient_id,
        decision=ClinicalDecision.ACCEPTED,
        actor_username="physician",
    )

    stored = audit.get_run(run_id)
    stored_snapshot = json.loads(stored["fact_snapshot_json"])
    assert stored_snapshot["facts"] == snapshot["facts"]
    assert stored_snapshot["patient_link_id"] == patient_id
    assert stored_snapshot["context_hash"] == stored["context_hash"]
    assert stored_snapshot["evaluation_context"]["content_hash"] == stored["context_hash"]
    expected_snapshot = json.dumps(
        stored_snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    assert stored["fact_snapshot_json"] == expected_snapshot
    assert stored["fact_snapshot_hash"] == hashlib.sha256(
        expected_snapshot.encode("utf-8")
    ).hexdigest()
    assert stored["run_status"] == "COMPLETED"
    assert len(stored["evaluations"]) == 1

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute(
            "UPDATE clinical_rule_evaluations SET outcome='ERROR' WHERE id=?",
            (evaluation_id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        db.execute("DELETE FROM clinical_decision_events WHERE id=?", (decision_id,))
    with pytest.raises(sqlite3.IntegrityError, match="RUNNING"):
        audit.append_evaluation(
            run_id=run_id,
            rule_version_id=rule_id,
            predicate_state=PredicateState.ERROR,
            outcome=RuleOutcome.ERROR,
            trace={"error": "late write"},
        )
    with pytest.raises(ValueError, match="already terminal"):
        audit.complete_run(run_id, status=RunStatus.COMPLETED)

    from src.services.scheduler import Scheduler

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(exist_ok=True)
    scheduler = Scheduler(app)
    scheduler.db_path = db_path
    scheduler.backup_dir = backup_dir
    scheduler._backup()
    backups = list(backup_dir.glob("backup_auto_*.db"))
    assert len(backups) == 1
    copied = sqlite3.connect(backups[0])
    try:
        assert copied.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert copied.execute(
            "SELECT run_status FROM clinical_engine_runs WHERE run_id=?", (run_id,)
        ).fetchone()[0] == "COMPLETED"
        assert copied.execute(
            "SELECT decision FROM clinical_decision_events WHERE id=?", (decision_id,)
        ).fetchone()[0] == "ACCEPTED"
    finally:
        copied.close()
