"""Append-only encounter documentation and explicit completion requirements."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any


SCHEMA_VERSION = "1.0"


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _backfill_legacy_requirements(db: sqlite3.Connection) -> None:
    rows = db.execute(
        """SELECT encounter.encounter_id,encounter.journey_id,
                  encounter.patient_link_id,encounter.accounting_invoice_id,
                  encounter.created_at,encounter.created_by
           FROM care_encounters encounter
           WHERE NOT EXISTS (
               SELECT 1 FROM care_encounter_document_requirements requirement
               WHERE requirement.encounter_id=encounter.encounter_id
           )"""
    ).fetchall()
    for row in rows:
        payload = {
            "encounter_id": str(row["encounter_id"]),
            "journey_id": str(row["journey_id"]),
            "patient_link_id": int(row["patient_link_id"]),
            "accounting_invoice_id": row["accounting_invoice_id"],
            "requirement_status": "LEGACY_EXEMPT",
            "source_code": "A9_LEGACY_BACKFILL",
            "created_at": str(row["created_at"]),
            "created_by": str(row["created_by"] or "system:a9-migration"),
        }
        db.execute(
            """INSERT INTO care_encounter_document_requirements
               (encounter_id,journey_id,patient_link_id,accounting_invoice_id,
                requirement_status,source_code,created_at,created_by,content_hash)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (*payload.values(), _hash(payload)),
        )


def ensure_encounter_documentation_storage(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS care_encounter_document_requirements (
            encounter_id TEXT PRIMARY KEY,
            journey_id TEXT NOT NULL,
            patient_link_id INTEGER NOT NULL,
            accounting_invoice_id INTEGER,
            requirement_status TEXT NOT NULL CHECK (requirement_status IN (
                'REQUIRED','LEGACY_EXEMPT'
            )),
            source_code TEXT NOT NULL CHECK (source_code IN (
                'DOCTOR_QUEUE_A9','A9_LEGACY_BACKFILL'
            )),
            created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
            created_by TEXT NOT NULL CHECK (length(trim(created_by))>0),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (
                (requirement_status='REQUIRED' AND source_code='DOCTOR_QUEUE_A9')
                OR
                (requirement_status='LEGACY_EXEMPT' AND source_code='A9_LEGACY_BACKFILL')
            ),
            FOREIGN KEY(encounter_id) REFERENCES care_encounters(encounter_id),
            FOREIGN KEY(journey_id) REFERENCES care_journeys(journey_id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id)
        );

        CREATE TABLE IF NOT EXISTS care_encounter_document_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            encounter_id TEXT NOT NULL,
            journey_id TEXT NOT NULL,
            patient_link_id INTEGER NOT NULL,
            accounting_invoice_id INTEGER NOT NULL CHECK (accounting_invoice_id>0),
            event_type TEXT NOT NULL CHECK (event_type IN (
                'DRAFT_SAVED','SIGNED','AMENDED','ENTERED_IN_ERROR'
            )),
            document_status TEXT NOT NULL CHECK (document_status IN (
                'DRAFT','SIGNED','ENTERED_IN_ERROR'
            )),
            chief_complaint TEXT,
            objective_findings TEXT,
            assessment TEXT,
            plan TEXT,
            followup_instructions TEXT,
            problems_json TEXT NOT NULL DEFAULT '[]'
                CHECK (json_valid(problems_json) AND json_type(problems_json)='array'),
            outcome_code TEXT CHECK (outcome_code IS NULL OR outcome_code IN (
                'STABLE_CONTINUE','PLAN_CHANGED','FOLLOWUP_REQUIRED','REFERRED',
                'URGENT_ESCALATION','OTHER'
            )),
            amendment_reason TEXT,
            authored_at TEXT NOT NULL CHECK (datetime(authored_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_user_id INTEGER,
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username))>0),
            idempotency_key TEXT NOT NULL UNIQUE,
            supersedes_event_id INTEGER UNIQUE,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (datetime(recorded_at)>=datetime(authored_at)),
            CHECK (
                (event_type='DRAFT_SAVED' AND document_status='DRAFT'
                 AND outcome_code IS NULL AND amendment_reason IS NULL)
                OR
                (event_type='SIGNED' AND document_status='SIGNED'
                 AND length(trim(COALESCE(assessment,'')))>0
                 AND length(trim(COALESCE(plan,'')))>0
                 AND outcome_code IS NOT NULL AND amendment_reason IS NULL)
                OR
                (event_type='AMENDED' AND document_status='SIGNED'
                 AND length(trim(COALESCE(assessment,'')))>0
                 AND length(trim(COALESCE(plan,'')))>0
                 AND outcome_code IS NOT NULL
                 AND length(trim(COALESCE(amendment_reason,'')))>0)
                OR
                (event_type='ENTERED_IN_ERROR'
                 AND document_status='ENTERED_IN_ERROR'
                 AND length(trim(COALESCE(amendment_reason,'')))>0)
            ),
            FOREIGN KEY(encounter_id) REFERENCES care_encounters(encounter_id),
            FOREIGN KEY(journey_id) REFERENCES care_journeys(journey_id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(actor_user_id) REFERENCES users(id),
            FOREIGN KEY(supersedes_event_id)
                REFERENCES care_encounter_document_events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_encounter_document_stream
        ON care_encounter_document_events(encounter_id,recorded_at DESC,id DESC);
        CREATE INDEX IF NOT EXISTS idx_encounter_document_patient
        ON care_encounter_document_events(patient_link_id,recorded_at DESC,id DESC);

        CREATE TRIGGER IF NOT EXISTS trg_encounter_document_requirement_no_update
        BEFORE UPDATE ON care_encounter_document_requirements
        BEGIN SELECT RAISE(ABORT,'encounter documentation requirement is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS trg_encounter_document_requirement_no_delete
        BEFORE DELETE ON care_encounter_document_requirements
        BEGIN SELECT RAISE(ABORT,'encounter documentation requirement cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_encounter_document_requirement_scope
        BEFORE INSERT ON care_encounter_document_requirements
        WHEN NOT EXISTS (
            SELECT 1 FROM care_encounters encounter
            WHERE encounter.encounter_id=NEW.encounter_id
              AND encounter.journey_id=NEW.journey_id
              AND encounter.patient_link_id=NEW.patient_link_id
              AND encounter.accounting_invoice_id IS NEW.accounting_invoice_id
        )
        BEGIN SELECT RAISE(ABORT,'encounter documentation requirement scope mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_encounter_document_no_update
        BEFORE UPDATE ON care_encounter_document_events
        BEGIN SELECT RAISE(ABORT,'encounter documents are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_encounter_document_no_delete
        BEFORE DELETE ON care_encounter_document_events
        BEGIN SELECT RAISE(ABORT,'encounter documents cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_encounter_document_scope
        BEFORE INSERT ON care_encounter_document_events
        WHEN NOT EXISTS (
            SELECT 1 FROM care_encounters encounter
            WHERE encounter.encounter_id=NEW.encounter_id
              AND encounter.journey_id=NEW.journey_id
              AND encounter.patient_link_id=NEW.patient_link_id
              AND encounter.accounting_invoice_id=NEW.accounting_invoice_id
        )
        BEGIN SELECT RAISE(ABORT,'encounter document scope mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_encounter_document_first
        BEFORE INSERT ON care_encounter_document_events
        WHEN NOT EXISTS (
            SELECT 1 FROM care_encounter_document_events event
            WHERE event.encounter_id=NEW.encounter_id
        ) AND (
            NEW.event_type NOT IN ('DRAFT_SAVED','SIGNED')
            OR NEW.supersedes_event_id IS NOT NULL
        )
        BEGIN SELECT RAISE(ABORT,'first encounter document must be draft or signed'); END;

        CREATE TRIGGER IF NOT EXISTS trg_encounter_document_linear
        BEFORE INSERT ON care_encounter_document_events
        WHEN EXISTS (
            SELECT 1 FROM care_encounter_document_events event
            WHERE event.encounter_id=NEW.encounter_id
        ) AND NEW.supersedes_event_id IS NOT (
            SELECT head.id FROM care_encounter_document_events head
            WHERE head.encounter_id=NEW.encounter_id
            ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
        )
        BEGIN SELECT RAISE(ABORT,'encounter document must supersede current head'); END;

        CREATE TRIGGER IF NOT EXISTS trg_encounter_document_transition
        BEFORE INSERT ON care_encounter_document_events
        WHEN NEW.supersedes_event_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM care_encounter_document_events prior
            WHERE prior.id=NEW.supersedes_event_id AND (
                (prior.document_status='DRAFT'
                 AND NEW.event_type IN ('DRAFT_SAVED','SIGNED','ENTERED_IN_ERROR'))
                OR
                (prior.document_status='SIGNED'
                 AND NEW.event_type IN ('AMENDED','ENTERED_IN_ERROR'))
            )
        )
        BEGIN SELECT RAISE(ABORT,'invalid encounter document transition'); END;

        CREATE TRIGGER IF NOT EXISTS trg_encounter_document_sign_active
        BEFORE INSERT ON care_encounter_document_events
        WHEN NEW.event_type='SIGNED' AND NOT EXISTS (
            SELECT 1 FROM care_encounter_events current
            WHERE current.encounter_id=NEW.encounter_id
              AND current.id=(
                  SELECT head.id FROM care_encounter_events head
                  WHERE head.encounter_id=NEW.encounter_id
                  ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
              ) AND current.event_type='STARTED'
        )
        BEGIN SELECT RAISE(ABORT,'encounter must be active before document signing'); END;

        CREATE TRIGGER IF NOT EXISTS trg_encounter_completion_requires_document
        BEFORE INSERT ON care_encounter_events
        WHEN NEW.event_type='COMPLETED'
          AND EXISTS (
              SELECT 1 FROM care_encounter_document_requirements requirement
              WHERE requirement.encounter_id=NEW.encounter_id
                AND requirement.requirement_status='REQUIRED'
          )
          AND NOT EXISTS (
              SELECT 1 FROM care_encounter_document_events document
              WHERE document.encounter_id=NEW.encounter_id
                AND document.id=(
                    SELECT head.id FROM care_encounter_document_events head
                    WHERE head.encounter_id=NEW.encounter_id
                    ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
                ) AND document.document_status='SIGNED'
          )
        BEGIN SELECT RAISE(ABORT,'signed encounter document required for completion'); END;
        """
    )
    _backfill_legacy_requirements(db)
    db.commit()


__all__ = ["SCHEMA_VERSION", "ensure_encounter_documentation_storage"]
