"""Append-only SMS response, consent, audience and exclusive Journey attribution."""
from __future__ import annotations

import sqlite3


POSITIVE_RESPONSES = ("INTERESTED", "BOOKING_REQUEST")


def ensure_campaign_journey_attribution_storage(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS campaign_audience_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            patient_link_id INTEGER NOT NULL,
            accounting_patient_id INTEGER,
            grp TEXT NOT NULL CHECK (grp IN ('treated','control')),
            full_name_snapshot TEXT NOT NULL,
            recipient_snapshot TEXT NOT NULL,
            assigned_at TEXT NOT NULL CHECK (datetime(assigned_at) IS NOT NULL),
            assignment_key TEXT NOT NULL UNIQUE CHECK (length(trim(assignment_key))>=12),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            UNIQUE(campaign_id, patient_link_id),
            FOREIGN KEY(campaign_id) REFERENCES sms_campaigns(id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id)
        );
        CREATE INDEX IF NOT EXISTS idx_campaign_audience_snapshot_group
        ON campaign_audience_snapshots(campaign_id, grp, patient_link_id);

        CREATE TABLE IF NOT EXISTS sms_response_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sms_message_id INTEGER NOT NULL,
            campaign_id INTEGER,
            patient_link_id INTEGER NOT NULL,
            response_type TEXT NOT NULL CHECK (response_type IN (
                'INTERESTED','BOOKING_REQUEST','DECLINED','STOP','OTHER'
            )),
            occurred_at TEXT NOT NULL CHECK (datetime(occurred_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_user_id INTEGER,
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username))>0),
            note TEXT,
            delivery_status_snapshot TEXT,
            idempotency_key TEXT NOT NULL UNIQUE
                CHECK (length(trim(idempotency_key))>=12),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (datetime(recorded_at)>=datetime(occurred_at)),
            CHECK (note IS NULL OR length(note)<=2000),
            FOREIGN KEY(sms_message_id) REFERENCES sms_messages(id),
            FOREIGN KEY(campaign_id) REFERENCES sms_campaigns(id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(actor_user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_sms_response_message
        ON sms_response_events(sms_message_id, occurred_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_sms_response_campaign
        ON sms_response_events(campaign_id, response_type, occurred_at DESC);
        CREATE INDEX IF NOT EXISTS idx_sms_response_patient
        ON sms_response_events(patient_link_id, occurred_at DESC, id DESC);

        CREATE TABLE IF NOT EXISTS sms_consent_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_link_id INTEGER NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN ('OPTED_IN','OPTED_OUT')),
            source TEXT NOT NULL CHECK (source IN (
                'PATIENT_RESPONSE','STAFF_RECORDED','DATA_CORRECTION'
            )),
            sms_message_id INTEGER,
            occurred_at TEXT NOT NULL CHECK (datetime(occurred_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_user_id INTEGER,
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username))>0),
            note TEXT,
            idempotency_key TEXT NOT NULL UNIQUE
                CHECK (length(trim(idempotency_key))>=12),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (datetime(recorded_at)>=datetime(occurred_at)),
            CHECK (note IS NULL OR length(note)<=2000),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(sms_message_id) REFERENCES sms_messages(id),
            FOREIGN KEY(actor_user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_sms_consent_patient
        ON sms_consent_events(patient_link_id, occurred_at DESC, id DESC);

        CREATE TABLE IF NOT EXISTS campaign_journey_attributions (
            attribution_id TEXT PRIMARY KEY,
            journey_id TEXT NOT NULL UNIQUE,
            patient_link_id INTEGER NOT NULL,
            created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
            created_by TEXT NOT NULL CHECK (length(trim(created_by))>0),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            FOREIGN KEY(journey_id) REFERENCES care_journeys(journey_id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id)
        );
        CREATE INDEX IF NOT EXISTS idx_campaign_journey_patient
        ON campaign_journey_attributions(patient_link_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS campaign_journey_attribution_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attribution_id TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN (
                'ATTRIBUTED','REATTRIBUTED','REVOKED','ENTERED_IN_ERROR'
            )),
            status TEXT NOT NULL CHECK (status IN (
                'ATTRIBUTED','REVOKED','ENTERED_IN_ERROR'
            )),
            campaign_id INTEGER,
            sms_message_id INTEGER,
            response_event_id INTEGER,
            reason_code TEXT NOT NULL CHECK (length(trim(reason_code))>0),
            note TEXT,
            effective_at TEXT NOT NULL CHECK (datetime(effective_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_user_id INTEGER,
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username))>0),
            supersedes_event_id INTEGER UNIQUE,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (datetime(recorded_at)>=datetime(effective_at)),
            CHECK (note IS NULL OR length(note)<=2000),
            FOREIGN KEY(attribution_id)
                REFERENCES campaign_journey_attributions(attribution_id),
            FOREIGN KEY(campaign_id) REFERENCES sms_campaigns(id),
            FOREIGN KEY(sms_message_id) REFERENCES sms_messages(id),
            FOREIGN KEY(response_event_id) REFERENCES sms_response_events(id),
            FOREIGN KEY(actor_user_id) REFERENCES users(id),
            FOREIGN KEY(supersedes_event_id)
                REFERENCES campaign_journey_attribution_events(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_journey_one_root
        ON campaign_journey_attribution_events(attribution_id)
        WHERE supersedes_event_id IS NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_journey_one_child
        ON campaign_journey_attribution_events(supersedes_event_id)
        WHERE supersedes_event_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_campaign_journey_event_head
        ON campaign_journey_attribution_events(
            attribution_id, recorded_at DESC, id DESC
        );
        CREATE INDEX IF NOT EXISTS idx_campaign_journey_campaign
        ON campaign_journey_attribution_events(campaign_id, status, id DESC);

        CREATE TRIGGER IF NOT EXISTS trg_campaign_audience_no_update
        BEFORE UPDATE ON campaign_audience_snapshots
        BEGIN SELECT RAISE(ABORT, 'campaign audience snapshot is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_audience_no_delete
        BEFORE DELETE ON campaign_audience_snapshots
        BEGIN SELECT RAISE(ABORT, 'campaign audience snapshot cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_sms_response_no_update
        BEFORE UPDATE ON sms_response_events
        BEGIN SELECT RAISE(ABORT, 'SMS response events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_sms_response_no_delete
        BEFORE DELETE ON sms_response_events
        BEGIN SELECT RAISE(ABORT, 'SMS response events cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_sms_consent_no_update
        BEFORE UPDATE ON sms_consent_events
        BEGIN SELECT RAISE(ABORT, 'SMS consent events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_sms_consent_no_delete
        BEFORE DELETE ON sms_consent_events
        BEGIN SELECT RAISE(ABORT, 'SMS consent events cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_journey_root_no_update
        BEFORE UPDATE ON campaign_journey_attributions
        BEGIN SELECT RAISE(ABORT, 'campaign journey attribution root is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_journey_root_no_delete
        BEFORE DELETE ON campaign_journey_attributions
        BEGIN SELECT RAISE(ABORT, 'campaign journey attribution root cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_journey_event_no_update
        BEFORE UPDATE ON campaign_journey_attribution_events
        BEGIN SELECT RAISE(ABORT, 'campaign journey attribution events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_campaign_journey_event_no_delete
        BEFORE DELETE ON campaign_journey_attribution_events
        BEGIN SELECT RAISE(ABORT, 'campaign journey attribution events cannot be deleted'); END;

        CREATE TRIGGER IF NOT EXISTS trg_campaign_audience_scope
        BEFORE INSERT ON campaign_audience_snapshots
        WHEN NOT EXISTS (
            SELECT 1 FROM patient_links patient
            WHERE patient.id=NEW.patient_link_id
              AND (
                  NEW.accounting_patient_id IS NULL
                  OR patient.accounting_patient_id=NEW.accounting_patient_id
              )
        )
        BEGIN SELECT RAISE(ABORT, 'campaign audience patient scope mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_sms_response_scope
        BEFORE INSERT ON sms_response_events
        WHEN NOT EXISTS (
            SELECT 1 FROM sms_messages message
            WHERE message.id=NEW.sms_message_id
              AND message.patient_link_id=NEW.patient_link_id
              AND message.campaign_id IS NEW.campaign_id
              AND message.status='sent'
        )
        BEGIN SELECT RAISE(ABORT, 'SMS response message scope mismatch or message not sent'); END;

        CREATE TRIGGER IF NOT EXISTS trg_sms_consent_scope
        BEFORE INSERT ON sms_consent_events
        WHEN NEW.sms_message_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM sms_messages message
            WHERE message.id=NEW.sms_message_id
              AND message.patient_link_id=NEW.patient_link_id
        )
        BEGIN SELECT RAISE(ABORT, 'SMS consent message/patient scope mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_campaign_journey_root_scope
        BEFORE INSERT ON campaign_journey_attributions
        WHEN NOT EXISTS (
            SELECT 1 FROM care_journeys journey
            WHERE journey.journey_id=NEW.journey_id
              AND journey.patient_link_id=NEW.patient_link_id
        )
        BEGIN SELECT RAISE(ABORT, 'campaign attribution journey/patient mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_campaign_journey_positive_scope
        BEFORE INSERT ON campaign_journey_attribution_events
        WHEN NEW.event_type IN ('ATTRIBUTED','REATTRIBUTED') AND NOT EXISTS (
            SELECT 1
            FROM campaign_journey_attributions root
            JOIN care_journeys journey ON journey.journey_id=root.journey_id
            JOIN sms_messages message ON message.id=NEW.sms_message_id
            JOIN sms_response_events response ON response.id=NEW.response_event_id
            WHERE root.attribution_id=NEW.attribution_id
              AND journey.patient_link_id=root.patient_link_id
              AND message.patient_link_id=root.patient_link_id
              AND message.campaign_id=NEW.campaign_id
              AND message.status='sent'
              AND response.sms_message_id=message.id
              AND response.patient_link_id=root.patient_link_id
              AND response.campaign_id=NEW.campaign_id
              AND response.response_type IN ('INTERESTED','BOOKING_REQUEST')
        )
        BEGIN SELECT RAISE(ABORT, 'campaign attribution requires positive same-patient response evidence'); END;

        CREATE TRIGGER IF NOT EXISTS trg_campaign_journey_first_event
        BEFORE INSERT ON campaign_journey_attribution_events
        WHEN NOT EXISTS (
            SELECT 1 FROM campaign_journey_attribution_events prior
            WHERE prior.attribution_id=NEW.attribution_id
        ) AND (
            NEW.event_type<>'ATTRIBUTED' OR NEW.status<>'ATTRIBUTED'
            OR NEW.supersedes_event_id IS NOT NULL
        )
        BEGIN SELECT RAISE(ABORT, 'first campaign attribution event must be ATTRIBUTED'); END;

        CREATE TRIGGER IF NOT EXISTS trg_campaign_journey_next_event
        BEFORE INSERT ON campaign_journey_attribution_events
        WHEN EXISTS (
            SELECT 1 FROM campaign_journey_attribution_events prior
            WHERE prior.attribution_id=NEW.attribution_id
        ) AND (
            NEW.supersedes_event_id IS NULL
            OR NEW.supersedes_event_id<>(
                SELECT head.id FROM campaign_journey_attribution_events head
                WHERE head.attribution_id=NEW.attribution_id
                  AND NOT EXISTS (
                      SELECT 1 FROM campaign_journey_attribution_events child
                      WHERE child.supersedes_event_id=head.id
                  )
                ORDER BY head.recorded_at DESC, head.id DESC LIMIT 1
            )
        )
        BEGIN SELECT RAISE(ABORT, 'campaign attribution event must supersede current head'); END;

        CREATE TRIGGER IF NOT EXISTS trg_campaign_journey_transition
        BEFORE INSERT ON campaign_journey_attribution_events
        WHEN (
            (NEW.event_type='ATTRIBUTED' AND NEW.status<>'ATTRIBUTED')
            OR (NEW.event_type='REATTRIBUTED' AND (
                NEW.status<>'ATTRIBUTED'
                OR length(trim(COALESCE(NEW.note,'')))=0
                OR (SELECT status FROM campaign_journey_attribution_events
                    WHERE id=NEW.supersedes_event_id)='ENTERED_IN_ERROR'
            ))
            OR (NEW.event_type='REVOKED' AND (
                NEW.status<>'REVOKED'
                OR length(trim(COALESCE(NEW.note,'')))=0
                OR (SELECT status FROM campaign_journey_attribution_events
                    WHERE id=NEW.supersedes_event_id)<>'ATTRIBUTED'
            ))
            OR (NEW.event_type='ENTERED_IN_ERROR' AND (
                NEW.status<>'ENTERED_IN_ERROR'
                OR length(trim(COALESCE(NEW.note,'')))=0
                OR (SELECT status FROM campaign_journey_attribution_events
                    WHERE id=NEW.supersedes_event_id)='ENTERED_IN_ERROR'
            ))
        )
        BEGIN SELECT RAISE(ABORT, 'invalid campaign journey attribution lifecycle'); END;

        CREATE TRIGGER IF NOT EXISTS trg_campaign_journey_recorded_order
        BEFORE INSERT ON campaign_journey_attribution_events
        WHEN NEW.supersedes_event_id IS NOT NULL AND datetime(NEW.recorded_at)<datetime((
            SELECT prior.recorded_at FROM campaign_journey_attribution_events prior
            WHERE prior.id=NEW.supersedes_event_id
        ))
        BEGIN SELECT RAISE(ABORT, 'campaign attribution recorded_at cannot move backwards'); END;
        """
    )
    db.commit()
