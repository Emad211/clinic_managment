"""Mutable operational leases with monotonic fencing tokens."""
from __future__ import annotations

import sqlite3

from src.adapters.sqlite.core import get_db


def ensure_operational_lease_storage(
    db: sqlite3.Connection | None = None,
) -> None:
    db = db or get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS operational_leases (
            lease_name TEXT PRIMARY KEY
                CHECK (length(trim(lease_name)) BETWEEN 3 AND 160),
            owner_id TEXT NOT NULL CHECK (length(trim(owner_id)) BETWEEN 3 AND 240),
            fencing_token INTEGER NOT NULL CHECK (fencing_token > 0),
            acquired_at TEXT NOT NULL CHECK (datetime(acquired_at) IS NOT NULL),
            heartbeat_at TEXT NOT NULL CHECK (datetime(heartbeat_at) IS NOT NULL),
            expires_at TEXT NOT NULL CHECK (datetime(expires_at) IS NOT NULL),
            CHECK (datetime(acquired_at) <= datetime(heartbeat_at)),
            CHECK (datetime(heartbeat_at) < datetime(expires_at))
        );

        CREATE TABLE IF NOT EXISTS operational_job_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_key TEXT NOT NULL UNIQUE
                CHECK (length(trim(job_key)) BETWEEN 3 AND 240),
            lease_name TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            fencing_token INTEGER NOT NULL CHECK (fencing_token > 0),
            status TEXT NOT NULL CHECK (status IN ('RUNNING','COMPLETED','FAILED')),
            started_at TEXT NOT NULL CHECK (datetime(started_at) IS NOT NULL),
            completed_at TEXT,
            error_code TEXT,
            CHECK (completed_at IS NULL OR datetime(completed_at) >= datetime(started_at))
        );

        CREATE INDEX IF NOT EXISTS idx_operational_leases_expiry
        ON operational_leases(expires_at);
        CREATE INDEX IF NOT EXISTS idx_operational_job_runs_status
        ON operational_job_runs(status, started_at DESC);
        """
    )
    db.commit()
