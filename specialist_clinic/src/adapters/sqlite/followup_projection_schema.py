"""Additive FO-2 cache storage for the shadow Work Item projection."""
from __future__ import annotations

import sqlite3

PROJECTION_VERSION = "1.0"
STATE_CLASSES = ("ACTION_REQUIRED", "WAITING", "BLOCKED", "TERMINAL")
OWNER_ROLES = ("RECEPTION", "NURSING", "PHYSICIAN", "MANAGER")


def ensure_followup_projection_storage(db: sqlite3.Connection) -> None:
    """Install a rebuildable cache; never project or mutate source truth here."""
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS followup_work_item_projection (
            episode_id TEXT PRIMARY KEY,
            patient_link_id INTEGER NOT NULL,
            episode_type TEXT NOT NULL,
            reason_code TEXT NOT NULL CHECK (length(trim(reason_code)) > 0),
            reason_label TEXT NOT NULL CHECK (length(trim(reason_label)) > 0),
            why_created TEXT NOT NULL CHECK (length(trim(why_created)) > 0),
            current_state TEXT NOT NULL CHECK (length(trim(current_state)) > 0),
            state_class TEXT NOT NULL CHECK (state_class IN (
                'ACTION_REQUIRED','WAITING','BLOCKED','TERMINAL'
            )),
            next_action_code TEXT,
            next_action_label TEXT,
            waiting_reason_code TEXT,
            waiting_reason_label TEXT,
            blocked_reason_code TEXT,
            blocked_reason_label TEXT,
            owner_role_proposal TEXT CHECK (
                owner_role_proposal IS NULL OR owner_role_proposal IN (
                    'RECEPTION','NURSING','PHYSICIAN','MANAGER'
                )
            ),
            owner_user_id INTEGER,
            action_due_at TEXT CHECK (
                action_due_at IS NULL OR datetime(action_due_at) IS NOT NULL
            ),
            target_at TEXT CHECK (
                target_at IS NULL OR datetime(target_at) IS NOT NULL
            ),
            priority INTEGER NOT NULL CHECK (priority BETWEEN 0 AND 1000),
            sla_state TEXT NOT NULL CHECK (length(trim(sla_state)) > 0),
            last_source_event_at TEXT CHECK (
                last_source_event_at IS NULL
                OR datetime(last_source_event_at) IS NOT NULL
            ),
            last_episode_event_id INTEGER,
            sms_state TEXT,
            appointment_state TEXT,
            evidence_state TEXT,
            source_count INTEGER NOT NULL CHECK (source_count > 0),
            source_fingerprint TEXT NOT NULL CHECK (length(source_fingerprint)=64),
            state_detail_json TEXT NOT NULL DEFAULT '{}'
                CHECK (json_valid(state_detail_json)),
            projection_version TEXT NOT NULL
                CHECK (length(trim(projection_version)) > 0),
            policy_version TEXT NOT NULL
                CHECK (length(trim(policy_version)) > 0),
            as_of_at TEXT NOT NULL CHECK (datetime(as_of_at) IS NOT NULL),
            projection_hash TEXT NOT NULL UNIQUE CHECK (length(projection_hash)=64),
            rebuilt_at TEXT NOT NULL CHECK (datetime(rebuilt_at) IS NOT NULL),
            CHECK (owner_user_id IS NULL),
            CHECK (
                (state_class='ACTION_REQUIRED'
                 AND length(trim(COALESCE(next_action_code,'')))>0
                 AND length(trim(COALESCE(next_action_label,'')))>0
                 AND waiting_reason_code IS NULL
                 AND waiting_reason_label IS NULL
                 AND blocked_reason_code IS NULL
                 AND blocked_reason_label IS NULL
                 AND owner_role_proposal IS NOT NULL)
                OR
                (state_class='WAITING'
                 AND next_action_code IS NULL
                 AND next_action_label IS NULL
                 AND length(trim(COALESCE(waiting_reason_code,'')))>0
                 AND length(trim(COALESCE(waiting_reason_label,'')))>0
                 AND blocked_reason_code IS NULL
                 AND blocked_reason_label IS NULL
                 AND owner_role_proposal IS NOT NULL)
                OR
                (state_class='BLOCKED'
                 AND next_action_code IS NULL
                 AND next_action_label IS NULL
                 AND waiting_reason_code IS NULL
                 AND waiting_reason_label IS NULL
                 AND length(trim(COALESCE(blocked_reason_code,'')))>0
                 AND length(trim(COALESCE(blocked_reason_label,'')))>0
                 AND owner_role_proposal IS NOT NULL)
                OR
                (state_class='TERMINAL'
                 AND next_action_code IS NULL
                 AND next_action_label IS NULL
                 AND waiting_reason_code IS NULL
                 AND waiting_reason_label IS NULL
                 AND blocked_reason_code IS NULL
                 AND blocked_reason_label IS NULL
                 AND owner_role_proposal IS NULL)
            ),
            FOREIGN KEY(episode_id) REFERENCES followup_episodes(episode_id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(last_episode_event_id) REFERENCES followup_episode_events(id),
            FOREIGN KEY(owner_user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_followup_projection_role_state_due
        ON followup_work_item_projection(
            owner_role_proposal, state_class, action_due_at, episode_id
        );
        CREATE INDEX IF NOT EXISTS idx_followup_projection_patient
        ON followup_work_item_projection(patient_link_id, state_class, episode_id);
        CREATE INDEX IF NOT EXISTS idx_followup_projection_target
        ON followup_work_item_projection(target_at, state_class, episode_id);
        CREATE INDEX IF NOT EXISTS idx_followup_projection_rebuilt
        ON followup_work_item_projection(rebuilt_at, episode_id);
        """
    )
    db.commit()


__all__ = [
    "OWNER_ROLES",
    "PROJECTION_VERSION",
    "STATE_CLASSES",
    "ensure_followup_projection_storage",
]
