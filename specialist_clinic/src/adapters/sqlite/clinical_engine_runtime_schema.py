"""Additive runtime-freshness guards for Clinical Engine v2.

The main schema is intentionally idempotent and existing clinic databases are upgraded
in place. This module owns the safety-critical additions needed to know whether an
audited engine run still represents the current patient record:

* ``patient_links.clinical_data_revision`` is a monotonic per-patient counter.
* database triggers increment it for every patient-owned source consumed by v2.
* shared catalog changes invalidate every affected patient snapshot.
* collection reconciliation events are append-only clinical facts and also invalidate
  prior runs.

The migration is safe to call repeatedly. Missing guards fail loudly; silently running
without them could make a stale recommendation look current.
"""
from __future__ import annotations

import os
import sqlite3
import threading

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.clinical_reconciliation_schema import (
    ensure_clinical_reconciliation_storage,
)
from src.adapters.sqlite.clinical_flag_history_schema import (
    ensure_clinical_flag_history_storage,
)
from src.adapters.sqlite.clinical_context_schema import (
    ensure_clinical_context_storage,
)
from src.adapters.sqlite.clinical_data_conflict_schema import (
    ensure_clinical_data_conflict_storage,
)


_SCHEMA_VERSION = 6
_MIGRATION_LOCK = threading.Lock()
_VERIFIED_DATABASES: set[tuple[str, int]] = set()
_CLINICAL_SOURCE_TABLES = (
    "patient_conditions",
    "patient_medications",
    "allergies",
    "vital_readings",
    "lab_results",
)


def _database_path(db: sqlite3.Connection) -> str | None:
    """Return a stable path for file databases; ``None`` for connection-local DBs."""
    rows = db.execute("PRAGMA database_list").fetchall()
    for row in rows:
        try:
            name, filename = str(row["name"]), str(row["file"] or "")
        except (TypeError, IndexError):
            name, filename = str(row[1]), str(row[2] or "")
        if name != "main":
            continue
        return os.path.normcase(os.path.realpath(filename)) if filename else None
    return None


def _memory_connection_is_ready(db: sqlite3.Connection) -> bool:
    """Use a TEMP marker tied to the exact in-memory connection.

    Python may reuse ``id(connection)`` after close, so object ids are not safe
    process-wide cache keys for ``:memory:`` databases. A TEMP table disappears
    with the connection and cannot produce a false positive on a later database.
    """
    try:
        row = db.execute(
            "SELECT version FROM temp.clinical_runtime_schema_marker LIMIT 1"
        ).fetchone()
        return bool(row and int(row["version"]) == _SCHEMA_VERSION)
    except sqlite3.DatabaseError:
        return False


def _mark_memory_connection_ready(db: sqlite3.Connection) -> None:
    db.execute(
        "CREATE TEMP TABLE IF NOT EXISTS clinical_runtime_schema_marker "
        "(version INTEGER NOT NULL)"
    )
    db.execute("DELETE FROM temp.clinical_runtime_schema_marker")
    db.execute(
        "INSERT INTO temp.clinical_runtime_schema_marker(version) VALUES (?)",
        (_SCHEMA_VERSION,),
    )


def _column_names(db: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in db.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _ensure_column(
    db: sqlite3.Connection, table: str, column: str, declaration: str
) -> None:
    if column in _column_names(db, table):
        return
    try:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
    except sqlite3.OperationalError:
        # Another process may have completed the same additive migration after
        # our first PRAGMA read. Accept only that exact successful outcome.
        if column not in _column_names(db, table):
            raise


def _revision_trigger_sql(table: str) -> str:
    prefix = f"trg_clinical_revision_{table}"
    return f"""
    CREATE TRIGGER IF NOT EXISTS {prefix}_insert
    AFTER INSERT ON {table}
    BEGIN
        UPDATE patient_links
           SET clinical_data_revision = clinical_data_revision + 1
         WHERE id = NEW.patient_link_id;
    END;

    CREATE TRIGGER IF NOT EXISTS {prefix}_update
    AFTER UPDATE ON {table}
    BEGIN
        UPDATE patient_links
           SET clinical_data_revision = clinical_data_revision + 1
         WHERE id = OLD.patient_link_id;
        UPDATE patient_links
           SET clinical_data_revision = clinical_data_revision + 1
         WHERE id = NEW.patient_link_id
           AND NEW.patient_link_id <> OLD.patient_link_id;
    END;

    CREATE TRIGGER IF NOT EXISTS {prefix}_delete
    AFTER DELETE ON {table}
    BEGIN
        UPDATE patient_links
           SET clinical_data_revision = clinical_data_revision + 1
         WHERE id = OLD.patient_link_id;
    END;
    """


def _shared_trigger_sql() -> str:
    return """
    -- The active flag catalog determines which NOT_ASKED facts exist and how a
    -- stored patient flag is typed. Any catalog change therefore invalidates all
    -- patient snapshots, even though no patient-owned row changed.
    CREATE TRIGGER IF NOT EXISTS trg_clinical_revision_flag_catalog_insert
    AFTER INSERT ON flag_catalog
    BEGIN
        UPDATE patient_links
           SET clinical_data_revision = clinical_data_revision + 1;
    END;

    CREATE TRIGGER IF NOT EXISTS trg_clinical_revision_flag_catalog_update
    AFTER UPDATE OF flag_key, flag_type, options_json, definition_hash,
                    definition_version, is_active
    ON flag_catalog
    WHEN COALESCE(OLD.flag_key, '') <> COALESCE(NEW.flag_key, '')
      OR COALESCE(OLD.flag_type, '') <> COALESCE(NEW.flag_type, '')
      OR COALESCE(OLD.options_json, '') <> COALESCE(NEW.options_json, '')
      OR COALESCE(OLD.definition_hash, '') <> COALESCE(NEW.definition_hash, '')
      OR COALESCE(OLD.definition_version, 0) <> COALESCE(NEW.definition_version, 0)
      OR COALESCE(OLD.is_active, 0) <> COALESCE(NEW.is_active, 0)
    BEGIN
        UPDATE patient_links
           SET clinical_data_revision = clinical_data_revision + 1;
    END;

    CREATE TRIGGER IF NOT EXISTS trg_clinical_revision_flag_catalog_delete
    AFTER DELETE ON flag_catalog
    BEGIN
        UPDATE patient_links
           SET clinical_data_revision = clinical_data_revision + 1;
    END;

    -- Condition display metadata is not a fact, but the canonical condition code
    -- is. Changing a code invalidates only patients linked to that condition.
    CREATE TRIGGER IF NOT EXISTS trg_clinical_revision_condition_code_update
    AFTER UPDATE OF code ON conditions
    WHEN COALESCE(OLD.code, '') <> COALESCE(NEW.code, '')
    BEGIN
        UPDATE patient_links
           SET clinical_data_revision = clinical_data_revision + 1
         WHERE id IN (
             SELECT patient_link_id
               FROM patient_conditions
              WHERE condition_id = NEW.id AND is_active = 1
         );
    END;

    -- Clinical flag events are append-only. Every event changes one patient's
    -- effective clinical decision-input snapshot.
    CREATE TRIGGER IF NOT EXISTS trg_clinical_revision_flag_event_insert
    AFTER INSERT ON clinical_flag_events
    BEGIN
        UPDATE patient_links
           SET clinical_data_revision = clinical_data_revision + 1
         WHERE id = NEW.patient_link_id;
    END;

    -- Conflict resolution is a clinical input and invalidates the prior run.
    CREATE TRIGGER IF NOT EXISTS trg_clinical_revision_data_conflict_insert
    AFTER INSERT ON clinical_data_conflict_events
    BEGIN
        UPDATE patient_links
           SET clinical_data_revision = clinical_data_revision + 1
         WHERE id = NEW.patient_link_id;
    END;

    -- Allergy concept semantics affect canonical identity. Be conservative: catalog
    -- semantic changes invalidate all snapshots because previously unmapped exact
    -- aliases may become mappable at the next storage reconciliation.
    CREATE TRIGGER IF NOT EXISTS trg_clinical_revision_allergy_catalog_insert
    AFTER INSERT ON allergy_catalog
    BEGIN
        UPDATE patient_links
           SET clinical_data_revision = clinical_data_revision + 1;
    END;

    CREATE TRIGGER IF NOT EXISTS trg_clinical_revision_allergy_catalog_update
    AFTER UPDATE OF concept_key, aliases_json, definition_hash, is_active
    ON allergy_catalog
    WHEN COALESCE(OLD.concept_key,'')<>COALESCE(NEW.concept_key,'')
      OR COALESCE(OLD.aliases_json,'')<>COALESCE(NEW.aliases_json,'')
      OR COALESCE(OLD.definition_hash,'')<>COALESCE(NEW.definition_hash,'')
      OR COALESCE(OLD.is_active,0)<>COALESCE(NEW.is_active,0)
    BEGIN
        UPDATE patient_links
           SET clinical_data_revision = clinical_data_revision + 1;
    END;

    CREATE TRIGGER IF NOT EXISTS trg_clinical_revision_allergy_catalog_delete
    AFTER DELETE ON allergy_catalog
    BEGIN
        UPDATE patient_links
           SET clinical_data_revision = clinical_data_revision + 1;
    END;

    -- A review event changes verification/absence semantics even when the source
    -- rows themselves are unchanged, so every appended reconciliation event
    -- invalidates the previous clinical run for that patient.
    CREATE TRIGGER IF NOT EXISTS trg_clinical_revision_reconciliation_insert
    AFTER INSERT ON clinical_reconciliation_events
    BEGIN
        UPDATE patient_links
           SET clinical_data_revision = clinical_data_revision + 1
         WHERE id = NEW.patient_link_id;
    END;
    """


def _expected_trigger_names() -> set[str]:
    names = {
        "trg_clinical_revision_patient_identity",
        "trg_clinical_revision_flag_catalog_insert",
        "trg_clinical_revision_flag_catalog_update",
        "trg_clinical_revision_flag_catalog_delete",
        "trg_clinical_revision_condition_code_update",
        "trg_clinical_revision_reconciliation_insert",
        "trg_clinical_revision_flag_event_insert",
        "trg_clinical_revision_data_conflict_insert",
        "trg_clinical_revision_allergy_catalog_insert",
        "trg_clinical_revision_allergy_catalog_update",
        "trg_clinical_revision_allergy_catalog_delete",
    }
    for table in _CLINICAL_SOURCE_TABLES:
        prefix = f"trg_clinical_revision_{table}"
        names.update({f"{prefix}_insert", f"{prefix}_update", f"{prefix}_delete"})
    return names


def ensure_runtime_schema(db: sqlite3.Connection | None = None) -> None:
    """Install and verify the monotonic clinical-data revision contract once per DB."""
    db = db or get_db()
    database_path = _database_path(db)
    cache_key = (database_path, _SCHEMA_VERSION) if database_path else None
    if cache_key is not None and cache_key in _VERIFIED_DATABASES:
        return
    if cache_key is None and _memory_connection_is_ready(db):
        return

    with _MIGRATION_LOCK:
        if cache_key is not None and cache_key in _VERIFIED_DATABASES:
            return
        if cache_key is None and _memory_connection_is_ready(db):
            return

        # Remove installed revision triggers whose body targets the retired
        # mutable patient_flags table before that table is migrated/dropped.
        db.executescript(
            """
            DROP TRIGGER IF EXISTS trg_clinical_revision_patient_flags_insert;
            DROP TRIGGER IF EXISTS trg_clinical_revision_patient_flags_update;
            DROP TRIGGER IF EXISTS trg_clinical_revision_patient_flags_delete;
            DROP TRIGGER IF EXISTS trg_clinical_revision_flag_catalog_insert;
            DROP TRIGGER IF EXISTS trg_clinical_revision_flag_catalog_update;
            DROP TRIGGER IF EXISTS trg_clinical_revision_flag_catalog_delete;
            DROP TRIGGER IF EXISTS trg_clinical_revision_flag_event_insert;
            """
        )
        ensure_clinical_flag_history_storage(db)
        _ensure_column(
            db,
            "patient_links",
            "clinical_data_revision",
            "INTEGER NOT NULL DEFAULT 0",
        )
        ensure_clinical_reconciliation_storage(db)
        ensure_clinical_data_conflict_storage(db)
        context_ready = ensure_clinical_context_storage(db)
        if _table_exists(db, "followup_tasks"):
            _ensure_column(
                db,
                "followup_tasks",
                "clinical_context_hash",
                "TEXT",
            )
            db.execute(
                "DROP INDEX IF EXISTS idx_followup_open_clinical_semantic"
            )
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "idx_followup_open_clinical_semantic_context "
                "ON followup_tasks(patient_link_id, clinical_semantic_key, "
                "clinical_context_hash) "
                "WHERE source_engine='clinical_v2' AND status='open' "
                "AND clinical_semantic_key IS NOT NULL "
                "AND clinical_context_hash IS NOT NULL"
            )

        # Demographic fields are part of the canonical fact snapshot. Updating
        # the revision itself does not recurse because it is not in UPDATE OF.
        db.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS trg_clinical_revision_patient_identity
            AFTER UPDATE OF birthdate, gender ON patient_links
            WHEN COALESCE(OLD.birthdate, '') <> COALESCE(NEW.birthdate, '')
              OR COALESCE(OLD.gender, '') <> COALESCE(NEW.gender, '')
            BEGIN
                UPDATE patient_links
                   SET clinical_data_revision = clinical_data_revision + 1
                 WHERE id = NEW.id;
            END;
            """
        )
        for table in _CLINICAL_SOURCE_TABLES:
            db.executescript(_revision_trigger_sql(table))
        db.executescript(
            """
            DROP TRIGGER IF EXISTS trg_clinical_revision_flag_catalog_insert;
            DROP TRIGGER IF EXISTS trg_clinical_revision_flag_catalog_update;
            DROP TRIGGER IF EXISTS trg_clinical_revision_flag_catalog_delete;
            DROP TRIGGER IF EXISTS trg_clinical_revision_flag_event_insert;
            DROP TRIGGER IF EXISTS trg_clinical_revision_condition_code_update;
            DROP TRIGGER IF EXISTS trg_clinical_revision_reconciliation_insert;
            DROP TRIGGER IF EXISTS trg_clinical_revision_data_conflict_insert;
            DROP TRIGGER IF EXISTS trg_clinical_revision_allergy_catalog_insert;
            DROP TRIGGER IF EXISTS trg_clinical_revision_allergy_catalog_update;
            DROP TRIGGER IF EXISTS trg_clinical_revision_allergy_catalog_delete;
            """
        )
        db.executescript(_shared_trigger_sql())

        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_patient_links_clinical_revision "
            "ON patient_links(id, clinical_data_revision)"
        )

        columns = _column_names(db, "patient_links")
        if "clinical_data_revision" not in columns:
            raise RuntimeError("clinical_data_revision migration was not installed")

        expected = _expected_trigger_names()
        marks = ",".join("?" for _ in expected)
        rows = db.execute(
            f"SELECT name FROM sqlite_master WHERE type='trigger' "
            f"AND name IN ({marks})",
            tuple(sorted(expected)),
        ).fetchall()
        present = {str(row["name"]) for row in rows}
        missing = sorted(expected - present)
        if missing:
            raise RuntimeError(
                "Clinical data revision guards are incomplete: "
                + ", ".join(missing)
            )

        if cache_key is None and context_ready:
            _mark_memory_connection_ready(db)
        db.commit()
        if cache_key is not None and context_ready:
            _VERIFIED_DATABASES.add(cache_key)
