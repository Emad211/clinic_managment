"""Repository for appointments."""
from src.adapters.sqlite.core import get_db


class AppointmentRepository:

    def create(self, pid: int, *, scheduled_at, appt_type, notes=None,
               recurrence_months=None, parent_appointment_id=None, created_by=None) -> int:
        db = get_db()
        cur = db.execute(
            """INSERT INTO appointments
               (patient_link_id, scheduled_at, appt_type, notes, recurrence_months, parent_appointment_id, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (pid, scheduled_at, appt_type, notes, recurrence_months, parent_appointment_id, created_by),
        )
        db.commit()
        return cur.lastrowid

    def get(self, appt_id: int) -> dict | None:
        db = get_db()
        row = db.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
        return dict(row) if row else None

    def list_range(self, date_from: str, date_to: str, status: str = None) -> list[dict]:
        """date_from/date_to are gregorian 'YYYY-MM-DD'. Returns appts with patient name."""
        db = get_db()
        params = [f"{date_from} 00:00:00", f"{date_to} 23:59:59"]
        sql = """SELECT a.*, p.full_name AS patient_name, p.phone_number
                 FROM appointments a JOIN patient_links p ON p.id = a.patient_link_id
                 WHERE a.scheduled_at BETWEEN ? AND ?"""
        if status:
            sql += " AND a.status = ?"
            params.append(status)
        sql += " ORDER BY a.scheduled_at ASC"
        return [dict(r) for r in db.execute(sql, params).fetchall()]

    def list_for_patient(self, pid: int) -> list[dict]:
        db = get_db()
        return [dict(r) for r in db.execute(
            "SELECT * FROM appointments WHERE patient_link_id=? ORDER BY scheduled_at DESC", (pid,)).fetchall()]

    def upcoming(self, limit: int = 50) -> list[dict]:
        db = get_db()
        return [dict(r) for r in db.execute(
            """SELECT a.*, p.full_name AS patient_name, p.phone_number
               FROM appointments a JOIN patient_links p ON p.id=a.patient_link_id
               WHERE a.status='scheduled' AND a.scheduled_at >= datetime('now','+3 hours','+30 minutes')
               ORDER BY a.scheduled_at ASC LIMIT ?""", (limit,)).fetchall()]

    def set_status(self, appt_id: int, status: str):
        db = get_db()
        db.execute("UPDATE appointments SET status=? WHERE id=?", (status, appt_id))
        db.commit()

    def due_reminders(self, within_hours: int = 24) -> list[dict]:
        """Scheduled appts within the next N hours that haven't had a reminder sent."""
        db = get_db()
        return [dict(r) for r in db.execute(
            """SELECT a.*, p.full_name AS patient_name, p.phone_number
               FROM appointments a JOIN patient_links p ON p.id=a.patient_link_id
               WHERE a.status='scheduled' AND a.reminder_sent=0
                 AND a.scheduled_at >= datetime('now','+3 hours','+30 minutes')
                 AND a.scheduled_at <= datetime('now','+3 hours','+30 minutes', ?)""",
            (f'+{within_hours} hours',)).fetchall()]

    def mark_reminder_sent(self, appt_id: int):
        db = get_db()
        db.execute("UPDATE appointments SET reminder_sent=1 WHERE id=?", (appt_id,))
        db.commit()
