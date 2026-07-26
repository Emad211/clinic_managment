"""Append-only operational follow-up contact history."""
from __future__ import annotations

import sqlite3


CONTACT_CHANNELS = (
    "PHONE",
    "SMS",
    "IN_PERSON",
    "SYSTEM",
    "OTHER",
)
CONTACT_OUTCOMES = (
    "REACHED",
    "NO_ANSWER",
    "BUSY",
    "WRONG_NUMBER",
    "CALLBACK_REQUESTED",
    "DECLINED",
    "BOOKED",
    "MESSAGE_SENT",
    "MESSAGE_DELIVERED",
    "OTHER",
)


def ensure_followup_operations_storage(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS followup_contact_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            patient_link_id INTEGER NOT NULL,
            journey_id TEXT,
            channel TEXT NOT NULL CHECK (channel IN (
                'PHONE','SMS','IN_PERSON','SYSTEM','OTHER'
            )),
            outcome TEXT NOT NULL CHECK (outcome IN (
                'REACHED','NO_ANSWER','BUSY','WRONG_NUMBER',
                'CALLBACK_REQUESTED','DECLINED','BOOKED',
                'MESSAGE_SENT','MESSAGE_DELIVERED','OTHER'
            )),
            occurred_at TEXT NOT NULL CHECK (datetime(occurred_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_user_id INTEGER,
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username)) > 0),
            note TEXT,
            next_contact_at TEXT CHECK (
                next_contact_at IS NULL OR datetime(next_contact_at) IS NOT NULL
            ),
            idempotency_key TEXT NOT NULL UNIQUE
                CHECK (length(trim(idempotency_key)) >= 12),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (datetime(recorded_at) >= datetime(occurred_at)),
            FOREIGN KEY(task_id) REFERENCES followup_tasks(id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(journey_id) REFERENCES care_journeys(journey_id),
            FOREIGN KEY(actor_user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_followup_contact_task
        ON followup_contact_events(task_id, occurred_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_followup_contact_patient
        ON followup_contact_events(patient_link_id, occurred_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_followup_contact_next
        ON followup_contact_events(next_contact_at, outcome)
        WHERE next_contact_at IS NOT NULL;

        CREATE TRIGGER IF NOT EXISTS trg_followup_contact_no_update
        BEFORE UPDATE ON followup_contact_events
        BEGIN SELECT RAISE(ABORT, 'follow-up contact events are append-only'); END;

        CREATE TRIGGER IF NOT EXISTS trg_followup_contact_no_delete
        BEFORE DELETE ON followup_contact_events
        BEGIN SELECT RAISE(ABORT, 'follow-up contact events cannot be deleted'); END;

        CREATE TRIGGER IF NOT EXISTS trg_followup_contact_task_patient_scope
        BEFORE INSERT ON followup_contact_events
        WHEN NOT EXISTS (
            SELECT 1 FROM followup_tasks task
            WHERE task.id=NEW.task_id
              AND task.patient_link_id=NEW.patient_link_id
        )
        BEGIN SELECT RAISE(ABORT, 'contact task/patient scope mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_followup_contact_journey_scope
        BEFORE INSERT ON followup_contact_events
        WHEN NEW.journey_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM care_journeys journey
            WHERE journey.journey_id=NEW.journey_id
              AND journey.patient_link_id=NEW.patient_link_id
        )
        BEGIN SELECT RAISE(ABORT, 'contact journey/patient scope mismatch'); END;
        """
    )
