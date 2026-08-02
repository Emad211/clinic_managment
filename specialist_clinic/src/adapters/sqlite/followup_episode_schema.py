"""Additive FO-1 storage for deterministic follow-up episodes and source links."""
from __future__ import annotations

import sqlite3

SCHEMA_VERSION = "1.0"
EPISODE_TYPES = (
    "ADMIN_FOLLOWUP",
    "CLINICAL_TASK",
    "ENCOUNTER_COMMITMENT",
    "ENGAGEMENT",
)
SOURCE_TYPES = (
    "ADMIN_TASK",
    "CLINICAL_TASK",
    "ENCOUNTER_COMMITMENT",
    "ENGAGEMENT_APPROVAL",
    "SMS_MESSAGE",
    "APPOINTMENT",
    "CONTACT_EVENT",
    "CLINICAL_OUTCOME",
)
RELATION_TYPES = (
    "PRIMARY",
    "COMMUNICATION",
    "SCHEDULE",
    "CONTACT",
    "OUTCOME",
    "RELATED",
)
EVENT_TYPES = (
    "EPISODE_OPENED",
    "SOURCE_LINKED",
    "ROUTED",
    "CLAIMED",
    "ASSIGNED",
    "ACTION_DUE_CHANGED",
    "TARGET_CHANGED",
    "WAITING_STARTED",
    "WAITING_ENDED",
    "CONTACT_RECORDED",
    "SMS_QUEUED",
    "SMS_SENT",
    "SMS_DELIVERED",
    "SMS_FAILED",
    "APPOINTMENT_BOOKED",
    "APPOINTMENT_CANCELLED",
    "APPOINTMENT_NO_SHOW",
    "EVIDENCE_SUGGESTED",
    "ESCALATED",
    "ADMINISTRATIVE_GOAL_MET",
    "EPISODE_CLOSED",
    "ENTERED_IN_ERROR",
)

_REQUIRED_TABLES = frozenset(
    {"followup_episodes", "followup_episode_links", "followup_episode_events"}
)
_REQUIRED_TRIGGERS = frozenset(
    {
        "trg_followup_episodes_no_update",
        "trg_followup_episodes_no_delete",
        "trg_followup_episode_links_no_update",
        "trg_followup_episode_links_no_delete",
        "trg_followup_episode_links_patient_scope",
        "trg_followup_episode_events_no_update",
        "trg_followup_episode_events_no_delete",
        "trg_followup_episode_events_first",
        "trg_followup_episode_events_linear",
        "trg_followup_episode_events_scope",
        "trg_followup_episode_events_recorded_order",
        "trg_followup_episode_source_link_event_scope",
    }
)


def ensure_followup_episode_storage(db: sqlite3.Connection) -> None:
    """Install FO-1 stores without linking or mutating any existing source row."""
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS followup_episodes (
            episode_id TEXT PRIMARY KEY
                CHECK (length(episode_id)=69 AND substr(episode_id,1,5)='fuep_'),
            patient_link_id INTEGER NOT NULL,
            episode_type TEXT NOT NULL CHECK (episode_type IN (
                'ADMIN_FOLLOWUP','CLINICAL_TASK','ENCOUNTER_COMMITMENT','ENGAGEMENT'
            )),
            semantic_key TEXT NOT NULL
                CHECK (length(trim(semantic_key)) BETWEEN 3 AND 300),
            period_key TEXT NOT NULL
                CHECK (length(trim(period_key)) BETWEEN 1 AND 200),
            identity_version TEXT NOT NULL
                CHECK (length(trim(identity_version)) BETWEEN 1 AND 20),
            opened_at TEXT NOT NULL CHECK (datetime(opened_at) IS NOT NULL),
            created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
            created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
            identity_hash TEXT NOT NULL UNIQUE CHECK (length(identity_hash)=64),
            CHECK (datetime(created_at) >= datetime(opened_at)),
            UNIQUE(
                patient_link_id, episode_type, semantic_key,
                period_key, identity_version
            ),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id)
        );
        CREATE INDEX IF NOT EXISTS idx_followup_episodes_patient
        ON followup_episodes(patient_link_id, opened_at DESC, episode_id);

        CREATE TABLE IF NOT EXISTS followup_episode_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_id TEXT NOT NULL,
            patient_link_id INTEGER NOT NULL,
            source_type TEXT NOT NULL CHECK (source_type IN (
                'ADMIN_TASK','CLINICAL_TASK','ENCOUNTER_COMMITMENT',
                'ENGAGEMENT_APPROVAL','SMS_MESSAGE','APPOINTMENT',
                'CONTACT_EVENT','CLINICAL_OUTCOME'
            )),
            source_id TEXT NOT NULL CHECK (length(trim(source_id)) > 0),
            source_revision TEXT NOT NULL CHECK (length(source_revision)=64),
            relation_type TEXT NOT NULL CHECK (relation_type IN (
                'PRIMARY','COMMUNICATION','SCHEDULE','CONTACT','OUTCOME','RELATED'
            )),
            linked_at TEXT NOT NULL CHECK (datetime(linked_at) IS NOT NULL),
            linked_by TEXT NOT NULL CHECK (length(trim(linked_by)) > 0),
            idempotency_key TEXT NOT NULL UNIQUE
                CHECK (length(trim(idempotency_key)) >= 16),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            UNIQUE(episode_id, source_type, source_id),
            FOREIGN KEY(episode_id) REFERENCES followup_episodes(episode_id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id)
        );
        CREATE INDEX IF NOT EXISTS idx_followup_episode_links_source
        ON followup_episode_links(source_type, source_id);
        CREATE INDEX IF NOT EXISTS idx_followup_episode_links_episode
        ON followup_episode_links(episode_id, id);

        CREATE TABLE IF NOT EXISTS followup_episode_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_id TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN (
                'EPISODE_OPENED','SOURCE_LINKED','ROUTED','CLAIMED','ASSIGNED',
                'ACTION_DUE_CHANGED','TARGET_CHANGED','WAITING_STARTED','WAITING_ENDED',
                'CONTACT_RECORDED','SMS_QUEUED','SMS_SENT','SMS_DELIVERED','SMS_FAILED',
                'APPOINTMENT_BOOKED','APPOINTMENT_CANCELLED','APPOINTMENT_NO_SHOW',
                'EVIDENCE_SUGGESTED','ESCALATED','ADMINISTRATIVE_GOAL_MET',
                'EPISODE_CLOSED','ENTERED_IN_ERROR'
            )),
            effective_at TEXT NOT NULL CHECK (datetime(effective_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username)) > 0),
            actor_user_id INTEGER,
            idempotency_key TEXT NOT NULL UNIQUE
                CHECK (length(trim(idempotency_key)) >= 16),
            supersedes_event_id INTEGER UNIQUE,
            payload_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload_json)),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (datetime(recorded_at) >= datetime(effective_at)),
            FOREIGN KEY(episode_id) REFERENCES followup_episodes(episode_id),
            FOREIGN KEY(actor_user_id) REFERENCES users(id),
            FOREIGN KEY(supersedes_event_id) REFERENCES followup_episode_events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_followup_episode_events_stream
        ON followup_episode_events(episode_id, recorded_at DESC, id DESC);

        CREATE TRIGGER IF NOT EXISTS trg_followup_episodes_no_update
        BEFORE UPDATE ON followup_episodes
        BEGIN SELECT RAISE(ABORT, 'follow-up episode identity is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS trg_followup_episodes_no_delete
        BEFORE DELETE ON followup_episodes
        BEGIN SELECT RAISE(ABORT, 'follow-up episodes cannot be deleted'); END;

        CREATE TRIGGER IF NOT EXISTS trg_followup_episode_links_no_update
        BEFORE UPDATE ON followup_episode_links
        BEGIN SELECT RAISE(ABORT, 'follow-up episode links are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS trg_followup_episode_links_no_delete
        BEFORE DELETE ON followup_episode_links
        BEGIN SELECT RAISE(ABORT, 'follow-up episode links cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_followup_episode_links_patient_scope
        BEFORE INSERT ON followup_episode_links
        WHEN NOT EXISTS (
            SELECT 1 FROM followup_episodes episode
            WHERE episode.episode_id=NEW.episode_id
              AND episode.patient_link_id=NEW.patient_link_id
        )
        BEGIN SELECT RAISE(ABORT, 'episode link patient scope mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_followup_episode_events_no_update
        BEFORE UPDATE ON followup_episode_events
        BEGIN SELECT RAISE(ABORT, 'follow-up episode events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_followup_episode_events_no_delete
        BEFORE DELETE ON followup_episode_events
        BEGIN SELECT RAISE(ABORT, 'follow-up episode events cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_followup_episode_events_first
        BEFORE INSERT ON followup_episode_events
        WHEN NOT EXISTS (
            SELECT 1 FROM followup_episode_events event
            WHERE event.episode_id=NEW.episode_id
        ) AND (
            NEW.event_type<>'EPISODE_OPENED'
            OR NEW.supersedes_event_id IS NOT NULL
        )
        BEGIN SELECT RAISE(ABORT, 'first follow-up episode event must be EPISODE_OPENED'); END;
        CREATE TRIGGER IF NOT EXISTS trg_followup_episode_events_linear
        BEFORE INSERT ON followup_episode_events
        WHEN EXISTS (
            SELECT 1 FROM followup_episode_events event
            WHERE event.episode_id=NEW.episode_id
        ) AND NEW.supersedes_event_id IS NOT (
            SELECT head.id FROM followup_episode_events head
            WHERE head.episode_id=NEW.episode_id
              AND NOT EXISTS (
                  SELECT 1 FROM followup_episode_events child
                  WHERE child.supersedes_event_id=head.id
              )
            ORDER BY head.id DESC LIMIT 1
        )
        BEGIN SELECT RAISE(ABORT, 'episode event must supersede current head'); END;
        CREATE TRIGGER IF NOT EXISTS trg_followup_episode_events_scope
        BEFORE INSERT ON followup_episode_events
        WHEN NEW.supersedes_event_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM followup_episode_events prior
            WHERE prior.id=NEW.supersedes_event_id
              AND prior.episode_id=NEW.episode_id
        )
        BEGIN SELECT RAISE(ABORT, 'episode event supersession scope mismatch'); END;
        CREATE TRIGGER IF NOT EXISTS trg_followup_episode_events_recorded_order
        BEFORE INSERT ON followup_episode_events
        WHEN NEW.supersedes_event_id IS NOT NULL
         AND datetime(NEW.recorded_at) < datetime((
             SELECT prior.recorded_at FROM followup_episode_events prior
             WHERE prior.id=NEW.supersedes_event_id
         ))
        BEGIN SELECT RAISE(ABORT, 'episode recorded_at cannot move backwards'); END;
        CREATE TRIGGER IF NOT EXISTS trg_followup_episode_source_link_event_scope
        BEFORE INSERT ON followup_episode_events
        WHEN NEW.event_type='SOURCE_LINKED' AND NOT EXISTS (
            SELECT 1 FROM followup_episode_links link
            WHERE link.id=CAST(json_extract(NEW.payload_json,'$.link_id') AS INTEGER)
              AND link.episode_id=NEW.episode_id
        )
        BEGIN SELECT RAISE(ABORT, 'source-linked event must reference a link in the episode'); END;
        """
    )

    tables = {
        str(row[0])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    missing_tables = sorted(_REQUIRED_TABLES - tables)
    if missing_tables:
        raise RuntimeError(
            "follow-up episode tables incomplete: " + ", ".join(missing_tables)
        )

    triggers = {
        str(row[0])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    missing_triggers = sorted(_REQUIRED_TRIGGERS - triggers)
    if missing_triggers:
        raise RuntimeError(
            "follow-up episode guards incomplete: " + ", ".join(missing_triggers)
        )
    db.commit()


__all__ = [
    "EPISODE_TYPES",
    "EVENT_TYPES",
    "RELATION_TYPES",
    "SCHEMA_VERSION",
    "SOURCE_TYPES",
    "ensure_followup_episode_storage",
]
