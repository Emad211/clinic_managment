"""Additive runtime-freshness guards for Clinical Engine v2.

The main schema is intentionally idempotent and existing clinic databases are upgraded
in place. This module owns the safety-critical additions needed to know whether an
audited engine run still represents the current patient record:

* ``patient_links.clinical_data_revision`` is a monotonic per-patient counter.
* database triggers increment it for every patient-owned source consumed by v2.
* shared catalog changes invalidate every affected patient snapshot.

The migration is safe to call repeatedly. Missing guards fail loudly; silently running
without them could make a stale recommendation look current.
"""
from __future__ import annotations

import os
import sqlite3
import threading

from src.adapters.sqlite.core import get_db


_SCHEMA_VERSION = 2
_MIGRATION_LOCK = threading.Lock()
_VERIFIED_DATABASES: set[tuple[str, int]] = set()
_CLINICAL_SOURCE_TABLES = (
    "patient_conditions",
    "patient_medications",
    "allergies",
    "patient_flags",
    "vital_readings",
    "lab_results",
)


def _database_identity(db: sqlite3.Connection) -> str:
    rows = db.execute("PRAGMA database_list").fetchall()
    for row in rows:
        try:
            name, filename = str(row["name"]), str(row["file"] or "")
        except (TypeError, IndexError):
            name, filename = str(row[1]), str(row[2] or "")
        if name != "main":
            continue
        if filename:
            return os.path.normcase(os.path.realpath(filename))
        # Each in-memory connection owns a distinct database and therefore needs
        # its own one-time installation and verification.
        return f":memory:{id(db)}"
    return f":connection:{id(db)}"


def _column_names(db: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in db.execute(f"PRAGMA table_info({table})").fetchall()
    }


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


def _catalog_trigger_sql() -> str:
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
    AFTER UPDATE ON flag_catalog
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
    """


def _expected_trigger_names() -> set[str]:
    names = {
        "trg_clinical_revision_patient_identity",
        "trg_clinical_revision_flag_catalog_insert",
        "trg_clinical_revision_flag_catalog_update",
        "trg_clinical_revision_flag_catalog_delete",
        "trg_clinical_revision_condition_code_update",
    }
    for table in _CLINICAL_SOURCE_TABLES:
        prefix = f"trg_clinical_revision_{table}"
        names.update({f"{prefix}_insert", f"{prefix}_update", f"{prefix}_delete"})
    return names


def ensure_runtime_schema(db: sqlite3.Connection | None = None) -> None:
    """Install and verify the monotonic clinical-data revision contract once per DB."""
    db = db or get_db()
    cache_key = (_database_identity(db), _SCHEMA_VERSION)
    if cache_key in _VERIFIED_DATABASES:
        return

    with _MIGRATION_LOCK:
        if cache_key in _VERIFIED_DATABASES:
            return
        _ensure_column(
            db,
            "patient_links",
            "clinical_data_revision",
            "INTEGER NOT NULL DEFAULT 0",
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
        db.executescript(_catalog_trigger_sql())

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
        db.commit()
        _VERIFIED_DATABASES.add(cache_key)
