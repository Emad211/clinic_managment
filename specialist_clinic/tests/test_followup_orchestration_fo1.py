from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from src.adapters.sqlite.followup_episode_repo import (
    FollowupEpisodeConflict,
    FollowupEpisodeRepository,
)
from src.adapters.sqlite.followup_operations_schema import ensure_followup_operations_storage
from src.services.followup_orchestration.backfill import FollowupEpisodeBackfillService
from src.services.followup_orchestration.identity import EpisodeIdentity


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY);
        CREATE TABLE patient_links (id INTEGER PRIMARY KEY);
        CREATE TABLE care_journeys (
            journey_id TEXT PRIMARY KEY,
            patient_link_id INTEGER NOT NULL
        );
        CREATE TABLE appointments (
            id INTEGER PRIMARY KEY,
            patient_link_id INTEGER NOT NULL,
            scheduled_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT
        );
        CREATE TABLE followup_tasks (
            id INTEGER PRIMARY KEY,
            patient_link_id INTEGER NOT NULL,
            due_date TEXT,
            status TEXT,
            source_engine TEXT,
            source_rule TEXT,
            source_event TEXT,
            appointment_id INTEGER,
            clinical_task_key TEXT,
            clinical_due_period TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE clinical_task_events (
            id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL,
            appointment_id INTEGER,
            status TEXT,
            recorded_at TEXT NOT NULL
        );
        CREATE TABLE clinical_outcome_events (
            id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        );
        CREATE TABLE care_plan_commitments (
            commitment_id TEXT PRIMARY KEY,
            patient_link_id INTEGER NOT NULL,
            document_event_id INTEGER NOT NULL,
            client_key TEXT NOT NULL,
            original_due_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE care_plan_commitment_task_links (
            commitment_id TEXT PRIMARY KEY,
            task_id INTEGER NOT NULL
        );
        CREATE TABLE care_plan_commitment_events (
            id INTEGER PRIMARY KEY,
            commitment_id TEXT NOT NULL,
            appointment_id INTEGER,
            recorded_at TEXT NOT NULL
        );
        CREATE TABLE engagement_approvals (
            id INTEGER PRIMARY KEY,
            patient_link_id INTEGER NOT NULL,
            event_key TEXT NOT NULL,
            period_key TEXT NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT
        );
        CREATE TABLE engagement_dispatch (
            id INTEGER PRIMARY KEY,
            patient_link_id INTEGER NOT NULL,
            event_key TEXT NOT NULL,
            period_key TEXT NOT NULL,
            channel TEXT NOT NULL,
            ref_id INTEGER,
            created_at TEXT NOT NULL
        );
        CREATE TABLE sms_messages (
            id INTEGER PRIMARY KEY,
            patient_link_id INTEGER,
            source_type TEXT,
            source_ref TEXT,
            created_at TEXT NOT NULL,
            status TEXT,
            delivery_status TEXT
        );
        CREATE TABLE followup_contact_events (
            id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL,
            patient_link_id INTEGER NOT NULL,
            journey_id TEXT,
            channel TEXT,
            outcome TEXT,
            occurred_at TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            actor_user_id INTEGER,
            actor_username TEXT,
            note TEXT,
            next_contact_at TEXT,
            idempotency_key TEXT NOT NULL,
            content_hash TEXT NOT NULL
        );
        CREATE TABLE followup_booking_requests (
            id INTEGER PRIMARY KEY,
            idempotency_key TEXT,
            patient_link_id INTEGER NOT NULL,
            appointment_id INTEGER NOT NULL,
            scheduled_at TEXT NOT NULL,
            task_ids_json TEXT NOT NULL,
            actor_user_id INTEGER,
            actor_username TEXT,
            created_at TEXT NOT NULL,
            content_hash TEXT NOT NULL
        );

        INSERT INTO patient_links VALUES (1), (2);
        INSERT INTO appointments VALUES
            (10,1,'2026-08-10 09:00:00','2026-08-01 08:00:00','scheduled'),
            (20,1,'2026-08-12 10:00:00','2026-08-01 08:10:00','scheduled'),
            (30,1,'2026-08-13 11:00:00','2026-08-01 08:20:00','scheduled');
        INSERT INTO followup_tasks VALUES
            (1,1,'2026-08-10','open','',NULL,'lapsed',10,NULL,NULL,'2026-08-01 09:00:00'),
            (2,1,'2026-08-12','open','clinical_v2','RULE-1','clinical_due',20,'clinical-key-1','2026-08','2026-08-01 09:05:00'),
            (3,1,'2026-08-13','open','encounter_plan','commit-1','encounter_plan_commitment',30,NULL,NULL,'2026-08-01 09:10:00'),
            (4,2,'2026-08-15','open','',NULL,'manual',NULL,NULL,NULL,'2026-08-01 09:15:00');
        INSERT INTO care_plan_commitments VALUES
            ('commit-1',1,100,'client-1','2026-08-13 09:00:00','2026-08-01 09:08:00');
        INSERT INTO care_plan_commitment_task_links VALUES ('commit-1',3);
        INSERT INTO care_plan_commitment_events VALUES
            (1,'commit-1',30,'2026-08-01 09:10:00');
        INSERT INTO engagement_dispatch VALUES
            (1,1,'lapsed','lapsed:2026-08','worklist',1,'2026-08-01 09:00:00');
        INSERT INTO engagement_approvals VALUES
            (5,1,'lapsed','lapsed:2026-08','2026-08-01 09:01:00','pending');
        INSERT INTO sms_messages VALUES
            (7,1,'engagement','5','2026-08-01 09:02:00','sent','Delivered'),
            (8,1,'manual',NULL,'2026-08-01 09:03:00','sent','Delivered');
        INSERT INTO followup_contact_events VALUES
            (9,1,1,NULL,'PHONE','REACHED','2026-08-02 10:00:00','2026-08-02 10:00:00',NULL,'staff',NULL,NULL,'contact-idempotency-0001','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');
        INSERT INTO clinical_task_events VALUES
            (11,2,20,'SCHEDULED','2026-08-01 09:20:00');
        INSERT INTO clinical_outcome_events VALUES
            (12,2,'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb','2026-08-02 11:00:00');
        INSERT INTO followup_booking_requests VALUES
            (13,'booking-idempotency-1',1,10,'2026-08-10 09:00:00','[1]',NULL,'staff','2026-08-01 09:30:00','cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc');
        """
    )
    return db


def _source_snapshot(db: sqlite3.Connection) -> str:
    tables = (
        "followup_tasks",
        "clinical_task_events",
        "clinical_outcome_events",
        "care_plan_commitments",
        "care_plan_commitment_task_links",
        "care_plan_commitment_events",
        "engagement_approvals",
        "engagement_dispatch",
        "sms_messages",
        "appointments",
        "followup_contact_events",
        "followup_booking_requests",
    )
    payload = {}
    for table in tables:
        payload[table] = [
            list(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
        ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_episode_identity_is_deterministic_and_normalized():
    left = EpisodeIdentity.build(
        patient_link_id=1,
        episode_type="engagement",
        semantic_key=" Engagement:Lapsed ",
        period_key="LAPSED:2026-08",
    )
    right = EpisodeIdentity.build(
        patient_link_id=1,
        episode_type="ENGAGEMENT",
        semantic_key="engagement:lapsed",
        period_key="lapsed:2026-08",
    )
    assert left == right
    assert len(left.identity_hash) == 64
    assert left.episode_id == "fuep_" + left.identity_hash


def test_schema_is_idempotent_and_installed_through_followup_operations():
    db = _db()
    ensure_followup_operations_storage(db)
    ensure_followup_operations_storage(db)
    names = {
        row[0]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "followup_episodes",
        "followup_episode_links",
        "followup_episode_events",
    } <= names


def test_episode_links_and_events_are_immutable_append_only():
    db = _db()
    repo = FollowupEpisodeRepository(db)
    identity = EpisodeIdentity.build(
        patient_link_id=1,
        episode_type="ADMIN_FOLLOWUP",
        semantic_key="admin-task:1",
        period_key="2026-08-10",
    )
    episode, created = repo.create_episode_once(
        identity,
        actor_username="test",
        opened_at="2026-08-01 09:00:00",
    )
    assert created is True
    link, linked = repo.link_source_once(
        episode_id=episode["episode_id"],
        patient_link_id=1,
        source_type="ADMIN_TASK",
        source_id="1",
        source_revision="d" * 64,
        relation_type="PRIMARY",
        actor_username="test",
        linked_at="2026-08-01 09:00:00",
    )
    assert linked is True
    assert [row["event_type"] for row in repo.events(episode["episode_id"])] == [
        "EPISODE_OPENED",
        "SOURCE_LINKED",
    ]
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE followup_episodes SET semantic_key='changed' WHERE episode_id=?",
            (episode["episode_id"],),
        )
    db.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM followup_episode_links WHERE id=?", (link["id"],))
    db.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE followup_episode_events SET event_type='ROUTED' WHERE episode_id=?",
            (episode["episode_id"],),
        )


def test_source_patient_mismatch_is_rejected():
    db = _db()
    repo = FollowupEpisodeRepository(db)
    identity = EpisodeIdentity.build(
        patient_link_id=1,
        episode_type="ADMIN_FOLLOWUP",
        semantic_key="admin-task:1",
        period_key="2026-08-10",
    )
    repo.create_episode_once(
        identity,
        actor_username="test",
        opened_at="2026-08-01 09:00:00",
    )
    with pytest.raises(FollowupEpisodeConflict, match="EPISODE_SOURCE_PATIENT_MISMATCH"):
        repo.link_source_once(
            episode_id=identity.episode_id,
            patient_link_id=1,
            source_type="ADMIN_TASK",
            source_id="4",
            source_revision="e" * 64,
            relation_type="RELATED",
            actor_username="test",
            linked_at="2026-08-01 09:15:00",
        )


def test_backfill_is_deterministic_idempotent_and_preserves_sources():
    db = _db()
    before = _source_snapshot(db)
    service = FollowupEpisodeBackfillService(db)

    dry_one = service.run(apply=False)
    dry_two = service.run(apply=False)
    assert dry_one["plan_hash"] == dry_two["plan_hash"]
    assert dry_one["episodes_planned"] == 4
    assert dry_one["links_planned"] == 12
    assert dry_one["orphan_reasons"] == {"SMS_OUTSIDE_FOLLOWUP_ENGAGEMENT": 1}

    first = service.run(apply=True)
    second = service.run(apply=True)
    assert first["episodes_created"] == 4
    assert first["links_created"] == 12
    assert second["episodes_created"] == 0
    assert second["episodes_existing"] == 4
    assert second["links_created"] == 0
    assert second["links_existing"] == 12
    assert _source_snapshot(db) == before

    assert db.execute("SELECT COUNT(*) FROM followup_episodes").fetchone()[0] == 4
    assert db.execute("SELECT COUNT(*) FROM followup_episode_links").fetchone()[0] == 12
    assert db.execute("SELECT COUNT(*) FROM followup_episode_events").fetchone()[0] == 16


def test_backfill_report_contains_no_patient_identity():
    db = _db()
    payload = FollowupEpisodeBackfillService(db).run(apply=False)
    rendered = json.dumps(payload, ensure_ascii=False, default=str)
    assert "phone" not in rendered.lower()
    assert "full_name" not in rendered.lower()
    assert "patient_link_id" not in rendered.lower()
