#!/usr/bin/env python3
"""Dry-run or explicitly apply the FO-2 shadow Work Item projection."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
SPECIALIST_ROOT = SCRIPT_DIR.parent
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))

from src.services.followup_orchestration.identity import canonical_hash  # noqa: E402
from src.services.followup_orchestration.projection_service import (  # noqa: E402
    FollowupProjectionService,
)

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
    "followup_episodes",
    "followup_episode_links",
    "followup_episode_events",
)


def _enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


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
    order = ",".join(f'"{column}"' for column in columns) if columns else "rowid"
    digest = hashlib.sha256()
    for row in db.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall():
        digest.update(
            json.dumps(
                [value.hex() if isinstance(value, bytes) else value for value in tuple(row)],
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


def run(database: Path, *, as_of_at: str, apply: bool) -> dict:
    if apply and not _enabled("FOLLOWUP_PROJECTION_SHADOW"):
        raise RuntimeError(
            "--apply requires FOLLOWUP_PROJECTION_SHADOW=1; default remains OFF"
        )
    db = _connect(database, apply=apply)
    try:
        before = source_truth_digest(db)
        result = FollowupProjectionService(db).run(
            as_of_at=as_of_at,
            apply=apply,
        )
        after = source_truth_digest(db)
        if before != after:
            if apply:
                db.rollback()
            raise RuntimeError("source truth changed during FO-2 projection rebuild")
        return {
            "program": "FOUX-V1",
            "tranche": "FO-2",
            "shadow_only": True,
            "contains_phi": False,
            "source_truth_unchanged": True,
            "source_truth_digest": before["combined"],
            **result,
        }
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the deterministic FOUX-V1 FO-2 shadow projection."
    )
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = run(
        args.database.resolve(),
        as_of_at=args.as_of,
        apply=bool(args.apply),
    )
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
