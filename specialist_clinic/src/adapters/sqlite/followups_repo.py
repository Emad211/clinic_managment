"""Repository for administrative tasks plus read-only clinical-task projections.

Administrative tasks keep their compact mutable workflow. Clinical Engine v2 tasks are
never resolved or scheduled by updating ``followup_tasks``; their state is projected from
append-only ``clinical_task_events`` through ``ClinicalCareLoopRepository``.
"""
from __future__ import annotations

import sqlite3

from src.adapters.sqlite.clinical_care_loop_schema import (
    ensure_clinical_care_loop_storage,
)
from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now


class FollowupRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

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
        """Create a non-engine administrative worklist task."""
        if source_event == "clinical_due":
            raise ValueError(
                "Clinical Engine tasks must use ClinicalFollowupRepository"
            )
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

    @staticmethod
    def _assert_administrative(db, task_ids: list[int]) -> None:
        if not task_ids:
            return
        placeholders = ",".join("?" for _ in task_ids)
        row = db.execute(
            f"""SELECT id FROM followup_tasks
                WHERE id IN ({placeholders})
                  AND source_engine IN ('clinical_v2','encounter_plan') LIMIT 1""",
            task_ids,
        ).fetchone()
        if row:
            raise ValueError(
                "governed follow-up tasks require append-only lifecycle transitions"
            )

    def set_appointment(self, task_id: int, appointment_id):
        db = get_db()
        self._assert_administrative(db, [int(task_id)])
        db.execute(
            "UPDATE followup_tasks SET appointment_id=? WHERE id=?",
            (appointment_id, task_id),
        )
        db.commit()

    def assign_appointment_bulk(
        self,
        task_ids: list,
        appointment_id,
        *,
        commit: bool = True,
    ):
        if not task_ids:
            return
        normalized = [int(value) for value in task_ids]
        db = self._db()
        self._assert_administrative(db, normalized)
        placeholders = ",".join("?" for _ in normalized)
        db.execute(
            "UPDATE followup_tasks SET appointment_id=? "
            f"WHERE id IN ({placeholders})",
            [appointment_id, *normalized],
        )
        if commit:
            db.commit()

    def exists_open(self, patient_link_id: int, reason: str) -> bool:
        if get_db().execute(
            """SELECT 1 FROM followup_tasks
               WHERE patient_link_id=? AND reason=? AND status='open'
                 AND COALESCE(source_engine,'') NOT IN ('clinical_v2','encounter_plan')
               LIMIT 1""",
            (patient_link_id, reason),
        ).fetchone():
            return True
        from src.adapters.sqlite.clinical_care_loop_repo import (
            ClinicalCareLoopRepository,
        )

        if ClinicalCareLoopRepository().list_current(
            patient_link_id=patient_link_id,
            reason=reason,
            include_terminal=False,
        ):
            return True
        if reason != "encounter_plan":
            return False
        from src.adapters.sqlite.encounter_plan_commitment_repo import (
            EncounterPlanCommitmentRepository,
        )
        return bool(
            EncounterPlanCommitmentRepository().list_current(
                patient_link_id=patient_link_id,
                include_terminal=False,
            )
        )

    @staticmethod
    def _admin_open(reason: str | None = None, query: str | None = None) -> list[dict]:
        sql = """SELECT f.*, p.full_name AS patient_name,
                        p.phone_number, p.national_id,
                        f.status AS current_status,
                        f.assigned_to AS current_assigned_to,
                        f.appointment_id AS current_appointment_id,
                        f.due_date AS current_due_at,
                        NULL AS current_event_id,
                        NULL AS latest_outcome_event_id
                 FROM followup_tasks f
                 JOIN patient_links p ON p.id=f.patient_link_id
                 WHERE f.status='open'
                   AND COALESCE(f.source_engine,'') NOT IN ('clinical_v2','encounter_plan')"""
        params: list = []
        if reason:
            sql += " AND f.reason=?"
            params.append(reason)
        if query:
            like = f"%{query.strip()}%"
            sql += " AND (p.national_id LIKE ? OR p.full_name LIKE ? OR p.phone_number LIKE ?)"
            params.extend((like, like, like))
        return [
            dict(row)
            for row in get_db().execute(sql, params).fetchall()
        ]

    @staticmethod
    def _sort_open(rows: list[dict]) -> list[dict]:
        return sorted(
            rows,
            key=lambda row: (
                (row.get("current_due_at") or row.get("due_date")) is None,
                row.get("current_due_at") or row.get("due_date") or "9999-12-31",
                -int(row["id"]),
            ),
        )

    def list_open(self, reason: str | None = None) -> list[dict]:
        from src.adapters.sqlite.clinical_care_loop_repo import (
            ClinicalCareLoopRepository,
        )

        ensure_clinical_care_loop_storage(get_db())
        rows = self._admin_open(reason=reason)
        rows.extend(
            ClinicalCareLoopRepository().list_current(
                reason=reason,
                include_terminal=False,
            )
        )
        from src.adapters.sqlite.encounter_plan_commitment_repo import (
            EncounterPlanCommitmentRepository,
        )
        plan_rows = EncounterPlanCommitmentRepository().list_current(
            include_terminal=False
        )
        if reason:
            plan_rows = [row for row in plan_rows if row.get("reason") == reason]
        rows.extend(plan_rows)
        return self._sort_open(rows)

    def search_open(self, query: str) -> list[dict]:
        from src.adapters.sqlite.clinical_care_loop_repo import (
            ClinicalCareLoopRepository,
        )

        ensure_clinical_care_loop_storage(get_db())
        rows = self._admin_open(query=query)
        rows.extend(
            ClinicalCareLoopRepository().list_current(
                query=query,
                include_terminal=False,
            )
        )
        from src.adapters.sqlite.encounter_plan_commitment_repo import (
            EncounterPlanCommitmentRepository,
        )
        rows.extend(
            EncounterPlanCommitmentRepository().list_current(
                query=query,
                include_terminal=False,
            )
        )
        return self._sort_open(rows)

    def list_for_patient(self, patient_link_id: int) -> list[dict]:
        from src.adapters.sqlite.clinical_care_loop_repo import (
            ClinicalCareLoopRepository,
        )

        db = get_db()
        ensure_clinical_care_loop_storage(db)
        admin = [
            dict(row)
            for row in db.execute(
                """SELECT *, status AS current_status,
                          NULL AS current_event_id
                   FROM followup_tasks
                   WHERE patient_link_id=?
                     AND COALESCE(source_engine,'') NOT IN ('clinical_v2','encounter_plan')
                   ORDER BY id DESC""",
                (patient_link_id,),
            ).fetchall()
        ]
        clinical = ClinicalCareLoopRepository().list_current(
            patient_link_id=patient_link_id,
            include_terminal=True,
        )
        from src.adapters.sqlite.encounter_plan_commitment_repo import (
            EncounterPlanCommitmentRepository,
        )
        plan = EncounterPlanCommitmentRepository().list_current(
            patient_link_id=patient_link_id,
            include_terminal=True,
        )
        for row in plan:
            row["status"] = (
                "open" if row["current_status"] in {"OPEN","IN_PROGRESS","SCHEDULED"}
                else "done" if row["current_status"] == "COMPLETED"
                else "dismissed"
            )
        for row in clinical:
            row["status"] = (
                "open"
                if row["current_status"]
                in {"OPEN", "ASSIGNED", "SCHEDULED", "IN_PROGRESS", "DEFERRED"}
                else "done"
                if row["current_status"] == "COMPLETED"
                else "dismissed"
            )
        return sorted([*admin, *clinical, *plan], key=lambda row: -int(row["id"]))

    def resolve(
        self,
        task_id: int,
        status: str,
        call_log: str | None = None,
    ):
        db = get_db()
        self._assert_administrative(db, [int(task_id)])
        cursor = db.execute(
            """UPDATE followup_tasks
               SET status=?, call_log=COALESCE(?, call_log),
                   resolved_at=?
               WHERE id=? AND COALESCE(source_engine,'') NOT IN ('clinical_v2','encounter_plan')""",
            (
                status,
                call_log,
                iran_now().strftime("%Y-%m-%d %H:%M:%S"),
                task_id,
            ),
        )
        if cursor.rowcount != 1:
            db.rollback()
            raise LookupError("administrative follow-up task not found")
        db.commit()

    def counts_by_reason(self) -> dict:
        counts = {
            row["reason"]: int(row["count"])
            for row in get_db().execute(
                """SELECT reason, COUNT(*) AS count
                   FROM followup_tasks
                   WHERE status='open'
                     AND COALESCE(source_engine,'') NOT IN ('clinical_v2','encounter_plan')
                   GROUP BY reason"""
            ).fetchall()
        }
        from src.adapters.sqlite.clinical_care_loop_repo import (
            ClinicalCareLoopRepository,
        )

        for row in ClinicalCareLoopRepository().list_current(
            include_terminal=False
        ):
            reason = row.get("reason")
            counts[reason] = counts.get(reason, 0) + 1
        from src.adapters.sqlite.encounter_plan_commitment_repo import (
            EncounterPlanCommitmentRepository,
        )
        for row in EncounterPlanCommitmentRepository().list_current(
            include_terminal=False
        ):
            reason = row.get("reason")
            counts[reason] = counts.get(reason, 0) + 1
        return counts
