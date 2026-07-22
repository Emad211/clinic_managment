"""Destructive-but-preserving removal of retired Clinical Engine v1 lineage.

This migration primitive is intentionally not called during application startup yet.
It is introduced and tested separately so the following tranche can first remove the
last repository fields and then activate this cleanup with a small, reviewable diff.

The migration preserves all v2 rule versions and clinician decisions while removing:

* ``clinical_rule_versions.source_legacy_rule_id``
* ``clinical_decision_events.legacy_source_suggestion_log_id``
* the retired ``clinical_rules`` and ``suggestion_log`` tables

Any non-NULL lineage value fails loudly. The project has seed/synthetic data, so such a
database must be explicitly reset rather than silently importing unverifiable history.
"""
from __future__ import annotations

import sqlite3
from typing import Any


class LegacyClinicalLineagePresent(RuntimeError):
    """Raised when destructive cleanup would discard referenced legacy lineage."""


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    return bool(
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    )


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(db, table):
        return set()
    return {
        str(row["name"])
        for row in db.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _assert_no_lineage(
    db: sqlite3.Connection,
    table: str,
    column: str,
) -> None:
    if column not in _columns(db, table):
        return
    row = db.execute(
        f"SELECT id FROM {table} WHERE {column} IS NOT NULL LIMIT 1"
    ).fetchone()
    if row:
        raise LegacyClinicalLineagePresent(
            f"{table}.{column} contains legacy lineage at row {int(row['id'])}; "
            "reset the seed database explicitly"
        )


def _rebuild_rule_versions(db: sqlite3.Connection) -> None:
    if "source_legacy_rule_id" not in _columns(db, "clinical_rule_versions"):
        return
    db.execute("DROP TRIGGER IF EXISTS trg_rule_version_content_immutable")
    db.execute("DROP TRIGGER IF EXISTS trg_rule_versions_no_delete")
    db.execute("DROP TABLE IF EXISTS clinical_rule_versions_clean")
    db.execute(
        """CREATE TABLE clinical_rule_versions_clean (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_code TEXT NOT NULL,
            version TEXT NOT NULL,
            schema_version TEXT NOT NULL DEFAULT '2.0',
            dsl_version TEXT NOT NULL DEFAULT '2.0',
            phase TEXT NOT NULL CHECK (phase IN ('PREFLIGHT', 'SAFETY', 'ROUTINE')),
            action_type TEXT NOT NULL,
            rule_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            lifecycle_status TEXT NOT NULL DEFAULT 'DRAFT'
                CHECK (lifecycle_status IN ('DRAFT', 'VALIDATED', 'APPROVED',
                                            'SILENT', 'ACTIVE', 'SUSPENDED',
                                            'RETIRED')),
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            approved_by TEXT,
            approved_at TEXT,
            supersedes_rule_version_id INTEGER,
            retired_at TEXT,
            change_note TEXT,
            UNIQUE(rule_code, version),
            UNIQUE(content_hash),
            FOREIGN KEY(supersedes_rule_version_id)
                REFERENCES clinical_rule_versions_clean(id)
        )"""
    )
    db.execute(
        """INSERT INTO clinical_rule_versions_clean (
            id, rule_code, version, schema_version, dsl_version, phase,
            action_type, rule_json, content_hash, lifecycle_status,
            created_by, created_at, approved_by, approved_at,
            supersedes_rule_version_id, retired_at, change_note
        )
        SELECT
            id, rule_code, version, schema_version, dsl_version, phase,
            action_type, rule_json, content_hash, lifecycle_status,
            created_by, created_at, approved_by, approved_at,
            supersedes_rule_version_id, retired_at, change_note
        FROM clinical_rule_versions"""
    )
    db.execute("DROP TABLE clinical_rule_versions")
    db.execute(
        "ALTER TABLE clinical_rule_versions_clean "
        "RENAME TO clinical_rule_versions"
    )
    db.execute(
        "CREATE INDEX idx_rule_versions_code "
        "ON clinical_rule_versions(rule_code, id DESC)"
    )
    db.execute(
        "CREATE INDEX idx_rule_versions_status "
        "ON clinical_rule_versions(lifecycle_status, phase)"
    )
    db.execute(
        """CREATE TRIGGER trg_rule_version_content_immutable
        BEFORE UPDATE OF rule_code, version, schema_version, dsl_version, phase,
                         action_type, rule_json, content_hash, created_by,
                         created_at, supersedes_rule_version_id
        ON clinical_rule_versions BEGIN
            SELECT RAISE(ABORT, 'clinical rule version content is immutable');
        END"""
    )
    db.execute(
        """CREATE TRIGGER trg_rule_versions_no_delete
        BEFORE DELETE ON clinical_rule_versions BEGIN
            SELECT RAISE(ABORT, 'clinical rule versions cannot be deleted');
        END"""
    )


def _rebuild_decisions(db: sqlite3.Connection) -> None:
    if (
        "legacy_source_suggestion_log_id"
        not in _columns(db, "clinical_decision_events")
    ):
        return
    db.execute("DROP TRIGGER IF EXISTS trg_decision_events_no_update")
    db.execute("DROP TRIGGER IF EXISTS trg_decision_events_no_delete")
    db.execute("DROP TRIGGER IF EXISTS trg_decision_events_terminal_run_only")
    db.execute("DROP TABLE IF EXISTS clinical_decision_events_clean")
    db.execute(
        """CREATE TABLE clinical_decision_events_clean (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recommendation_event_id INTEGER NOT NULL,
            patient_link_id INTEGER NOT NULL,
            decision TEXT NOT NULL
                CHECK (decision IN ('ACCEPTED', 'DISMISSED', 'DEFERRED',
                                    'CORRECTED')),
            reason_code TEXT,
            reason_text TEXT,
            actor_user_id INTEGER,
            actor_username TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            supersedes_event_id INTEGER,
            FOREIGN KEY(recommendation_event_id)
                REFERENCES clinical_recommendation_events(id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(actor_user_id) REFERENCES users(id),
            FOREIGN KEY(supersedes_event_id)
                REFERENCES clinical_decision_events_clean(id)
        )"""
    )
    db.execute(
        """INSERT INTO clinical_decision_events_clean (
            id, recommendation_event_id, patient_link_id, decision,
            reason_code, reason_text, actor_user_id, actor_username,
            occurred_at, supersedes_event_id
        )
        SELECT
            id, recommendation_event_id, patient_link_id, decision,
            reason_code, reason_text, actor_user_id, actor_username,
            occurred_at, supersedes_event_id
        FROM clinical_decision_events"""
    )
    db.execute("DROP TABLE clinical_decision_events")
    db.execute(
        "ALTER TABLE clinical_decision_events_clean "
        "RENAME TO clinical_decision_events"
    )
    db.execute(
        "CREATE INDEX idx_decision_events_recommendation "
        "ON clinical_decision_events(recommendation_event_id, occurred_at, id)"
    )
    db.execute(
        "CREATE INDEX idx_decision_events_patient "
        "ON clinical_decision_events(patient_link_id, occurred_at DESC)"
    )
    db.execute(
        """CREATE TRIGGER trg_decision_events_no_update
        BEFORE UPDATE ON clinical_decision_events BEGIN
            SELECT RAISE(ABORT, 'clinical_decision_events are immutable');
        END"""
    )
    db.execute(
        """CREATE TRIGGER trg_decision_events_no_delete
        BEFORE DELETE ON clinical_decision_events BEGIN
            SELECT RAISE(ABORT, 'clinical_decision_events cannot be deleted');
        END"""
    )
    db.execute(
        """CREATE TRIGGER trg_decision_events_terminal_run_only
        BEFORE INSERT ON clinical_decision_events
        WHEN (SELECT r.run_status
              FROM clinical_recommendation_events e
              JOIN clinical_engine_runs r ON r.run_id=e.run_id
              WHERE e.id=NEW.recommendation_event_id) = 'RUNNING'
        BEGIN
            SELECT RAISE(ABORT,
                         'clinical decisions require a terminal engine run');
        END"""
    )


def cleanup_legacy_clinical_schema(
    db: sqlite3.Connection,
) -> dict[str, Any]:
    """Remove retired v1 lineage while preserving v2 rows and immutability guards.

    Returns a deterministic change report. A second call is a no-op. Every rebuild
    statement executes inside one explicit transaction; no ``executescript`` implicit
    commit is permitted in this safety boundary.
    """
    _assert_no_lineage(
        db,
        "clinical_rule_versions",
        "source_legacy_rule_id",
    )
    _assert_no_lineage(
        db,
        "clinical_decision_events",
        "legacy_source_suggestion_log_id",
    )

    before = {
        "rule_column": "source_legacy_rule_id"
        in _columns(db, "clinical_rule_versions"),
        "decision_column": "legacy_source_suggestion_log_id"
        in _columns(db, "clinical_decision_events"),
        "clinical_rules_table": _table_exists(db, "clinical_rules"),
        "suggestion_log_table": _table_exists(db, "suggestion_log"),
    }
    if not any(before.values()):
        return {"changed": False, "removed": []}

    db.commit()
    foreign_keys = int(db.execute("PRAGMA foreign_keys").fetchone()[0])
    db.execute("PRAGMA foreign_keys=OFF")
    try:
        db.execute("BEGIN IMMEDIATE")
        _rebuild_rule_versions(db)
        _rebuild_decisions(db)
        db.execute("DROP TABLE IF EXISTS suggestion_log")
        db.execute("DROP TABLE IF EXISTS clinical_rules")
        violations = db.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                "legacy cleanup produced foreign-key violations: "
                + ", ".join(str(tuple(row)) for row in violations[:5])
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys else 'OFF'}")

    removed = [key for key, value in before.items() if value]
    return {"changed": True, "removed": removed}
