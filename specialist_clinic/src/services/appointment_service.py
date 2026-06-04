"""Appointment logic, including recurring (periodic) appointments."""
from datetime import datetime
from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.common.utils import add_months


class AppointmentService:
    def __init__(self, repo: AppointmentRepository | None = None):
        self.repo = repo or AppointmentRepository()

    def schedule(self, pid: int, *, scheduled_at: str, appt_type: str, notes: str = None,
                 recurrence_months: int = None, created_by: str = None) -> int:
        return self.repo.create(
            pid, scheduled_at=scheduled_at, appt_type=appt_type, notes=notes,
            recurrence_months=recurrence_months or None, created_by=created_by,
        )

    def mark_done(self, appt_id: int, created_by: str = None):
        """Mark an appointment done; if recurring, auto-create the next one."""
        appt = self.repo.get(appt_id)
        if not appt:
            return
        self.repo.set_status(appt_id, 'done')
        rec = appt.get('recurrence_months')
        if rec:
            try:
                base = datetime.strptime(appt['scheduled_at'][:19], '%Y-%m-%d %H:%M:%S')
            except Exception:
                base = datetime.strptime(appt['scheduled_at'][:10], '%Y-%m-%d')
            nxt = add_months(base, int(rec))
            self.repo.create(
                appt['patient_link_id'],
                scheduled_at=nxt.strftime('%Y-%m-%d %H:%M:%S'),
                appt_type=appt.get('appt_type'),
                notes=appt.get('notes'),
                recurrence_months=rec,
                parent_appointment_id=appt_id,
                created_by=created_by,
            )

    def set_status(self, appt_id: int, status: str):
        self.repo.set_status(appt_id, status)
