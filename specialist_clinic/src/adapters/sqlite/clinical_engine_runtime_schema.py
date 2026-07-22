"""Additive runtime-freshness guards for Clinical Engine v2.

The main schema is intentionally idempotent and existing clinic databases are upgraded
in place.  This module owns the small set of safety-critical additions needed to know
whether an audited engine run still represents the current patient record:

* ``patient_links.clinical_data_revision`` is a monotonic per-patient counter.
* database triggers increment it for every source table consumed by the v2 fact layer.

The migration is safe to call repeatedly.  Missing guards fail loudly; silently running
without them could make a stale recommendation look current.
"""
from __future__ import annotations

import sqlite3

from src.adapters.sqlite.core import get_db


_CLINICAL_SOURCE_TABLES = (
    "patient_conditions",
    "patient_medications",
    "allergies",
    "patient_flags",
    "vital_readings",
    "lab_results",
)


def _column_names(db: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in db.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_column(
    db: sqlite3.Connection, table: str, column: str, declaration: str
) -> None:
    if column in _column_names(db, table):
        return
    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


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


def _expected_trigger_names() -> set[str]:
    names = {"trg_clinical_revision_patient_identity"}
    for table in _CLINICAL_SOURCE_TABLES:
        prefix = f"trg_clinical_revision_{table}"
        names.update({f"{prefix}_insert", f"{prefix}_update", f"{prefix}_delete"})
    return names


def ensure_runtime_schema(db: sqlite3.Connection | None = None) -> None:
    """Install and verify the monotonic clinical-data revision contract."""
    db = db or get_db()
    _ensure_column(
        db,
        "patient_links",
        "clinical_data_revision",
        "INTEGER NOT NULL DEFAULT 0",
    )

    # Demographic fields are part of the canonical fact snapshot.  Updating the
    # revision column itself does not recurse because it is not listed after UPDATE OF.
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
        f"SELECT name FROM sqlite_master WHERE type='trigger' AND name IN ({marks})",
        tuple(sorted(expected)),
    ).fetchall()
    present = {str(row["name"]) for row in rows}
    missing = sorted(expected - present)
    if missing:
        raise RuntimeError(
            "Clinical data revision guards are incomplete: " + ", ".join(missing)
        )
    db.commit()
