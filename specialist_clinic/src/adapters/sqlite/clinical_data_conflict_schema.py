"""Safety-critical storage for source provenance, completeness and conflict resolution."""
from __future__ import annotations

import hashlib
import json
import sqlite3


_REQUIRED_TRIGGERS = {
    "trg_data_conflict_no_update",
    "trg_data_conflict_no_delete",
    "trg_data_conflict_first_event",
    "trg_data_conflict_subsequent_event",
    "trg_data_conflict_same_scope",
    "trg_data_conflict_recorded_order",
    "trg_data_conflict_transition",
    "trg_data_conflict_resolution_shape",
    "trg_allergy_concept_validate_insert",
    "trg_allergy_concept_validate_update",
}
for _source_table in ("patient_conditions", "patient_medications", "allergies"):
    _REQUIRED_TRIGGERS.update({
        f"trg_{_source_table}_provenance_insert",
        f"trg_{_source_table}_provenance_update",
    })


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
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
    db: sqlite3.Connection,
    table: str,
    column: str,
    declaration: str,
) -> None:
    if not _table_exists(db, table) or column in _columns(db, table):
        return
    try:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
    except sqlite3.OperationalError:
        if column not in _columns(db, table):
            raise


def _definition_hash(concept_key: str, display_name: str, aliases: list[str]) -> str:
    raw = json.dumps(
        {
            "concept_key": concept_key,
            "display_name": display_name,
            "aliases": sorted({alias.strip().lower() for alias in aliases if alias.strip()}),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _seed_allergy_catalog(db: sqlite3.Connection) -> None:
    rows = (
        ("penicillin", "پنی‌سیلین", ["penicillin", "پنی سیلین", "پنی‌سیلین"]),
        ("aspirin", "آسپرین", ["aspirin", "asa", "آسپرین"]),
        ("sulfonamide", "سولفونامید", ["sulfa", "sulfonamide", "سولفا", "سولفونامید"]),
        (
            "trimethoprim_sulfamethoxazole",
            "کوتریموکسازول",
            [
                "co-trimoxazole",
                "cotrimoxazole",
                "trimethoprim-sulfamethoxazole",
                "trimethoprim sulfamethoxazole",
                "کوتریموکسازول",
                "تری‌متوپریم-سولفامتوکسازول",
            ],
        ),
        ("ibuprofen", "ایبوپروفن", ["ibuprofen", "ایبوپروفن"]),
        ("latex", "لاتکس", ["latex", "لاتکس"]),
        ("peanut", "بادام‌زمینی", ["peanut", "بادام زمینی", "بادام‌زمینی"]),
        ("egg", "تخم‌مرغ", ["egg", "تخم مرغ", "تخم‌مرغ"]),
        ("contrast_media", "مادهٔ حاجب", ["contrast", "contrast media", "ماده حاجب", "مادهٔ حاجب"]),
    )
    for concept_key, display_name, aliases in rows:
        aliases_json = json.dumps(aliases, ensure_ascii=False, separators=(",", ":"))
        db.execute(
            """INSERT OR IGNORE INTO allergy_catalog
               (concept_key, display_name, aliases_json, definition_hash, is_active)
               VALUES (?, ?, ?, ?, 1)""",
            (
                concept_key,
                display_name,
                aliases_json,
                _definition_hash(concept_key, display_name, aliases),
            ),
        )


def ensure_clinical_data_conflict_storage(db: sqlite3.Connection) -> None:
    """Install provenance and an immutable conflict-resolution ledger.

    The function is idempotent.  Missing guards are safety failures and abort startup.
    It is also safe on partial pre-v2 databases: installation is deferred until the
    patient-owned source tables and patient_links exist.
    """
    prerequisites = {
        "patient_links",
        "patient_conditions",
        "patient_medications",
        "allergies",
        "clinical_reconciliation_events",
    }
    if any(not _table_exists(db, table) for table in prerequisites):
        return

    for table in ("patient_conditions", "patient_medications", "allergies"):
        _ensure_column(
            db,
            table,
            "source_system",
            "TEXT NOT NULL DEFAULT 'clinic'",
        )
        _ensure_column(db, table, "source_record_id", "TEXT")
        _ensure_column(
            db,
            table,
            "source_assertion",
            "TEXT NOT NULL DEFAULT 'PRESENT'",
        )
        _ensure_column(
            db,
            table,
            "verification",
            "TEXT NOT NULL DEFAULT 'CONFIRMED'",
        )
        _ensure_column(db, table, "recorded_by", "TEXT")
    _ensure_column(db, "allergies", "allergy_concept_id", "INTEGER")

    for column, declaration in (
        ("conflict_snapshot_hash", "TEXT"),
        ("conflict_count", "INTEGER NOT NULL DEFAULT 0"),
        ("unresolved_conflict_count", "INTEGER NOT NULL DEFAULT 0"),
        ("mapping_complete", "INTEGER NOT NULL DEFAULT 0"),
        ("reviewed_sources_json", "TEXT NOT NULL DEFAULT '[]'"),
    ):
        _ensure_column(
            db,
            "clinical_reconciliation_events",
            column,
            declaration,
        )

    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS allergy_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            concept_key TEXT NOT NULL UNIQUE
                CHECK (length(trim(concept_key)) BETWEEN 2 AND 120),
            display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
            aliases_json TEXT NOT NULL DEFAULT '[]'
                CHECK (json_valid(aliases_json) AND json_type(aliases_json)='array'),
            definition_hash TEXT NOT NULL CHECK (length(definition_hash)=64),
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
            created_at TEXT NOT NULL DEFAULT (datetime('now','+3 hours','+30 minutes'))
        );

        CREATE TABLE IF NOT EXISTS clinical_data_conflict_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_link_id INTEGER NOT NULL,
            collection_key TEXT NOT NULL
                CHECK (collection_key IN ('conditions','medications','allergies')),
            conflict_group_key TEXT NOT NULL
                CHECK (length(trim(conflict_group_key)) BETWEEN 3 AND 300),
            concept_key TEXT NOT NULL CHECK (length(trim(concept_key)) > 0),
            event_type TEXT NOT NULL
                CHECK (event_type IN ('OPENED','REOPENED','RESOLVED','ENTERED_IN_ERROR')),
            status TEXT NOT NULL
                CHECK (status IN ('OPEN','RESOLVED','ENTERED_IN_ERROR')),
            candidate_set_hash TEXT NOT NULL CHECK (length(candidate_set_hash)=64),
            candidates_json TEXT NOT NULL
                CHECK (json_valid(candidates_json) AND json_type(candidates_json)='array'),
            resolution_method TEXT
                CHECK (resolution_method IS NULL OR resolution_method IN (
                    'SELECT_CANDIDATE','CONFIRMED_ABSENT','MARK_UNKNOWN','MERGE_CANDIDATES'
                )),
            selected_candidate_keys_json TEXT NOT NULL DEFAULT '[]'
                CHECK (json_valid(selected_candidate_keys_json)
                       AND json_type(selected_candidate_keys_json)='array'),
            resolved_value_json TEXT
                CHECK (resolved_value_json IS NULL OR json_valid(resolved_value_json)),
            verification TEXT NOT NULL DEFAULT 'CONFIRMED'
                CHECK (verification IN ('CONFIRMED','PROVISIONAL','UNVERIFIED','REFUTED')),
            effective_at TEXT NOT NULL CHECK (datetime(effective_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            source TEXT NOT NULL DEFAULT 'clinician'
                CHECK (source IN ('clinician','patient','caregiver','imported','system')),
            actor_user_id INTEGER,
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username)) > 0),
            supersedes_event_id INTEGER,
            note TEXT,
            content_hash TEXT NOT NULL CHECK (length(content_hash)=64),
            created_at TEXT NOT NULL DEFAULT (datetime('now','+3 hours','+30 minutes')),
            CHECK (datetime(effective_at) <= datetime(recorded_at)),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(actor_user_id) REFERENCES users(id),
            FOREIGN KEY(supersedes_event_id) REFERENCES clinical_data_conflict_events(id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_data_conflict_one_root
        ON clinical_data_conflict_events(patient_link_id, collection_key, conflict_group_key)
        WHERE supersedes_event_id IS NULL;

        CREATE UNIQUE INDEX IF NOT EXISTS idx_data_conflict_one_child
        ON clinical_data_conflict_events(supersedes_event_id)
        WHERE supersedes_event_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_data_conflict_patient_collection
        ON clinical_data_conflict_events(
            patient_link_id, collection_key, conflict_group_key, recorded_at DESC, id DESC
        );

        CREATE INDEX IF NOT EXISTS idx_allergies_concept
        ON allergies(patient_link_id, allergy_concept_id, is_active);

        CREATE TRIGGER IF NOT EXISTS trg_data_conflict_no_update
        BEFORE UPDATE ON clinical_data_conflict_events
        BEGIN
            SELECT RAISE(ABORT, 'clinical data conflict events are append-only');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_data_conflict_no_delete
        BEFORE DELETE ON clinical_data_conflict_events
        BEGIN
            SELECT RAISE(ABORT, 'clinical data conflict events cannot be deleted');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_data_conflict_first_event
        BEFORE INSERT ON clinical_data_conflict_events
        WHEN NOT EXISTS (
            SELECT 1 FROM clinical_data_conflict_events prior
            WHERE prior.patient_link_id=NEW.patient_link_id
              AND prior.collection_key=NEW.collection_key
              AND prior.conflict_group_key=NEW.conflict_group_key
        )
        AND (
            NEW.supersedes_event_id IS NOT NULL
            OR NEW.event_type<>'OPENED'
            OR NEW.status<>'OPEN'
        )
        BEGIN
            SELECT RAISE(ABORT, 'first conflict event must open the group');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_data_conflict_subsequent_event
        BEFORE INSERT ON clinical_data_conflict_events
        WHEN EXISTS (
            SELECT 1 FROM clinical_data_conflict_events prior
            WHERE prior.patient_link_id=NEW.patient_link_id
              AND prior.collection_key=NEW.collection_key
              AND prior.conflict_group_key=NEW.conflict_group_key
        )
        AND (
            NEW.supersedes_event_id IS NULL
            OR NEW.supersedes_event_id<>(
                SELECT head.id FROM clinical_data_conflict_events head
                WHERE head.patient_link_id=NEW.patient_link_id
                  AND head.collection_key=NEW.collection_key
                  AND head.conflict_group_key=NEW.conflict_group_key
                  AND NOT EXISTS (
                    SELECT 1 FROM clinical_data_conflict_events child
                    WHERE child.supersedes_event_id=head.id
                  )
                ORDER BY head.recorded_at DESC, head.id DESC LIMIT 1
            )
        )
        BEGIN
            SELECT RAISE(ABORT, 'conflict event must supersede the current head');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_data_conflict_same_scope
        BEFORE INSERT ON clinical_data_conflict_events
        WHEN NEW.supersedes_event_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1 FROM clinical_data_conflict_events prior
             WHERE prior.id=NEW.supersedes_event_id
               AND prior.patient_link_id=NEW.patient_link_id
               AND prior.collection_key=NEW.collection_key
               AND prior.conflict_group_key=NEW.conflict_group_key
               AND prior.concept_key=NEW.concept_key
         )
        BEGIN
            SELECT RAISE(ABORT, 'conflict supersession must stay in one patient concept group');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_data_conflict_recorded_order
        BEFORE INSERT ON clinical_data_conflict_events
        WHEN NEW.supersedes_event_id IS NOT NULL
         AND datetime(NEW.recorded_at) < datetime((
             SELECT recorded_at FROM clinical_data_conflict_events
             WHERE id=NEW.supersedes_event_id
         ))
        BEGIN
            SELECT RAISE(ABORT, 'conflict recorded_at cannot move backwards');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_data_conflict_transition
        BEFORE INSERT ON clinical_data_conflict_events
        WHEN (
            (NEW.event_type IN ('OPENED','REOPENED') AND NEW.status<>'OPEN')
            OR (NEW.event_type='RESOLVED' AND NEW.status<>'RESOLVED')
            OR (NEW.event_type='ENTERED_IN_ERROR' AND NEW.status<>'ENTERED_IN_ERROR')
            OR (
                NEW.supersedes_event_id IS NOT NULL
                AND (SELECT status FROM clinical_data_conflict_events
                     WHERE id=NEW.supersedes_event_id)='ENTERED_IN_ERROR'
            )
            OR (
                NEW.event_type='RESOLVED'
                AND (SELECT status FROM clinical_data_conflict_events
                     WHERE id=NEW.supersedes_event_id)<>'OPEN'
            )
        )
        BEGIN
            SELECT RAISE(ABORT, 'invalid clinical conflict lifecycle transition');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_data_conflict_resolution_shape
        BEFORE INSERT ON clinical_data_conflict_events
        WHEN (
            (NEW.status='OPEN' AND (
                NEW.resolution_method IS NOT NULL
                OR json_array_length(NEW.selected_candidate_keys_json)<>0
                OR NEW.resolved_value_json IS NOT NULL
            ))
            OR (NEW.status='RESOLVED' AND NEW.resolution_method IS NULL)
            OR (NEW.resolution_method='SELECT_CANDIDATE'
                AND json_array_length(NEW.selected_candidate_keys_json)<>1)
            OR (NEW.resolution_method='MERGE_CANDIDATES'
                AND (json_array_length(NEW.selected_candidate_keys_json)<2
                     OR NEW.resolved_value_json IS NULL
                     OR json_type(NEW.resolved_value_json)<>'object'))
            OR (NEW.resolution_method IN ('CONFIRMED_ABSENT','MARK_UNKNOWN')
                AND (json_array_length(NEW.selected_candidate_keys_json)<>0
                     OR NEW.resolved_value_json IS NOT NULL))
        )
        BEGIN
            SELECT RAISE(ABORT, 'invalid clinical conflict resolution payload');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_allergy_concept_validate_insert
        BEFORE INSERT ON allergies
        WHEN NEW.allergy_concept_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1 FROM allergy_catalog catalog
             WHERE catalog.id=NEW.allergy_concept_id AND catalog.is_active=1
         )
        BEGIN
            SELECT RAISE(ABORT, 'allergy concept must reference an active catalog row');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_allergy_concept_validate_update
        BEFORE UPDATE OF allergy_concept_id ON allergies
        WHEN NEW.allergy_concept_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1 FROM allergy_catalog catalog
             WHERE catalog.id=NEW.allergy_concept_id AND catalog.is_active=1
         )
        BEGIN
            SELECT RAISE(ABORT, 'allergy concept must reference an active catalog row');
        END;
        """
    )
    for table in ("patient_conditions", "patient_medications", "allergies"):
        db.executescript(
            f"""
            CREATE TRIGGER IF NOT EXISTS trg_{table}_provenance_insert
            BEFORE INSERT ON {table}
            WHEN NEW.source_assertion NOT IN ('PRESENT','ABSENT','UNKNOWN')
              OR NEW.verification NOT IN ('CONFIRMED','PROVISIONAL','UNVERIFIED','REFUTED')
              OR length(trim(NEW.source_system))=0
            BEGIN
                SELECT RAISE(ABORT, 'invalid clinical source provenance');
            END;

            CREATE TRIGGER IF NOT EXISTS trg_{table}_provenance_update
            BEFORE UPDATE OF source_system, source_record_id, source_assertion, verification
            ON {table}
            WHEN NEW.source_assertion NOT IN ('PRESENT','ABSENT','UNKNOWN')
              OR NEW.verification NOT IN ('CONFIRMED','PROVISIONAL','UNVERIFIED','REFUTED')
              OR length(trim(NEW.source_system))=0
            BEGIN
                SELECT RAISE(ABORT, 'invalid clinical source provenance');
            END;
            """
        )

    _seed_allergy_catalog(db)

    # Deterministic, exact-only mapping. Ambiguous/free-text values remain unmapped.
    db.execute(
        """UPDATE allergies
           SET allergy_concept_id=(
               SELECT catalog.id FROM allergy_catalog catalog
               WHERE catalog.is_active=1
                 AND (
                   lower(trim(catalog.display_name))=lower(trim(allergies.substance))
                   OR EXISTS (
                       SELECT 1 FROM json_each(catalog.aliases_json) alias
                       WHERE lower(trim(CAST(alias.value AS TEXT)))=
                             lower(trim(allergies.substance))
                   )
                 )
               LIMIT 1
           )
           WHERE allergy_concept_id IS NULL
             AND (
               SELECT COUNT(*) FROM allergy_catalog catalog
               WHERE catalog.is_active=1
                 AND (
                   lower(trim(catalog.display_name))=lower(trim(allergies.substance))
                   OR EXISTS (
                       SELECT 1 FROM json_each(catalog.aliases_json) alias
                       WHERE lower(trim(CAST(alias.value AS TEXT)))=
                             lower(trim(allergies.substance))
                   )
                 )
             )=1"""
    )

    for table in ("patient_conditions", "patient_medications", "allergies"):
        db.execute(
            f"""UPDATE {table}
                SET source_system=COALESCE(NULLIF(trim(source_system),''),'clinic'),
                    source_record_id=COALESCE(NULLIF(trim(source_record_id),''), ? || ':' || id),
                    source_assertion=COALESCE(NULLIF(trim(source_assertion),''),'PRESENT'),
                    verification=COALESCE(NULLIF(trim(verification),''),'CONFIRMED')""",
            (table,),
        )

    table = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='clinical_data_conflict_events'"
    ).fetchone()
    if not table:
        raise RuntimeError("clinical data conflict storage was not installed")
    present = {
        str(row["name"])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    missing = sorted(_REQUIRED_TRIGGERS - present)
    if missing:
        raise RuntimeError(
            "clinical data conflict guards are incomplete: " + ", ".join(missing)
        )
    db.commit()
