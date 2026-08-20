"""Repository for append-only follow-up contact events and contact summaries."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
from typing import Any

from src.adapters.sqlite.core import get_db

_IRAN_TZ = timezone(timedelta(hours=3, minutes=30))


def _text(value: datetime | str | None = None) -> str:
    if value is None:
        parsed = datetime.now(_IRAN_TZ)
    elif isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_IRAN_TZ).replace(tzinfo=None)
    return parsed.isoformat(sep=" ", timespec="seconds")


def _hash(payload: dict[str, Any]) -> str:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class FollowupContactConflict(RuntimeError):
    pass


class FollowupOperationsRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    @staticmethod
    def _row(row) -> dict | None:
        return dict(row) if row else None

    def task_identity(self, task_id: int) -> dict | None:
        row = self._db().execute(
            """SELECT task.id, task.patient_link_id, task.source_engine,
                      task.source_run_id, task.source_recommendation_event_id,
                      task.appointment_id, task.status
               FROM followup_tasks task WHERE task.id=?""",
            (int(task_id),),
        ).fetchone()
        return self._row(row)

    def create_contact(
        self,
        *,
        task_id: int,
        channel: str,
        outcome: str,
        actor_username: str,
        idempotency_key: str,
        actor_user_id: int | None = None,
        occurred_at: datetime | str | None = None,
        recorded_at: datetime | str | None = None,
        note: str | None = None,
        next_contact_at: datetime | str | None = None,
        journey_id: str | None = None,
        commit: bool = True,
    ) -> dict:
        task = self.task_identity(task_id)
        if not task:
            raise LookupError("follow-up task not found")
        key = str(idempotency_key or "").strip()
        if len(key) < 12:
            raise ValueError("contact idempotency key is required")
        prior = self._db().execute(
            "SELECT * FROM followup_contact_events WHERE idempotency_key=?",
            (key,),
        ).fetchone()
        if prior:
            if int(prior["task_id"]) != int(task_id):
                raise FollowupContactConflict("contact idempotency scope mismatch")
            return dict(prior)

        recorded = _text(recorded_at)
        occurred = _text(occurred_at or recorded)
        if datetime.fromisoformat(recorded) < datetime.fromisoformat(occurred):
            recorded = occurred
        next_contact = _text(next_contact_at) if next_contact_at else None
        payload = {
            "task_id": int(task_id),
            "patient_link_id": int(task["patient_link_id"]),
            "journey_id": str(journey_id) if journey_id else None,
            "channel": str(channel).strip().upper(),
            "outcome": str(outcome).strip().upper(),
            "occurred_at": occurred,
            "recorded_at": recorded,
            "actor_user_id": int(actor_user_id) if actor_user_id else None,
            "actor_username": str(actor_username or "").strip(),
            "note": str(note).strip() if note else None,
            "next_contact_at": next_contact,
            "idempotency_key": key,
        }
        cursor = self._db().execute(
            """INSERT INTO followup_contact_events
               (task_id, patient_link_id, journey_id, channel, outcome,
                occurred_at, recorded_at, actor_user_id, actor_username,
                note, next_contact_at, idempotency_key, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload["task_id"],
                payload["patient_link_id"],
                payload["journey_id"],
                payload["channel"],
                payload["outcome"],
                payload["occurred_at"],
                payload["recorded_at"],
                payload["actor_user_id"],
                payload["actor_username"],
                payload["note"],
                payload["next_contact_at"],
                payload["idempotency_key"],
                _hash(payload),
            ),
        )
        if commit:
            self._db().commit()
        row = self._db().execute(
            "SELECT * FROM followup_contact_events WHERE id=?",
            (cursor.lastrowid,),
        ).fetchone()
        return dict(row)

    def list_for_task(self, task_id: int, limit: int = 100) -> list[dict]:
        rows = self._db().execute(
            """SELECT * FROM followup_contact_events
               WHERE task_id=? ORDER BY occurred_at DESC, id DESC LIMIT ?""",
            (int(task_id), int(limit)),
        ).fetchall()
        return [dict(row) for row in rows]

    def patient_summary(self, patient_link_id: int) -> dict | None:
        """Return the patient's most recent contact event plus their contact totals.

        Contacts are read by patient rather than by task id. A patient's follow-up list
        merges three id spaces (administrative tasks, clinical care-loop tasks and plan
        commitments), while `task_id` here references `followup_tasks` alone, so filtering
        by a mixed set of ids would attribute one task's contacts to another.
        Returns None when the patient has never been contacted.
        """
        row = self._db().execute(
            """SELECT event.*,
                      (SELECT COUNT(*) FROM followup_contact_events total
                       WHERE total.patient_link_id=event.patient_link_id)
                      AS contact_count,
                      (SELECT COUNT(*) FROM followup_contact_events reached
                       WHERE reached.patient_link_id=event.patient_link_id
                         AND reached.outcome='REACHED') AS reached_count,
                      (SELECT MIN(pending.next_contact_at)
                       FROM followup_contact_events pending
                       WHERE pending.patient_link_id=event.patient_link_id
                         AND pending.next_contact_at IS NOT NULL)
                      AS earliest_next_contact_at
               FROM followup_contact_events event
               WHERE event.patient_link_id=?
               ORDER BY event.occurred_at DESC, event.id DESC
               LIMIT 1""",
            (int(patient_link_id),),
        ).fetchone()
        if not row:
            return None
        return {
            "contact_count": int(row["contact_count"]),
            "reached_count": int(row["reached_count"]),
            "last_contact_id": int(row["id"]),
            "last_contact_task_id": int(row["task_id"]),
            "last_contact_at": row["occurred_at"],
            "last_contact_channel": row["channel"],
            "last_contact_outcome": row["outcome"],
            "last_contact_note": row["note"],
            "last_contact_actor": row["actor_username"],
            "next_contact_at": row["earliest_next_contact_at"],
        }

    def summaries(self, task_ids: list[int]) -> dict[int, dict]:
        ids = [int(value) for value in task_ids if value]
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        rows = self._db().execute(
            f"""WITH ranked AS (
                    SELECT event.*,
                           COUNT(*) OVER (PARTITION BY task_id) AS contact_count,
                           ROW_NUMBER() OVER (
                               PARTITION BY task_id
                               ORDER BY occurred_at DESC,id DESC
                           ) AS recency_rank
                    FROM followup_contact_events event
                    WHERE task_id IN ({marks})
                )
                SELECT * FROM ranked WHERE recency_rank=1""",
            ids,
        ).fetchall()
        result: dict[int, dict] = {}
        for row in rows:
            task_id = int(row["task_id"])
            result[task_id] = {
                "contact_count": int(row["contact_count"]),
                "last_contact_id": int(row["id"]),
                "last_contact_at": row["occurred_at"],
                "last_contact_channel": row["channel"],
                "last_contact_outcome": row["outcome"],
                "last_contact_note": row["note"],
                "next_contact_at": row["next_contact_at"],
            }
        return result

    def due_callbacks(
        self,
        as_of: datetime | str | None = None,
        *,
        task_ids: list[int] | None = None,
    ) -> list[dict]:
        current = _text(as_of)
        ids = sorted({int(value) for value in (task_ids or []) if value})
        if task_ids is not None and not ids:
            return []
        task_filter = ""
        params: list[object] = [current]
        if ids:
            marks = ",".join("?" for _ in ids)
            task_filter = f" AND event.task_id IN ({marks})"
            params.extend(ids)
        rows = self._db().execute(
            f"""SELECT event.*, task.reason, task.detail,
                      patient.full_name AS patient_name,
                      patient.phone_number
               FROM followup_contact_events event
               JOIN followup_tasks task ON task.id=event.task_id
               JOIN patient_links patient ON patient.id=event.patient_link_id
               WHERE event.next_contact_at IS NOT NULL
                 AND datetime(event.next_contact_at)<=datetime(?)
                 {task_filter}
                 AND event.id=(
                     SELECT latest.id FROM followup_contact_events latest
                     WHERE latest.task_id=event.task_id
                     ORDER BY latest.occurred_at DESC, latest.id DESC LIMIT 1
                 )
               ORDER BY event.next_contact_at, event.id""",
            params,
        ).fetchall()
        return [dict(row) for row in rows]
