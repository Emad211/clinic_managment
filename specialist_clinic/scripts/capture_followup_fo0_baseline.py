#!/usr/bin/env python3
"""Capture aggregate FOUX-V1 FO-0 metrics from specialist.db in read-only mode.

The repository intentionally does not contain a production database. This utility gives
operators one reproducible way to capture the operational baseline without importing the
Flask app, running migrations, exposing patient rows, or mutating SQLite.

Only aggregate counts and database metadata are emitted. No patient identifier, phone,
clinical value, message body, note, or other PHI is selected.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable
from urllib.parse import quote


SCHEMA_VERSION = "1.0"
TEHRAN = timezone(timedelta(hours=3, minutes=30))
NONTERMINAL_CLINICAL = (
    "OPEN",
    "ASSIGNED",
    "SCHEDULED",
    "IN_PROGRESS",
    "DEFERRED",
)
NONTERMINAL_PLAN = ("OPEN", "IN_PROGRESS", "SCHEDULED")
INFLIGHT_DELIVERY = (
    "PendingApproval",
    "WaitingForSend",
    "Sending",
    "SendToOperator",
    "Sent",
    "SubmissionUnknown",
)
RELEVANT_TABLES = (
    "patient_links",
    "followup_tasks",
    "clinical_task_events",
    "care_plan_commitment_events",
    "engagement_approvals",
    "engagement_dispatch",
    "sms_messages",
    "sms_campaigns",
    "appointments",
    "followup_contact_events",
    "operational_job_runs",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _readonly_uri(path: Path) -> str:
    encoded = quote(path.resolve().as_posix(), safe="/:")
    return f"file:{encoded}?mode=ro"


def _table_names(db: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _count(
    db: sqlite3.Connection,
    tables: set[str],
    required_tables: Iterable[str],
    sql: str,
    params: Iterable[Any] = (),
) -> int | None:
    if not set(required_tables).issubset(tables):
        return None
    row = db.execute(sql, tuple(params)).fetchone()
    return int(row[0] or 0) if row else 0


def _placeholders(values: Iterable[str]) -> str:
    return ",".join("?" for _ in values)


def capture(database_path: str | Path, *, captured_at: datetime | None = None) -> dict:
    """Return aggregate baseline metrics without changing the database file."""
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"specialist database not found: {path}")

    before_size = path.stat().st_size
    before_hash = _sha256(path)
    now = captured_at or datetime.now(TEHRAN)
    now_text = now.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
    today = now.date().isoformat()

    db = sqlite3.connect(_readonly_uri(path), uri=True, timeout=30)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        tables = _table_names(db)
        quick_check_row = db.execute("PRAGMA quick_check").fetchone()
        quick_check = str(quick_check_row[0] if quick_check_row else "missing")

        clinical_head_sql = """
            WITH head AS (
                SELECT event.*
                FROM clinical_task_events event
                WHERE NOT EXISTS (
                    SELECT 1 FROM clinical_task_events child
                    WHERE child.supersedes_event_id=event.id
                )
            )
            SELECT COUNT(*) FROM head WHERE status IN ({})
        """.format(_placeholders(NONTERMINAL_CLINICAL))
        clinical_unassigned_sql = """
            WITH head AS (
                SELECT event.*
                FROM clinical_task_events event
                WHERE NOT EXISTS (
                    SELECT 1 FROM clinical_task_events child
                    WHERE child.supersedes_event_id=event.id
                )
            )
            SELECT COUNT(*) FROM head
            WHERE status IN ({})
              AND length(trim(COALESCE(assigned_to,'')))=0
        """.format(_placeholders(NONTERMINAL_CLINICAL))
        plan_head_sql = """
            WITH head AS (
                SELECT event.*
                FROM care_plan_commitment_events event
                WHERE NOT EXISTS (
                    SELECT 1 FROM care_plan_commitment_events child
                    WHERE child.supersedes_event_id=event.id
                )
            )
            SELECT COUNT(*) FROM head WHERE status IN ({})
        """.format(_placeholders(NONTERMINAL_PLAN))
        plan_unassigned_sql = """
            WITH head AS (
                SELECT event.*
                FROM care_plan_commitment_events event
                WHERE NOT EXISTS (
                    SELECT 1 FROM care_plan_commitment_events child
                    WHERE child.supersedes_event_id=event.id
                )
            )
            SELECT COUNT(*) FROM head
            WHERE status IN ({})
              AND length(trim(COALESCE(assigned_to,'')))=0
        """.format(_placeholders(NONTERMINAL_PLAN))

        metrics: dict[str, int | None] = {
            "active_patients": _count(
                db,
                tables,
                ("patient_links",),
                "SELECT COUNT(*) FROM patient_links WHERE is_active=1",
            ),
            "open_admin_tasks": _count(
                db,
                tables,
                ("followup_tasks",),
                """SELECT COUNT(*) FROM followup_tasks
                   WHERE status='open'
                     AND COALESCE(source_engine,'') NOT IN
                         ('clinical_v2','encounter_plan')""",
            ),
            "unassigned_open_admin_tasks": _count(
                db,
                tables,
                ("followup_tasks",),
                """SELECT COUNT(*) FROM followup_tasks
                   WHERE status='open'
                     AND COALESCE(source_engine,'') NOT IN
                         ('clinical_v2','encounter_plan')
                     AND length(trim(COALESCE(assigned_to,'')))=0""",
            ),
            "overdue_open_admin_tasks": _count(
                db,
                tables,
                ("followup_tasks",),
                """SELECT COUNT(*) FROM followup_tasks
                   WHERE status='open'
                     AND COALESCE(source_engine,'') NOT IN
                         ('clinical_v2','encounter_plan')
                     AND due_date IS NOT NULL AND date(due_date)<date(?)""",
                (today,),
            ),
            "current_nonterminal_clinical_tasks": _count(
                db,
                tables,
                ("clinical_task_events",),
                clinical_head_sql,
                NONTERMINAL_CLINICAL,
            ),
            "unassigned_current_clinical_tasks": _count(
                db,
                tables,
                ("clinical_task_events",),
                clinical_unassigned_sql,
                NONTERMINAL_CLINICAL,
            ),
            "current_nonterminal_plan_commitments": _count(
                db,
                tables,
                ("care_plan_commitment_events",),
                plan_head_sql,
                NONTERMINAL_PLAN,
            ),
            "unassigned_current_plan_commitments": _count(
                db,
                tables,
                ("care_plan_commitment_events",),
                plan_unassigned_sql,
                NONTERMINAL_PLAN,
            ),
            "pending_engagement_approvals": _count(
                db,
                tables,
                ("engagement_approvals",),
                "SELECT COUNT(*) FROM engagement_approvals WHERE status='pending'",
            ),
            "failed_or_unknown_engagement_approvals": _count(
                db,
                tables,
                ("engagement_approvals",),
                """SELECT COUNT(*) FROM engagement_approvals
                   WHERE status IN ('failed','unknown')""",
            ),
            "engagement_dispatch_rows": _count(
                db,
                tables,
                ("engagement_dispatch",),
                "SELECT COUNT(*) FROM engagement_dispatch",
            ),
            "sms_delivered": _count(
                db,
                tables,
                ("sms_messages",),
                """SELECT COUNT(*) FROM sms_messages
                   WHERE delivery_status='Delivered'""",
            ),
            "sms_inflight_or_unknown": _count(
                db,
                tables,
                ("sms_messages",),
                """SELECT COUNT(*) FROM sms_messages
                   WHERE status='pending' OR delivery_status IN ({})""".format(
                    _placeholders(INFLIGHT_DELIVERY)
                ),
                INFLIGHT_DELIVERY,
            ),
            "sms_failed": _count(
                db,
                tables,
                ("sms_messages",),
                """SELECT COUNT(*) FROM sms_messages
                   WHERE status='failed'
                      OR delivery_status IN ('Failed','Rejected','Undeliverable')""",
            ),
            "due_scheduled_campaigns": _count(
                db,
                tables,
                ("sms_campaigns",),
                """SELECT COUNT(*) FROM sms_campaigns
                   WHERE status='scheduled' AND datetime(scheduled_at)<=datetime(?)""",
                (now_text,),
            ),
            "scheduled_appointments": _count(
                db,
                tables,
                ("appointments",),
                "SELECT COUNT(*) FROM appointments WHERE status='scheduled'",
            ),
            "no_show_appointments": _count(
                db,
                tables,
                ("appointments",),
                "SELECT COUNT(*) FROM appointments WHERE status='no_show'",
            ),
            "contact_events": _count(
                db,
                tables,
                ("followup_contact_events",),
                "SELECT COUNT(*) FROM followup_contact_events",
            ),
            "callbacks_due_from_latest_contact": _count(
                db,
                tables,
                ("followup_contact_events",),
                """WITH latest AS (
                       SELECT event.* FROM followup_contact_events event
                       WHERE NOT EXISTS (
                           SELECT 1 FROM followup_contact_events newer
                           WHERE newer.task_id=event.task_id
                             AND (datetime(newer.occurred_at)>datetime(event.occurred_at)
                                  OR (newer.occurred_at=event.occurred_at
                                      AND newer.id>event.id))
                       )
                   )
                   SELECT COUNT(*) FROM latest
                   WHERE next_contact_at IS NOT NULL
                     AND datetime(next_contact_at)<=datetime(?)""",
                (now_text,),
            ),
            "scheduler_failed_job_keys": _count(
                db,
                tables,
                ("operational_job_runs",),
                "SELECT COUNT(*) FROM operational_job_runs WHERE status='FAILED'",
            ),
            "scheduler_running_job_keys": _count(
                db,
                tables,
                ("operational_job_runs",),
                "SELECT COUNT(*) FROM operational_job_runs WHERE status='RUNNING'",
            ),
        }

        open_parts = [
            metrics.get("open_admin_tasks"),
            metrics.get("current_nonterminal_clinical_tasks"),
            metrics.get("current_nonterminal_plan_commitments"),
        ]
        unassigned_parts = [
            metrics.get("unassigned_open_admin_tasks"),
            metrics.get("unassigned_current_clinical_tasks"),
            metrics.get("unassigned_current_plan_commitments"),
        ]
        if all(value is not None for value in open_parts):
            metrics["current_open_work_items_total"] = sum(
                int(value or 0) for value in open_parts
            )
        else:
            metrics["current_open_work_items_total"] = None
        if all(value is not None for value in unassigned_parts):
            metrics["current_unassigned_work_items_total"] = sum(
                int(value or 0) for value in unassigned_parts
            )
        else:
            metrics["current_unassigned_work_items_total"] = None

        total = metrics.get("current_open_work_items_total")
        unassigned = metrics.get("current_unassigned_work_items_total")
        unassigned_rate = (
            round((int(unassigned) / int(total)) * 100, 2)
            if total not in (None, 0) and unassigned is not None
            else 0.0 if total == 0 and unassigned is not None
            else None
        )

        result = {
            "schema_version": SCHEMA_VERSION,
            "program": "FOUX-V1",
            "tranche": "FO-0",
            "captured_at_tehran": now.isoformat(timespec="seconds"),
            "read_only": True,
            "contains_phi": False,
            "database": {
                "file_name": path.name,
                "size_bytes": before_size,
                "sha256": before_hash,
                "quick_check": quick_check,
            },
            "table_presence": {
                name: name in tables for name in RELEVANT_TABLES
            },
            "metrics": metrics,
            "derived": {
                "unassigned_open_work_item_percent": unassigned_rate,
            },
            "definitions": {
                "current_open_work_items_total": (
                    "open administrative rows + current nonterminal clinical task "
                    "heads + current nonterminal encounter-plan commitment heads"
                ),
                "unassigned": (
                    "current task/event head has no non-blank assigned_to; role queues "
                    "do not exist before FO-4"
                ),
                "callbacks_due_from_latest_contact": (
                    "latest append-only contact event per task has next_contact_at at or "
                    "before capture time"
                ),
            },
        }
    finally:
        db.close()

    after_size = path.stat().st_size
    after_hash = _sha256(path)
    if before_size != after_size or before_hash != after_hash:
        raise RuntimeError("baseline capture changed the database file")
    result["database_unchanged_after_capture"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Capture aggregate Follow-up Orchestration FO-0 baseline metrics from "
            "specialist.db without modifying it."
        )
    )
    parser.add_argument("--database", required=True, help="Path to specialist.db")
    parser.add_argument(
        "--output",
        help="Optional JSON output path. Defaults to stdout.",
    )
    args = parser.parse_args()

    payload = capture(args.database)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
