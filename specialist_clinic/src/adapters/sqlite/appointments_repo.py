"""Repository for appointments with optional caller-owned transactions."""
from __future__ import annotations

import sqlite3

from src.adapters.sqlite.core import get_db


class AppointmentRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    def create(
        self,
        pid: int,
        *,
        scheduled_at,
        appt_type,
        notes=None,
        recurrence_months=None,
        parent_appointment_id=None,
        created_by=None,
        commit: bool = True,
    ) -> int:
        db = self._db()
        cursor = db.execute(
            """INSERT INTO appointments
               (patient_link_id, scheduled_at, appt_type, notes,
                recurrence_months, parent_appointment_id, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                int(pid),
                scheduled_at,
                appt_type,
                notes,
                recurrence_months,
                parent_appointment_id,
                created_by,
            ),
        )
        if commit:
            db.commit()
        return int(cursor.lastrowid)

    def get(self, appt_id: int) -> dict | None:
        row = self._db().execute(
            "SELECT * FROM appointments WHERE id=?", (int(appt_id),)
        ).fetchone()
        return dict(row) if row else None

    def list_range(
        self, date_from: str, date_to: str, status: str | None = None
    ) -> list[dict]:
        params = [f"{date_from} 00:00:00", f"{date_to} 23:59:59"]
        sql = """SELECT a.*, p.full_name AS patient_name, p.phone_number
                 FROM appointments a JOIN patient_links p ON p.id=a.patient_link_id
                 WHERE a.scheduled_at BETWEEN ? AND ?"""
        if status:
            sql += " AND a.status=?"
            params.append(status)
        sql += " ORDER BY a.scheduled_at ASC"
        return [dict(row) for row in self._db().execute(sql, params).fetchall()]

    def list_for_patient(self, pid: int) -> list[dict]:
        return [
            dict(row)
            for row in self._db().execute(
                """SELECT * FROM appointments
                   WHERE patient_link_id=? ORDER BY scheduled_at DESC""",
                (int(pid),),
            ).fetchall()
        ]

    def scheduled_for_patient_date(self, pid: int, work_date: str) -> list[dict]:
        """Explicit candidates only; no fuzzy time or identity matching."""
        rows = self._db().execute(
            """SELECT appointment.*
               FROM appointments appointment
               WHERE appointment.patient_link_id=?
                 AND appointment.status='scheduled'
                 AND date(appointment.scheduled_at)=date(?)
                 AND NOT EXISTS (
                     SELECT 1 FROM encounter_appointment_links link
                     JOIN encounter_appointment_link_events event
                       ON event.link_id=link.link_id
                     WHERE link.appointment_id=appointment.id
                       AND event.id=(
                           SELECT head.id
                           FROM encounter_appointment_link_events head
                           WHERE head.link_id=link.link_id
                           ORDER BY head.recorded_at DESC, head.id DESC LIMIT 1
                       )
                       AND event.status='LINKED'
                 )
               ORDER BY appointment.scheduled_at, appointment.id""",
            (int(pid), str(work_date)),
        ).fetchall()
        return [dict(row) for row in rows]

    def upcoming(self, limit: int = 50) -> list[dict]:
        return [
            dict(row)
            for row in self._db().execute(
                """SELECT a.*, p.full_name AS patient_name, p.phone_number
                   FROM appointments a JOIN patient_links p ON p.id=a.patient_link_id
                   WHERE a.status='scheduled'
                     AND a.scheduled_at >= datetime('now','+3 hours','+30 minutes')
                   ORDER BY a.scheduled_at ASC LIMIT ?""",
                (int(limit),),
            ).fetchall()
        ]

    # --- Operational aggregates -------------------------------------------
    # `appointments` carries no price column, so nothing here can be turned into
    # money. These aggregates deliberately return counts only; booking volume is
    # not revenue and must never be presented as such.

    def outcome_counts(self, date_from: str, date_to: str) -> dict:
        """Appointment outcomes in a closed window, grouped by stored status."""
        rows = self._db().execute(
            """SELECT status, COUNT(*) AS count FROM appointments
               WHERE scheduled_at BETWEEN ? AND ?
               GROUP BY status""",
            (f"{date_from} 00:00:00", f"{date_to} 23:59:59"),
        ).fetchall()
        counts = {"scheduled": 0, "done": 0, "no_show": 0, "cancelled": 0}
        other = 0
        for row in rows:
            key = str(row["status"] or "")
            if key in counts:
                counts[key] = int(row["count"] or 0)
            else:
                other += int(row["count"] or 0)
        counts["other"] = other
        counts["total"] = sum(counts.values())
        return counts

    def scheduled_ahead_count(self, date_to: str) -> int:
        """Still-scheduled future appointments up to and including a date."""
        row = self._db().execute(
            """SELECT COUNT(*) AS count FROM appointments
               WHERE status='scheduled'
                 AND scheduled_at >= datetime('now','+3 hours','+30 minutes')
                 AND scheduled_at <= ?""",
            (f"{date_to} 23:59:59",),
        ).fetchone()
        return int(row["count"] or 0)

    def lost_opportunities(
        self, date_from: str, date_to: str, *, limit: int = 20
    ) -> list[dict]:
        """Cancelled / no-show appointments in a window, newest first.

        This is the drill-down behind the lost-opportunity counts: every number a
        manager sees must lead back to the patient who produced it.
        """
        rows = self._db().execute(
            """SELECT a.id, a.patient_link_id, a.scheduled_at, a.status,
                      a.appt_type, p.full_name AS patient_name, p.phone_number
               FROM appointments a JOIN patient_links p ON p.id=a.patient_link_id
               WHERE a.scheduled_at BETWEEN ? AND ?
                 AND a.status IN ('no_show','cancelled')
               ORDER BY a.scheduled_at DESC, a.id DESC LIMIT ?""",
            (f"{date_from} 00:00:00", f"{date_to} 23:59:59", int(limit)),
        ).fetchall()
        return [dict(row) for row in rows]

    def set_status(self, appt_id: int, status: str, *, commit: bool = True):
        db = self._db()
        db.execute(
            "UPDATE appointments SET status=? WHERE id=?",
            (status, int(appt_id)),
        )
        if commit:
            db.commit()

    def due_reminders(self, within_hours: int = 24) -> list[dict]:
        return [
            dict(row)
            for row in self._db().execute(
                """SELECT a.*, p.full_name AS patient_name, p.phone_number
                   FROM appointments a JOIN patient_links p ON p.id=a.patient_link_id
                   WHERE a.status='scheduled' AND a.reminder_sent=0
                     AND a.scheduled_at >= datetime('now','+3 hours','+30 minutes')
                     AND a.scheduled_at <= datetime(
                         'now','+3 hours','+30 minutes', ?
                     )""",
                (f"+{int(within_hours)} hours",),
            ).fetchall()
        ]

    def mark_reminder_sent(self, appt_id: int, *, commit: bool = True):
        db = self._db()
        db.execute(
            "UPDATE appointments SET reminder_sent=1 WHERE id=?", (int(appt_id),)
        )
        if commit:
            db.commit()
