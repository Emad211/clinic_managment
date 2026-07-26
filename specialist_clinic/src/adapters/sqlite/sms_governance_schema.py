"""Immutable consent, message-purpose and delivery-event storage for SMS governance."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import sqlite3


PURPOSES = ("CARE", "MARKETING", "LEGACY_UNCLASSIFIED")
CONSENT_PURPOSES = ("CARE", "MARKETING")
CONSENT_DECISIONS = ("GRANTED", "REVOKED")


def _canonical_hash(payload: dict) -> str:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _now(db: sqlite3.Connection) -> str:
    return str(
        db.execute(
            "SELECT datetime('now','+3 hours','+30 minutes')"
        ).fetchone()[0]
    )


def _insert_legacy_consent(
    db: sqlite3.Connection,
    *,
    patient_link_id: int,
    purpose: str,
    decision: str,
    effective_at: str,
    source_code: str,
) -> None:
    idempotency_key = f"sms-consent-migration:{patient_link_id}:{purpose}"
    payload = {
        "patient_link_id": int(patient_link_id),
        "purpose": purpose,
        "decision": decision,
        "source_code": source_code,
        "effective_at": effective_at,
        "recorded_at": effective_at,
        "actor_user_id": None,
        "actor_username": "system:sms-governance-migration",
        "reason_code": source_code,
        "note": None,
        "idempotency_key": idempotency_key,
        "supersedes_event_id": None,
    }
    db.execute(
        """INSERT OR IGNORE INTO sms_consent_events
           (patient_link_id, purpose, decision, source_code, effective_at,
            recorded_at, actor_user_id, actor_username, reason_code, note,
            idempotency_key, supersedes_event_id, content_hash)
           VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, ?, NULL, ?)""",
        (
            patient_link_id,
            purpose,
            decision,
            source_code,
            effective_at,
            effective_at,
            payload["actor_username"],
            source_code,
            idempotency_key,
            _canonical_hash(payload),
        ),
    )


def _backfill_consent(db: sqlite3.Connection) -> None:
    rows = db.execute(
        """SELECT id, COALESCE(sms_opt_out,0) AS sms_opt_out,
                  COALESCE(enrolled_at, updated_at,
                           datetime('now','+3 hours','+30 minutes')) AS effective_at
           FROM patient_links"""
    ).fetchall()
    for row in rows:
        patient_id = int(row["id"])
        effective_at = str(row["effective_at"] or _now(db))
        opted_out = bool(row["sms_opt_out"])
        for purpose in CONSENT_PURPOSES:
            exists = db.execute(
                """SELECT 1 FROM sms_consent_events
                   WHERE patient_link_id=? AND purpose=? LIMIT 1""",
                (patient_id, purpose),
            ).fetchone()
            if exists:
                continue
            if opted_out:
                decision = "REVOKED"
                source = "LEGACY_GLOBAL_OPT_OUT"
            elif purpose == "CARE":
                decision = "GRANTED"
                source = "LEGACY_CARE_RELATIONSHIP"
            else:
                # No historical evidence of promotional consent exists. Preserve safety
                # by requiring an explicit future grant instead of assuming opt-in.
                decision = "REVOKED"
                source = "LEGACY_NO_MARKETING_OPT_IN"
            _insert_legacy_consent(
                db,
                patient_link_id=patient_id,
                purpose=purpose,
                decision=decision,
                effective_at=effective_at,
                source_code=source,
            )


def _legacy_purpose(row) -> str:
    campaign_type = str(row["campaign_type"] or "").strip().lower()
    source_type = str(row["source_type"] or "").strip().lower()
    if campaign_type == "reminder":
        return "CARE"
    if row["campaign_id"] is not None:
        return "MARKETING"
    if source_type in {
        "engagement",
        "appointment",
        "appointment_reminder",
        "invoice_outreach",
        "care",
    }:
        return "CARE"
    return "LEGACY_UNCLASSIFIED"


def _backfill_message_governance(db: sqlite3.Connection) -> None:
    rows = db.execute(
        """SELECT message.id, message.campaign_id, message.patient_link_id,
                  message.recipient, message.provider, message.source_type,
                  message.created_at, campaign.campaign_type
           FROM sms_messages message
           LEFT JOIN sms_campaigns campaign ON campaign.id=message.campaign_id
           WHERE NOT EXISTS (
               SELECT 1 FROM sms_message_governance governance
               WHERE governance.message_id=message.id
           )"""
    ).fetchall()
    for row in rows:
        created_at = str(row["created_at"] or _now(db))
        purpose = _legacy_purpose(row)
        provider = str(row["provider"] or "legacy-unknown").strip().lower()
        payload = {
            "message_id": int(row["id"]),
            "patient_link_id": row["patient_link_id"],
            "purpose": purpose,
            "consent_decision": "LEGACY_UNKNOWN",
            "consent_event_id": None,
            "allowed_at_submission": 0,
            "provider_name": provider,
            "recipient_canonical": str(row["recipient"] or ""),
            "source_policy": "LEGACY_BACKFILL_UNTRUSTED",
            "created_at": created_at,
            "created_by": "system:sms-governance-migration",
        }
        db.execute(
            """INSERT INTO sms_message_governance
               (message_id, patient_link_id, purpose, consent_decision,
                consent_event_id, allowed_at_submission, provider_name,
                recipient_canonical, source_policy, created_at, created_by,
                content_hash)
               VALUES (?, ?, ?, 'LEGACY_UNKNOWN', NULL, 0, ?, ?,
                       'LEGACY_BACKFILL_UNTRUSTED', ?,
                       'system:sms-governance-migration', ?)""",
            (
                payload["message_id"],
                payload["patient_link_id"],
                purpose,
                provider,
                payload["recipient_canonical"],
                created_at,
                _canonical_hash(payload),
            ),
        )


def _backfill_delivery_events(db: sqlite3.Connection) -> None:
    rows = db.execute(
        """SELECT message.id, message.provider, message.delivery_status,
                  message.delivery_status_int, message.provider_request_id,
                  message.provider_msgid, message.error,
                  COALESCE(message.delivery_checked_at, message.sent_at,
                           message.created_at,
                           datetime('now','+3 hours','+30 minutes')) AS occurred_at
           FROM sms_messages message
           WHERE NOT EXISTS (
               SELECT 1 FROM sms_delivery_events event
               WHERE event.message_id=message.id
           )"""
    ).fetchall()
    for row in rows:
        occurred_at = str(row["occurred_at"] or _now(db))
        provider = str(row["provider"] or "legacy-unknown").strip().lower()
        status = str(row["delivery_status"] or "LegacyUnknown")
        payload = {
            "message_id": int(row["id"]),
            "provider_name": provider,
            "status": status,
            "status_int": row["delivery_status_int"],
            "occurred_at": occurred_at,
            "recorded_at": occurred_at,
            "source_code": "LEGACY_BACKFILL",
            "provider_request_id": row["provider_request_id"],
            "provider_msgid": row["provider_msgid"],
            "error_code": str(row["error"] or "")[:200] or None,
            "supersedes_event_id": None,
        }
        db.execute(
            """INSERT INTO sms_delivery_events
               (message_id, provider_name, status, status_int, occurred_at,
                recorded_at, source_code, provider_request_id, provider_msgid,
                error_code, supersedes_event_id, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, 'LEGACY_BACKFILL', ?, ?, ?, NULL, ?)""",
            (
                payload["message_id"],
                provider,
                status,
                payload["status_int"],
                occurred_at,
                occurred_at,
                payload["provider_request_id"],
                payload["provider_msgid"],
                payload["error_code"],
                _canonical_hash(payload),
            ),
        )


def ensure_sms_governance_storage(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS sms_consent_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_link_id INTEGER NOT NULL,
            purpose TEXT NOT NULL CHECK (purpose IN ('CARE','MARKETING')),
            decision TEXT NOT NULL CHECK (decision IN ('GRANTED','REVOKED')),
            source_code TEXT NOT NULL CHECK (length(trim(source_code))>0),
            effective_at TEXT NOT NULL CHECK (datetime(effective_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_user_id INTEGER,
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username))>0),
            reason_code TEXT,
            note TEXT,
            idempotency_key TEXT NOT NULL UNIQUE,
            supersedes_event_id INTEGER UNIQUE,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (datetime(recorded_at)>=datetime(effective_at)),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(actor_user_id) REFERENCES users(id),
            FOREIGN KEY(supersedes_event_id) REFERENCES sms_consent_events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_sms_consent_current
        ON sms_consent_events(patient_link_id, purpose, recorded_at DESC, id DESC);

        CREATE TABLE IF NOT EXISTS sms_message_governance (
            message_id INTEGER PRIMARY KEY,
            patient_link_id INTEGER,
            purpose TEXT NOT NULL CHECK (purpose IN (
                'CARE','MARKETING','LEGACY_UNCLASSIFIED'
            )),
            consent_decision TEXT NOT NULL CHECK (consent_decision IN (
                'GRANTED','REVOKED','LEGACY_UNKNOWN'
            )),
            consent_event_id INTEGER,
            allowed_at_submission INTEGER NOT NULL CHECK (
                allowed_at_submission IN (0,1)
            ),
            provider_name TEXT NOT NULL CHECK (length(trim(provider_name))>0),
            recipient_canonical TEXT NOT NULL,
            source_policy TEXT NOT NULL CHECK (length(trim(source_policy))>0),
            created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
            created_by TEXT NOT NULL CHECK (length(trim(created_by))>0),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            FOREIGN KEY(message_id) REFERENCES sms_messages(id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(consent_event_id) REFERENCES sms_consent_events(id)
        );

        CREATE TABLE IF NOT EXISTS sms_delivery_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            provider_name TEXT NOT NULL CHECK (length(trim(provider_name))>0),
            status TEXT NOT NULL CHECK (length(trim(status))>0),
            status_int INTEGER,
            occurred_at TEXT NOT NULL CHECK (datetime(occurred_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            source_code TEXT NOT NULL CHECK (source_code IN (
                'LEGACY_BACKFILL','SUBMISSION','PROVIDER_POLL','SYSTEM_EXPIRY'
            )),
            provider_request_id TEXT,
            provider_msgid TEXT,
            error_code TEXT,
            supersedes_event_id INTEGER UNIQUE,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (datetime(recorded_at)>=datetime(occurred_at)),
            FOREIGN KEY(message_id) REFERENCES sms_messages(id),
            FOREIGN KEY(supersedes_event_id) REFERENCES sms_delivery_events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_sms_delivery_stream
        ON sms_delivery_events(message_id, recorded_at DESC, id DESC);

        CREATE TRIGGER IF NOT EXISTS trg_sms_consent_no_update
        BEFORE UPDATE ON sms_consent_events
        BEGIN SELECT RAISE(ABORT, 'SMS consent events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_sms_consent_no_delete
        BEFORE DELETE ON sms_consent_events
        BEGIN SELECT RAISE(ABORT, 'SMS consent events cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_sms_consent_first_event
        BEFORE INSERT ON sms_consent_events
        WHEN NOT EXISTS (
            SELECT 1 FROM sms_consent_events event
            WHERE event.patient_link_id=NEW.patient_link_id
              AND event.purpose=NEW.purpose
        ) AND NEW.supersedes_event_id IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'first SMS consent event cannot supersede'); END;
        CREATE TRIGGER IF NOT EXISTS trg_sms_consent_linear_event
        BEFORE INSERT ON sms_consent_events
        WHEN EXISTS (
            SELECT 1 FROM sms_consent_events event
            WHERE event.patient_link_id=NEW.patient_link_id
              AND event.purpose=NEW.purpose
        ) AND NEW.supersedes_event_id IS NOT (
            SELECT event.id FROM sms_consent_events event
            WHERE event.patient_link_id=NEW.patient_link_id
              AND event.purpose=NEW.purpose
            ORDER BY event.recorded_at DESC, event.id DESC LIMIT 1
        )
        BEGIN SELECT RAISE(ABORT, 'SMS consent event must supersede current head'); END;

        CREATE TRIGGER IF NOT EXISTS trg_sms_governance_no_update
        BEFORE UPDATE ON sms_message_governance
        BEGIN SELECT RAISE(ABORT, 'SMS message governance is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS trg_sms_governance_no_delete
        BEFORE DELETE ON sms_message_governance
        BEGIN SELECT RAISE(ABORT, 'SMS message governance cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_sms_governance_consent_scope
        BEFORE INSERT ON sms_message_governance
        WHEN NEW.consent_event_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM sms_consent_events consent
            WHERE consent.id=NEW.consent_event_id
              AND consent.patient_link_id=NEW.patient_link_id
              AND consent.purpose=NEW.purpose
              AND consent.decision=NEW.consent_decision
        )
        BEGIN SELECT RAISE(ABORT, 'SMS governance consent scope mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_sms_message_submission_governance
        BEFORE UPDATE OF delivery_status ON sms_messages
        WHEN NEW.delivery_status='Submitting' AND NOT EXISTS (
            SELECT 1 FROM sms_message_governance governance
            WHERE governance.message_id=NEW.id
              AND governance.allowed_at_submission=1
              AND governance.consent_decision='GRANTED'
              AND governance.provider_name=NEW.provider
        )
        BEGIN SELECT RAISE(ABORT, 'SMS submission requires governed consent'); END;

        CREATE TRIGGER IF NOT EXISTS trg_sms_delivery_no_update
        BEFORE UPDATE ON sms_delivery_events
        BEGIN SELECT RAISE(ABORT, 'SMS delivery events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_sms_delivery_no_delete
        BEFORE DELETE ON sms_delivery_events
        BEGIN SELECT RAISE(ABORT, 'SMS delivery events cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_sms_delivery_first_event
        BEFORE INSERT ON sms_delivery_events
        WHEN NOT EXISTS (
            SELECT 1 FROM sms_delivery_events event
            WHERE event.message_id=NEW.message_id
        ) AND NEW.supersedes_event_id IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'first SMS delivery event cannot supersede'); END;
        CREATE TRIGGER IF NOT EXISTS trg_sms_delivery_linear_event
        BEFORE INSERT ON sms_delivery_events
        WHEN EXISTS (
            SELECT 1 FROM sms_delivery_events event
            WHERE event.message_id=NEW.message_id
        ) AND NEW.supersedes_event_id IS NOT (
            SELECT event.id FROM sms_delivery_events event
            WHERE event.message_id=NEW.message_id
            ORDER BY event.recorded_at DESC, event.id DESC LIMIT 1
        )
        BEGIN SELECT RAISE(ABORT, 'SMS delivery event must supersede current head'); END;
        """
    )
    _backfill_consent(db)
    _backfill_message_governance(db)
    _backfill_delivery_events(db)
    db.commit()


__all__ = [
    "CONSENT_DECISIONS",
    "CONSENT_PURPOSES",
    "PURPOSES",
    "ensure_sms_governance_storage",
]
