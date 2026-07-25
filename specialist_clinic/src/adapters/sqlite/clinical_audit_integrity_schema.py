"""Append-only integrity checkpoints for immutable clinical audit history."""
from __future__ import annotations

import sqlite3

from src.adapters.sqlite.core import get_db


_REQUIRED_TRIGGERS = {
    "trg_clinical_audit_checkpoints_no_update",
    "trg_clinical_audit_checkpoints_no_delete",
}


def ensure_clinical_audit_integrity_storage(
    db: sqlite3.Connection | None = None,
) -> None:
    db = db or get_db()
    # A checkpoint must never silently omit a critical event family merely because a
    # copied or test database has not yet touched that subsystem. Install the additive
    # dependencies before creating or verifying an audit root.
    from src.adapters.sqlite.clinical_care_loop_schema import (
        ensure_clinical_care_loop_storage,
    )
    from src.adapters.sqlite.security_permission_schema import (
        ensure_security_permission_storage,
    )

    ensure_clinical_care_loop_storage(db)
    ensure_security_permission_storage(db)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS clinical_audit_checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope_version TEXT NOT NULL
                CHECK (length(trim(scope_version)) BETWEEN 1 AND 40),
            root_hash TEXT NOT NULL CHECK (length(root_hash)=64),
            table_counts_json TEXT NOT NULL
                CHECK (json_valid(table_counts_json)
                       AND json_type(table_counts_json)='object'),
            table_max_rowid_json TEXT NOT NULL
                CHECK (json_valid(table_max_rowid_json)
                       AND json_type(table_max_rowid_json)='object'),
            previous_checkpoint_hash TEXT
                CHECK (previous_checkpoint_hash IS NULL
                       OR length(previous_checkpoint_hash)=64),
            checkpoint_hash TEXT NOT NULL UNIQUE
                CHECK (length(checkpoint_hash)=64),
            created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
            created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0)
        );

        CREATE TRIGGER IF NOT EXISTS trg_clinical_audit_checkpoints_no_update
        BEFORE UPDATE ON clinical_audit_checkpoints
        BEGIN
            SELECT RAISE(ABORT, 'clinical audit checkpoints are append-only');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_audit_checkpoints_no_delete
        BEFORE DELETE ON clinical_audit_checkpoints
        BEGIN
            SELECT RAISE(ABORT, 'clinical audit checkpoints cannot be deleted');
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
            "clinical audit integrity guards are incomplete: "
            + ", ".join(missing)
        )
    db.commit()
