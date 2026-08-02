#!/usr/bin/env python3
"""Dry-run or apply FO-1 Episode/link backfill against Specialist Clinic SQLite."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
SPECIALIST_ROOT = SCRIPT_DIR.parent
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))

from src.adapters.sqlite.followup_episode_schema import (  # noqa: E402
    ensure_followup_episode_storage,
)
from src.services.followup_orchestration.backfill import (  # noqa: E402
    FollowupEpisodeBackfillService,
)
from src.services.followup_orchestration.identity import canonical_hash  # noqa: E402

SOURCE_TABLES = (
    "followup_tasks",
    "clinical_task_events",
    "clinical_outcome_events",
    "care_plan_commitments",
    "care_plan_commitment_task_links",
    "care_plan_commitment_events",
    "followup_contact_events",
    "followup_booking_requests",
    "engagement_approvals",
    "engagement_dispatch",
    "sms_messages",
    "appointments",
)


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    return bool(
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    )


def _table_digest(db: sqlite3.Connection, table: str) -> str | None:
    if not _table_exists(db, table):
        return None
    columns = [
        str(row[1]) for row in db.execute(f"PRAGMA table_info({table})").fetchall()
    ]
    order = ", ".join(f'"{column}"' for column in columns) if columns else "rowid"
    digest = hashlib.sha256()
    for row in db.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall():
        digest.update(
            json.dumps(
                [
                    value.hex() if isinstance(value, bytes) else value
                    for value in tuple(row)
                ],
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def source_truth_digest(db: sqlite3.Connection) -> dict:
    tables = {table: _table_digest(db, table) for table in SOURCE_TABLES}
    return {"tables": tables, "combined": canonical_hash(tables)}


def _connect(path: Path, *, apply: bool) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    if apply:
        connection = sqlite3.connect(str(path), timeout=30)
    else:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
        connection.execute("PRAGMA query_only=ON")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def run(database: Path, *, apply: bool) -> dict:
    db = _connect(database, apply=apply)
    try:
        before = source_truth_digest(db)
        if apply:
            ensure_followup_episode_storage(db)
        result = FollowupEpisodeBackfillService(db).run(apply=apply)
        after = source_truth_digest(db)
        if before != after:
            if apply:
                db.rollback()
            raise RuntimeError("existing source truth changed during FO-1 backfill")
        return {
            "program": "FOUX-V1",
            "tranche": "FO-1",
            "database_file_sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
            "contains_phi": False,
            "source_truth_unchanged": True,
            **result,
        }
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan or apply deterministic FO-1 follow-up Episode links."
    )
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = run(args.database.resolve(), apply=bool(args.apply))
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
