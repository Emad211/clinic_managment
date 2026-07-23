"""Additive storage and database guards for explicit clinical evaluation context."""
from __future__ import annotations

import sqlite3


_CONTEXT_HASH_DEFAULT = "0" * 64
_REQUIRED_TABLES = {"clinical_encounters", "clinical_encounter_events"}
_REQUIRED_TRIGGERS = {
    "trg_clinical_encounters_no_update",
    "trg_clinical_encounters_no_delete",
    "trg_clinical_encounters_appointment_patient",
    "trg_encounter_events_no_update",
    "trg_encounter_events_no_delete",
    "trg_encounter_events_first",
    "trg_encounter_events_subsequent",
    "trg_encounter_events_scope",
    "trg_encounter_events_recorded_order",
    "trg_encounter_events_transition",
    "trg_engine_runs_context_contract",
    "trg_engine_runs_identity_immutable",
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


def ensure_clinical_context_storage(db: sqlite3.Connection) -> None:
    """Install encounter history and bind every new engine run to one context hash."""
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS clinical_encounters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            encounter_key TEXT NOT NULL UNIQUE
                CHECK (length(trim(encounter_key)) BETWEEN 3 AND 200),
            patient_link_id INTEGER NOT NULL,
            appointment_id INTEGER,
            created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
            created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(appointment_id) REFERENCES appointments(id)
        );

        CREATE INDEX IF NOT EXISTS idx_clinical_encounters_patient
        ON clinical_encounters(patient_link_id, created_at DESC, id DESC);

        CREATE TABLE IF NOT EXISTS clinical_encounter_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            encounter_id INTEGER NOT NULL,
            event_type TEXT NOT NULL
                CHECK (event_type IN (
                    'OPENED','UPDATED','FINALIZED','CANCELLED','ENTERED_IN_ERROR'
                )),
            status TEXT NOT NULL
                CHECK (status IN ('OPEN','FINALIZED','CANCELLED','ENTERED_IN_ERROR')),
            care_setting TEXT NOT NULL
                CHECK (care_setting IN (
                    'primary_care','specialty_clinic','urgent_care','telehealth'
                )),
            encounter_type TEXT NOT NULL
                CHECK (encounter_type IN (
                    'office_visit','followup','urgent_visit','televisit',
                    'medication_review','preventive_visit','chronic_care_review'
                )),
            reason_codes_json TEXT NOT NULL DEFAULT '[]'
                CHECK (json_valid(reason_codes_json)
                       AND json_type(reason_codes_json)='array'),
            chief_complaint TEXT,
            responsible_actor TEXT,
            effective_at TEXT NOT NULL CHECK (datetime(effective_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            content_hash TEXT NOT NULL CHECK (length(content_hash)=64),
            actor_user_id INTEGER,
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username)) > 0),
            supersedes_event_id INTEGER,
            note TEXT,
            CHECK (datetime(effective_at) <= datetime(recorded_at)),
            CHECK (chief_complaint IS NULL OR length(chief_complaint) <= 1000),
            CHECK (responsible_actor IS NULL OR length(responsible_actor) <= 200),
            FOREIGN KEY(encounter_id) REFERENCES clinical_encounters(id),
            FOREIGN KEY(actor_user_id) REFERENCES users(id),
            FOREIGN KEY(supersedes_event_id) REFERENCES clinical_encounter_events(id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_encounter_events_one_root
        ON clinical_encounter_events(encounter_id)
        WHERE supersedes_event_id IS NULL;

        CREATE UNIQUE INDEX IF NOT EXISTS idx_encounter_events_one_child
        ON clinical_encounter_events(supersedes_event_id)
        WHERE supersedes_event_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_encounter_events_head
        ON clinical_encounter_events(encounter_id, recorded_at DESC, id DESC);

        CREATE TRIGGER IF NOT EXISTS trg_clinical_encounters_no_update
        BEFORE UPDATE ON clinical_encounters
        BEGIN
            SELECT RAISE(ABORT, 'clinical encounter identity is immutable');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_encounters_no_delete
        BEFORE DELETE ON clinical_encounters
        BEGIN
            SELECT RAISE(ABORT, 'clinical encounters cannot be deleted');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_encounters_appointment_patient
        BEFORE INSERT ON clinical_encounters
        WHEN NEW.appointment_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1 FROM appointments appointment
             WHERE appointment.id=NEW.appointment_id
               AND appointment.patient_link_id=NEW.patient_link_id
         )
        BEGIN
            SELECT RAISE(ABORT, 'appointment does not belong to encounter patient');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_encounter_events_no_update
        BEFORE UPDATE ON clinical_encounter_events
        BEGIN
            SELECT RAISE(ABORT, 'clinical encounter events are append-only');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_encounter_events_no_delete
        BEFORE DELETE ON clinical_encounter_events
        BEGIN
            SELECT RAISE(ABORT, 'clinical encounter events cannot be deleted');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_encounter_events_first
        BEFORE INSERT ON clinical_encounter_events
        WHEN NOT EXISTS (
                SELECT 1 FROM clinical_encounter_events prior
                WHERE prior.encounter_id=NEW.encounter_id
             )
         AND (
                NEW.supersedes_event_id IS NOT NULL
                OR NEW.event_type<>'OPENED'
                OR NEW.status<>'OPEN'
             )
        BEGIN
            SELECT RAISE(ABORT, 'first encounter event must open the encounter');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_encounter_events_subsequent
        BEFORE INSERT ON clinical_encounter_events
        WHEN EXISTS (
                SELECT 1 FROM clinical_encounter_events prior
                WHERE prior.encounter_id=NEW.encounter_id
             )
         AND (
                NEW.supersedes_event_id IS NULL
                OR NEW.supersedes_event_id<>(
                    SELECT head.id
                    FROM clinical_encounter_events head
                    WHERE head.encounter_id=NEW.encounter_id
                      AND NOT EXISTS (
                          SELECT 1 FROM clinical_encounter_events child
                          WHERE child.supersedes_event_id=head.id
                      )
                    ORDER BY head.recorded_at DESC, head.id DESC LIMIT 1
                )
             )
        BEGIN
            SELECT RAISE(ABORT, 'encounter event must supersede the current head');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_encounter_events_scope
        BEFORE INSERT ON clinical_encounter_events
        WHEN NEW.supersedes_event_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1 FROM clinical_encounter_events prior
             WHERE prior.id=NEW.supersedes_event_id
               AND prior.encounter_id=NEW.encounter_id
         )
        BEGIN
            SELECT RAISE(ABORT, 'encounter supersession must stay in one encounter');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_encounter_events_recorded_order
        BEFORE INSERT ON clinical_encounter_events
        WHEN NEW.supersedes_event_id IS NOT NULL
         AND datetime(NEW.recorded_at) < datetime((
             SELECT prior.recorded_at FROM clinical_encounter_events prior
             WHERE prior.id=NEW.supersedes_event_id
         ))
        BEGIN
            SELECT RAISE(ABORT, 'encounter recorded_at cannot move backwards');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_encounter_events_transition
        BEFORE INSERT ON clinical_encounter_events
        WHEN (
            (NEW.event_type IN ('OPENED','UPDATED') AND NEW.status<>'OPEN')
            OR (NEW.event_type='FINALIZED' AND NEW.status<>'FINALIZED')
            OR (NEW.event_type='CANCELLED' AND NEW.status<>'CANCELLED')
            OR (NEW.event_type='ENTERED_IN_ERROR' AND NEW.status<>'ENTERED_IN_ERROR')
            OR (
                NEW.supersedes_event_id IS NOT NULL
                AND (SELECT prior.status FROM clinical_encounter_events prior
                     WHERE prior.id=NEW.supersedes_event_id)<>'OPEN'
            )
        )
        BEGIN
            SELECT RAISE(ABORT, 'invalid clinical encounter lifecycle transition');
        END;
        """
    )

    _ensure_column(
        db,
        "clinical_engine_runs",
        "evaluation_mode",
        "TEXT NOT NULL DEFAULT 'LONGITUDINAL'",
    )
    _ensure_column(
        db,
        "clinical_engine_runs",
        "context_key",
        "TEXT NOT NULL DEFAULT 'legacy-context'",
    )
    _ensure_column(
        db,
        "clinical_engine_runs",
        "context_json",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    _ensure_column(
        db,
        "clinical_engine_runs",
        "context_hash",
        f"TEXT NOT NULL DEFAULT '{_CONTEXT_HASH_DEFAULT}'",
    )
    _ensure_column(db, "clinical_engine_runs", "encounter_event_id", "INTEGER")

    db.executescript(
        """
        DROP TRIGGER IF EXISTS trg_engine_runs_identity_immutable;
        DROP TRIGGER IF EXISTS trg_engine_runs_context_contract;

        CREATE TRIGGER trg_engine_runs_identity_immutable
        BEFORE UPDATE OF patient_link_id, encounter_key, encounter_event_id,
                         evaluation_mode, context_key, context_json, context_hash,
                         as_of_at, started_at, engine_version, ruleset_id,
                         fact_snapshot_json, fact_snapshot_hash, created_by
        ON clinical_engine_runs
        BEGIN
            SELECT RAISE(ABORT, 'clinical_engine_run identity, context and snapshot are immutable');
        END;

        CREATE TRIGGER trg_engine_runs_context_contract
        BEFORE INSERT ON clinical_engine_runs
        WHEN length(NEW.context_hash)<>64
          OR length(trim(NEW.context_key))<3
          OR NOT json_valid(NEW.context_json)
          OR json_type(NEW.context_json)<>'object'
          OR NEW.evaluation_mode NOT IN ('ENCOUNTER','LONGITUDINAL')
          OR (
               NEW.evaluation_mode='LONGITUDINAL'
               AND (NEW.encounter_key IS NOT NULL OR NEW.encounter_event_id IS NOT NULL)
             )
          OR (
               NEW.evaluation_mode='ENCOUNTER'
               AND (
                    NEW.encounter_key IS NULL
                    OR NEW.encounter_event_id IS NULL
                    OR NOT EXISTS (
                        SELECT 1
                        FROM clinical_encounter_events event
                        JOIN clinical_encounters encounter
                          ON encounter.id=event.encounter_id
                        WHERE event.id=NEW.encounter_event_id
                          AND encounter.encounter_key=NEW.encounter_key
                          AND encounter.patient_link_id=NEW.patient_link_id
                          AND event.status IN ('OPEN','FINALIZED')
                    )
               )
             )
        BEGIN
            SELECT RAISE(ABORT, 'invalid clinical engine evaluation context');
        END;
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_engine_runs_current_context "
        "ON clinical_engine_runs(patient_link_id, context_hash, engine_version, started_at DESC)"
    )

    tables = {
        str(row["name"])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('clinical_encounters','clinical_encounter_events')"
        ).fetchall()
    }
    missing_tables = sorted(_REQUIRED_TABLES - tables)
    if missing_tables:
        raise RuntimeError(
            "clinical context storage is incomplete: " + ", ".join(missing_tables)
        )
    run_columns = _columns(db, "clinical_engine_runs")
    missing_columns = sorted(
        {
            "evaluation_mode",
            "context_key",
            "context_json",
            "context_hash",
            "encounter_event_id",
        }
        - run_columns
    )
    if missing_columns:
        raise RuntimeError(
            "clinical engine run context columns are incomplete: "
            + ", ".join(missing_columns)
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
            "clinical context guards are incomplete: "
            + ", ".join(missing_triggers)
        )
    db.commit()
