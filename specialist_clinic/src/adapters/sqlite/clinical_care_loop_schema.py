"""Append-only lifecycle storage for the closed Clinical Engine care loop."""
from __future__ import annotations

import hashlib
import json
import sqlite3

from src.adapters.sqlite.core import get_db


_REQUIRED_TABLES = {"clinical_task_events", "clinical_outcome_events"}
_REQUIRED_TRIGGERS = {
    "trg_clinical_task_events_no_update",
    "trg_clinical_task_events_no_delete",
    "trg_clinical_task_events_first",
    "trg_clinical_task_events_subsequent",
    "trg_clinical_task_events_scope",
    "trg_clinical_task_events_recorded_order",
    "trg_clinical_task_events_transition",
    "trg_clinical_task_events_appointment_patient",
    "trg_clinical_outcome_events_no_update",
    "trg_clinical_outcome_events_no_delete",
    "trg_clinical_followup_identity_immutable",
    "trg_clinical_followup_no_delete",
}


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in db.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _ensure_column(
    db: sqlite3.Connection,
    table: str,
    column: str,
    declaration: str,
) -> None:
    if column in _columns(db, table):
        return
    try:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
    except sqlite3.OperationalError:
        if column not in _columns(db, table):
            raise


def _hash(payload: dict) -> str:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _backfill_open_clinical_tasks(db: sqlite3.Connection) -> None:
    """Create roots for legacy open tasks; never fabricate terminal evidence."""
    rows = db.execute(
        """SELECT task.id, task.due_date, task.created_at, task.status
           FROM followup_tasks task
           WHERE task.source_engine='clinical_v2'
             AND NOT EXISTS (
                 SELECT 1 FROM clinical_task_events event
                 WHERE event.task_id=task.id
             )
           ORDER BY task.id"""
    ).fetchall()
    terminal = [
        int(row[0]) for row in rows if str(row[3] or "open") != "open"
    ]
    if terminal:
        raise RuntimeError(
            "legacy terminal clinical tasks have no outcome evidence; "
            "reset seed data: " + ",".join(str(value) for value in terminal)
        )
    for row in rows:
        task_id = int(row[0])
        due_at = str(row[1] or "").strip() or None
        if due_at and len(due_at) == 10:
            due_at = f"{due_at} 00:00:00"
        recorded_at = str(row[2] or "").strip()
        if not recorded_at:
            recorded_at = str(
                db.execute(
                    "SELECT datetime('now','+3 hours','+30 minutes')"
                ).fetchone()[0]
            )
        payload = {
            "task_id": task_id,
            "event_type": "CREATED",
            "status": "OPEN",
            "assigned_to": None,
            "appointment_id": None,
            "due_at": due_at,
            "disposition_code": None,
            "outcome_event_id": None,
            "effective_at": recorded_at,
            "recorded_at": recorded_at,
            "supersedes_event_id": None,
        }
        db.execute(
            """INSERT INTO clinical_task_events
               (task_id, event_type, status, due_at, effective_at,
                recorded_at, actor_username, content_hash)
               VALUES (?, 'CREATED', 'OPEN', ?, ?, ?,
                       'legacy-open-task-migration', ?)""",
            (task_id, due_at, recorded_at, recorded_at, _hash(payload)),
        )


def ensure_clinical_care_loop_storage(
    db: sqlite3.Connection | None = None,
) -> None:
    """Install and verify clinical-task lifecycle and outcome evidence storage."""
    db = db or get_db()
    tables = {
        str(row["name"])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "followup_tasks" not in tables:
        return

    _ensure_column(db, "followup_tasks", "clinical_due_period", "TEXT")
    _ensure_column(
        db,
        "followup_tasks",
        "clinical_source_decision_event_id",
        "INTEGER REFERENCES clinical_decision_events(id)",
    )
    # The previous index treated every clinical root row as permanently open because
    # status now lives in the event stream. Remove it before recurrence is evaluated.
    db.execute(
        "DROP INDEX IF EXISTS idx_followup_open_clinical_semantic_context"
    )

    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS clinical_outcome_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            outcome_type TEXT NOT NULL CHECK (outcome_type IN (
                'OBSERVATION','PATIENT_REPORTED','ENCOUNTER_COMPLETED',
                'PROCEDURE_COMPLETED','LAB_COMPLETED','OTHER'
            )),
            fact_key TEXT,
            value_json TEXT,
            unit TEXT,
            verification TEXT NOT NULL CHECK (verification IN (
                'CONFIRMED','PROVISIONAL','UNVERIFIED'
            )),
            observed_at TEXT NOT NULL CHECK (datetime(observed_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            source_system TEXT NOT NULL CHECK (length(trim(source_system)) > 0),
            source_record_id TEXT,
            note TEXT,
            actor_user_id INTEGER,
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username)) > 0),
            content_hash TEXT NOT NULL CHECK (length(content_hash)=64),
            CHECK (datetime(observed_at) <= datetime(recorded_at)),
            CHECK (value_json IS NULL OR json_valid(value_json)),
            CHECK (fact_key IS NULL OR length(trim(fact_key)) BETWEEN 3 AND 200),
            CHECK (note IS NULL OR length(note) <= 2000),
            FOREIGN KEY(task_id) REFERENCES followup_tasks(id),
            FOREIGN KEY(actor_user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_clinical_outcomes_task
        ON clinical_outcome_events(task_id, recorded_at DESC, id DESC);

        CREATE TABLE IF NOT EXISTS clinical_task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN (
                'CREATED','ASSIGNED','SCHEDULED','STARTED','DEFERRED',
                'COMPLETED','NOT_DONE','ENTERED_IN_ERROR'
            )),
            status TEXT NOT NULL CHECK (status IN (
                'OPEN','ASSIGNED','SCHEDULED','IN_PROGRESS','DEFERRED',
                'COMPLETED','NOT_DONE','ENTERED_IN_ERROR'
            )),
            assigned_to TEXT,
            appointment_id INTEGER,
            due_at TEXT,
            disposition_code TEXT,
            outcome_event_id INTEGER,
            note TEXT,
            effective_at TEXT NOT NULL CHECK (datetime(effective_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_user_id INTEGER,
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username)) > 0),
            supersedes_event_id INTEGER,
            content_hash TEXT NOT NULL CHECK (length(content_hash)=64),
            CHECK (datetime(effective_at) <= datetime(recorded_at)),
            CHECK (due_at IS NULL OR datetime(due_at) IS NOT NULL),
            CHECK (note IS NULL OR length(note) <= 2000),
            FOREIGN KEY(task_id) REFERENCES followup_tasks(id),
            FOREIGN KEY(appointment_id) REFERENCES appointments(id),
            FOREIGN KEY(outcome_event_id) REFERENCES clinical_outcome_events(id),
            FOREIGN KEY(actor_user_id) REFERENCES users(id),
            FOREIGN KEY(supersedes_event_id) REFERENCES clinical_task_events(id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_clinical_task_events_one_root
        ON clinical_task_events(task_id)
        WHERE supersedes_event_id IS NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_clinical_task_events_one_child
        ON clinical_task_events(supersedes_event_id)
        WHERE supersedes_event_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_clinical_task_events_head
        ON clinical_task_events(task_id, recorded_at DESC, id DESC);

        CREATE TRIGGER IF NOT EXISTS trg_clinical_outcome_events_no_update
        BEFORE UPDATE ON clinical_outcome_events
        BEGIN SELECT RAISE(ABORT, 'clinical outcome events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_clinical_outcome_events_no_delete
        BEFORE DELETE ON clinical_outcome_events
        BEGIN SELECT RAISE(ABORT, 'clinical outcome events cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_clinical_task_events_no_update
        BEFORE UPDATE ON clinical_task_events
        BEGIN SELECT RAISE(ABORT, 'clinical task events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_clinical_task_events_no_delete
        BEFORE DELETE ON clinical_task_events
        BEGIN SELECT RAISE(ABORT, 'clinical task events cannot be deleted'); END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_task_events_first
        BEFORE INSERT ON clinical_task_events
        WHEN NOT EXISTS (
                SELECT 1 FROM clinical_task_events prior
                WHERE prior.task_id=NEW.task_id
             )
         AND (NEW.supersedes_event_id IS NOT NULL
              OR NEW.event_type<>'CREATED' OR NEW.status<>'OPEN')
        BEGIN SELECT RAISE(ABORT, 'first clinical task event must be CREATED/OPEN'); END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_task_events_subsequent
        BEFORE INSERT ON clinical_task_events
        WHEN EXISTS (
                SELECT 1 FROM clinical_task_events prior
                WHERE prior.task_id=NEW.task_id
             )
         AND (NEW.supersedes_event_id IS NULL
              OR NEW.supersedes_event_id<>(
                    SELECT head.id FROM clinical_task_events head
                    WHERE head.task_id=NEW.task_id
                      AND NOT EXISTS (
                          SELECT 1 FROM clinical_task_events child
                          WHERE child.supersedes_event_id=head.id
                      )
                    ORDER BY head.recorded_at DESC, head.id DESC LIMIT 1
              ))
        BEGIN SELECT RAISE(ABORT, 'clinical task event must supersede current head'); END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_task_events_scope
        BEFORE INSERT ON clinical_task_events
        WHEN NEW.supersedes_event_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1 FROM clinical_task_events prior
             WHERE prior.id=NEW.supersedes_event_id AND prior.task_id=NEW.task_id
         )
        BEGIN SELECT RAISE(ABORT, 'clinical task supersession must stay in one task'); END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_task_events_recorded_order
        BEFORE INSERT ON clinical_task_events
        WHEN NEW.supersedes_event_id IS NOT NULL
         AND datetime(NEW.recorded_at) < datetime((
             SELECT prior.recorded_at FROM clinical_task_events prior
             WHERE prior.id=NEW.supersedes_event_id
         ))
        BEGIN SELECT RAISE(ABORT, 'clinical task recorded_at cannot move backwards'); END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_task_events_appointment_patient
        BEFORE INSERT ON clinical_task_events
        WHEN NEW.appointment_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1 FROM appointments appointment
             JOIN followup_tasks task ON task.id=NEW.task_id
             WHERE appointment.id=NEW.appointment_id
               AND appointment.patient_link_id=task.patient_link_id
         )
        BEGIN SELECT RAISE(ABORT, 'appointment does not belong to clinical task patient'); END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_task_events_transition
        BEFORE INSERT ON clinical_task_events
        WHEN (
            (NEW.event_type='CREATED' AND NEW.status<>'OPEN')
            OR (NEW.event_type='ASSIGNED' AND
                (NEW.status<>'ASSIGNED' OR length(trim(COALESCE(NEW.assigned_to,'')))=0))
            OR (NEW.event_type='SCHEDULED' AND
                (NEW.status<>'SCHEDULED' OR NEW.appointment_id IS NULL))
            OR (NEW.event_type='STARTED' AND NEW.status<>'IN_PROGRESS')
            OR (NEW.event_type='DEFERRED' AND
                (NEW.status<>'DEFERRED' OR NEW.due_at IS NULL))
            OR (NEW.event_type='COMPLETED' AND (
                NEW.status<>'COMPLETED' OR NEW.outcome_event_id IS NULL
                OR NOT EXISTS (
                    SELECT 1 FROM clinical_outcome_events outcome
                    WHERE outcome.id=NEW.outcome_event_id AND outcome.task_id=NEW.task_id
                )
            ))
            OR (NEW.event_type='NOT_DONE' AND (
                NEW.status<>'NOT_DONE' OR NEW.disposition_code NOT IN (
                    'PATIENT_DECLINED','UNREACHABLE','CLINICIAN_CANCELLED',
                    'DUPLICATE','NO_LONGER_NEEDED','OTHER'
                )
            ))
            OR (NEW.event_type='ENTERED_IN_ERROR' AND NEW.status<>'ENTERED_IN_ERROR')
            OR (NEW.supersedes_event_id IS NOT NULL
                AND (SELECT prior.status FROM clinical_task_events prior
                     WHERE prior.id=NEW.supersedes_event_id)
                    IN ('COMPLETED','NOT_DONE','ENTERED_IN_ERROR')
                AND NEW.event_type<>'ENTERED_IN_ERROR')
        )
        BEGIN SELECT RAISE(ABORT, 'invalid clinical task lifecycle transition'); END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_followup_identity_immutable
        BEFORE UPDATE OF patient_link_id, reason, detail, due_date, fulfillment,
                         source_rule, source_event, source_engine, source_run_id,
                         source_recommendation_event_id, clinical_semantic_key,
                         clinical_context_hash, clinical_task_key,
                         clinical_due_period, clinical_source_decision_event_id
        ON followup_tasks
        WHEN OLD.source_engine='clinical_v2'
        BEGIN SELECT RAISE(ABORT, 'clinical follow-up identity is immutable'); END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_followup_no_delete
        BEFORE DELETE ON followup_tasks
        WHEN OLD.source_engine='clinical_v2'
        BEGIN SELECT RAISE(ABORT, 'clinical follow-ups cannot be deleted'); END;
        """
    )

    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_followup_clinical_task_key "
        "ON followup_tasks(clinical_task_key) "
        "WHERE source_engine='clinical_v2' AND clinical_task_key IS NOT NULL"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_clinical_followup_due_period "
        "ON followup_tasks(patient_link_id, clinical_semantic_key, "
        "clinical_context_hash, clinical_due_period) "
        "WHERE source_engine='clinical_v2'"
    )
    _backfill_open_clinical_tasks(db)

    tables = {
        str(row["name"])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    missing_tables = sorted(_REQUIRED_TABLES - tables)
    if missing_tables:
        raise RuntimeError(
            "clinical care-loop tables are incomplete: " + ", ".join(missing_tables)
        )
    triggers = {
        str(row["name"])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    missing_triggers = sorted(_REQUIRED_TRIGGERS - triggers)
    if missing_triggers:
        raise RuntimeError(
            "clinical care-loop guards are incomplete: " + ", ".join(missing_triggers)
        )
    db.commit()
