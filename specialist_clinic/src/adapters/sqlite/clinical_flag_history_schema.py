"""Canonical append-only storage and migration for longitudinal clinical flags."""
from __future__ import annotations

from contextlib import contextmanager
import sqlite3
from typing import Any
from uuid import uuid4

from src.common.utils import parse_datetime
from src.domain.clinical_engine.flag_history import (
    ClinicalFlagState,
    ClinicalFlagValueError,
    canonical_options_json,
    encode_flag_value,
    flag_definition_hash,
    normalize_flag_type,
)


_REQUIRED_TRIGGERS = frozenset(
    {
        "trg_flag_events_no_update",
        "trg_flag_events_no_delete",
        "trg_flag_events_catalog_match",
        "trg_flag_events_value_contract",
        "trg_flag_events_first_event",
        "trg_flag_events_subsequent_event",
        "trg_flag_events_supersession_scope",
        "trg_flag_events_supersession_current",
        "trg_flag_events_recorded_order",
        "trg_flag_catalog_event_key_immutable",
        "trg_flag_catalog_definition_insert_guard",
        "trg_flag_catalog_definition_update_guard",
    }
)


class ClinicalFlagHistoryMigrationError(RuntimeError):
    """Copied flag data cannot be migrated without guessing clinical meaning."""


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    return (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


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
    if column not in _columns(db, table):
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


@contextmanager
def _atomic(db: sqlite3.Connection):
    if db.in_transaction:
        name = "clinical_flag_history_migration"
        db.execute(f"SAVEPOINT {name}")
        try:
            yield
            db.execute(f"RELEASE SAVEPOINT {name}")
        except Exception:
            db.execute(f"ROLLBACK TO SAVEPOINT {name}")
            db.execute(f"RELEASE SAVEPOINT {name}")
            raise
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.commit()
    except Exception:
        db.rollback()
        raise


def _execute_statements(db: sqlite3.Connection, script: str) -> None:
    """Execute a SQL script statement-by-statement without implicit commits."""
    buffer = ""
    for line in script.splitlines():
        buffer += line + "\n"
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            buffer = ""
            if statement:
                db.execute(statement)
    if buffer.strip():
        raise RuntimeError("incomplete clinical flag migration SQL")


def _create_event_table(db: sqlite3.Connection) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS clinical_flag_events (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               patient_link_id INTEGER NOT NULL,
               flag_key TEXT NOT NULL CHECK (length(trim(flag_key)) > 0),
               status TEXT NOT NULL
                 CHECK (status IN ('PRESENT','UNKNOWN','NOT_ASKED')),
               value_json TEXT,
               flag_type TEXT NOT NULL
                 CHECK (flag_type IN ('bool','enum','date','text')),
               definition_hash TEXT NOT NULL CHECK (length(definition_hash)=64),
               verification TEXT NOT NULL DEFAULT 'CONFIRMED'
                 CHECK (verification IN (
                   'CONFIRMED','PROVISIONAL','UNVERIFIED','REFUTED'
                 )),
               source TEXT NOT NULL DEFAULT 'clinician'
                 CHECK (source IN (
                   'clinician','patient','caregiver','imported','system'
                 )),
               source_record_id TEXT,
               actor_user_id INTEGER,
               actor_username TEXT NOT NULL
                 CHECK (length(trim(actor_username)) > 0),
               effective_at TEXT NOT NULL
                 CHECK (datetime(effective_at) IS NOT NULL),
               recorded_at TEXT NOT NULL
                 CHECK (datetime(recorded_at) IS NOT NULL),
               batch_id TEXT NOT NULL CHECK (length(trim(batch_id)) > 0),
               supersedes_event_id INTEGER,
               note TEXT,
               CHECK (datetime(effective_at) <= datetime(recorded_at)),
               CHECK (
                 (status='PRESENT' AND value_json IS NOT NULL
                   AND json_valid(value_json))
                 OR (status<>'PRESENT' AND value_json IS NULL)
               ),
               FOREIGN KEY (patient_link_id) REFERENCES patient_links(id),
               FOREIGN KEY (flag_key) REFERENCES flag_catalog(flag_key),
               FOREIGN KEY (actor_user_id) REFERENCES users(id),
               FOREIGN KEY (supersedes_event_id)
                 REFERENCES clinical_flag_events(id)
           )"""
    )
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_clinical_flag_events_projection
           ON clinical_flag_events(
             patient_link_id, flag_key, recorded_at DESC, id DESC
           )"""
    )
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_clinical_flag_events_effective
           ON clinical_flag_events(
             patient_link_id, effective_at, recorded_at, id
           )"""
    )
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_clinical_flag_events_batch
           ON clinical_flag_events(patient_link_id, batch_id, id)"""
    )
    db.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_clinical_flag_events_one_per_batch
           ON clinical_flag_events(patient_link_id, batch_id, flag_key)"""
    )
    db.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_clinical_flag_events_one_child
           ON clinical_flag_events(supersedes_event_id)
           WHERE supersedes_event_id IS NOT NULL"""
    )
    required_columns = {
        "id",
        "patient_link_id",
        "flag_key",
        "status",
        "value_json",
        "flag_type",
        "definition_hash",
        "verification",
        "source",
        "source_record_id",
        "actor_user_id",
        "actor_username",
        "effective_at",
        "recorded_at",
        "batch_id",
        "supersedes_event_id",
        "note",
    }
    missing = sorted(required_columns - _columns(db, "clinical_flag_events"))
    if missing:
        raise ClinicalFlagHistoryMigrationError(
            "clinical_flag_events has an incompatible partial schema: "
            + ", ".join(missing)
        )


def _validate_existing_event_graph(db: sqlite3.Connection) -> None:
    invalid_roots = db.execute(
        """SELECT patient_link_id, flag_key,
                  SUM(CASE WHEN supersedes_event_id IS NULL THEN 1 ELSE 0 END)
                    AS roots
             FROM clinical_flag_events
            GROUP BY patient_link_id, flag_key
           HAVING roots<>1
            LIMIT 1"""
    ).fetchone()
    if invalid_roots:
        raise ClinicalFlagHistoryMigrationError(
            "clinical flag history must have exactly one root: "
            f"patient={invalid_roots['patient_link_id']} "
            f"flag={invalid_roots['flag_key']!r} "
            f"roots={invalid_roots['roots']}"
        )
    multiple_heads = db.execute(
        """SELECT event.patient_link_id, event.flag_key, COUNT(*) AS count
             FROM clinical_flag_events event
            WHERE NOT EXISTS (
              SELECT 1 FROM clinical_flag_events child
               WHERE child.supersedes_event_id=event.id
            )
            GROUP BY event.patient_link_id, event.flag_key
           HAVING COUNT(*)<>1
            LIMIT 1"""
    ).fetchone()
    if multiple_heads:
        raise ClinicalFlagHistoryMigrationError(
            "clinical flag history is not a single linear chain: "
            f"patient={multiple_heads['patient_link_id']} "
            f"flag={multiple_heads['flag_key']!r} "
            f"heads={multiple_heads['count']}"
        )
    invalid_scope = db.execute(
        """SELECT child.id
             FROM clinical_flag_events child
             JOIN clinical_flag_events parent
               ON parent.id=child.supersedes_event_id
            WHERE child.patient_link_id<>parent.patient_link_id
               OR child.flag_key<>parent.flag_key
            LIMIT 1"""
    ).fetchone()
    if invalid_scope:
        raise ClinicalFlagHistoryMigrationError(
            "clinical flag supersession crosses patient or flag scope: "
            f"event={invalid_scope['id']}"
        )
    reversed_recording = db.execute(
        """SELECT child.id
             FROM clinical_flag_events child
             JOIN clinical_flag_events parent
               ON parent.id=child.supersedes_event_id
            WHERE datetime(child.recorded_at)<datetime(parent.recorded_at)
            LIMIT 1"""
    ).fetchone()
    if reversed_recording:
        raise ClinicalFlagHistoryMigrationError(
            "clinical flag recorded time moves backwards: "
            f"event={reversed_recording['id']}"
        )


def _drop_guards(db: sqlite3.Connection) -> None:
    for name in _REQUIRED_TRIGGERS:
        db.execute(f"DROP TRIGGER IF EXISTS {name}")


def _install_guards(db: sqlite3.Connection) -> None:
    _drop_guards(db)
    _execute_statements(
        db,
        """
        CREATE TRIGGER trg_flag_events_no_update
        BEFORE UPDATE ON clinical_flag_events
        BEGIN
          SELECT RAISE(ABORT, 'clinical flag events are append-only');
        END;

        CREATE TRIGGER trg_flag_events_no_delete
        BEFORE DELETE ON clinical_flag_events
        BEGIN
          SELECT RAISE(ABORT, 'clinical flag events are append-only');
        END;

        CREATE TRIGGER trg_flag_events_catalog_match
        BEFORE INSERT ON clinical_flag_events
        WHEN NOT EXISTS (
          SELECT 1 FROM flag_catalog catalog
           WHERE catalog.flag_key=NEW.flag_key
             AND catalog.is_active=1
             AND catalog.flag_type=NEW.flag_type
             AND catalog.definition_hash=NEW.definition_hash
        )
        BEGIN
          SELECT RAISE(ABORT, 'clinical flag event does not match active catalog definition');
        END;

        CREATE TRIGGER trg_flag_events_value_contract
        BEFORE INSERT ON clinical_flag_events
        WHEN NEW.status='PRESENT' AND NOT (
          (NEW.flag_type='bool' AND json_type(NEW.value_json) IN ('true','false'))
          OR
          (NEW.flag_type='enum'
            AND json_type(NEW.value_json)='text'
            AND EXISTS (
              SELECT 1
                FROM flag_catalog catalog, json_each(catalog.options_json) option
               WHERE catalog.flag_key=NEW.flag_key
                 AND json_extract(option.value, '$.value') = json_extract(NEW.value_json, '$')
            ))
          OR
          (NEW.flag_type='date'
            AND json_type(NEW.value_json)='text'
            AND length(json_extract(NEW.value_json, '$'))=10
            AND json_extract(NEW.value_json, '$') GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            AND date(json_extract(NEW.value_json, '$')) = json_extract(NEW.value_json, '$'))
          OR
          (NEW.flag_type='text'
            AND json_type(NEW.value_json)='text'
            AND length(trim(json_extract(NEW.value_json, '$'))) BETWEEN 1 AND 2000)
        )
        BEGIN
          SELECT RAISE(ABORT, 'clinical flag event value violates catalog type');
        END;

        CREATE TRIGGER trg_flag_events_first_event
        BEFORE INSERT ON clinical_flag_events
        WHEN NEW.supersedes_event_id IS NULL
         AND EXISTS (
           SELECT 1 FROM clinical_flag_events prior
            WHERE prior.patient_link_id=NEW.patient_link_id
              AND prior.flag_key=NEW.flag_key
         )
        BEGIN
          SELECT RAISE(ABORT, 'subsequent clinical flag event must supersede current head');
        END;

        CREATE TRIGGER trg_flag_events_subsequent_event
        BEFORE INSERT ON clinical_flag_events
        WHEN NEW.supersedes_event_id IS NOT NULL
         AND NOT EXISTS (
           SELECT 1 FROM clinical_flag_events prior
            WHERE prior.id=NEW.supersedes_event_id
         )
        BEGIN
          SELECT RAISE(ABORT, 'superseded clinical flag event does not exist');
        END;

        CREATE TRIGGER trg_flag_events_supersession_scope
        BEFORE INSERT ON clinical_flag_events
        WHEN NEW.supersedes_event_id IS NOT NULL
         AND NOT EXISTS (
           SELECT 1 FROM clinical_flag_events prior
            WHERE prior.id=NEW.supersedes_event_id
              AND prior.patient_link_id=NEW.patient_link_id
              AND prior.flag_key=NEW.flag_key
         )
        BEGIN
          SELECT RAISE(ABORT, 'clinical flag supersession must stay in patient and flag scope');
        END;

        CREATE TRIGGER trg_flag_events_supersession_current
        BEFORE INSERT ON clinical_flag_events
        WHEN NEW.supersedes_event_id IS NOT NULL
         AND NEW.supersedes_event_id <> (
           SELECT prior.id
             FROM clinical_flag_events prior
            WHERE prior.patient_link_id=NEW.patient_link_id
              AND prior.flag_key=NEW.flag_key
              AND NOT EXISTS (
                SELECT 1 FROM clinical_flag_events child
                 WHERE child.supersedes_event_id=prior.id
              )
            ORDER BY prior.recorded_at DESC, prior.id DESC
            LIMIT 1
         )
        BEGIN
          SELECT RAISE(ABORT, 'clinical flag event must supersede current head');
        END;

        CREATE TRIGGER trg_flag_events_recorded_order
        BEFORE INSERT ON clinical_flag_events
        WHEN NEW.supersedes_event_id IS NOT NULL
         AND datetime(NEW.recorded_at) < datetime((
           SELECT recorded_at FROM clinical_flag_events
            WHERE id=NEW.supersedes_event_id
         ))
        BEGIN
          SELECT RAISE(ABORT, 'clinical flag recorded_at cannot move backwards');
        END;

        CREATE TRIGGER trg_flag_catalog_event_key_immutable
        BEFORE UPDATE OF flag_key ON flag_catalog
        WHEN NEW.flag_key<>OLD.flag_key
         AND EXISTS (
           SELECT 1 FROM clinical_flag_events event
            WHERE event.flag_key=OLD.flag_key
         )
        BEGIN
          SELECT RAISE(ABORT, 'flag_key with audit events is immutable');
        END;

        CREATE TRIGGER trg_flag_catalog_definition_insert_guard
        BEFORE INSERT ON flag_catalog
        WHEN NEW.flag_type NOT IN ('bool','enum','date','text')
          OR NEW.options_json IS NULL
          OR NOT json_valid(NEW.options_json)
          OR json_type(NEW.options_json)<>'array'
          OR NEW.definition_hash IS NULL
          OR length(NEW.definition_hash)<>64
          OR NEW.definition_version IS NULL
          OR NEW.definition_version < 1
          OR (NEW.flag_type='enum' AND json_array_length(NEW.options_json)=0)
          OR (NEW.flag_type='enum' AND EXISTS (
            SELECT 1 FROM json_each(NEW.options_json) option
             WHERE json_type(option.value)<>'object'
                OR json_type(option.value, '$.value')<>'text'
                OR length(trim(json_extract(option.value, '$.value')))=0
                OR json_type(option.value, '$.label')<>'text'
                OR length(trim(json_extract(option.value, '$.label')))=0
          ))
          OR (NEW.flag_type='enum' AND EXISTS (
            SELECT 1
              FROM json_each(NEW.options_json) option
             GROUP BY json_extract(option.value, '$.value')
            HAVING COUNT(*)>1
          ))
          OR (NEW.flag_type<>'enum' AND NEW.options_json<>'[]')
        BEGIN
          SELECT RAISE(ABORT, 'clinical flag catalog definition is incomplete');
        END;

        CREATE TRIGGER trg_flag_catalog_definition_update_guard
        BEFORE UPDATE OF flag_key, flag_type, options_json, definition_hash,
                         definition_version, is_active
        ON flag_catalog
        WHEN NEW.flag_type NOT IN ('bool','enum','date','text')
          OR NEW.options_json IS NULL
          OR NOT json_valid(NEW.options_json)
          OR json_type(NEW.options_json)<>'array'
          OR NEW.definition_hash IS NULL
          OR length(NEW.definition_hash)<>64
          OR NEW.definition_version IS NULL
          OR NEW.definition_version < 1
          OR (NEW.flag_type='enum' AND json_array_length(NEW.options_json)=0)
          OR (NEW.flag_type='enum' AND EXISTS (
            SELECT 1 FROM json_each(NEW.options_json) option
             WHERE json_type(option.value)<>'object'
                OR json_type(option.value, '$.value')<>'text'
                OR length(trim(json_extract(option.value, '$.value')))=0
                OR json_type(option.value, '$.label')<>'text'
                OR length(trim(json_extract(option.value, '$.label')))=0
          ))
          OR (NEW.flag_type='enum' AND EXISTS (
            SELECT 1
              FROM json_each(NEW.options_json) option
             GROUP BY json_extract(option.value, '$.value')
            HAVING COUNT(*)>1
          ))
          OR (NEW.flag_type<>'enum' AND NEW.options_json<>'[]')
          OR (
            (COALESCE(NEW.flag_key,'')<>COALESCE(OLD.flag_key,'')
             OR COALESCE(NEW.flag_type,'')<>COALESCE(OLD.flag_type,'')
             OR COALESCE(NEW.options_json,'')<>COALESCE(OLD.options_json,'')
             OR COALESCE(NEW.is_active,0)<>COALESCE(OLD.is_active,0))
            AND (
              NEW.definition_version<>OLD.definition_version+1
              OR COALESCE(NEW.definition_hash,'')=COALESCE(OLD.definition_hash,'')
            )
          )
          OR (
            COALESCE(NEW.flag_key,'')=COALESCE(OLD.flag_key,'')
            AND COALESCE(NEW.flag_type,'')=COALESCE(OLD.flag_type,'')
            AND COALESCE(NEW.options_json,'')=COALESCE(OLD.options_json,'')
            AND COALESCE(NEW.is_active,0)=COALESCE(OLD.is_active,0)
            AND (
              NEW.definition_version<>OLD.definition_version
              OR COALESCE(NEW.definition_hash,'')<>COALESCE(OLD.definition_hash,'')
            )
          )
        BEGIN
          SELECT RAISE(ABORT, 'semantic flag catalog change requires a new definition hash');
        END;
        """
    )


def _canonicalize_catalog(db: sqlite3.Connection) -> None:
    rows = db.execute("SELECT * FROM flag_catalog ORDER BY id").fetchall()
    for row in rows:
        try:
            flag_type = normalize_flag_type(row["flag_type"])
            keys = set(row.keys())
            source_options = (
                row["options_json"]
                if "options_json" in keys and row["options_json"]
                else (row["options"] if "options" in keys else None)
            )
            options_json = canonical_options_json(
                source_options,
                flag_type=flag_type,
            )
            definition_version = int(row["definition_version"] or 1)
            definition_hash = flag_definition_hash(
                row["flag_key"],
                flag_type,
                options_json,
                row["is_active"],
                definition_version,
            )
        except ClinicalFlagValueError as exc:
            raise ClinicalFlagHistoryMigrationError(
                f"invalid flag catalog row {row['flag_key']!r}: {exc}"
            ) from exc
        db.execute(
            """UPDATE flag_catalog
                  SET flag_type=?, options_json=?, definition_hash=?,
                      definition_version=?
                WHERE id=?""",
            (
                flag_type,
                options_json,
                definition_hash,
                definition_version,
                row["id"],
            ),
        )


def _legacy_event_payload(row: sqlite3.Row) -> tuple[str, str | None, str]:
    raw = row["value"]
    if raw is None or str(raw).strip() == "":
        return ClinicalFlagState.UNKNOWN.value, None, "UNVERIFIED"
    try:
        value_json = encode_flag_value(
            ClinicalFlagState.PRESENT,
            raw,
            flag_type=row["flag_type"],
            options_json=row["options_json"],
        )
    except ClinicalFlagValueError as exc:
        raise ClinicalFlagHistoryMigrationError(
            f"patient flag {row['id']} cannot be migrated safely: {exc}"
        ) from exc
    return ClinicalFlagState.PRESENT.value, value_json, "PROVISIONAL"


def _migrate_legacy_rows(db: sqlite3.Connection) -> int:
    if not _table_exists(db, "patient_flags"):
        return 0
    orphan = db.execute(
        """SELECT patient_flag.id, patient_flag.flag_key
             FROM patient_flags patient_flag
             LEFT JOIN flag_catalog catalog
               ON catalog.flag_key=patient_flag.flag_key
            WHERE catalog.flag_key IS NULL
            ORDER BY patient_flag.id LIMIT 1"""
    ).fetchone()
    if orphan:
        raise ClinicalFlagHistoryMigrationError(
            "patient flag cannot be migrated without a catalog definition: "
            f"id={orphan['id']} key={orphan['flag_key']!r}"
        )
    rows = db.execute(
        """SELECT patient_flag.*, catalog.flag_type, catalog.options_json,
                  catalog.definition_hash
             FROM patient_flags patient_flag
             JOIN flag_catalog catalog ON catalog.flag_key=patient_flag.flag_key
            ORDER BY patient_flag.patient_link_id, patient_flag.id"""
    ).fetchall()
    migrated = 0
    touched_patients: set[int] = set()
    for row in rows:
        existing = db.execute(
            """SELECT id FROM clinical_flag_events
                WHERE source='imported' AND source_record_id=?
                ORDER BY id LIMIT 1""",
            (f"patient_flags:{row['id']}",),
        ).fetchone()
        if existing:
            continue
        parsed = parse_datetime(row["updated_at"])
        if parsed is None:
            raise ClinicalFlagHistoryMigrationError(
                f"patient flag {row['id']} has an invalid updated_at"
            )
        timestamp = parsed.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
        status, value_json, verification = _legacy_event_payload(row)
        db.execute(
            """INSERT INTO clinical_flag_events
               (patient_link_id, flag_key, status, value_json, flag_type,
                definition_hash, verification, source, source_record_id,
                actor_username, effective_at, recorded_at, batch_id, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'imported', ?, ?, ?, ?, ?, ?)""",
            (
                row["patient_link_id"],
                row["flag_key"],
                status,
                value_json,
                row["flag_type"],
                row["definition_hash"],
                verification,
                f"patient_flags:{row['id']}",
                str(row["recorded_by"] or "legacy-flag-migration").strip()
                or "legacy-flag-migration",
                timestamp,
                timestamp,
                f"legacy-flag-migration:{row['patient_link_id']}:{uuid4()}",
                "Migrated from retired mutable patient_flags storage.",
            ),
        )
        migrated += 1
        touched_patients.add(int(row["patient_link_id"]))

    for row in rows:
        found = db.execute(
            """SELECT 1 FROM clinical_flag_events
                WHERE source='imported' AND source_record_id=?""",
            (f"patient_flags:{row['id']}",),
        ).fetchone()
        if not found:
            raise ClinicalFlagHistoryMigrationError(
                f"patient flag {row['id']} was not represented by an event"
            )
    db.execute("DROP TABLE patient_flags")
    if touched_patients and "clinical_data_revision" in _columns(db, "patient_links"):
        marks = ",".join("?" for _ in touched_patients)
        db.execute(
            f"""UPDATE patient_links
                   SET clinical_data_revision=clinical_data_revision+1
                 WHERE id IN ({marks})""",
            tuple(sorted(touched_patients)),
        )
    return migrated


def ensure_clinical_flag_history_storage(
    db: sqlite3.Connection,
) -> dict[str, Any]:
    """Install canonical flag history and migrate the mutable legacy table."""
    with _atomic(db):
        if not _table_exists(db, "flag_catalog"):
            raise ClinicalFlagHistoryMigrationError("flag_catalog is missing")
        _ensure_column(db, "flag_catalog", "record_section", "TEXT")
        _ensure_column(db, "flag_catalog", "options", "TEXT")
        _ensure_column(db, "flag_catalog", "options_json", "TEXT")
        _ensure_column(db, "flag_catalog", "definition_hash", "TEXT")
        _ensure_column(
            db,
            "flag_catalog",
            "definition_version",
            "INTEGER NOT NULL DEFAULT 1",
        )
        duplicate = db.execute(
            """SELECT flag_key, COUNT(*) AS count FROM flag_catalog
                GROUP BY flag_key HAVING COUNT(*)>1 LIMIT 1"""
        ).fetchone()
        if duplicate:
            raise ClinicalFlagHistoryMigrationError(
                f"duplicate flag catalog key: {duplicate['flag_key']}"
            )
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_flag_catalog_key "
            "ON flag_catalog(flag_key)"
        )
        # Old guards can reject the backfill because their installed body may not
        # understand the new semantic columns yet.
        _drop_guards(db)
        _canonicalize_catalog(db)
        _create_event_table(db)
        migrated = _migrate_legacy_rows(db)
        _validate_existing_event_graph(db)
        _install_guards(db)

        present = {
            str(row["name"])
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        missing = sorted(_REQUIRED_TRIGGERS - present)
        if missing:
            raise RuntimeError(
                "clinical flag audit guards are incomplete: " + ", ".join(missing)
            )
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ClinicalFlagHistoryMigrationError(
                "clinical flag history migration left foreign-key violations"
            )
    return {"migrated": migrated, "legacy_table_removed": not _table_exists(db, "patient_flags")}
