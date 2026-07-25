"""Safety-critical additive storage for clinical collection reconciliation."""
from __future__ import annotations

import sqlite3


_TABLE = "clinical_reconciliation_events"
_REQUIRED_TRIGGERS = {
    "trg_reconciliation_no_update",
    "trg_reconciliation_no_delete",
    "trg_reconciliation_supersedes_same_scope",
    "trg_medication_catalog_validate_insert",
    "trg_medication_catalog_validate_update",
    "trg_medication_catalog_resolve_insert",
    "trg_medication_catalog_resolve_update",
}


def _column_names(db: sqlite3.Connection, table: str) -> set[str]:
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
    if column in _column_names(db, table):
        return
    try:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
    except sqlite3.OperationalError:
        # Accept only a concurrent successful installation of this exact column.
        if column not in _column_names(db, table):
            raise


def ensure_clinical_reconciliation_storage(db: sqlite3.Connection) -> None:
    """Install effective intervals and the append-only review event ledger.

    Missing reconciliation storage changes clinical meaning (empty vs explicitly
    absent), so unlike optional catalog seeds this migration must fail startup loudly.
    """
    _ensure_column(db, "patient_conditions", "resolved_at", "TEXT")
    _ensure_column(db, "patient_medications", "end_date", "TEXT")
    _ensure_column(db, "patient_medications", "drug_class", "TEXT")
    _ensure_column(db, "patient_medications", "drug_catalog_id", "INTEGER")
    _ensure_column(
        db,
        "allergies",
        "is_active",
        "INTEGER NOT NULL DEFAULT 1",
    )
    _ensure_column(db, "allergies", "resolved_at", "TEXT")

    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS clinical_reconciliation_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_link_id INTEGER NOT NULL,
            collection_key TEXT NOT NULL
                CHECK (collection_key IN ('conditions','medications','allergies')),
            completeness TEXT NOT NULL
                CHECK (completeness IN ('complete','partial')),
            item_count INTEGER NOT NULL CHECK (item_count >= 0),
            content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
            source TEXT NOT NULL DEFAULT 'clinician'
                CHECK (source IN ('clinician','patient','caregiver','imported','system')),
            patient_confirmed INTEGER NOT NULL DEFAULT 0
                CHECK (patient_confirmed IN (0,1)),
            actor_user_id INTEGER,
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username)) > 0),
            reconciled_at TEXT NOT NULL,
            note TEXT,
            supersedes_event_id INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','+3 hours','+30 minutes')),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(actor_user_id) REFERENCES users(id),
            FOREIGN KEY(supersedes_event_id) REFERENCES clinical_reconciliation_events(id)
        );

        CREATE INDEX IF NOT EXISTS idx_reconciliation_patient_collection
        ON clinical_reconciliation_events(
            patient_link_id, collection_key, reconciled_at DESC, id DESC
        );

        CREATE INDEX IF NOT EXISTS idx_patient_medications_catalog
        ON patient_medications(patient_link_id, drug_catalog_id, is_active);

        CREATE TRIGGER IF NOT EXISTS trg_reconciliation_no_update
        BEFORE UPDATE ON clinical_reconciliation_events
        BEGIN
            SELECT RAISE(ABORT, 'clinical reconciliation events are append-only');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_reconciliation_no_delete
        BEFORE DELETE ON clinical_reconciliation_events
        BEGIN
            SELECT RAISE(ABORT, 'clinical reconciliation events are append-only');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_reconciliation_supersedes_same_scope
        BEFORE INSERT ON clinical_reconciliation_events
        WHEN NEW.supersedes_event_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1 FROM clinical_reconciliation_events prior
             WHERE prior.id=NEW.supersedes_event_id
               AND prior.patient_link_id=NEW.patient_link_id
               AND prior.collection_key=NEW.collection_key
         )
        BEGIN
            SELECT RAISE(ABORT, 'reconciliation supersession must stay in patient collection');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_medication_catalog_validate_insert
        BEFORE INSERT ON patient_medications
        WHEN NEW.drug_catalog_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1 FROM drug_catalog catalog
             WHERE catalog.id=NEW.drug_catalog_id AND catalog.is_active=1
         )
        BEGIN
            SELECT RAISE(ABORT, 'medication concept must reference an active drug catalog row');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_medication_catalog_validate_update
        BEFORE UPDATE OF drug_catalog_id ON patient_medications
        WHEN NEW.drug_catalog_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1 FROM drug_catalog catalog
             WHERE catalog.id=NEW.drug_catalog_id AND catalog.is_active=1
         )
        BEGIN
            SELECT RAISE(ABORT, 'medication concept must reference an active drug catalog row');
        END;

        -- Existing forms already submit the exact catalog name and class. Resolve
        -- that pair only when it identifies one active concept unambiguously.
        CREATE TRIGGER IF NOT EXISTS trg_medication_catalog_resolve_insert
        AFTER INSERT ON patient_medications
        WHEN NEW.drug_catalog_id IS NULL
         AND NEW.drug_class IS NOT NULL
         AND (
             SELECT COUNT(*) FROM drug_catalog catalog
             WHERE catalog.is_active=1
               AND lower(trim(catalog.generic_fa))=lower(trim(NEW.drug_name))
               AND COALESCE(catalog.drug_class_key,'')=COALESCE(NEW.drug_class,'')
         )=1
        BEGIN
            UPDATE patient_medications
               SET drug_catalog_id=(
                   SELECT catalog.id FROM drug_catalog catalog
                   WHERE catalog.is_active=1
                     AND lower(trim(catalog.generic_fa))=lower(trim(NEW.drug_name))
                     AND COALESCE(catalog.drug_class_key,'')=COALESCE(NEW.drug_class,'')
                   LIMIT 1
               )
             WHERE id=NEW.id;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_medication_catalog_resolve_update
        AFTER UPDATE OF drug_name, drug_class ON patient_medications
        WHEN NEW.drug_catalog_id IS NULL
         AND NEW.drug_class IS NOT NULL
         AND (
             SELECT COUNT(*) FROM drug_catalog catalog
             WHERE catalog.is_active=1
               AND lower(trim(catalog.generic_fa))=lower(trim(NEW.drug_name))
               AND COALESCE(catalog.drug_class_key,'')=COALESCE(NEW.drug_class,'')
         )=1
        BEGIN
            UPDATE patient_medications
               SET drug_catalog_id=(
                   SELECT catalog.id FROM drug_catalog catalog
                   WHERE catalog.is_active=1
                     AND lower(trim(catalog.generic_fa))=lower(trim(NEW.drug_name))
                     AND COALESCE(catalog.drug_class_key,'')=COALESCE(NEW.drug_class,'')
                   LIMIT 1
               )
             WHERE id=NEW.id;
        END;
        """
    )

    # One-time safe backfill. Free-text or ambiguous rows deliberately remain NULL
    # and surface UNMAPPED_MEDICATION_CONCEPT until a clinician resolves them.
    db.execute(
        """UPDATE patient_medications
           SET drug_catalog_id=(
               SELECT catalog.id FROM drug_catalog catalog
               WHERE catalog.is_active=1
                 AND lower(trim(catalog.generic_fa))=
                     lower(trim(patient_medications.drug_name))
                 AND COALESCE(catalog.drug_class_key,'')=
                     COALESCE(patient_medications.drug_class,'')
               LIMIT 1
           )
           WHERE drug_catalog_id IS NULL
             AND drug_class IS NOT NULL
             AND (
                 SELECT COUNT(*) FROM drug_catalog catalog
                 WHERE catalog.is_active=1
                   AND lower(trim(catalog.generic_fa))=
                       lower(trim(patient_medications.drug_name))
                   AND COALESCE(catalog.drug_class_key,'')=
                       COALESCE(patient_medications.drug_class,'')
             )=1"""
    )

    table = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (_TABLE,),
    ).fetchone()
    if not table:
        raise RuntimeError("clinical reconciliation table was not installed")

    trigger_rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' "
        f"AND name IN ({','.join('?' for _ in _REQUIRED_TRIGGERS)})",
        tuple(sorted(_REQUIRED_TRIGGERS)),
    ).fetchall()
    present = {str(row["name"]) for row in trigger_rows}
    missing = sorted(_REQUIRED_TRIGGERS - present)
    if missing:
        raise RuntimeError(
            "clinical reconciliation audit guards are incomplete: "
            + ", ".join(missing)
        )
    db.commit()
