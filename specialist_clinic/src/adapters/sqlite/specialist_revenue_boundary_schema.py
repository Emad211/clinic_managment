"""SQLite storage for specialist-program cutover, care journeys and revenue attribution."""
from __future__ import annotations

import sqlite3


SCHEMA_VERSION = "1.0"


def ensure_specialist_revenue_boundary_storage(db: sqlite3.Connection) -> None:
    """Install the specialist-only revenue boundary without touching accounting.

    The specialist database is disposable during development, but the schema is still
    fail-closed: identities and event histories are append-only, and accounting revenue
    can be included only through an explicit invoice-attribution event.
    """
    db.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_patient_links_accounting_unique
        ON patient_links(accounting_patient_id)
        WHERE accounting_patient_id IS NOT NULL;

        CREATE TABLE IF NOT EXISTS specialist_program_enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_link_id INTEGER NOT NULL UNIQUE,
            accounting_patient_id INTEGER NOT NULL UNIQUE,
            effective_at TEXT NOT NULL CHECK (datetime(effective_at) IS NOT NULL),
            accounting_snapshot_at TEXT NOT NULL
                CHECK (datetime(accounting_snapshot_at) IS NOT NULL),
            accounting_invoice_cutoff_id INTEGER NOT NULL DEFAULT 0
                CHECK (accounting_invoice_cutoff_id >= 0),
            history_policy TEXT NOT NULL DEFAULT 'VISIBLE_EXCLUDED'
                CHECK (history_policy='VISIBLE_EXCLUDED'),
            created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
            CHECK (datetime(accounting_snapshot_at) >= datetime(effective_at)),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id)
        );

        CREATE TABLE IF NOT EXISTS care_journeys (
            journey_id TEXT PRIMARY KEY,
            patient_link_id INTEGER NOT NULL,
            enrollment_id INTEGER NOT NULL,
            origin_type TEXT NOT NULL CHECK (length(trim(origin_type)) > 0),
            origin_ref TEXT,
            created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
            created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(enrollment_id) REFERENCES specialist_program_enrollments(id)
        );
        CREATE INDEX IF NOT EXISTS idx_care_journeys_patient
        ON care_journeys(patient_link_id, created_at DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_care_journeys_origin
        ON care_journeys(patient_link_id, origin_type, origin_ref)
        WHERE origin_ref IS NOT NULL;

        CREATE TABLE IF NOT EXISTS care_journey_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            journey_id TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN (
                'OPENED','COMPLETED','CANCELLED','ENTERED_IN_ERROR'
            )),
            effective_at TEXT NOT NULL CHECK (datetime(effective_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username)) > 0),
            note TEXT,
            supersedes_event_id INTEGER UNIQUE,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (datetime(recorded_at) >= datetime(effective_at)),
            FOREIGN KEY(journey_id) REFERENCES care_journeys(journey_id),
            FOREIGN KEY(supersedes_event_id) REFERENCES care_journey_events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_care_journey_events_stream
        ON care_journey_events(journey_id, recorded_at DESC, id DESC);

        CREATE TABLE IF NOT EXISTS care_encounters (
            encounter_id TEXT PRIMARY KEY,
            journey_id TEXT NOT NULL,
            patient_link_id INTEGER NOT NULL,
            encounter_type TEXT NOT NULL CHECK (length(trim(encounter_type)) > 0),
            accounting_invoice_id INTEGER UNIQUE,
            created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
            created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
            FOREIGN KEY(journey_id) REFERENCES care_journeys(journey_id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id)
        );
        CREATE INDEX IF NOT EXISTS idx_care_encounters_patient
        ON care_encounters(patient_link_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS care_encounter_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            encounter_id TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN (
                'CREATED','SCHEDULED','STARTED','COMPLETED','NO_SHOW',
                'CANCELLED','ENTERED_IN_ERROR'
            )),
            effective_at TEXT NOT NULL CHECK (datetime(effective_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username)) > 0),
            note TEXT,
            supersedes_event_id INTEGER UNIQUE,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (datetime(recorded_at) >= datetime(effective_at)),
            FOREIGN KEY(encounter_id) REFERENCES care_encounters(encounter_id),
            FOREIGN KEY(supersedes_event_id) REFERENCES care_encounter_events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_care_encounter_events_stream
        ON care_encounter_events(encounter_id, recorded_at DESC, id DESC);

        CREATE TABLE IF NOT EXISTS accounting_invoice_attribution_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            accounting_invoice_id INTEGER NOT NULL CHECK (accounting_invoice_id > 0),
            accounting_patient_id INTEGER NOT NULL CHECK (accounting_patient_id > 0),
            patient_link_id INTEGER NOT NULL,
            enrollment_id INTEGER NOT NULL,
            journey_id TEXT NOT NULL,
            encounter_id TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN (
                'ATTRIBUTED','REVOKED','ENTERED_IN_ERROR'
            )),
            reason_code TEXT NOT NULL CHECK (length(trim(reason_code)) > 0),
            effective_at TEXT NOT NULL CHECK (datetime(effective_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username)) > 0),
            note TEXT,
            supersedes_event_id INTEGER UNIQUE,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (datetime(recorded_at) >= datetime(effective_at)),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(enrollment_id) REFERENCES specialist_program_enrollments(id),
            FOREIGN KEY(journey_id) REFERENCES care_journeys(journey_id),
            FOREIGN KEY(encounter_id) REFERENCES care_encounters(encounter_id),
            FOREIGN KEY(supersedes_event_id)
                REFERENCES accounting_invoice_attribution_events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_invoice_attribution_invoice
        ON accounting_invoice_attribution_events(
            accounting_invoice_id, recorded_at DESC, id DESC
        );
        CREATE INDEX IF NOT EXISTS idx_invoice_attribution_patient
        ON accounting_invoice_attribution_events(
            patient_link_id, recorded_at DESC, id DESC
        );

        CREATE TRIGGER IF NOT EXISTS trg_specialist_enrollment_no_update
        BEFORE UPDATE ON specialist_program_enrollments
        BEGIN SELECT RAISE(ABORT, 'specialist enrollment is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS trg_specialist_enrollment_no_delete
        BEFORE DELETE ON specialist_program_enrollments
        BEGIN SELECT RAISE(ABORT, 'specialist enrollment cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_specialist_enrollment_identity
        BEFORE INSERT ON specialist_program_enrollments
        WHEN NOT EXISTS (
            SELECT 1 FROM patient_links patient
            WHERE patient.id=NEW.patient_link_id
              AND patient.accounting_patient_id=NEW.accounting_patient_id
        )
        BEGIN SELECT RAISE(ABORT, 'specialist enrollment identity mismatch'); END;
        CREATE TRIGGER IF NOT EXISTS trg_enrolled_accounting_identity_immutable
        BEFORE UPDATE OF accounting_patient_id ON patient_links
        WHEN EXISTS (
            SELECT 1 FROM specialist_program_enrollments enrollment
            WHERE enrollment.patient_link_id=OLD.id
        ) AND NEW.accounting_patient_id IS NOT OLD.accounting_patient_id
        BEGIN SELECT RAISE(ABORT, 'enrolled accounting identity is immutable'); END;

        CREATE TRIGGER IF NOT EXISTS trg_care_journeys_no_update
        BEFORE UPDATE ON care_journeys
        BEGIN SELECT RAISE(ABORT, 'care journey identity is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS trg_care_journeys_no_delete
        BEFORE DELETE ON care_journeys
        BEGIN SELECT RAISE(ABORT, 'care journeys cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_care_journey_events_no_update
        BEFORE UPDATE ON care_journey_events
        BEGIN SELECT RAISE(ABORT, 'care journey events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_care_journey_events_no_delete
        BEFORE DELETE ON care_journey_events
        BEGIN SELECT RAISE(ABORT, 'care journey events cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_care_journey_first_event
        BEFORE INSERT ON care_journey_events
        WHEN NOT EXISTS (
            SELECT 1 FROM care_journey_events e WHERE e.journey_id=NEW.journey_id
        ) AND (NEW.event_type<>'OPENED' OR NEW.supersedes_event_id IS NOT NULL)
        BEGIN SELECT RAISE(ABORT, 'first journey event must be OPENED'); END;
        CREATE TRIGGER IF NOT EXISTS trg_care_journey_linear_event
        BEFORE INSERT ON care_journey_events
        WHEN EXISTS (
            SELECT 1 FROM care_journey_events e WHERE e.journey_id=NEW.journey_id
        ) AND NEW.supersedes_event_id IS NOT (
            SELECT e.id FROM care_journey_events e
            WHERE e.journey_id=NEW.journey_id
            ORDER BY e.recorded_at DESC, e.id DESC LIMIT 1
        )
        BEGIN SELECT RAISE(ABORT, 'journey event must supersede current head'); END;

        CREATE TRIGGER IF NOT EXISTS trg_care_encounters_no_update
        BEFORE UPDATE ON care_encounters
        BEGIN SELECT RAISE(ABORT, 'care encounter identity is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS trg_care_encounters_no_delete
        BEFORE DELETE ON care_encounters
        BEGIN SELECT RAISE(ABORT, 'care encounters cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_care_encounter_patient_scope
        BEFORE INSERT ON care_encounters
        WHEN NOT EXISTS (
            SELECT 1 FROM care_journeys journey
            WHERE journey.journey_id=NEW.journey_id
              AND journey.patient_link_id=NEW.patient_link_id
        )
        BEGIN SELECT RAISE(ABORT, 'encounter patient must match journey patient'); END;
        CREATE TRIGGER IF NOT EXISTS trg_care_encounter_events_no_update
        BEFORE UPDATE ON care_encounter_events
        BEGIN SELECT RAISE(ABORT, 'care encounter events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_care_encounter_events_no_delete
        BEFORE DELETE ON care_encounter_events
        BEGIN SELECT RAISE(ABORT, 'care encounter events cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_care_encounter_first_event
        BEFORE INSERT ON care_encounter_events
        WHEN NOT EXISTS (
            SELECT 1 FROM care_encounter_events e
            WHERE e.encounter_id=NEW.encounter_id
        ) AND (NEW.event_type<>'CREATED' OR NEW.supersedes_event_id IS NOT NULL)
        BEGIN SELECT RAISE(ABORT, 'first encounter event must be CREATED'); END;
        CREATE TRIGGER IF NOT EXISTS trg_care_encounter_linear_event
        BEFORE INSERT ON care_encounter_events
        WHEN EXISTS (
            SELECT 1 FROM care_encounter_events e
            WHERE e.encounter_id=NEW.encounter_id
        ) AND NEW.supersedes_event_id IS NOT (
            SELECT e.id FROM care_encounter_events e
            WHERE e.encounter_id=NEW.encounter_id
            ORDER BY e.recorded_at DESC, e.id DESC LIMIT 1
        )
        BEGIN SELECT RAISE(ABORT, 'encounter event must supersede current head'); END;

        CREATE TRIGGER IF NOT EXISTS trg_invoice_attribution_no_update
        BEFORE UPDATE ON accounting_invoice_attribution_events
        BEGIN SELECT RAISE(ABORT, 'invoice attribution is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_invoice_attribution_no_delete
        BEFORE DELETE ON accounting_invoice_attribution_events
        BEGIN SELECT RAISE(ABORT, 'invoice attribution cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_invoice_attribution_scope
        BEFORE INSERT ON accounting_invoice_attribution_events
        WHEN NOT EXISTS (
            SELECT 1
            FROM specialist_program_enrollments enrollment
            JOIN care_journeys journey ON journey.enrollment_id=enrollment.id
            JOIN care_encounters encounter ON encounter.journey_id=journey.journey_id
            WHERE enrollment.id=NEW.enrollment_id
              AND enrollment.patient_link_id=NEW.patient_link_id
              AND enrollment.accounting_patient_id=NEW.accounting_patient_id
              AND journey.journey_id=NEW.journey_id
              AND journey.patient_link_id=NEW.patient_link_id
              AND encounter.encounter_id=NEW.encounter_id
              AND encounter.patient_link_id=NEW.patient_link_id
              AND encounter.accounting_invoice_id=NEW.accounting_invoice_id
              AND datetime(NEW.effective_at) >= datetime(enrollment.effective_at)
        )
        BEGIN SELECT RAISE(ABORT, 'invoice attribution scope mismatch'); END;
        """
    )
