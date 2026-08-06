"""Repository for current lead state and append-only lifecycle events."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.lead_pipeline_schema import ensure_lead_pipeline_storage
from src.common.utils import iran_now


_OPEN_STATUSES = {"NEW", "CONTACTED", "APPOINTMENT_BOOKED", "ATTENDED"}


def _now_text() -> str:
    current = iran_now()
    if current.tzinfo is not None:
        current = current.replace(tzinfo=None)
    return current.isoformat(sep=" ", timespec="seconds")


def _normalize_phone(value: object) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if digits.startswith("98") and len(digits) == 12:
        digits = "0" + digits[2:]
    return digits


class LeadRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db
        ensure_lead_pipeline_storage(self._db())

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    @staticmethod
    def normalize_phone(value: object) -> str:
        return _normalize_phone(value)

    def get(self, lead_id: int) -> dict | None:
        row = self._db().execute(
            """SELECT lead.*,referrer.full_name AS referrer_patient_name
               FROM growth_leads lead
               LEFT JOIN patient_links referrer
                 ON referrer.id=lead.referrer_patient_link_id
               WHERE lead.id=?""",
            (int(lead_id),),
        ).fetchone()
        return dict(row) if row else None

    def active_by_phone(self, phone_number: str) -> dict | None:
        phone = _normalize_phone(phone_number)
        if not phone:
            return None
        row = self._db().execute(
            """SELECT lead.*,referrer.full_name AS referrer_patient_name
               FROM growth_leads lead
               LEFT JOIN patient_links referrer
                 ON referrer.id=lead.referrer_patient_link_id
               WHERE lead.phone_number=? AND lead.status IN (
                   'NEW','CONTACTED','APPOINTMENT_BOOKED','ATTENDED'
               )
               ORDER BY lead.id DESC LIMIT 1""",
            (phone,),
        ).fetchone()
        return dict(row) if row else None

    def create(
        self,
        *,
        full_name: str,
        phone_number: str,
        national_id: str | None,
        source_code: str,
        source_detail: str | None,
        referrer_name: str | None,
        referrer_patient_link_id: int | None,
        interest_code: str | None,
        owner_username: str | None,
        next_action_at: str | None,
        notes: str | None,
        actor_username: str,
    ) -> dict:
        db = self._db()
        phone = _normalize_phone(phone_number)
        existing = self.active_by_phone(phone)
        if existing:
            return {**existing, "duplicate": True}
        now = _now_text()
        cursor = db.execute(
            """INSERT INTO growth_leads
               (full_name, phone_number, national_id, source_code,
                source_detail, referrer_name, referrer_patient_link_id,
                interest_code, owner_username, status, next_action_at,
                notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'NEW', ?, ?, ?, ?)""",
            (
                full_name,
                phone,
                national_id,
                source_code,
                source_detail,
                referrer_name,
                referrer_patient_link_id,
                interest_code,
                owner_username,
                next_action_at,
                notes,
                now,
                now,
            ),
        )
        lead_id = int(cursor.lastrowid)
        self.append_event(
            lead_id=lead_id,
            event_type="CREATED",
            from_status=None,
            to_status="NEW",
            actor_username=actor_username,
            note=notes,
            payload={
                "source_code": source_code,
                "owner_username": owner_username,
                "next_action_at": next_action_at,
                "referrer_patient_link_id": referrer_patient_link_id,
            },
            commit=False,
        )
        db.commit()
        return {**self.get(lead_id), "duplicate": False}

    def update_state(
        self,
        lead_id: int,
        *,
        to_status: str,
        owner_username: str | None = None,
        next_action_at: str | None = None,
        appointment_at: str | None = None,
        lost_reason: str | None = None,
        note: str | None = None,
        actor_username: str,
        payload: dict | None = None,
        patient_link_id: int | None = None,
        appointment_id: int | None = None,
        converted_at: str | None = None,
        commit: bool = True,
    ) -> dict:
        db = self._db()
        current = self.get(lead_id)
        if not current:
            raise LookupError("lead not found")
        now = _now_text()
        db.execute(
            """UPDATE growth_leads
               SET status=?,
                   owner_username=COALESCE(?, owner_username),
                   next_action_at=?,
                   appointment_at=COALESCE(?, appointment_at),
                   lost_reason=?,
                   notes=COALESCE(?, notes),
                   patient_link_id=COALESCE(?, patient_link_id),
                   appointment_id=COALESCE(?, appointment_id),
                   converted_at=COALESCE(?, converted_at),
                   updated_at=?
               WHERE id=?""",
            (
                to_status,
                owner_username,
                next_action_at,
                appointment_at,
                lost_reason,
                note,
                patient_link_id,
                appointment_id,
                converted_at,
                now,
                int(lead_id),
            ),
        )
        self.append_event(
            lead_id=int(lead_id),
            event_type="STATUS_CHANGED",
            from_status=current["status"],
            to_status=to_status,
            actor_username=actor_username,
            note=note,
            payload={
                **(payload or {}),
                "next_action_at": next_action_at,
                "appointment_at": appointment_at,
                "lost_reason": lost_reason,
                "patient_link_id": patient_link_id,
                "appointment_id": appointment_id,
            },
            commit=False,
        )
        if commit:
            db.commit()
        return self.get(lead_id)

    def append_event(
        self,
        *,
        lead_id: int,
        event_type: str,
        from_status: str | None,
        to_status: str | None,
        actor_username: str,
        note: str | None = None,
        payload: dict | None = None,
        commit: bool = True,
    ) -> int:
        cursor = self._db().execute(
            """INSERT INTO growth_lead_events
               (lead_id, event_type, from_status, to_status, occurred_at,
                actor_username, note, payload_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                int(lead_id),
                event_type,
                from_status,
                to_status,
                _now_text(),
                actor_username,
                note,
                json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
            ),
        )
        if commit:
            self._db().commit()
        return int(cursor.lastrowid)

    def list_events(self, lead_id: int, limit: int = 100) -> list[dict]:
        return [
            dict(row)
            for row in self._db().execute(
                """SELECT * FROM growth_lead_events
                   WHERE lead_id=? ORDER BY occurred_at DESC,id DESC LIMIT ?""",
                (int(lead_id), int(limit)),
            ).fetchall()
        ]

    def list(
        self,
        *,
        status: str | None = None,
        owner_username: str | None = None,
        query: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        clauses = []
        params: list[Any] = []
        if status:
            clauses.append("lead.status=?")
            params.append(status)
        if owner_username:
            clauses.append("lead.owner_username=?")
            params.append(owner_username)
        if query:
            like = f"%{query.strip()}%"
            clauses.append(
                "(lead.full_name LIKE ? OR lead.phone_number LIKE ? OR "
                "COALESCE(lead.national_id,'') LIKE ? OR "
                "COALESCE(lead.referrer_name,'') LIKE ? OR "
                "COALESCE(referrer.full_name,'') LIKE ?)"
            )
            params.extend((like, like, like, like, like))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(int(limit))
        rows = self._db().execute(
            """SELECT lead.*,referrer.full_name AS referrer_patient_name
               FROM growth_leads lead
               LEFT JOIN patient_links referrer
                 ON referrer.id=lead.referrer_patient_link_id"""
            + where
            + " ORDER BY CASE lead.status "
              "WHEN 'NEW' THEN 0 WHEN 'CONTACTED' THEN 1 "
              "WHEN 'APPOINTMENT_BOOKED' THEN 2 WHEN 'ATTENDED' THEN 3 "
              "WHEN 'CONVERTED' THEN 4 ELSE 5 END, "
              "CASE WHEN lead.next_action_at IS NULL THEN 1 ELSE 0 END, "
              "lead.next_action_at,lead.id DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def counts(self) -> dict[str, int]:
        result = {status: 0 for status in (*_OPEN_STATUSES, "CONVERTED", "LOST")}
        rows = self._db().execute(
            "SELECT status,COUNT(*) AS count FROM growth_leads GROUP BY status"
        ).fetchall()
        for row in rows:
            result[str(row["status"])] = int(row["count"] or 0)
        result["OPEN"] = sum(result.get(status, 0) for status in _OPEN_STATUSES)
        return result

    def due(self, as_of: str) -> list[dict]:
        rows = self._db().execute(
            """SELECT lead.*,referrer.full_name AS referrer_patient_name
               FROM growth_leads lead
               LEFT JOIN patient_links referrer
                 ON referrer.id=lead.referrer_patient_link_id
               WHERE lead.status IN (
                   'NEW','CONTACTED','APPOINTMENT_BOOKED','ATTENDED'
               )
                 AND lead.next_action_at IS NOT NULL
                 AND datetime(lead.next_action_at)<=datetime(?)
               ORDER BY lead.next_action_at,lead.id""",
            (str(as_of),),
        ).fetchall()
        return [dict(row) for row in rows]


__all__ = ["LeadRepository"]
