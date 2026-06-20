"""Repository for the physician visit-queue state (`doctor_visit_log`).

phase3_doctor_queue_plan.md. The live queue itself is a read-only read of OPEN
accounting invoices (via accounting_bridge); this table only holds the specialist-side
«در نوبت / انجام‌شده» state the physician sets — it NEVER closes the accounting invoice
(that stays reception's job). All SQL for this aggregate lives here. Idempotent via
UNIQUE accounting_invoice_id.
"""
from src.adapters.sqlite.core import get_db

_NOW = "datetime('now','+3 hours','+30 minutes')"


class DoctorQueueRepository:

    def log_map(self, work_date: str) -> dict:
        """{accounting_invoice_id: row} for one work_date — merged with the live queue."""
        db = get_db()
        rows = db.execute(
            "SELECT * FROM doctor_visit_log WHERE work_date=?", (work_date,)).fetchall()
        return {r["accounting_invoice_id"]: dict(r) for r in rows}

    def start(self, *, accounting_invoice_id, patient_link_id, national_id, full_name, work_date):
        """Mark a queued patient as in_progress (idempotent; never downgrades a done row)."""
        db = get_db()
        db.execute(
            f"""INSERT OR IGNORE INTO doctor_visit_log
                  (accounting_invoice_id, patient_link_id, national_id, full_name, work_date,
                   status, started_at)
                VALUES (?, ?, ?, ?, ?, 'in_progress', {_NOW})""",
            (accounting_invoice_id, patient_link_id, national_id, full_name, work_date))
        db.execute(
            f"""UPDATE doctor_visit_log
                SET status='in_progress', started_at=COALESCE(started_at, {_NOW})
                WHERE accounting_invoice_id=? AND status!='done'""",
            (accounting_invoice_id,))
        db.commit()

    def mark_done(self, *, accounting_invoice_id, patient_link_id, national_id, full_name,
                  work_date, done_by, notes=None):
        """End-of-visit: physician-side state only — does NOT close the accounting invoice."""
        db = get_db()
        db.execute(
            """INSERT OR IGNORE INTO doctor_visit_log
                  (accounting_invoice_id, patient_link_id, national_id, full_name, work_date, status)
                VALUES (?, ?, ?, ?, ?, 'done')""",
            (accounting_invoice_id, patient_link_id, national_id, full_name, work_date))
        db.execute(
            f"""UPDATE doctor_visit_log
                SET status='done', done_at={_NOW}, done_by=?,
                    physician_notes=COALESCE(?, physician_notes)
                WHERE accounting_invoice_id=?""",
            (done_by, notes, accounting_invoice_id))
        db.commit()
