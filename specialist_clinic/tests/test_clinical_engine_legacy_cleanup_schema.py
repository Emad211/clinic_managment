"""Adversarial tests for the isolated legacy-schema cleanup primitive."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sqlite3
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))
if str(SPECIALIST_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT / "tests"))

from test_clinical_engine_v2_compiler import valid_rule
from src.adapters.sqlite.clinical_engine_audit_repo import (
    ClinicalEngineAuditRepository,
)
from src.adapters.sqlite.clinical_engine_legacy_cleanup_schema import (
    LegacyClinicalLineagePresent,
    cleanup_legacy_clinical_schema,
)
from src.adapters.sqlite.clinical_engine_rules_repo import (
    ClinicalEngineRulesRepository,
)
from src.domain.clinical_engine import RunStatus
from src.services.clinical_engine.compiler import RuleCompiler


def _restore_retired_schema(db) -> None:
    """Recreate the exact compatibility surface consumed by this migration test.

    Application startup correctly removes these objects. The migration primitive is
    tested against an explicitly reconstructed pre-cutover database so runtime never
    needs a skip flag or test-only bypass.
    """
    db.executescript(
        """
        CREATE TABLE clinical_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_code TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            category TEXT NOT NULL
        );
        CREATE TABLE suggestion_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_link_id INTEGER NOT NULL,
            rule_code TEXT NOT NULL,
            suggestion_text TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id)
        );
        ALTER TABLE clinical_rule_versions
          ADD COLUMN source_legacy_rule_id INTEGER
          REFERENCES clinical_rules(id);
        ALTER TABLE clinical_decision_events
          ADD COLUMN legacy_source_suggestion_log_id INTEGER
          REFERENCES suggestion_log(id);
        """
    )
    db.commit()


@pytest.fixture()
def cleanup_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "legacy-cleanup.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "legacy-cleanup-test",
        }
    )
    context = app.app_context()
    context.push()
    from src.adapters.sqlite.core import get_db

    _restore_retired_schema(get_db())
    yield app
    context.pop()
    core._initialized = False


def _patient(db) -> int:
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, enrolled_by)
               VALUES ('CLEANUP01', 'Cleanup Patient', 'pytest')"""
        ).lastrowid
    )
    db.commit()
    return patient_id


def _two_rule_versions() -> tuple[int, int]:
    repository = ClinicalEngineRulesRepository()
    compiler = RuleCompiler()
    first_raw = valid_rule()
    first_raw["rule_code"] = "CLEANUP-RULE"
    first_raw["version"] = "2.0.0"
    first = repository.create_rule_version(
        compiler.compile(first_raw),
        created_by="pytest",
    )
    second_raw = deepcopy(first_raw)
    second_raw["version"] = "2.0.1"
    second_raw["governance"]["supersedes"] = "CLEANUP-RULE@2.0.0"
    second = repository.create_rule_version(
        compiler.compile(second_raw),
        created_by="pytest",
        supersedes_rule_version_id=first,
    )
    return first, second


def _two_decisions(db, patient_id: int) -> tuple[int, int]:
    audit = ClinicalEngineAuditRepository()
    run_id = audit.start_run(
        patient_link_id=patient_id,
        as_of_at="2026-07-22 10:00:00",
        engine_version="cleanup-test",
        fact_snapshot={
            "schema_version": "2.0",
            "patient_link_id": patient_id,
            "clinical_data_revision": 0,
            "facts": [],
        },
    )
    recommendation_id = audit.append_recommendation_event(
        run_id=run_id,
        recommendation_key="cleanup:recommendation",
        action_type="educate",
        event_type="CREATED",
        payload={"suggestion_only": True},
    )
    audit.complete_run(run_id, status=RunStatus.COMPLETED)
    first = int(
        db.execute(
            """INSERT INTO clinical_decision_events
               (recommendation_event_id, patient_link_id, decision,
                actor_username, occurred_at)
               VALUES (?, ?, 'DEFERRED', 'doctor', '2026-07-22 10:10:00')""",
            (recommendation_id, patient_id),
        ).lastrowid
    )
    second = int(
        db.execute(
            """INSERT INTO clinical_decision_events
               (recommendation_event_id, patient_link_id, decision,
                actor_username, occurred_at, supersedes_event_id)
               VALUES (?, ?, 'ACCEPTED', 'doctor',
                       '2026-07-22 10:20:00', ?)""",
            (recommendation_id, patient_id, first),
        ).lastrowid
    )
    db.commit()
    return first, second


def _columns(db, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in db.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _objects(db, kind: str) -> set[str]:
    return {
        str(row["name"])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type=?",
            (kind,),
        ).fetchall()
    }


def test_cleanup_preserves_v2_rows_and_reinstalls_guards(cleanup_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db)
    first_rule, second_rule = _two_rule_versions()
    first_decision, second_decision = _two_decisions(db, patient_id)
    db.execute(
        """INSERT INTO clinical_rules (rule_code, title, category)
           VALUES ('LEGACY-ONLY', 'Legacy only', 'educate')"""
    )
    db.execute(
        """INSERT INTO suggestion_log
           (patient_link_id, rule_code, suggestion_text, status)
           VALUES (?, 'LEGACY-ONLY', 'retired suggestion', 'dismissed')""",
        (patient_id,),
    )
    db.commit()

    result = cleanup_legacy_clinical_schema(db)

    assert result["changed"] is True
    assert set(result["removed"]) == {
        "rule_column",
        "decision_column",
        "clinical_rules_table",
        "suggestion_log_table",
    }
    assert "source_legacy_rule_id" not in _columns(
        db, "clinical_rule_versions"
    )
    assert "legacy_source_suggestion_log_id" not in _columns(
        db, "clinical_decision_events"
    )
    tables = _objects(db, "table")
    assert "clinical_rules" not in tables
    assert "suggestion_log" not in tables

    stored_rules = db.execute(
        """SELECT id, supersedes_rule_version_id
           FROM clinical_rule_versions ORDER BY id"""
    ).fetchall()
    assert [int(row["id"]) for row in stored_rules] == [
        first_rule,
        second_rule,
    ]
    assert int(stored_rules[1]["supersedes_rule_version_id"]) == first_rule
    stored_decisions = db.execute(
        """SELECT id, supersedes_event_id
           FROM clinical_decision_events ORDER BY id"""
    ).fetchall()
    assert [int(row["id"]) for row in stored_decisions] == [
        first_decision,
        second_decision,
    ]
    assert int(stored_decisions[1]["supersedes_event_id"]) == first_decision
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []

    triggers = _objects(db, "trigger")
    assert {
        "trg_rule_version_content_immutable",
        "trg_rule_versions_no_delete",
        "trg_decision_events_no_update",
        "trg_decision_events_no_delete",
        "trg_decision_events_terminal_run_only",
    } <= triggers
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute(
            "UPDATE clinical_decision_events SET reason_text='changed' "
            "WHERE id=?",
            (second_decision,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        db.execute(
            "DELETE FROM clinical_rule_versions WHERE id=?",
            (second_rule,),
        )
    db.rollback()

    assert cleanup_legacy_clinical_schema(db) == {
        "changed": False,
        "removed": [],
    }


def test_cleanup_is_fully_atomic_on_mid_rebuild_failure(
    cleanup_app,
    monkeypatch,
):
    from src.adapters.sqlite import clinical_engine_legacy_cleanup_schema
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db)
    first_rule, second_rule = _two_rule_versions()
    first_decision, second_decision = _two_decisions(db, patient_id)
    db.execute(
        """INSERT INTO clinical_rules (rule_code, title, category)
           VALUES ('LEGACY-ROLLBACK', 'Legacy rollback', 'educate')"""
    )
    db.execute(
        """INSERT INTO suggestion_log
           (patient_link_id, rule_code, status)
           VALUES (?, 'LEGACY-ROLLBACK', 'pending')""",
        (patient_id,),
    )
    db.commit()

    before_columns = {
        "rules": _columns(db, "clinical_rule_versions"),
        "decisions": _columns(db, "clinical_decision_events"),
    }
    before_triggers = _objects(db, "trigger")
    before_tables = _objects(db, "table")

    def fail_after_first_rebuild(_db):
        raise RuntimeError("simulated second-table rebuild failure")

    monkeypatch.setattr(
        clinical_engine_legacy_cleanup_schema,
        "_rebuild_decisions",
        fail_after_first_rebuild,
    )

    with pytest.raises(RuntimeError, match="simulated second-table"):
        clinical_engine_legacy_cleanup_schema.cleanup_legacy_clinical_schema(db)

    assert _columns(db, "clinical_rule_versions") == before_columns["rules"]
    assert _columns(db, "clinical_decision_events") == before_columns[
        "decisions"
    ]
    assert _objects(db, "trigger") == before_triggers
    assert _objects(db, "table") == before_tables
    assert not {
        "clinical_rule_versions_clean",
        "clinical_decision_events_clean",
    } & _objects(db, "table")
    assert [
        int(row["id"])
        for row in db.execute(
            "SELECT id FROM clinical_rule_versions ORDER BY id"
        ).fetchall()
    ] == [first_rule, second_rule]
    assert [
        int(row["id"])
        for row in db.execute(
            "SELECT id FROM clinical_decision_events ORDER BY id"
        ).fetchall()
    ] == [first_decision, second_decision]
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert int(db.execute("PRAGMA foreign_keys").fetchone()[0]) == 1


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("clinical_rule_versions", "source_legacy_rule_id"),
        (
            "clinical_decision_events",
            "legacy_source_suggestion_log_id",
        ),
    ],
)
def test_cleanup_refuses_non_null_legacy_lineage(
    cleanup_app,
    table,
    column,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db)
    legacy_rule_id = int(
        db.execute(
            """INSERT INTO clinical_rules (rule_code, title, category)
               VALUES ('LEGACY-BOUND', 'Legacy bound', 'educate')"""
        ).lastrowid
    )
    if table == "clinical_rule_versions":
        db.execute(
            """INSERT INTO clinical_rule_versions
               (rule_code, version, schema_version, dsl_version, phase,
                action_type, rule_json, content_hash, source_legacy_rule_id,
                lifecycle_status, created_by, created_at)
               VALUES ('BOUND-RULE', '1.0.0', '2.0', '2.0', 'ROUTINE',
                       'educate', '{}', 'bound-rule-hash', ?, 'DRAFT',
                       'pytest', '2026-07-22 10:00:00')""",
            (legacy_rule_id,),
        )
    else:
        audit = ClinicalEngineAuditRepository()
        run_id = audit.start_run(
            patient_link_id=patient_id,
            as_of_at="2026-07-22 10:00:00",
            engine_version="cleanup-test",
            fact_snapshot={"clinical_data_revision": 0, "facts": []},
        )
        recommendation_id = audit.append_recommendation_event(
            run_id=run_id,
            recommendation_key="cleanup:bound",
            action_type="educate",
            event_type="CREATED",
            payload={"suggestion_only": True},
        )
        audit.complete_run(run_id, status=RunStatus.COMPLETED)
        legacy_suggestion_id = int(
            db.execute(
                """INSERT INTO suggestion_log
                   (patient_link_id, rule_code, status)
                   VALUES (?, 'LEGACY-BOUND', 'accepted')""",
                (patient_id,),
            ).lastrowid
        )
        db.execute(
            """INSERT INTO clinical_decision_events
               (recommendation_event_id, patient_link_id, decision,
                actor_username, occurred_at, legacy_source_suggestion_log_id)
               VALUES (?, ?, 'ACCEPTED', 'doctor',
                       '2026-07-22 10:10:00', ?)""",
            (recommendation_id, patient_id, legacy_suggestion_id),
        )
    db.commit()

    with pytest.raises(
        LegacyClinicalLineagePresent,
        match=rf"{table}\.{column}",
    ):
        cleanup_legacy_clinical_schema(db)

    assert column in _columns(db, table)
    assert "clinical_rules" in _objects(db, "table")
