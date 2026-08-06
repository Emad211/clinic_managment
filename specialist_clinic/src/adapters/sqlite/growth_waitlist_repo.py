"""Repository for waitlist entries and consumed cancellation slots."""
from __future__ import annotations

from datetime import datetime
import sqlite3

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.growth_waitlist_schema import (
    ensure_growth_waitlist_storage,
)
from src.common.utils import iran_now


def _now_text() -> str:
    current = iran_now()
    if current.tzinfo is not None:
        current = current.replace(tzinfo=None)
    return current.replace(microsecond=0).isoformat(
        sep=" ", timespec="seconds"
    )


class GrowthWaitlistRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db
        ensure_growth_waitlist_storage(self._db())

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    def get(self, entry_id: int) -> dict | None:
        row = self._db().execute(
            """SELECT entry.*,patient.full_name AS patient_name,
                      patient.phone_number
               FROM growth_waitlist_entries entry
               JOIN patient_links patient ON patient.id=entry.patient_link_id
               WHERE entry.id=?""",
            (int(entry_id),),
        ).fetchone()
        return dict(row) if row else None

    def active_for_patient(self, patient_link_id: int) -> dict | None:
        row = self._db().execute(
            """SELECT * FROM growth_waitlist_entries
               WHERE patient_link_id=? AND status IN ('WAITING','OFFERED')
               ORDER BY id DESC LIMIT 1""",
            (int(patient_link_id),),
        ).fetchone()
        return dict(row) if row else None

    def create(
        self,
        *,
        patient_link_id: int,
        appt_type: str,
        date_from: str | None,
        date_to: str | None,
        time_window: str,
        auto_fill: bool,
        priority: int,
        source_code: str,
        notes: str | None,
        created_by: str,
    ) -> dict:
        existing = self.active_for_patient(patient_link_id)
        if existing:
            return {**existing, "duplicate": True}
        now = _now_text()
        cursor = self._db().execute(
            """INSERT INTO growth_waitlist_entries
               (patient_link_id,appt_type,date_from,date_to,time_window,
                auto_fill,priority,source_code,status,notes,created_at,
                updated_at,created_by)
               VALUES (?,?,?,?,?,?,?,?, 'WAITING',?,?,?,?)""",
            (
                int(patient_link_id),
                appt_type,
                date_from,
                date_to,
                time_window,
                int(bool(auto_fill)),
                int(priority),
                source_code,
                notes,
                now,
                now,
                created_by,
            ),
        )
        self._db().commit()
        return {**self.get(int(cursor.lastrowid)), "duplicate": False}

    def list(self, *, status: str | None = None, limit: int = 500) -> list[dict]:
        params: list[object] = []
        where = ""
        if status:
            where = " WHERE entry.status=?"
            params.append(status)
        params.append(int(limit))
        rows = self._db().execute(
            """SELECT entry.*,patient.full_name AS patient_name,
                      patient.phone_number
               FROM growth_waitlist_entries entry
               JOIN patient_links patient ON patient.id=entry.patient_link_id"""
            + where
            + " ORDER BY CASE entry.status WHEN 'WAITING' THEN 0 "
              "WHEN 'OFFERED' THEN 1 ELSE 2 END,entry.priority,entry.id LIMIT ?",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def matching_for_slot(
        self,
        *,
        slot_at: str,
        appt_type: str,
    ) -> list[dict]:
        parsed = datetime.fromisoformat(str(slot_at))
        hour = parsed.hour
        window = (
            "MORNING" if hour < 12
            else "AFTERNOON" if hour < 17
            else "EVENING"
        )
        rows = self._db().execute(
            """SELECT entry.*,patient.full_name AS patient_name,
                      patient.phone_number
               FROM growth_waitlist_entries entry
               JOIN patient_links patient ON patient.id=entry.patient_link_id
               WHERE entry.status='WAITING'
                 AND entry.appt_type=?
                 AND (entry.date_from IS NULL OR date(entry.date_from)<=date(?))
                 AND (entry.date_to IS NULL OR date(entry.date_to)>=date(?))
                 AND entry.time_window IN ('ANY',?)
                 AND NOT EXISTS (
                   SELECT 1 FROM appointments future
                   WHERE future.patient_link_id=entry.patient_link_id
                     AND future.status='scheduled'
                     AND datetime(future.scheduled_at)>
                         datetime('now','+3 hours','+30 minutes')
                 )
               ORDER BY entry.priority,entry.created_at,entry.id""",
            (appt_type, slot_at, slot_at, window),
        ).fetchall()
        return [dict(row) for row in rows]

    def set_status(
        self,
        entry_id: int,
        *,
        status: str,
        offered_slot_at: str | None = None,
        booked_appointment_id: int | None = None,
        commit: bool = True,
    ) -> dict:
        self._db().execute(
            """UPDATE growth_waitlist_entries
               SET status=?,offered_slot_at=COALESCE(?,offered_slot_at),
                   booked_appointment_id=COALESCE(?,booked_appointment_id),
                   updated_at=?
               WHERE id=?""",
            (
                status,
                offered_slot_at,
                booked_appointment_id,
                _now_text(),
                int(entry_id),
            ),
        )
        if commit:
            self._db().commit()
        return self.get(entry_id)

    def slot_event(self, cancelled_appointment_id: int) -> dict | None:
        row = self._db().execute(
            """SELECT * FROM growth_slot_fill_events
               WHERE cancelled_appointment_id=?""",
            (int(cancelled_appointment_id),),
        ).fetchone()
        return dict(row) if row else None

    def record_slot_fill(
        self,
        *,
        cancelled_appointment_id: int,
        waitlist_entry_id: int,
        replacement_appointment_id: int | None,
        mode: str,
        slot_at: str,
        created_by: str,
        commit: bool = True,
    ) -> dict:
        existing = self.slot_event(cancelled_appointment_id)
        if existing:
            return existing
        cursor = self._db().execute(
            """INSERT INTO growth_slot_fill_events
               (cancelled_appointment_id,waitlist_entry_id,
                replacement_appointment_id,mode,slot_at,created_at,created_by)
               VALUES (?,?,?,?,?,?,?)""",
            (
                int(cancelled_appointment_id),
                int(waitlist_entry_id),
                replacement_appointment_id,
                mode,
                slot_at,
                _now_text(),
                created_by,
            ),
        )
        if commit:
            self._db().commit()
        row = self._db().execute(
            "SELECT * FROM growth_slot_fill_events WHERE id=?",
            (int(cursor.lastrowid),),
        ).fetchone()
        return dict(row)

    def counts(self) -> dict[str, int]:
        counts = {"WAITING": 0, "OFFERED": 0, "BOOKED": 0, "CANCELLED": 0}
        rows = self._db().execute(
            """SELECT status,COUNT(*) AS count
               FROM growth_waitlist_entries GROUP BY status"""
        ).fetchall()
        for row in rows:
            counts[str(row["status"])] = int(row["count"] or 0)
        return counts


__all__ = ["GrowthWaitlistRepository"]
