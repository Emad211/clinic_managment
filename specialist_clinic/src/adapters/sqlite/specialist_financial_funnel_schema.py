"""Append-only specialist appointment linkage and accounting financial observations."""
from __future__ import annotations

import sqlite3


def ensure_specialist_financial_funnel_storage(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS encounter_appointment_links (
            link_id TEXT PRIMARY KEY,
            appointment_id INTEGER NOT NULL UNIQUE,
            encounter_id TEXT NOT NULL UNIQUE,
            journey_id TEXT NOT NULL,
            patient_link_id INTEGER NOT NULL,
            created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
            created_by TEXT NOT NULL CHECK (length(trim(created_by))>0),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            FOREIGN KEY(appointment_id) REFERENCES appointments(id),
            FOREIGN KEY(encounter_id) REFERENCES care_encounters(encounter_id),
            FOREIGN KEY(journey_id) REFERENCES care_journeys(journey_id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id)
        );
        CREATE INDEX IF NOT EXISTS idx_encounter_appointment_patient
        ON encounter_appointment_links(patient_link_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS encounter_appointment_link_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            link_id TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN (
                'LINKED','ENTERED_IN_ERROR'
            )),
            status TEXT NOT NULL CHECK (status IN ('LINKED','ENTERED_IN_ERROR')),
            reason_code TEXT NOT NULL CHECK (length(trim(reason_code))>0),
            effective_at TEXT NOT NULL CHECK (datetime(effective_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username))>0),
            note TEXT,
            supersedes_event_id INTEGER UNIQUE,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (datetime(recorded_at)>=datetime(effective_at)),
            FOREIGN KEY(link_id) REFERENCES encounter_appointment_links(link_id),
            FOREIGN KEY(supersedes_event_id)
                REFERENCES encounter_appointment_link_events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_encounter_appointment_link_stream
        ON encounter_appointment_link_events(link_id, recorded_at DESC, id DESC);

        CREATE TABLE IF NOT EXISTS specialist_financial_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            accounting_invoice_id INTEGER NOT NULL CHECK (accounting_invoice_id>0),
            accounting_patient_id INTEGER NOT NULL CHECK (accounting_patient_id>0),
            patient_link_id INTEGER NOT NULL,
            journey_id TEXT NOT NULL,
            encounter_id TEXT NOT NULL,
            encounter_completion_event_id INTEGER NOT NULL,
            appointment_id INTEGER,
            invoice_status TEXT NOT NULL CHECK (length(trim(invoice_status))>0),
            work_date TEXT,
            closed_at TEXT CHECK (closed_at IS NULL OR datetime(closed_at) IS NOT NULL),
            source_total_amount INTEGER,
            visits_billed INTEGER NOT NULL DEFAULT 0 CHECK (visits_billed>=0),
            injections_billed INTEGER NOT NULL DEFAULT 0 CHECK (injections_billed>=0),
            procedures_billed INTEGER NOT NULL DEFAULT 0 CHECK (procedures_billed>=0),
            billed_amount INTEGER NOT NULL CHECK (billed_amount>=0),
            visits_collected INTEGER NOT NULL DEFAULT 0 CHECK (visits_collected>=0),
            injections_collected INTEGER NOT NULL DEFAULT 0 CHECK (injections_collected>=0),
            procedures_collected INTEGER NOT NULL DEFAULT 0 CHECK (procedures_collected>=0),
            collected_amount INTEGER NOT NULL CHECK (
                collected_amount>=0 AND collected_amount<=billed_amount
            ),
            billable_item_count INTEGER NOT NULL CHECK (billable_item_count>=0),
            paid_item_count INTEGER NOT NULL CHECK (
                paid_item_count>=0 AND paid_item_count<=billable_item_count
            ),
            collection_state TEXT NOT NULL CHECK (collection_state IN (
                'WAITING_FOR_INVOICE_CLOSURE','UNPAID','PARTIALLY_COLLECTED',
                'COLLECTED','CLOSED_NO_BILLABLE_ITEMS'
            )),
            payment_evidence TEXT NOT NULL DEFAULT 'ITEM_PAID_FLAGS'
                CHECK (payment_evidence='ITEM_PAID_FLAGS'),
            source_fingerprint TEXT NOT NULL CHECK (length(source_fingerprint)=64),
            observed_at TEXT NOT NULL CHECK (datetime(observed_at) IS NOT NULL),
            created_by TEXT NOT NULL CHECK (length(trim(created_by))>0),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            UNIQUE(accounting_invoice_id, source_fingerprint),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(journey_id) REFERENCES care_journeys(journey_id),
            FOREIGN KEY(encounter_id) REFERENCES care_encounters(encounter_id),
            FOREIGN KEY(encounter_completion_event_id)
                REFERENCES care_encounter_events(id),
            FOREIGN KEY(appointment_id) REFERENCES appointments(id)
        );
        CREATE INDEX IF NOT EXISTS idx_specialist_financial_invoice
        ON specialist_financial_observations(
            accounting_invoice_id, observed_at DESC, id DESC
        );
        CREATE INDEX IF NOT EXISTS idx_specialist_financial_patient
        ON specialist_financial_observations(patient_link_id, observed_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_specialist_financial_state
        ON specialist_financial_observations(collection_state, work_date, id DESC);

        CREATE TRIGGER IF NOT EXISTS trg_encounter_appointment_link_no_update
        BEFORE UPDATE ON encounter_appointment_links
        BEGIN SELECT RAISE(ABORT, 'encounter appointment link is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS trg_encounter_appointment_link_no_delete
        BEFORE DELETE ON encounter_appointment_links
        BEGIN SELECT RAISE(ABORT, 'encounter appointment link cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_encounter_appointment_event_no_update
        BEFORE UPDATE ON encounter_appointment_link_events
        BEGIN SELECT RAISE(ABORT, 'appointment link events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_encounter_appointment_event_no_delete
        BEFORE DELETE ON encounter_appointment_link_events
        BEGIN SELECT RAISE(ABORT, 'appointment link events cannot be deleted'); END;

        CREATE TRIGGER IF NOT EXISTS trg_encounter_appointment_scope
        BEFORE INSERT ON encounter_appointment_links
        WHEN NOT EXISTS (
            SELECT 1
            FROM appointments appointment
            JOIN care_encounters encounter
              ON encounter.encounter_id=NEW.encounter_id
            JOIN care_journeys journey
              ON journey.journey_id=encounter.journey_id
            WHERE appointment.id=NEW.appointment_id
              AND appointment.patient_link_id=NEW.patient_link_id
              AND encounter.patient_link_id=NEW.patient_link_id
              AND encounter.journey_id=NEW.journey_id
              AND journey.patient_link_id=NEW.patient_link_id
        )
        BEGIN SELECT RAISE(ABORT, 'appointment/encounter scope mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_encounter_appointment_first_event
        BEFORE INSERT ON encounter_appointment_link_events
        WHEN NOT EXISTS (
            SELECT 1 FROM encounter_appointment_link_events prior
            WHERE prior.link_id=NEW.link_id
        ) AND (
            NEW.event_type<>'LINKED' OR NEW.status<>'LINKED'
            OR NEW.supersedes_event_id IS NOT NULL
        )
        BEGIN SELECT RAISE(ABORT, 'first appointment link event must be LINKED'); END;

        CREATE TRIGGER IF NOT EXISTS trg_encounter_appointment_next_event
        BEFORE INSERT ON encounter_appointment_link_events
        WHEN EXISTS (
            SELECT 1 FROM encounter_appointment_link_events prior
            WHERE prior.link_id=NEW.link_id
        ) AND NEW.supersedes_event_id IS NOT (
            SELECT head.id FROM encounter_appointment_link_events head
            WHERE head.link_id=NEW.link_id
            ORDER BY head.recorded_at DESC, head.id DESC LIMIT 1
        )
        BEGIN SELECT RAISE(ABORT, 'appointment link event must supersede current head'); END;

        CREATE TRIGGER IF NOT EXISTS trg_financial_observation_no_update
        BEFORE UPDATE ON specialist_financial_observations
        BEGIN SELECT RAISE(ABORT, 'financial observations are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_financial_observation_no_delete
        BEFORE DELETE ON specialist_financial_observations
        BEGIN SELECT RAISE(ABORT, 'financial observations cannot be deleted'); END;

        CREATE TRIGGER IF NOT EXISTS trg_financial_observation_scope
        BEFORE INSERT ON specialist_financial_observations
        WHEN NOT EXISTS (
            SELECT 1
            FROM accounting_invoice_attribution_events attribution
            JOIN care_encounters encounter
              ON encounter.encounter_id=attribution.encounter_id
            JOIN care_journeys journey
              ON journey.journey_id=encounter.journey_id
            JOIN care_encounter_events completion
              ON completion.id=NEW.encounter_completion_event_id
            WHERE attribution.accounting_invoice_id=NEW.accounting_invoice_id
              AND attribution.id=(
                  SELECT head.id FROM accounting_invoice_attribution_events head
                  WHERE head.accounting_invoice_id=NEW.accounting_invoice_id
                  ORDER BY head.recorded_at DESC, head.id DESC LIMIT 1
              )
              AND attribution.event_type='ATTRIBUTED'
              AND attribution.accounting_patient_id=NEW.accounting_patient_id
              AND attribution.patient_link_id=NEW.patient_link_id
              AND attribution.journey_id=NEW.journey_id
              AND attribution.encounter_id=NEW.encounter_id
              AND encounter.accounting_invoice_id=NEW.accounting_invoice_id
              AND encounter.patient_link_id=NEW.patient_link_id
              AND encounter.journey_id=NEW.journey_id
              AND journey.patient_link_id=NEW.patient_link_id
              AND completion.encounter_id=NEW.encounter_id
              AND completion.event_type='COMPLETED'
              AND completion.id=(
                  SELECT latest.id FROM care_encounter_events latest
                  WHERE latest.encounter_id=NEW.encounter_id
                  ORDER BY latest.recorded_at DESC, latest.id DESC LIMIT 1
              )
              AND (
                  NEW.appointment_id IS NULL OR EXISTS (
                      SELECT 1
                      FROM encounter_appointment_links link
                      JOIN encounter_appointment_link_events link_event
                        ON link_event.link_id=link.link_id
                      WHERE link.appointment_id=NEW.appointment_id
                        AND link.encounter_id=NEW.encounter_id
                        AND link.patient_link_id=NEW.patient_link_id
                        AND link_event.id=(
                            SELECT link_head.id
                            FROM encounter_appointment_link_events link_head
                            WHERE link_head.link_id=link.link_id
                            ORDER BY link_head.recorded_at DESC, link_head.id DESC LIMIT 1
                        )
                        AND link_event.status='LINKED'
                  )
              )
        )
        BEGIN SELECT RAISE(ABORT, 'financial observation scope mismatch'); END;
        """
    )
    db.commit()
