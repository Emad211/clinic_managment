"""Repository for physician queue state; accounting remains strictly read-only."""
from __future__ import annotations

import sqlite3

from src.adapters.sqlite.core import get_db

_NOW = "datetime('now','+3 hours','+30 minutes')"


class DoctorQueueRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    def log_map(self, work_date: str) -> dict:
        rows = self._db().execute(
            "SELECT * FROM doctor_visit_log WHERE work_date=?", (work_date,)
        ).fetchall()
        return {int(row["accounting_invoice_id"]): dict(row) for row in rows}

    def start(
        self,
        *,
        accounting_invoice_id,
        patient_link_id,
        national_id,
        full_name,
        work_date,
        commit: bool = True,
    ) -> None:
        db = self._db()
        db.execute(
            f"""INSERT OR IGNORE INTO doctor_visit_log
                  (accounting_invoice_id, patient_link_id, national_id, full_name,
                   work_date, status, started_at)
                VALUES (?, ?, ?, ?, ?, 'in_progress', {_NOW})""",
            (
                int(accounting_invoice_id),
                patient_link_id,
                national_id,
                full_name,
                work_date,
            ),
        )
        db.execute(
            f"""UPDATE doctor_visit_log
                SET status='in_progress', started_at=COALESCE(started_at, {_NOW})
                WHERE accounting_invoice_id=? AND status!='done'""",
            (int(accounting_invoice_id),),
        )
        if commit:
            db.commit()

    def mark_done(
        self,
        *,
        accounting_invoice_id,
        patient_link_id,
        national_id,
        full_name,
        work_date,
        done_by,
        notes=None,
        commit: bool = True,
    ) -> None:
        db = self._db()
        db.execute(
            """INSERT OR IGNORE INTO doctor_visit_log
                  (accounting_invoice_id, patient_link_id, national_id, full_name,
                   work_date, status)
                VALUES (?, ?, ?, ?, ?, 'done')""",
            (
                int(accounting_invoice_id),
                patient_link_id,
                national_id,
                full_name,
                work_date,
            ),
        )
        db.execute(
            f"""UPDATE doctor_visit_log
                SET status='done', done_at={_NOW}, done_by=?,
                    physician_notes=COALESCE(?, physician_notes)
                WHERE accounting_invoice_id=?""",
            (str(done_by), notes, int(accounting_invoice_id)),
        )
        if commit:
            db.commit()
