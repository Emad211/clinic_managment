"""A7 payer breakdown, financial review, and evidenced adjustment storage.

Accounting remains read-only.  This schema stores only immutable specialist-side
observations and manager-reviewed correction evidence.  A missing refund/settlement row
is never interpreted as proof that no adjustment occurred; the current A4 observation
must receive an explicit review event before adjusted collection is publishable.
"""
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


def _backfill_review_obligations(db: sqlite3.Connection) -> None:
    rows = db.execute(
        """SELECT observation.id AS observation_id,
                  observation.accounting_invoice_id,
                  observation.journey_id,
                  observation.encounter_id,
                  observation.patient_link_id,
                  observation.observed_at
           FROM specialist_financial_observations observation
           WHERE observation.id=(
               SELECT latest.id FROM specialist_financial_observations latest
               WHERE latest.accounting_invoice_id=observation.accounting_invoice_id
               ORDER BY latest.observed_at DESC,latest.id DESC LIMIT 1
           ) AND NOT EXISTS (
               SELECT 1 FROM specialist_financial_review_events review
               WHERE review.accounting_invoice_id=observation.accounting_invoice_id
           )"""
    ).fetchall()
    for row in rows:
        key = f"financial-review-backfill:{int(row['accounting_invoice_id'])}:{int(row['observation_id'])}"
        payload = {
            "accounting_invoice_id": int(row["accounting_invoice_id"]),
            "financial_observation_id": int(row["observation_id"]),
            "journey_id": str(row["journey_id"]),
            "encounter_id": str(row["encounter_id"]),
            "patient_link_id": int(row["patient_link_id"]),
            "event_type": "REVIEW_REQUIRED",
            "status": "REVIEW_REQUIRED",
            "effective_at": str(row["observed_at"]),
            "recorded_at": str(row["observed_at"]),
            "actor_username": "system:a7-migration",
            "note": "Legacy observation requires explicit adjustment review.",
            "idempotency_key": key,
            "supersedes_event_id": None,
        }
        db.execute(
            """INSERT OR IGNORE INTO specialist_financial_review_events
               (accounting_invoice_id,financial_observation_id,journey_id,
                encounter_id,patient_link_id,event_type,status,effective_at,
                recorded_at,actor_username,note,idempotency_key,
                supersedes_event_id,content_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL,?)""",
            (*payload.values(), _hash(payload)),
        )


def ensure_specialist_payer_adjustment_storage(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS specialist_payer_breakdown_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            financial_observation_id INTEGER NOT NULL UNIQUE,
            accounting_invoice_id INTEGER NOT NULL,
            journey_id TEXT NOT NULL,
            encounter_id TEXT NOT NULL,
            patient_link_id INTEGER NOT NULL,
            patient_cash_collected INTEGER NOT NULL CHECK (patient_cash_collected>=0),
            patient_card_collected INTEGER NOT NULL CHECK (patient_card_collected>=0),
            insurance_collected INTEGER NOT NULL CHECK (insurance_collected>=0),
            unknown_collected INTEGER NOT NULL CHECK (unknown_collected>=0),
            unpaid_amount INTEGER NOT NULL CHECK (unpaid_amount>=0),
            paid_item_count INTEGER NOT NULL CHECK (paid_item_count>=0),
            unpaid_item_count INTEGER NOT NULL CHECK (unpaid_item_count>=0),
            unknown_payment_type_count INTEGER NOT NULL
                CHECK (unknown_payment_type_count>=0),
            evidence_code TEXT NOT NULL CHECK (evidence_code IN (
                'ACCOUNTING_ITEM_PAYMENT_TYPE_V1','LEGACY_UNAVAILABLE'
            )),
            source_fingerprint TEXT NOT NULL CHECK (length(source_fingerprint)=64),
            observed_at TEXT NOT NULL CHECK (datetime(observed_at) IS NOT NULL),
            created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
            created_by TEXT NOT NULL CHECK (length(trim(created_by))>0),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (
                patient_cash_collected+patient_card_collected+
                insurance_collected+unknown_collected=(
                    SELECT collected_amount
                    FROM specialist_financial_observations observation
                    WHERE observation.id=financial_observation_id
                )
            ),
            FOREIGN KEY(financial_observation_id)
                REFERENCES specialist_financial_observations(id),
            FOREIGN KEY(journey_id) REFERENCES care_journeys(journey_id),
            FOREIGN KEY(encounter_id) REFERENCES care_encounters(encounter_id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id)
        );
        CREATE INDEX IF NOT EXISTS idx_payer_breakdown_invoice
        ON specialist_payer_breakdown_observations(
            accounting_invoice_id,observed_at DESC,id DESC
        );

        CREATE TABLE IF NOT EXISTS specialist_financial_adjustment_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            adjustment_id TEXT NOT NULL,
            accounting_invoice_id INTEGER NOT NULL,
            financial_observation_id INTEGER NOT NULL,
            journey_id TEXT NOT NULL,
            encounter_id TEXT NOT NULL,
            patient_link_id INTEGER NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN (
                'RECORDED','CORRECTED','REVERSED','ENTERED_IN_ERROR'
            )),
            status TEXT NOT NULL CHECK (status IN (
                'ACTIVE','REVERSED','ENTERED_IN_ERROR'
            )),
            adjustment_type TEXT NOT NULL CHECK (adjustment_type IN (
                'REFUND','CHARGEBACK','INSURANCE_SETTLEMENT_CORRECTION',
                'WRITE_OFF','OTHER'
            )),
            signed_amount INTEGER NOT NULL CHECK (signed_amount<>0),
            evidence_type TEXT NOT NULL CHECK (evidence_type IN (
                'BANK_REFERENCE','INSURANCE_DOCUMENT','ACCOUNTING_ACTIVITY_LOG',
                'RECEIPT_DOCUMENT','MANUAL_VERIFIED'
            )),
            evidence_ref TEXT NOT NULL CHECK (length(trim(evidence_ref))>0),
            occurred_at TEXT NOT NULL CHECK (datetime(occurred_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username))>0),
            actor_user_id INTEGER,
            note TEXT,
            idempotency_key TEXT NOT NULL UNIQUE,
            supersedes_event_id INTEGER UNIQUE,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (datetime(recorded_at)>=datetime(occurred_at)),
            CHECK (
                (event_type IN ('RECORDED','CORRECTED') AND status='ACTIVE') OR
                (event_type='REVERSED' AND status='REVERSED') OR
                (event_type='ENTERED_IN_ERROR' AND status='ENTERED_IN_ERROR')
            ),
            CHECK (
                adjustment_type NOT IN ('REFUND','CHARGEBACK','WRITE_OFF')
                OR signed_amount<0
            ),
            FOREIGN KEY(financial_observation_id)
                REFERENCES specialist_financial_observations(id),
            FOREIGN KEY(journey_id) REFERENCES care_journeys(journey_id),
            FOREIGN KEY(encounter_id) REFERENCES care_encounters(encounter_id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(actor_user_id) REFERENCES users(id),
            FOREIGN KEY(supersedes_event_id)
                REFERENCES specialist_financial_adjustment_events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_financial_adjustment_stream
        ON specialist_financial_adjustment_events(
            adjustment_id,recorded_at DESC,id DESC
        );
        CREATE INDEX IF NOT EXISTS idx_financial_adjustment_invoice
        ON specialist_financial_adjustment_events(
            accounting_invoice_id,recorded_at DESC,id DESC
        );

        CREATE TABLE IF NOT EXISTS specialist_financial_review_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            accounting_invoice_id INTEGER NOT NULL,
            financial_observation_id INTEGER NOT NULL,
            journey_id TEXT NOT NULL,
            encounter_id TEXT NOT NULL,
            patient_link_id INTEGER NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN (
                'REVIEW_REQUIRED','REVIEWED_NO_ADJUSTMENT',
                'REVIEWED_WITH_ADJUSTMENT','REOPENED','ENTERED_IN_ERROR'
            )),
            status TEXT NOT NULL CHECK (status IN (
                'REVIEW_REQUIRED','REVIEWED','ENTERED_IN_ERROR'
            )),
            effective_at TEXT NOT NULL CHECK (datetime(effective_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username))>0),
            actor_user_id INTEGER,
            note TEXT,
            idempotency_key TEXT NOT NULL UNIQUE,
            supersedes_event_id INTEGER UNIQUE,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (datetime(recorded_at)>=datetime(effective_at)),
            CHECK (
                (event_type IN ('REVIEW_REQUIRED','REOPENED') AND
                 status='REVIEW_REQUIRED') OR
                (event_type IN ('REVIEWED_NO_ADJUSTMENT',
                                'REVIEWED_WITH_ADJUSTMENT') AND
                 status='REVIEWED') OR
                (event_type='ENTERED_IN_ERROR' AND
                 status='ENTERED_IN_ERROR')
            ),
            FOREIGN KEY(financial_observation_id)
                REFERENCES specialist_financial_observations(id),
            FOREIGN KEY(journey_id) REFERENCES care_journeys(journey_id),
            FOREIGN KEY(encounter_id) REFERENCES care_encounters(encounter_id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(actor_user_id) REFERENCES users(id),
            FOREIGN KEY(supersedes_event_id)
                REFERENCES specialist_financial_review_events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_financial_review_invoice
        ON specialist_financial_review_events(
            accounting_invoice_id,recorded_at DESC,id DESC
        );

        CREATE TRIGGER IF NOT EXISTS trg_payer_breakdown_no_update
        BEFORE UPDATE ON specialist_payer_breakdown_observations
        BEGIN SELECT RAISE(ABORT,'payer breakdown observation is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS trg_payer_breakdown_no_delete
        BEFORE DELETE ON specialist_payer_breakdown_observations
        BEGIN SELECT RAISE(ABORT,'payer breakdown observation cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_payer_breakdown_scope
        BEFORE INSERT ON specialist_payer_breakdown_observations
        WHEN NOT EXISTS (
            SELECT 1 FROM specialist_financial_observations observation
            WHERE observation.id=NEW.financial_observation_id
              AND observation.accounting_invoice_id=NEW.accounting_invoice_id
              AND observation.journey_id=NEW.journey_id
              AND observation.encounter_id=NEW.encounter_id
              AND observation.patient_link_id=NEW.patient_link_id
              AND observation.source_fingerprint=NEW.source_fingerprint
        )
        BEGIN SELECT RAISE(ABORT,'payer breakdown observation scope mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_financial_adjustment_no_update
        BEFORE UPDATE ON specialist_financial_adjustment_events
        BEGIN SELECT RAISE(ABORT,'financial adjustment events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_financial_adjustment_no_delete
        BEFORE DELETE ON specialist_financial_adjustment_events
        BEGIN SELECT RAISE(ABORT,'financial adjustment events cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_financial_adjustment_first
        BEFORE INSERT ON specialist_financial_adjustment_events
        WHEN NOT EXISTS (
            SELECT 1 FROM specialist_financial_adjustment_events event
            WHERE event.adjustment_id=NEW.adjustment_id
        ) AND (NEW.event_type<>'RECORDED' OR NEW.supersedes_event_id IS NOT NULL)
        BEGIN SELECT RAISE(ABORT,'first financial adjustment event must record'); END;
        CREATE TRIGGER IF NOT EXISTS trg_financial_adjustment_linear
        BEFORE INSERT ON specialist_financial_adjustment_events
        WHEN EXISTS (
            SELECT 1 FROM specialist_financial_adjustment_events event
            WHERE event.adjustment_id=NEW.adjustment_id
        ) AND NEW.supersedes_event_id IS NOT (
            SELECT event.id FROM specialist_financial_adjustment_events event
            WHERE event.adjustment_id=NEW.adjustment_id
            ORDER BY event.recorded_at DESC,event.id DESC LIMIT 1
        )
        BEGIN SELECT RAISE(ABORT,'financial adjustment must supersede current head'); END;
        CREATE TRIGGER IF NOT EXISTS trg_financial_adjustment_scope
        BEFORE INSERT ON specialist_financial_adjustment_events
        WHEN NOT EXISTS (
            SELECT 1 FROM specialist_financial_observations observation
            WHERE observation.id=NEW.financial_observation_id
              AND observation.accounting_invoice_id=NEW.accounting_invoice_id
              AND observation.journey_id=NEW.journey_id
              AND observation.encounter_id=NEW.encounter_id
              AND observation.patient_link_id=NEW.patient_link_id
        )
        BEGIN SELECT RAISE(ABORT,'financial adjustment scope mismatch'); END;
        CREATE TRIGGER IF NOT EXISTS trg_financial_adjustment_transition
        BEFORE INSERT ON specialist_financial_adjustment_events
        WHEN NEW.supersedes_event_id IS NOT NULL AND NOT (
            (NEW.event_type='CORRECTED' AND NEW.status='ACTIVE'
             AND length(trim(COALESCE(NEW.note,'')))>0) OR
            (NEW.event_type='REVERSED' AND NEW.status='REVERSED'
             AND length(trim(COALESCE(NEW.note,'')))>0) OR
            (NEW.event_type='ENTERED_IN_ERROR' AND
             NEW.status='ENTERED_IN_ERROR'
             AND length(trim(COALESCE(NEW.note,'')))>0)
        )
        BEGIN SELECT RAISE(ABORT,'invalid financial adjustment transition'); END;

        CREATE TRIGGER IF NOT EXISTS trg_financial_review_no_update
        BEFORE UPDATE ON specialist_financial_review_events
        BEGIN SELECT RAISE(ABORT,'financial review events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_financial_review_no_delete
        BEFORE DELETE ON specialist_financial_review_events
        BEGIN SELECT RAISE(ABORT,'financial review events cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_financial_review_first
        BEFORE INSERT ON specialist_financial_review_events
        WHEN NOT EXISTS (
            SELECT 1 FROM specialist_financial_review_events event
            WHERE event.accounting_invoice_id=NEW.accounting_invoice_id
        ) AND (NEW.event_type<>'REVIEW_REQUIRED' OR
               NEW.supersedes_event_id IS NOT NULL)
        BEGIN SELECT RAISE(ABORT,'first financial review event must require review'); END;
        CREATE TRIGGER IF NOT EXISTS trg_financial_review_linear
        BEFORE INSERT ON specialist_financial_review_events
        WHEN EXISTS (
            SELECT 1 FROM specialist_financial_review_events event
            WHERE event.accounting_invoice_id=NEW.accounting_invoice_id
        ) AND NEW.supersedes_event_id IS NOT (
            SELECT event.id FROM specialist_financial_review_events event
            WHERE event.accounting_invoice_id=NEW.accounting_invoice_id
            ORDER BY event.recorded_at DESC,event.id DESC LIMIT 1
        )
        BEGIN SELECT RAISE(ABORT,'financial review must supersede current head'); END;
        CREATE TRIGGER IF NOT EXISTS trg_financial_review_scope
        BEFORE INSERT ON specialist_financial_review_events
        WHEN NOT EXISTS (
            SELECT 1 FROM specialist_financial_observations observation
            WHERE observation.id=NEW.financial_observation_id
              AND observation.accounting_invoice_id=NEW.accounting_invoice_id
              AND observation.journey_id=NEW.journey_id
              AND observation.encounter_id=NEW.encounter_id
              AND observation.patient_link_id=NEW.patient_link_id
        )
        BEGIN SELECT RAISE(ABORT,'financial review scope mismatch'); END;
        CREATE TRIGGER IF NOT EXISTS trg_financial_review_transition
        BEFORE INSERT ON specialist_financial_review_events
        WHEN NEW.supersedes_event_id IS NOT NULL AND NOT (
            (NEW.event_type IN ('REVIEW_REQUIRED','REOPENED') AND
             NEW.status='REVIEW_REQUIRED') OR
            (NEW.event_type IN ('REVIEWED_NO_ADJUSTMENT',
                                'REVIEWED_WITH_ADJUSTMENT') AND
             NEW.status='REVIEWED') OR
            (NEW.event_type='ENTERED_IN_ERROR' AND
             NEW.status='ENTERED_IN_ERROR')
        )
        BEGIN SELECT RAISE(ABORT,'invalid financial review transition'); END;
        """
    )
    _backfill_review_obligations(db)
    db.commit()


__all__ = ["SCHEMA_VERSION", "ensure_specialist_payer_adjustment_storage"]
