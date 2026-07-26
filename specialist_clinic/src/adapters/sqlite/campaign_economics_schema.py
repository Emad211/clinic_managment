"""Immutable campaign execution, audience, response, attribution and direct-cost storage.

A6 does not infer revenue from time windows or provider acceptance.  Campaign economics
can be published only through the explicit chain:

    frozen audience -> governed message -> patient response -> CareJourney
    -> completed Encounter -> attributed invoice -> financial observation

The accounting database remains read-only; all tables below live in ``specialist.db``.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
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


def _now(db: sqlite3.Connection) -> str:
    return str(
        db.execute(
            "SELECT datetime('now','+3 hours','+30 minutes')"
        ).fetchone()[0]
    )


def _legacy_lifecycle_status(value: str | None) -> tuple[str, str, str | None]:
    normalized = str(value or "draft").strip().lower()
    if normalized == "scheduled":
        return "SCHEDULED", "SCHEDULED", None
    if normalized == "sending":
        return "SENDING", "SENDING", None
    if normalized == "done":
        return "COMPLETED", "COMPLETED", "LEGACY_UNVERIFIED"
    if normalized == "cancelled":
        return "CANCELLED", "CANCELLED", None
    if normalized in {"failed", "error"}:
        return "FAILED", "FAILED", "LEGACY_FAILURE"
    return "CREATED", "DRAFT", None


def _backfill_campaign_lifecycle(db: sqlite3.Connection) -> None:
    rows = db.execute(
        """SELECT id, status, scheduled_at, created_at, created_by
           FROM sms_campaigns
           WHERE NOT EXISTS (
               SELECT 1 FROM campaign_lifecycle_events event
               WHERE event.campaign_id=sms_campaigns.id
           )"""
    ).fetchall()
    for row in rows:
        event_type, status, outcome = _legacy_lifecycle_status(row["status"])
        recorded = str(row["created_at"] or _now(db))
        execution_id = (
            f"legacy-execution:{int(row['id'])}"
            if status in {"PREPARING", "SENDING", "AWAITING_DELIVERY", "COMPLETED", "FAILED"}
            else None
        )
        key = f"campaign-lifecycle-backfill:{int(row['id'])}"
        payload = {
            "campaign_id": int(row["id"]),
            "event_type": event_type,
            "status": status,
            "execution_id": execution_id,
            "outcome_code": outcome,
            "effective_at": recorded,
            "recorded_at": recorded,
            "actor_username": "system:campaign-economics-migration",
            "note": "Legacy mutable campaign status backfill; not trusted for ROI.",
            "idempotency_key": key,
            "supersedes_event_id": None,
        }
        db.execute(
            """INSERT OR IGNORE INTO campaign_lifecycle_events
               (campaign_id,event_type,status,execution_id,outcome_code,
                effective_at,recorded_at,actor_username,note,idempotency_key,
                supersedes_event_id,content_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?)""",
            (
                payload["campaign_id"], payload["event_type"], payload["status"],
                payload["execution_id"], payload["outcome_code"],
                payload["effective_at"], payload["recorded_at"],
                payload["actor_username"], payload["note"],
                payload["idempotency_key"], _hash(payload),
            ),
        )


def _legacy_audience_rows(db: sqlite3.Connection, campaign_id: int) -> list[dict]:
    rows = db.execute(
        """SELECT audience.patient_link_id, audience.accounting_patient_id,
                  upper(COALESCE(audience.grp,'treated')) AS legacy_group,
                  patient.phone_number
           FROM campaign_audience audience
           LEFT JOIN patient_links patient ON patient.id=audience.patient_link_id
           WHERE audience.campaign_id=?
           ORDER BY audience.id""",
        (int(campaign_id),),
    ).fetchall()
    output = [dict(row) for row in rows]
    known = {int(row["patient_link_id"]) for row in output if row["patient_link_id"]}
    messages = db.execute(
        """SELECT DISTINCT message.patient_link_id,
                  patient.accounting_patient_id, patient.phone_number
           FROM sms_messages message
           LEFT JOIN patient_links patient ON patient.id=message.patient_link_id
           WHERE message.campaign_id=? AND message.patient_link_id IS NOT NULL
           ORDER BY message.patient_link_id""",
        (int(campaign_id),),
    ).fetchall()
    for row in messages:
        patient_id = int(row["patient_link_id"])
        if patient_id in known:
            continue
        output.append(
            {
                "patient_link_id": patient_id,
                "accounting_patient_id": row["accounting_patient_id"],
                "legacy_group": "TREATED",
                "phone_number": row["phone_number"],
            }
        )
    return output


def _backfill_campaign_audience(db: sqlite3.Connection) -> None:
    campaigns = db.execute(
        """SELECT campaign.id, campaign.segment, campaign.campaign_type,
                  campaign.holdout_percent, campaign.created_at
           FROM sms_campaigns campaign
           WHERE NOT EXISTS (
               SELECT 1 FROM campaign_audience_snapshots snapshot
               WHERE snapshot.campaign_id=campaign.id
           )
             AND (
                 EXISTS (SELECT 1 FROM campaign_audience old
                         WHERE old.campaign_id=campaign.id)
                 OR EXISTS (SELECT 1 FROM sms_messages message
                            WHERE message.campaign_id=campaign.id)
             )"""
    ).fetchall()
    for campaign in campaigns:
        campaign_id = int(campaign["id"])
        members = _legacy_audience_rows(db, campaign_id)
        if not members:
            continue
        snapshot_id = "audience_legacy_" + uuid.uuid4().hex
        created = str(campaign["created_at"] or _now(db))
        treated = sum(
            1 for row in members if str(row["legacy_group"]).upper() != "CONTROL"
        )
        control = len(members) - treated
        purpose = "CARE" if campaign["campaign_type"] == "reminder" else "MARKETING"
        root = {
            "snapshot_id": snapshot_id,
            "campaign_id": campaign_id,
            "execution_id": f"legacy-execution:{campaign_id}",
            "snapshot_version": 1,
            "source_code": "LEGACY_BACKFILL_UNTRUSTED",
            "segment_key": str(campaign["segment"] or "legacy"),
            "purpose": purpose,
            "holdout_percent": int(campaign["holdout_percent"] or 0),
            "random_seed": f"legacy:{campaign_id}",
            "candidate_count": len(members),
            "eligible_count": len(members),
            "treated_count": treated,
            "control_count": control,
            "excluded_count": 0,
            "created_at": created,
            "created_by": "system:campaign-economics-migration",
        }
        db.execute(
            """INSERT INTO campaign_audience_snapshots
               (snapshot_id,campaign_id,execution_id,snapshot_version,source_code,
                segment_key,purpose,holdout_percent,random_seed,candidate_count,
                eligible_count,treated_count,control_count,excluded_count,
                created_at,created_by,content_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (*root.values(), _hash(root)),
        )
        for rank, row in enumerate(members, start=1):
            group = (
                "CONTROL"
                if str(row["legacy_group"]).upper() == "CONTROL"
                else "TREATED"
            )
            member = {
                "snapshot_id": snapshot_id,
                "campaign_id": campaign_id,
                "patient_link_id": int(row["patient_link_id"]),
                "accounting_patient_id": row["accounting_patient_id"],
                "assignment": group,
                "eligibility": "LEGACY_UNKNOWN",
                "finance_scope": "LEGACY_UNKNOWN",
                "consent_event_id": None,
                "consent_decision": "LEGACY_UNKNOWN",
                "recipient_canonical": str(row["phone_number"] or ""),
                "assigned_rank": rank,
                "exclusion_reason": None,
            }
            db.execute(
                """INSERT INTO campaign_audience_members
                   (snapshot_id,campaign_id,patient_link_id,accounting_patient_id,
                    assignment,eligibility,finance_scope,consent_event_id,
                    consent_decision,recipient_canonical,assigned_rank,
                    exclusion_reason,content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*member.values(), _hash(member)),
            )


def ensure_campaign_economics_storage(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS campaign_lifecycle_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN (
                'CREATED','SCHEDULED','PREPARING','SENDING',
                'AWAITING_DELIVERY','COMPLETED','FAILED','CANCELLED',
                'ENTERED_IN_ERROR'
            )),
            status TEXT NOT NULL CHECK (status IN (
                'DRAFT','SCHEDULED','PREPARING','SENDING',
                'AWAITING_DELIVERY','COMPLETED','FAILED','CANCELLED',
                'ENTERED_IN_ERROR'
            )),
            execution_id TEXT,
            outcome_code TEXT,
            effective_at TEXT NOT NULL CHECK (datetime(effective_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username))>0),
            note TEXT,
            idempotency_key TEXT NOT NULL UNIQUE,
            supersedes_event_id INTEGER UNIQUE,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (datetime(recorded_at)>=datetime(effective_at)),
            CHECK (
                (event_type='CREATED' AND status='DRAFT') OR
                (event_type='SCHEDULED' AND status='SCHEDULED') OR
                (event_type='PREPARING' AND status='PREPARING') OR
                (event_type='SENDING' AND status='SENDING') OR
                (event_type='AWAITING_DELIVERY' AND status='AWAITING_DELIVERY') OR
                (event_type='COMPLETED' AND status='COMPLETED') OR
                (event_type='FAILED' AND status='FAILED') OR
                (event_type='CANCELLED' AND status='CANCELLED') OR
                (event_type='ENTERED_IN_ERROR' AND status='ENTERED_IN_ERROR')
            ),
            CHECK (
                status IN ('DRAFT','SCHEDULED','CANCELLED')
                OR length(trim(COALESCE(execution_id,'')))>0
            ),
            FOREIGN KEY(campaign_id) REFERENCES sms_campaigns(id),
            FOREIGN KEY(supersedes_event_id) REFERENCES campaign_lifecycle_events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_campaign_lifecycle_current
        ON campaign_lifecycle_events(campaign_id,recorded_at DESC,id DESC);

        CREATE TABLE IF NOT EXISTS campaign_audience_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            campaign_id INTEGER NOT NULL UNIQUE,
            execution_id TEXT NOT NULL UNIQUE,
            snapshot_version INTEGER NOT NULL CHECK (snapshot_version=1),
            source_code TEXT NOT NULL CHECK (source_code IN (
                'NEW_FROZEN','LEGACY_BACKFILL_UNTRUSTED'
            )),
            segment_key TEXT NOT NULL CHECK (length(trim(segment_key))>0),
            purpose TEXT NOT NULL CHECK (purpose IN ('CARE','MARKETING')),
            holdout_percent INTEGER NOT NULL CHECK (
                holdout_percent BETWEEN 0 AND 50
            ),
            random_seed TEXT NOT NULL CHECK (length(trim(random_seed))>0),
            candidate_count INTEGER NOT NULL CHECK (candidate_count>=0),
            eligible_count INTEGER NOT NULL CHECK (eligible_count>=0),
            treated_count INTEGER NOT NULL CHECK (treated_count>=0),
            control_count INTEGER NOT NULL CHECK (control_count>=0),
            excluded_count INTEGER NOT NULL CHECK (excluded_count>=0),
            created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
            created_by TEXT NOT NULL CHECK (length(trim(created_by))>0),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (candidate_count=eligible_count+excluded_count),
            CHECK (eligible_count=treated_count+control_count),
            FOREIGN KEY(campaign_id) REFERENCES sms_campaigns(id)
        );

        CREATE TABLE IF NOT EXISTS campaign_audience_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id TEXT NOT NULL,
            campaign_id INTEGER NOT NULL,
            patient_link_id INTEGER NOT NULL,
            accounting_patient_id INTEGER,
            assignment TEXT NOT NULL CHECK (assignment IN (
                'TREATED','CONTROL','EXCLUDED'
            )),
            eligibility TEXT NOT NULL CHECK (eligibility IN (
                'ELIGIBLE','CONSENT_REVOKED','INVALID_PHONE','LEGACY_UNKNOWN'
            )),
            finance_scope TEXT NOT NULL CHECK (finance_scope IN (
                'ATTRIBUTABLE','NO_ACCOUNTING_LINK','LEGACY_UNKNOWN'
            )),
            consent_event_id INTEGER,
            consent_decision TEXT NOT NULL CHECK (consent_decision IN (
                'GRANTED','REVOKED','LEGACY_UNKNOWN'
            )),
            recipient_canonical TEXT,
            assigned_rank INTEGER NOT NULL CHECK (assigned_rank>0),
            exclusion_reason TEXT,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            UNIQUE(campaign_id,patient_link_id),
            CHECK (
                (assignment='EXCLUDED' AND eligibility<>'ELIGIBLE') OR
                (assignment IN ('TREATED','CONTROL') AND eligibility IN (
                    'ELIGIBLE','LEGACY_UNKNOWN'
                ))
            ),
            FOREIGN KEY(snapshot_id) REFERENCES campaign_audience_snapshots(snapshot_id),
            FOREIGN KEY(campaign_id) REFERENCES sms_campaigns(id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(consent_event_id) REFERENCES sms_consent_events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_campaign_audience_assignment
        ON campaign_audience_members(campaign_id,assignment,assigned_rank);

        CREATE TABLE IF NOT EXISTS campaign_response_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            patient_link_id INTEGER NOT NULL,
            message_id INTEGER,
            response_type TEXT NOT NULL CHECK (response_type IN (
                'POSITIVE','NEGATIVE','NO_RESPONSE','OPT_OUT'
            )),
            evidence_type TEXT NOT NULL CHECK (evidence_type IN (
                'INBOUND_REPLY','PATIENT_STATED','STAFF_PHONE_CALL',
                'LEGACY_UNKNOWN'
            )),
            evidence_ref TEXT,
            occurred_at TEXT NOT NULL CHECK (datetime(occurred_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username))>0),
            note TEXT,
            idempotency_key TEXT NOT NULL UNIQUE,
            supersedes_event_id INTEGER UNIQUE,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (datetime(recorded_at)>=datetime(occurred_at)),
            FOREIGN KEY(campaign_id) REFERENCES sms_campaigns(id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(message_id) REFERENCES sms_messages(id),
            FOREIGN KEY(supersedes_event_id) REFERENCES campaign_response_events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_campaign_response_current
        ON campaign_response_events(campaign_id,patient_link_id,recorded_at DESC,id DESC);

        CREATE TABLE IF NOT EXISTS campaign_journey_attribution_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            journey_id TEXT NOT NULL,
            campaign_id INTEGER NOT NULL,
            patient_link_id INTEGER NOT NULL,
            response_event_id INTEGER NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN (
                'ATTRIBUTED','REATTRIBUTED','REVOKED','ENTERED_IN_ERROR'
            )),
            status TEXT NOT NULL CHECK (status IN (
                'ATTRIBUTED','REVOKED','ENTERED_IN_ERROR'
            )),
            reason_code TEXT NOT NULL CHECK (length(trim(reason_code))>0),
            effective_at TEXT NOT NULL CHECK (datetime(effective_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username))>0),
            note TEXT,
            idempotency_key TEXT NOT NULL UNIQUE,
            supersedes_event_id INTEGER UNIQUE,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (datetime(recorded_at)>=datetime(effective_at)),
            CHECK (
                (event_type IN ('ATTRIBUTED','REATTRIBUTED') AND status='ATTRIBUTED') OR
                (event_type='REVOKED' AND status='REVOKED') OR
                (event_type='ENTERED_IN_ERROR' AND status='ENTERED_IN_ERROR')
            ),
            FOREIGN KEY(journey_id) REFERENCES care_journeys(journey_id),
            FOREIGN KEY(campaign_id) REFERENCES sms_campaigns(id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(response_event_id) REFERENCES campaign_response_events(id),
            FOREIGN KEY(supersedes_event_id)
                REFERENCES campaign_journey_attribution_events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_campaign_journey_current
        ON campaign_journey_attribution_events(journey_id,recorded_at DESC,id DESC);
        CREATE INDEX IF NOT EXISTS idx_campaign_attribution_campaign
        ON campaign_journey_attribution_events(campaign_id,recorded_at DESC,id DESC);

        CREATE TABLE IF NOT EXISTS campaign_wallet_grant_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            patient_link_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN (
                'GRANTED','GRANT_REVIEW_REQUIRED','GRANT_NOT_REQUIRED',
                'COMPENSATED','COMPENSATION_REVIEW_REQUIRED','ENTERED_IN_ERROR'
            )),
            status TEXT NOT NULL CHECK (status IN (
                'ACTIVE','NO_GRANT','COMPENSATED','REVIEW_REQUIRED','ENTERED_IN_ERROR'
            )),
            amount INTEGER NOT NULL CHECK (amount>0),
            wallet_transaction_id INTEGER,
            compensation_transaction_id INTEGER,
            reason_code TEXT NOT NULL CHECK (length(trim(reason_code))>0),
            occurred_at TEXT NOT NULL CHECK (datetime(occurred_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username))>0),
            note TEXT,
            idempotency_key TEXT NOT NULL UNIQUE,
            supersedes_event_id INTEGER UNIQUE,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (datetime(recorded_at)>=datetime(occurred_at)),
            CHECK (
                (event_type='GRANTED' AND status='ACTIVE' AND
                 wallet_transaction_id IS NOT NULL) OR
                (event_type='GRANT_REVIEW_REQUIRED' AND
                 status='REVIEW_REQUIRED') OR
                (event_type='GRANT_NOT_REQUIRED' AND status='NO_GRANT' AND
                 wallet_transaction_id IS NULL AND
                 compensation_transaction_id IS NULL) OR
                (event_type='COMPENSATED' AND status='COMPENSATED' AND
                 compensation_transaction_id IS NOT NULL) OR
                (event_type='COMPENSATION_REVIEW_REQUIRED' AND
                 status='REVIEW_REQUIRED') OR
                (event_type='ENTERED_IN_ERROR' AND status='ENTERED_IN_ERROR')
            ),
            FOREIGN KEY(campaign_id) REFERENCES sms_campaigns(id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(message_id) REFERENCES sms_messages(id),
            FOREIGN KEY(wallet_transaction_id) REFERENCES wallet_transactions(id),
            FOREIGN KEY(compensation_transaction_id) REFERENCES wallet_transactions(id),
            FOREIGN KEY(supersedes_event_id) REFERENCES campaign_wallet_grant_events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_campaign_wallet_current
        ON campaign_wallet_grant_events(
            campaign_id,patient_link_id,recorded_at DESC,id DESC
        );

        CREATE TABLE IF NOT EXISTS campaign_message_cost_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN (
                'RECORDED','ADJUSTED','ENTERED_IN_ERROR'
            )),
            status TEXT NOT NULL CHECK (status IN ('ACTIVE','ENTERED_IN_ERROR')),
            evidence_type TEXT NOT NULL CHECK (evidence_type IN (
                'ESTIMATED_CONFIGURED_RATE','PROVIDER_REPORTED','MANUAL_VERIFIED'
            )),
            currency TEXT NOT NULL CHECK (currency='TOMAN'),
            parts INTEGER NOT NULL CHECK (parts>0),
            unit_cost INTEGER NOT NULL CHECK (unit_cost>=0),
            amount INTEGER NOT NULL CHECK (amount>=0),
            source_ref TEXT,
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username))>0),
            note TEXT,
            idempotency_key TEXT NOT NULL UNIQUE,
            supersedes_event_id INTEGER UNIQUE,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (amount=parts*unit_cost),
            CHECK (
                (event_type IN ('RECORDED','ADJUSTED') AND status='ACTIVE') OR
                (event_type='ENTERED_IN_ERROR' AND status='ENTERED_IN_ERROR')
            ),
            FOREIGN KEY(campaign_id) REFERENCES sms_campaigns(id),
            FOREIGN KEY(message_id) REFERENCES sms_messages(id),
            FOREIGN KEY(supersedes_event_id) REFERENCES campaign_message_cost_events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_campaign_message_cost_current
        ON campaign_message_cost_events(message_id,recorded_at DESC,id DESC);

        CREATE TRIGGER IF NOT EXISTS trg_campaign_lifecycle_no_update
        BEFORE UPDATE ON campaign_lifecycle_events
        BEGIN SELECT RAISE(ABORT,'campaign lifecycle events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_lifecycle_no_delete
        BEFORE DELETE ON campaign_lifecycle_events
        BEGIN SELECT RAISE(ABORT,'campaign lifecycle events cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_lifecycle_first
        BEFORE INSERT ON campaign_lifecycle_events
        WHEN NOT EXISTS (
            SELECT 1 FROM campaign_lifecycle_events event
            WHERE event.campaign_id=NEW.campaign_id
        ) AND NEW.supersedes_event_id IS NOT NULL
        BEGIN SELECT RAISE(ABORT,'first campaign lifecycle event cannot supersede'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_lifecycle_linear
        BEFORE INSERT ON campaign_lifecycle_events
        WHEN EXISTS (
            SELECT 1 FROM campaign_lifecycle_events event
            WHERE event.campaign_id=NEW.campaign_id
        ) AND NEW.supersedes_event_id IS NOT (
            SELECT event.id FROM campaign_lifecycle_events event
            WHERE event.campaign_id=NEW.campaign_id
            ORDER BY event.recorded_at DESC,event.id DESC LIMIT 1
        )
        BEGIN SELECT RAISE(ABORT,'campaign lifecycle must supersede current head'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_lifecycle_transition
        BEFORE INSERT ON campaign_lifecycle_events
        WHEN NEW.supersedes_event_id IS NOT NULL AND NOT (
            ((SELECT status FROM campaign_lifecycle_events WHERE id=NEW.supersedes_event_id)='DRAFT'
                AND NEW.status IN ('SCHEDULED','PREPARING','CANCELLED','ENTERED_IN_ERROR')) OR
            ((SELECT status FROM campaign_lifecycle_events WHERE id=NEW.supersedes_event_id)='SCHEDULED'
                AND NEW.status IN ('PREPARING','CANCELLED','ENTERED_IN_ERROR')) OR
            ((SELECT status FROM campaign_lifecycle_events WHERE id=NEW.supersedes_event_id)='PREPARING'
                AND NEW.status IN ('SENDING','FAILED','CANCELLED','ENTERED_IN_ERROR')) OR
            ((SELECT status FROM campaign_lifecycle_events WHERE id=NEW.supersedes_event_id)='SENDING'
                AND NEW.status IN ('AWAITING_DELIVERY','FAILED','ENTERED_IN_ERROR')) OR
            ((SELECT status FROM campaign_lifecycle_events WHERE id=NEW.supersedes_event_id)='AWAITING_DELIVERY'
                AND NEW.status IN ('COMPLETED','FAILED','ENTERED_IN_ERROR')) OR
            ((SELECT status FROM campaign_lifecycle_events WHERE id=NEW.supersedes_event_id)='FAILED'
                AND NEW.status IN ('PREPARING','CANCELLED','ENTERED_IN_ERROR')) OR
            ((SELECT status FROM campaign_lifecycle_events WHERE id=NEW.supersedes_event_id)='ENTERED_IN_ERROR'
                AND NEW.status IN ('PREPARING','CANCELLED')) OR
            ((SELECT status FROM campaign_lifecycle_events WHERE id=NEW.supersedes_event_id) IN ('COMPLETED','CANCELLED')
                AND NEW.status='ENTERED_IN_ERROR')
        )
        BEGIN SELECT RAISE(ABORT,'invalid campaign lifecycle transition'); END;

        CREATE TRIGGER IF NOT EXISTS trg_campaign_audience_snapshot_no_update
        BEFORE UPDATE ON campaign_audience_snapshots
        BEGIN SELECT RAISE(ABORT,'campaign audience snapshot is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_audience_snapshot_no_delete
        BEFORE DELETE ON campaign_audience_snapshots
        BEGIN SELECT RAISE(ABORT,'campaign audience snapshot cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_audience_member_no_update
        BEFORE UPDATE ON campaign_audience_members
        BEGIN SELECT RAISE(ABORT,'campaign audience members are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_audience_member_no_delete
        BEFORE DELETE ON campaign_audience_members
        BEGIN SELECT RAISE(ABORT,'campaign audience members cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_audience_member_scope
        BEFORE INSERT ON campaign_audience_members
        WHEN NOT EXISTS (
            SELECT 1 FROM campaign_audience_snapshots snapshot
            WHERE snapshot.snapshot_id=NEW.snapshot_id
              AND snapshot.campaign_id=NEW.campaign_id
        )
        BEGIN SELECT RAISE(ABORT,'campaign audience member scope mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_campaign_response_no_update
        BEFORE UPDATE ON campaign_response_events
        BEGIN SELECT RAISE(ABORT,'campaign response events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_response_no_delete
        BEFORE DELETE ON campaign_response_events
        BEGIN SELECT RAISE(ABORT,'campaign response events cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_response_first
        BEFORE INSERT ON campaign_response_events
        WHEN NOT EXISTS (
            SELECT 1 FROM campaign_response_events event
            WHERE event.campaign_id=NEW.campaign_id
              AND event.patient_link_id=NEW.patient_link_id
        ) AND NEW.supersedes_event_id IS NOT NULL
        BEGIN SELECT RAISE(ABORT,'first campaign response cannot supersede'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_response_linear
        BEFORE INSERT ON campaign_response_events
        WHEN EXISTS (
            SELECT 1 FROM campaign_response_events event
            WHERE event.campaign_id=NEW.campaign_id
              AND event.patient_link_id=NEW.patient_link_id
        ) AND NEW.supersedes_event_id IS NOT (
            SELECT event.id FROM campaign_response_events event
            WHERE event.campaign_id=NEW.campaign_id
              AND event.patient_link_id=NEW.patient_link_id
            ORDER BY event.recorded_at DESC,event.id DESC LIMIT 1
        )
        BEGIN SELECT RAISE(ABORT,'campaign response must supersede current head'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_response_positive_evidence
        BEFORE INSERT ON campaign_response_events
        WHEN NEW.response_type='POSITIVE' AND (
            (NEW.evidence_type='INBOUND_REPLY' AND length(trim(COALESCE(NEW.evidence_ref,'')))=0) OR
            (NEW.evidence_type IN ('PATIENT_STATED','STAFF_PHONE_CALL')
                AND length(trim(COALESCE(NEW.note,'')))=0) OR
            NEW.evidence_type='LEGACY_UNKNOWN'
        )
        BEGIN SELECT RAISE(ABORT,'positive campaign response requires explicit evidence'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_response_message_scope
        BEFORE INSERT ON campaign_response_events
        WHEN NEW.message_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM sms_messages message
            WHERE message.id=NEW.message_id
              AND message.campaign_id=NEW.campaign_id
              AND message.patient_link_id=NEW.patient_link_id
        )
        BEGIN SELECT RAISE(ABORT,'campaign response message scope mismatch'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_response_treated_scope
        BEFORE INSERT ON campaign_response_events
        WHEN NEW.response_type='POSITIVE' AND NOT EXISTS (
            SELECT 1 FROM campaign_audience_members member
            JOIN campaign_audience_snapshots snapshot
              ON snapshot.snapshot_id=member.snapshot_id
            WHERE member.campaign_id=NEW.campaign_id
              AND member.patient_link_id=NEW.patient_link_id
              AND member.assignment='TREATED'
              AND member.eligibility='ELIGIBLE'
              AND snapshot.source_code='NEW_FROZEN'
        )
        BEGIN SELECT RAISE(ABORT,'positive response requires trusted treated audience'); END;

        CREATE TRIGGER IF NOT EXISTS trg_campaign_journey_no_update
        BEFORE UPDATE ON campaign_journey_attribution_events
        BEGIN SELECT RAISE(ABORT,'campaign journey attribution is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_journey_no_delete
        BEFORE DELETE ON campaign_journey_attribution_events
        BEGIN SELECT RAISE(ABORT,'campaign journey attribution cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_journey_first
        BEFORE INSERT ON campaign_journey_attribution_events
        WHEN NOT EXISTS (
            SELECT 1 FROM campaign_journey_attribution_events event
            WHERE event.journey_id=NEW.journey_id
        ) AND (NEW.event_type<>'ATTRIBUTED' OR NEW.supersedes_event_id IS NOT NULL)
        BEGIN SELECT RAISE(ABORT,'first campaign journey event must attribute'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_journey_linear
        BEFORE INSERT ON campaign_journey_attribution_events
        WHEN EXISTS (
            SELECT 1 FROM campaign_journey_attribution_events event
            WHERE event.journey_id=NEW.journey_id
        ) AND NEW.supersedes_event_id IS NOT (
            SELECT event.id FROM campaign_journey_attribution_events event
            WHERE event.journey_id=NEW.journey_id
            ORDER BY event.recorded_at DESC,event.id DESC LIMIT 1
        )
        BEGIN SELECT RAISE(ABORT,'campaign journey event must supersede current head'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_journey_scope
        BEFORE INSERT ON campaign_journey_attribution_events
        WHEN NEW.event_type IN ('ATTRIBUTED','REATTRIBUTED') AND NOT EXISTS (
            SELECT 1 FROM campaign_response_events response
            JOIN care_journeys journey ON journey.journey_id=NEW.journey_id
            WHERE response.id=NEW.response_event_id
              AND response.campaign_id=NEW.campaign_id
              AND response.patient_link_id=NEW.patient_link_id
              AND response.response_type='POSITIVE'
              AND journey.patient_link_id=NEW.patient_link_id
        )
        BEGIN SELECT RAISE(ABORT,'campaign journey attribution scope mismatch'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_journey_transition
        BEFORE INSERT ON campaign_journey_attribution_events
        WHEN NEW.supersedes_event_id IS NOT NULL AND NOT (
            (NEW.event_type='REATTRIBUTED' AND NEW.status='ATTRIBUTED'
             AND length(trim(COALESCE(NEW.note,'')))>0) OR
            (NEW.event_type='REVOKED' AND NEW.status='REVOKED'
             AND length(trim(COALESCE(NEW.note,'')))>0) OR
            (NEW.event_type='ENTERED_IN_ERROR' AND NEW.status='ENTERED_IN_ERROR'
             AND length(trim(COALESCE(NEW.note,'')))>0)
        )
        BEGIN SELECT RAISE(ABORT,'invalid campaign journey attribution transition'); END;

        CREATE TRIGGER IF NOT EXISTS trg_campaign_wallet_no_update
        BEFORE UPDATE ON campaign_wallet_grant_events
        BEGIN SELECT RAISE(ABORT,'campaign wallet grant events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_wallet_no_delete
        BEFORE DELETE ON campaign_wallet_grant_events
        BEGIN SELECT RAISE(ABORT,'campaign wallet grant events cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_wallet_first
        BEFORE INSERT ON campaign_wallet_grant_events
        WHEN NOT EXISTS (
            SELECT 1 FROM campaign_wallet_grant_events event
            WHERE event.campaign_id=NEW.campaign_id
              AND event.patient_link_id=NEW.patient_link_id
        ) AND (
            NEW.event_type NOT IN ('GRANTED','GRANT_REVIEW_REQUIRED')
            OR NEW.supersedes_event_id IS NOT NULL
        )
        BEGIN SELECT RAISE(ABORT,'first campaign wallet event must grant or require review'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_wallet_linear
        BEFORE INSERT ON campaign_wallet_grant_events
        WHEN EXISTS (
            SELECT 1 FROM campaign_wallet_grant_events event
            WHERE event.campaign_id=NEW.campaign_id
              AND event.patient_link_id=NEW.patient_link_id
        ) AND NEW.supersedes_event_id IS NOT (
            SELECT event.id FROM campaign_wallet_grant_events event
            WHERE event.campaign_id=NEW.campaign_id
              AND event.patient_link_id=NEW.patient_link_id
            ORDER BY event.recorded_at DESC,event.id DESC LIMIT 1
        )
        BEGIN SELECT RAISE(ABORT,'campaign wallet event must supersede current head'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_wallet_message_scope
        BEFORE INSERT ON campaign_wallet_grant_events
        WHEN NEW.event_type='GRANTED' AND NOT EXISTS (
            SELECT 1 FROM sms_messages message
            WHERE message.id=NEW.message_id
              AND message.campaign_id=NEW.campaign_id
              AND message.patient_link_id=NEW.patient_link_id
              AND message.status IN ('accepted','delivered','sent')
        )
        BEGIN SELECT RAISE(ABORT,'wallet grant requires accepted campaign message'); END;

        CREATE TRIGGER IF NOT EXISTS trg_campaign_cost_no_update
        BEFORE UPDATE ON campaign_message_cost_events
        BEGIN SELECT RAISE(ABORT,'campaign message cost events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_cost_no_delete
        BEFORE DELETE ON campaign_message_cost_events
        BEGIN SELECT RAISE(ABORT,'campaign message cost events cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_cost_first
        BEFORE INSERT ON campaign_message_cost_events
        WHEN NOT EXISTS (
            SELECT 1 FROM campaign_message_cost_events event
            WHERE event.message_id=NEW.message_id
        ) AND (NEW.event_type<>'RECORDED' OR NEW.supersedes_event_id IS NOT NULL)
        BEGIN SELECT RAISE(ABORT,'first message cost event must record'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_cost_linear
        BEFORE INSERT ON campaign_message_cost_events
        WHEN EXISTS (
            SELECT 1 FROM campaign_message_cost_events event
            WHERE event.message_id=NEW.message_id
        ) AND NEW.supersedes_event_id IS NOT (
            SELECT event.id FROM campaign_message_cost_events event
            WHERE event.message_id=NEW.message_id
            ORDER BY event.recorded_at DESC,event.id DESC LIMIT 1
        )
        BEGIN SELECT RAISE(ABORT,'campaign message cost must supersede current head'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_cost_scope
        BEFORE INSERT ON campaign_message_cost_events
        WHEN NOT EXISTS (
            SELECT 1 FROM sms_messages message
            WHERE message.id=NEW.message_id
              AND message.campaign_id=NEW.campaign_id
        )
        BEGIN SELECT RAISE(ABORT,'campaign message cost scope mismatch'); END;
        """
    )
    _backfill_campaign_lifecycle(db)
    _backfill_campaign_audience(db)
    db.commit()


__all__ = ["SCHEMA_VERSION", "ensure_campaign_economics_storage"]
