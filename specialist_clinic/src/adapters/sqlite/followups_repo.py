"""Generic repository for administrative and manually managed follow-up tasks.

Clinical Engine v2 task creation lives exclusively in ``clinical_followup_repo`` so the
ordinary worklist repository cannot bypass engine, revision, ruleset or seal checks.
"""
from __future__ import annotations

from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now


class FollowupRepository:
    def active_patient_ids(self) -> list[int]:
        return [
            int(row["id"])
            for row in get_db().execute(
                "SELECT id FROM patient_links "
                "WHERE is_active=1 ORDER BY id"
            ).fetchall()
        ]

    def create(
        self,
        patient_link_id: int,
        *,
        reason,
        detail=None,
        due_date=None,
        assigned_to=None,
        source_rule=None,
        source_event=None,
        appointment_id=None,
        fulfillment=None,
    ) -> int:
        """Create a non-engine worklist task.

        Refill tasks default to remote fulfillment; other administrative tasks
        default to in-person closure. Clinical v2 callers must use
        ``ClinicalFollowupRepository.create_clinical_task_once`` instead.
        """
        if fulfillment is None:
            fulfillment = (
                "remote" if reason == "refill" else "in_person"
            )
        db = get_db()
        cursor = db.execute(
            """INSERT INTO followup_tasks
               (patient_link_id, reason, detail, due_date, assigned_to,
                source_rule, source_event, appointment_id, fulfillment)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                patient_link_id,
                reason,
                detail,
                due_date,
                assigned_to,
                source_rule,
                source_event,
                appointment_id,
                fulfillment,
            ),
        )
        db.commit()
        return int(cursor.lastrowid)

    def set_appointment(self, task_id: int, appointment_id):
        db = get_db()
        db.execute(
            "UPDATE followup_tasks SET appointment_id=? WHERE id=?",
            (appointment_id, task_id),
        )
        db.commit()

    def assign_appointment_bulk(
        self,
        task_ids: list,
        appointment_id,
    ):
        if not task_ids:
            return
        db = get_db()
        placeholders = ",".join("?" for _ in task_ids)
        db.execute(
            "UPDATE followup_tasks SET appointment_id=? "
            f"WHERE id IN ({placeholders})",
            [appointment_id, *task_ids],
        )
        db.commit()

    def exists_open(self, patient_link_id: int, reason: str) -> bool:
        row = get_db().execute(
            """SELECT 1 FROM followup_tasks
               WHERE patient_link_id=? AND reason=? AND status='open'
               LIMIT 1""",
            (patient_link_id, reason),
        ).fetchone()
        return bool(row)

    def list_open(self, reason: str | None = None) -> list[dict]:
        sql = """SELECT f.*, p.full_name AS patient_name,
                        p.phone_number
                 FROM followup_tasks f
                 JOIN patient_links p ON p.id=f.patient_link_id
                 WHERE f.status='open'"""
        params: list = []
        if reason:
            sql += " AND f.reason=?"
            params.append(reason)
        sql += " ORDER BY f.due_date IS NULL, f.due_date ASC, f.id DESC"
        return [
            dict(row)
            for row in get_db().execute(sql, params).fetchall()
        ]

    def search_open(self, query: str) -> list[dict]:
        like = f"%{(query or '').strip()}%"
        sql = """SELECT f.*, p.full_name AS patient_name,
                        p.phone_number, p.national_id
                 FROM followup_tasks f
                 JOIN patient_links p ON p.id=f.patient_link_id
                 WHERE f.status='open'
                   AND (
                       p.national_id LIKE ?
                       OR p.full_name LIKE ?
                       OR p.phone_number LIKE ?
                   )
                 ORDER BY f.due_date IS NULL, f.due_date ASC, f.id DESC"""
        return [
            dict(row)
            for row in get_db().execute(
                sql,
                (like, like, like),
            ).fetchall()
        ]

    def list_for_patient(self, patient_link_id: int) -> list[dict]:
        return [
            dict(row)
            for row in get_db().execute(
                """SELECT * FROM followup_tasks
                   WHERE patient_link_id=? ORDER BY id DESC""",
                (patient_link_id,),
            ).fetchall()
        ]

    def resolve(
        self,
        task_id: int,
        status: str,
        call_log: str | None = None,
    ):
        db = get_db()
        db.execute(
            """UPDATE followup_tasks
               SET status=?, call_log=COALESCE(?, call_log),
                   resolved_at=?
               WHERE id=?""",
            (
                status,
                call_log,
                iran_now().strftime("%Y-%m-%d %H:%M:%S"),
                task_id,
            ),
        )
        db.commit()

    def counts_by_reason(self) -> dict:
        rows = get_db().execute(
            """SELECT reason, COUNT(*) AS count
               FROM followup_tasks
               WHERE status='open' GROUP BY reason"""
        ).fetchall()
        return {
            row["reason"]: row["count"] for row in rows
        }
