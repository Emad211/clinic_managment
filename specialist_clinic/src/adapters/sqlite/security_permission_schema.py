"""Append-only per-user permission overrides and database guards."""
from __future__ import annotations

import sqlite3

from src.adapters.sqlite.core import get_db


_REQUIRED_TRIGGERS = {
    "trg_security_permission_events_no_update",
    "trg_security_permission_events_no_delete",
    "trg_security_permission_events_first",
    "trg_security_permission_events_subsequent",
    "trg_security_permission_events_scope",
    "trg_security_permission_events_recorded_order",
}


def ensure_security_permission_storage(
    db: sqlite3.Connection | None = None,
) -> None:
    db = db or get_db()
    tables = {
        str(row["name"])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "users" not in tables:
        return

    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS security_permission_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            permission_key TEXT NOT NULL
                CHECK (length(trim(permission_key)) BETWEEN 3 AND 120),
            effect TEXT NOT NULL CHECK (effect IN ('GRANTED','REVOKED')),
            actor_user_id INTEGER,
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username)) > 0),
            reason TEXT NOT NULL CHECK (length(trim(reason)) BETWEEN 3 AND 1000),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            supersedes_event_id INTEGER,
            content_hash TEXT NOT NULL CHECK (length(content_hash)=64),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(actor_user_id) REFERENCES users(id),
            FOREIGN KEY(supersedes_event_id) REFERENCES security_permission_events(id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_security_permission_one_root
        ON security_permission_events(user_id, permission_key)
        WHERE supersedes_event_id IS NULL;

        CREATE UNIQUE INDEX IF NOT EXISTS idx_security_permission_one_child
        ON security_permission_events(supersedes_event_id)
        WHERE supersedes_event_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_security_permission_head
        ON security_permission_events(user_id, permission_key, recorded_at DESC, id DESC);

        CREATE TRIGGER IF NOT EXISTS trg_security_permission_events_no_update
        BEFORE UPDATE ON security_permission_events
        BEGIN
            SELECT RAISE(ABORT, 'security permission events are append-only');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_security_permission_events_no_delete
        BEFORE DELETE ON security_permission_events
        BEGIN
            SELECT RAISE(ABORT, 'security permission events cannot be deleted');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_security_permission_events_first
        BEFORE INSERT ON security_permission_events
        WHEN NOT EXISTS (
                SELECT 1 FROM security_permission_events prior
                WHERE prior.user_id=NEW.user_id
                  AND prior.permission_key=NEW.permission_key
             )
         AND NEW.supersedes_event_id IS NOT NULL
        BEGIN
            SELECT RAISE(ABORT, 'first permission event cannot supersede another event');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_security_permission_events_subsequent
        BEFORE INSERT ON security_permission_events
        WHEN EXISTS (
                SELECT 1 FROM security_permission_events prior
                WHERE prior.user_id=NEW.user_id
                  AND prior.permission_key=NEW.permission_key
             )
         AND (
                NEW.supersedes_event_id IS NULL
                OR NEW.supersedes_event_id<>(
                    SELECT head.id
                    FROM security_permission_events head
                    WHERE head.user_id=NEW.user_id
                      AND head.permission_key=NEW.permission_key
                      AND NOT EXISTS (
                          SELECT 1 FROM security_permission_events child
                          WHERE child.supersedes_event_id=head.id
                      )
                    ORDER BY head.recorded_at DESC, head.id DESC LIMIT 1
                )
             )
        BEGIN
            SELECT RAISE(ABORT, 'permission event must supersede current head');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_security_permission_events_scope
        BEFORE INSERT ON security_permission_events
        WHEN NEW.supersedes_event_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1 FROM security_permission_events prior
             WHERE prior.id=NEW.supersedes_event_id
               AND prior.user_id=NEW.user_id
               AND prior.permission_key=NEW.permission_key
         )
        BEGIN
            SELECT RAISE(ABORT, 'permission supersession must stay in one user and permission');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_security_permission_events_recorded_order
        BEFORE INSERT ON security_permission_events
        WHEN NEW.supersedes_event_id IS NOT NULL
         AND datetime(NEW.recorded_at) < datetime((
             SELECT prior.recorded_at
             FROM security_permission_events prior
             WHERE prior.id=NEW.supersedes_event_id
         ))
        BEGIN
            SELECT RAISE(ABORT, 'permission recorded_at cannot move backwards');
        END;
        """
    )

    triggers = {
        str(row["name"])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    missing = sorted(_REQUIRED_TRIGGERS - triggers)
    if missing:
        raise RuntimeError(
            "security permission guards are incomplete: " + ", ".join(missing)
        )
    db.commit()
