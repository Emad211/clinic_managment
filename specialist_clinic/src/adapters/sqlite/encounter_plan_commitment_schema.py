"""Append-only signed-plan commitments projected into the existing worklist."""
from __future__ import annotations

import sqlite3


SCHEMA_VERSION = "1.0"


COMMITMENT_TYPES = (
    "CALL_CHECK",
    "IN_PERSON_REVIEW",
    "LAB_REVIEW",
    "MEDICATION_REVIEW",
    "REFERRAL_CHECK",
    "HOME_MONITORING_REVIEW",
)


def _ensure_document_commitments_column(db: sqlite3.Connection) -> None:
    columns = {
        str(row["name"])
        for row in db.execute(
            "PRAGMA table_info(care_encounter_document_events)"
        ).fetchall()
    }
    if "commitments_json" not in columns:
        db.execute(
            """ALTER TABLE care_encounter_document_events
               ADD COLUMN commitments_json TEXT NOT NULL DEFAULT '[]'"""
        )


def ensure_encounter_plan_commitment_storage(db: sqlite3.Connection) -> None:
    _ensure_document_commitments_column(db)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS care_plan_commitments (
            commitment_id TEXT PRIMARY KEY,
            document_event_id INTEGER NOT NULL,
            encounter_id TEXT NOT NULL,
            journey_id TEXT NOT NULL,
            patient_link_id INTEGER NOT NULL,
            client_key TEXT NOT NULL,
            commitment_type TEXT NOT NULL CHECK (commitment_type IN (
                'CALL_CHECK','IN_PERSON_REVIEW','LAB_REVIEW',
                'MEDICATION_REVIEW','REFERRAL_CHECK',
                'HOME_MONITORING_REVIEW'
            )),
            instruction TEXT NOT NULL CHECK (length(trim(instruction))>0),
            fulfillment TEXT NOT NULL CHECK (fulfillment IN (
                'remote','in_person','hybrid'
            )),
            original_due_at TEXT NOT NULL CHECK (datetime(original_due_at) IS NOT NULL),
            original_assigned_to TEXT,
            created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
            created_by TEXT NOT NULL CHECK (length(trim(created_by))>0),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            UNIQUE(document_event_id,client_key),
            FOREIGN KEY(document_event_id)
                REFERENCES care_encounter_document_events(id),
            FOREIGN KEY(encounter_id) REFERENCES care_encounters(encounter_id),
            FOREIGN KEY(journey_id) REFERENCES care_journeys(journey_id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id)
        );
        CREATE INDEX IF NOT EXISTS idx_plan_commitment_patient
        ON care_plan_commitments(patient_link_id,original_due_at,commitment_id);
        CREATE INDEX IF NOT EXISTS idx_plan_commitment_encounter
        ON care_plan_commitments(encounter_id,created_at,commitment_id);

        CREATE TABLE IF NOT EXISTS care_plan_commitment_task_links (
            commitment_id TEXT PRIMARY KEY,
            task_id INTEGER NOT NULL UNIQUE,
            linked_at TEXT NOT NULL CHECK (datetime(linked_at) IS NOT NULL),
            linked_by TEXT NOT NULL CHECK (length(trim(linked_by))>0),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            FOREIGN KEY(commitment_id) REFERENCES care_plan_commitments(commitment_id),
            FOREIGN KEY(task_id) REFERENCES followup_tasks(id)
        );

        CREATE TABLE IF NOT EXISTS care_plan_commitment_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commitment_id TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN (
                'CREATED','STARTED','ASSIGNED','RESCHEDULED','SCHEDULED',
                'COMPLETED','CANCELLED','ENTERED_IN_ERROR'
            )),
            status TEXT NOT NULL CHECK (status IN (
                'OPEN','IN_PROGRESS','SCHEDULED','COMPLETED',
                'CANCELLED','ENTERED_IN_ERROR'
            )),
            due_at TEXT NOT NULL CHECK (datetime(due_at) IS NOT NULL),
            assigned_to TEXT,
            appointment_id INTEGER,
            evidence_type TEXT CHECK (evidence_type IS NULL OR evidence_type IN (
                'CONTACT_EVENT','APPOINTMENT','ENCOUNTER_DOCUMENT',
                'LAB_RESULT','MEDICATION_EVENT','VITAL_READING','MANUAL_VERIFIED'
            )),
            evidence_ref TEXT,
            outcome_code TEXT CHECK (outcome_code IS NULL OR outcome_code IN (
                'COMPLETED_AS_PLANNED','NO_LONGER_NEEDED','PATIENT_DECLINED',
                'UNREACHABLE','REFERRED_OUT','OTHER'
            )),
            note TEXT,
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_user_id INTEGER,
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username))>0),
            idempotency_key TEXT NOT NULL UNIQUE,
            supersedes_event_id INTEGER UNIQUE,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (
                (event_type='CREATED' AND status='OPEN'
                 AND evidence_type IS NULL AND evidence_ref IS NULL
                 AND outcome_code IS NULL AND appointment_id IS NULL)
                OR
                (event_type='STARTED' AND status='IN_PROGRESS'
                 AND evidence_type IS NULL AND evidence_ref IS NULL
                 AND outcome_code IS NULL)
                OR
                (event_type='ASSIGNED' AND status IN ('OPEN','IN_PROGRESS','SCHEDULED')
                 AND length(trim(COALESCE(assigned_to,'')))>0
                 AND evidence_type IS NULL AND evidence_ref IS NULL
                 AND outcome_code IS NULL)
                OR
                (event_type='RESCHEDULED' AND status IN ('OPEN','IN_PROGRESS','SCHEDULED')
                 AND evidence_type IS NULL AND evidence_ref IS NULL
                 AND outcome_code IS NULL)
                OR
                (event_type='SCHEDULED' AND status='SCHEDULED'
                 AND appointment_id IS NOT NULL
                 AND evidence_type IS NULL AND evidence_ref IS NULL
                 AND outcome_code IS NULL)
                OR
                (event_type='COMPLETED' AND status='COMPLETED'
                 AND evidence_type IS NOT NULL
                 AND length(trim(COALESCE(evidence_ref,'')))>0
                 AND outcome_code IS NOT NULL)
                OR
                (event_type='CANCELLED' AND status='CANCELLED'
                 AND length(trim(COALESCE(note,'')))>0
                 AND evidence_type IS NULL AND evidence_ref IS NULL)
                OR
                (event_type='ENTERED_IN_ERROR' AND status='ENTERED_IN_ERROR'
                 AND length(trim(COALESCE(note,'')))>0)
            ),
            FOREIGN KEY(commitment_id) REFERENCES care_plan_commitments(commitment_id),
            FOREIGN KEY(appointment_id) REFERENCES appointments(id),
            FOREIGN KEY(actor_user_id) REFERENCES users(id),
            FOREIGN KEY(supersedes_event_id)
                REFERENCES care_plan_commitment_events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_plan_commitment_stream
        ON care_plan_commitment_events(commitment_id,recorded_at DESC,id DESC);
        CREATE INDEX IF NOT EXISTS idx_plan_commitment_due
        ON care_plan_commitment_events(status,due_at);

        CREATE TRIGGER IF NOT EXISTS trg_plan_commitment_no_update
        BEFORE UPDATE ON care_plan_commitments
        BEGIN SELECT RAISE(ABORT,'plan commitments are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS trg_plan_commitment_no_delete
        BEFORE DELETE ON care_plan_commitments
        BEGIN SELECT RAISE(ABORT,'plan commitments cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_plan_commitment_link_no_update
        BEFORE UPDATE ON care_plan_commitment_task_links
        BEGIN SELECT RAISE(ABORT,'plan commitment task link is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS trg_plan_commitment_link_no_delete
        BEFORE DELETE ON care_plan_commitment_task_links
        BEGIN SELECT RAISE(ABORT,'plan commitment task link cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_plan_commitment_event_no_update
        BEFORE UPDATE ON care_plan_commitment_events
        BEGIN SELECT RAISE(ABORT,'plan commitment events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_plan_commitment_event_no_delete
        BEFORE DELETE ON care_plan_commitment_events
        BEGIN SELECT RAISE(ABORT,'plan commitment events cannot be deleted'); END;

        CREATE TRIGGER IF NOT EXISTS trg_plan_commitment_document_scope
        BEFORE INSERT ON care_plan_commitments
        WHEN NOT EXISTS (
            SELECT 1 FROM care_encounter_document_events document
            WHERE document.id=NEW.document_event_id
              AND document.encounter_id=NEW.encounter_id
              AND document.journey_id=NEW.journey_id
              AND document.patient_link_id=NEW.patient_link_id
              AND document.document_status='SIGNED'
              AND document.event_type IN ('SIGNED','AMENDED')
        )
        BEGIN SELECT RAISE(ABORT,'plan commitment signed document scope mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_plan_commitment_task_mutation_guard
        BEFORE UPDATE OF status,due_date,assigned_to,appointment_id,resolved_at
        ON followup_tasks
        WHEN OLD.source_engine='encounter_plan'
        BEGIN SELECT RAISE(ABORT,'plan commitment tasks require append-only lifecycle'); END;

        CREATE TRIGGER IF NOT EXISTS trg_plan_commitment_task_scope
        BEFORE INSERT ON care_plan_commitment_task_links
        WHEN NOT EXISTS (
            SELECT 1 FROM care_plan_commitments commitment
            JOIN followup_tasks task ON task.id=NEW.task_id
            WHERE commitment.commitment_id=NEW.commitment_id
              AND task.patient_link_id=commitment.patient_link_id
              AND task.source_engine='encounter_plan'
              AND task.source_event='encounter_plan_commitment'
              AND task.source_rule=commitment.commitment_id
        )
        BEGIN SELECT RAISE(ABORT,'plan commitment task scope mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_plan_commitment_appointment_scope
        BEFORE INSERT ON care_plan_commitment_events
        WHEN NEW.appointment_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM care_plan_commitments commitment
            JOIN appointments appointment
              ON appointment.id=NEW.appointment_id
            WHERE commitment.commitment_id=NEW.commitment_id
              AND appointment.patient_link_id=commitment.patient_link_id
        )
        BEGIN SELECT RAISE(ABORT,'plan commitment appointment scope mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_plan_commitment_first_event
        BEFORE INSERT ON care_plan_commitment_events
        WHEN NOT EXISTS (
            SELECT 1 FROM care_plan_commitment_events event
            WHERE event.commitment_id=NEW.commitment_id
        ) AND (NEW.event_type<>'CREATED' OR NEW.supersedes_event_id IS NOT NULL)
        BEGIN SELECT RAISE(ABORT,'first plan commitment event must be CREATED'); END;

        CREATE TRIGGER IF NOT EXISTS trg_plan_commitment_linear_event
        BEFORE INSERT ON care_plan_commitment_events
        WHEN EXISTS (
            SELECT 1 FROM care_plan_commitment_events event
            WHERE event.commitment_id=NEW.commitment_id
        ) AND NEW.supersedes_event_id IS NOT (
            SELECT head.id FROM care_plan_commitment_events head
            WHERE head.commitment_id=NEW.commitment_id
            ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
        )
        BEGIN SELECT RAISE(ABORT,'plan commitment event must supersede current head'); END;

        CREATE TRIGGER IF NOT EXISTS trg_plan_commitment_transition
        BEFORE INSERT ON care_plan_commitment_events
        WHEN NEW.supersedes_event_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM care_plan_commitment_events prior
            WHERE prior.id=NEW.supersedes_event_id AND (
                (prior.status='OPEN' AND NEW.event_type IN (
                    'STARTED','ASSIGNED','RESCHEDULED','SCHEDULED',
                    'COMPLETED','CANCELLED','ENTERED_IN_ERROR'
                ))
                OR
                (prior.status='IN_PROGRESS' AND NEW.event_type IN (
                    'ASSIGNED','RESCHEDULED','SCHEDULED','COMPLETED',
                    'CANCELLED','ENTERED_IN_ERROR'
                ))
                OR
                (prior.status='SCHEDULED' AND NEW.event_type IN (
                    'STARTED','ASSIGNED','RESCHEDULED','SCHEDULED',
                    'COMPLETED','CANCELLED','ENTERED_IN_ERROR'
                ))
            )
        )
        BEGIN SELECT RAISE(ABORT,'invalid plan commitment transition'); END;
        """
    )
    db.commit()


__all__ = [
    "COMMITMENT_TYPES",
    "SCHEMA_VERSION",
    "ensure_encounter_plan_commitment_storage",
]
