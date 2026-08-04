"""Additive immutable storage for FOUX-V1 FO-6 governed CARE SMS.

The schema stores policy/template versions, PHI-minimized candidate snapshots and
append-only decisions.  It deliberately does not store raw phone numbers,
rendered message bodies, patient names, free text, scheduler jobs, an outbox or
cross-channel transitions.
"""
from __future__ import annotations

import sqlite3


_TABLES = frozenset(
    {
        "sms_auto_guard_policy_versions",
        "sms_auto_guard_template_versions",
        "sms_auto_guard_candidates",
        "sms_auto_guard_decision_events",
    }
)
_TRIGGERS = frozenset(
    {
        "trg_sms_auto_policy_no_update",
        "trg_sms_auto_policy_no_delete",
        "trg_sms_auto_template_no_update",
        "trg_sms_auto_template_no_delete",
        "trg_sms_auto_candidate_no_update",
        "trg_sms_auto_candidate_no_delete",
        "trg_sms_auto_decision_no_update",
        "trg_sms_auto_decision_no_delete",
    }
)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sms_auto_guard_policy_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_key TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version > 0),
    purpose TEXT NOT NULL CHECK(purpose = 'CARE'),
    policy_json TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK(length(content_hash) = 64),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(policy_key, version),
    UNIQUE(policy_key, content_hash)
);

CREATE TABLE IF NOT EXISTS sms_auto_guard_template_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL CHECK(
        event_key IN ('appointment_reminder', 'refill_due')
    ),
    version INTEGER NOT NULL CHECK(version > 0),
    policy_version_id INTEGER NOT NULL,
    template_text TEXT NOT NULL CHECK(length(trim(template_text)) > 0),
    message_type TEXT NOT NULL DEFAULT 'Informational',
    content_hash TEXT NOT NULL CHECK(length(content_hash) = 64),
    approved_by TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    FOREIGN KEY(policy_version_id)
        REFERENCES sms_auto_guard_policy_versions(id),
    UNIQUE(event_key, version),
    UNIQUE(event_key, content_hash)
);

CREATE TABLE IF NOT EXISTS sms_auto_guard_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_link_id INTEGER NOT NULL,
    event_key TEXT NOT NULL CHECK(
        event_key IN ('appointment_reminder', 'refill_due')
    ),
    period_key TEXT NOT NULL CHECK(length(trim(period_key)) > 0),
    generation_no INTEGER NOT NULL CHECK(generation_no > 0),
    policy_version_id INTEGER NOT NULL,
    template_version_id INTEGER NOT NULL,
    purpose TEXT NOT NULL CHECK(purpose = 'CARE'),
    consent_event_id INTEGER NOT NULL,
    phone_hash TEXT NOT NULL CHECK(length(phone_hash) = 64),
    source_hash TEXT NOT NULL CHECK(length(source_hash) = 64),
    body_hash TEXT NOT NULL CHECK(length(body_hash) = 64),
    provider_name TEXT NOT NULL CHECK(
        provider_name IN ('kavenegar', 'mediana')
    ),
    snapshot_hash TEXT NOT NULL CHECK(length(snapshot_hash) = 64),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
    FOREIGN KEY(policy_version_id)
        REFERENCES sms_auto_guard_policy_versions(id),
    FOREIGN KEY(template_version_id)
        REFERENCES sms_auto_guard_template_versions(id),
    FOREIGN KEY(consent_event_id) REFERENCES sms_consent_events(id),
    UNIQUE(patient_link_id, event_key, period_key, generation_no)
);

CREATE TABLE IF NOT EXISTS sms_auto_guard_decision_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL,
    decision_type TEXT NOT NULL CHECK(
        decision_type IN (
            'CREATED', 'DENIED', 'SUPERSEDED', 'CLAIMED',
            'SUBMITTED', 'SUBMISSION_FAILED'
        )
    ),
    attempt_no INTEGER NOT NULL DEFAULT 0 CHECK(attempt_no >= 0),
    reason_code TEXT NOT NULL,
    revalidation_hash TEXT CHECK(
        revalidation_hash IS NULL OR length(revalidation_hash) = 64
    ),
    message_id INTEGER,
    payload_json TEXT NOT NULL DEFAULT '{}',
    actor_username TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY(candidate_id) REFERENCES sms_auto_guard_candidates(id),
    FOREIGN KEY(message_id) REFERENCES sms_messages(id)
);

CREATE INDEX IF NOT EXISTS idx_sms_auto_policy_latest
    ON sms_auto_guard_policy_versions(policy_key, version DESC);
CREATE INDEX IF NOT EXISTS idx_sms_auto_template_latest
    ON sms_auto_guard_template_versions(event_key, version DESC);
CREATE INDEX IF NOT EXISTS idx_sms_auto_candidate_identity
    ON sms_auto_guard_candidates(
        patient_link_id, event_key, period_key, generation_no DESC
    );
CREATE INDEX IF NOT EXISTS idx_sms_auto_candidate_expiry
    ON sms_auto_guard_candidates(expires_at, id);
CREATE INDEX IF NOT EXISTS idx_sms_auto_decision_candidate
    ON sms_auto_guard_decision_events(candidate_id, id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sms_auto_claim_attempt
    ON sms_auto_guard_decision_events(candidate_id, attempt_no)
    WHERE decision_type='CLAIMED';
CREATE UNIQUE INDEX IF NOT EXISTS idx_sms_auto_terminal_attempt
    ON sms_auto_guard_decision_events(candidate_id, attempt_no)
    WHERE decision_type IN ('SUBMITTED', 'SUBMISSION_FAILED');
CREATE UNIQUE INDEX IF NOT EXISTS idx_sms_auto_submitted_once
    ON sms_auto_guard_decision_events(candidate_id)
    WHERE decision_type='SUBMITTED';
CREATE UNIQUE INDEX IF NOT EXISTS idx_sms_auto_superseded_once
    ON sms_auto_guard_decision_events(candidate_id)
    WHERE decision_type='SUPERSEDED';

CREATE TRIGGER IF NOT EXISTS trg_sms_auto_policy_no_update
BEFORE UPDATE ON sms_auto_guard_policy_versions
BEGIN
    SELECT RAISE(ABORT, 'sms auto-guard policy versions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_sms_auto_policy_no_delete
BEFORE DELETE ON sms_auto_guard_policy_versions
BEGIN
    SELECT RAISE(ABORT, 'sms auto-guard policy versions are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_sms_auto_template_no_update
BEFORE UPDATE ON sms_auto_guard_template_versions
BEGIN
    SELECT RAISE(ABORT, 'sms auto-guard template versions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_sms_auto_template_no_delete
BEFORE DELETE ON sms_auto_guard_template_versions
BEGIN
    SELECT RAISE(ABORT, 'sms auto-guard template versions are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_sms_auto_candidate_no_update
BEFORE UPDATE ON sms_auto_guard_candidates
BEGIN
    SELECT RAISE(ABORT, 'sms auto-guard candidates are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_sms_auto_candidate_no_delete
BEFORE DELETE ON sms_auto_guard_candidates
BEGIN
    SELECT RAISE(ABORT, 'sms auto-guard candidates are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_sms_auto_decision_no_update
BEFORE UPDATE ON sms_auto_guard_decision_events
BEGIN
    SELECT RAISE(ABORT, 'sms auto-guard decisions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_sms_auto_decision_no_delete
BEFORE DELETE ON sms_auto_guard_decision_events
BEGIN
    SELECT RAISE(ABORT, 'sms auto-guard decisions are append-only');
END;
"""


def storage_ready(db: sqlite3.Connection) -> bool:
    db.row_factory = sqlite3.Row
    table_rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    trigger_rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'"
    ).fetchall()
    tables = {str(row["name"]) for row in table_rows}
    triggers = {str(row["name"]) for row in trigger_rows}
    return _TABLES.issubset(tables) and _TRIGGERS.issubset(triggers)


def ensure_sms_auto_guard_storage(db: sqlite3.Connection) -> None:
    """Install only the additive FO-6 storage on an explicit mutation path."""
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA_SQL)
    db.commit()
    if not storage_ready(db):
        raise RuntimeError("FO-6 SMS auto-guard storage installation incomplete")


__all__ = [
    "ensure_sms_auto_guard_storage",
    "storage_ready",
]
