"""Low-risk growth automations that create authoritative Work Center tasks.

This stage creates operational work only. Patient messaging remains governed by the
existing message pipeline and is handled in the dedicated messaging stage.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import sqlite3

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.common.utils import iran_now


class GrowthAutomationService:
    def __init__(self, db: sqlite3.Connection | None = None):
        self.db = db or get_db()
        self.followups = FollowupRepository(self.db)

    @staticmethod
    def _now() -> datetime:
        current = iran_now()
        if current.tzinfo is not None:
            current = current.replace(tzinfo=None)
        return current.replace(microsecond=0)

    def _task_exists(self, source_rule: str) -> bool:
        return bool(
            self.db.execute(
                """SELECT 1 FROM followup_tasks
                   WHERE source_rule=? AND status='open' LIMIT 1""",
                (source_rule,),
            ).fetchone()
        )

    def _create_once(
        self,
        *,
        patient_link_id: int,
        reason: str,
        detail: str,
        source_rule: str,
        source_event: str,
        appointment_id: int | None = None,
        assigned_to: str | None = None,
    ) -> int | None:
        if self._task_exists(source_rule):
            return None
        return self.followups.create(
            int(patient_link_id),
            reason=reason,
            detail=detail,
            due_date=self._now().isoformat(sep=" ", timespec="seconds"),
            assigned_to=assigned_to,
            source_rule=source_rule,
            source_event=source_event,
            appointment_id=appointment_id,
            fulfillment="remote",
        )

    def recover_no_shows(self, *, assigned_to: str | None = None) -> dict:
        cutoff = self._now().isoformat(sep=" ", timespec="seconds")
        rows = self.db.execute(
            """SELECT appointment.id,appointment.patient_link_id,
                      appointment.scheduled_at,patient.full_name
               FROM appointments appointment
               JOIN patient_links patient ON patient.id=appointment.patient_link_id
               WHERE appointment.status='no_show'
                 AND datetime(appointment.scheduled_at)<=datetime(?)
               ORDER BY appointment.scheduled_at,appointment.id""",
            (cutoff,),
        ).fetchall()
        created = []
        duplicates = 0
        for row in rows:
            source_rule = f"growth:no-show:{int(row['id'])}"
            task_id = self._create_once(
                patient_link_id=int(row["patient_link_id"]),
                reason="no_show_recovery",
                detail=(
                    f"بازیابی عدم حضور {row['full_name']} برای نوبت "
                    f"{row['scheduled_at']}"
                ),
                source_rule=source_rule,
                source_event="appointment_no_show",
                appointment_id=int(row["id"]),
                assigned_to=assigned_to,
            )
            if task_id is None:
                duplicates += 1
            else:
                created.append(task_id)
        return {
            "eligible": len(rows),
            "created": len(created),
            "duplicates": duplicates,
            "task_ids": created,
        }

    def recover_cancellations(self, *, assigned_to: str | None = None) -> dict:
        rows = self.db.execute(
            """SELECT appointment.id,appointment.patient_link_id,
                      appointment.scheduled_at,patient.full_name
               FROM appointments appointment
               JOIN patient_links patient ON patient.id=appointment.patient_link_id
               WHERE appointment.status='cancelled'
               ORDER BY appointment.scheduled_at DESC,appointment.id DESC"""
        ).fetchall()
        created = []
        duplicates = 0
        for row in rows:
            has_future = self.db.execute(
                """SELECT 1 FROM appointments
                   WHERE patient_link_id=? AND status='scheduled'
                     AND datetime(scheduled_at)>datetime('now','+3 hours','+30 minutes')
                   LIMIT 1""",
                (int(row["patient_link_id"]),),
            ).fetchone()
            if has_future:
                continue
            source_rule = f"growth:cancelled:{int(row['id'])}"
            task_id = self._create_once(
                patient_link_id=int(row["patient_link_id"]),
                reason="cancellation_recovery",
                detail=(
                    f"جایگزینی نوبت لغوشده {row['full_name']}؛ نوبت قبلی: "
                    f"{row['scheduled_at']}"
                ),
                source_rule=source_rule,
                source_event="appointment_cancelled",
                appointment_id=int(row["id"]),
                assigned_to=assigned_to,
            )
            if task_id is None:
                duplicates += 1
            else:
                created.append(task_id)
        return {
            "eligible": len(rows),
            "created": len(created),
            "duplicates": duplicates,
            "task_ids": created,
        }

    def recall_inactive_patients(
        self,
        *,
        inactive_days: int = 180,
        assigned_to: str | None = None,
    ) -> dict:
        days = max(int(inactive_days), 30)
        cutoff = (self._now().date() - timedelta(days=days)).isoformat()
        period = self._now().strftime("%Y-%m")
        rows = self.db.execute(
            """SELECT patient.id,patient.full_name,
                      MAX(CASE WHEN appointment.status='done'
                               THEN appointment.scheduled_at END) AS last_done,
                      patient.enrolled_at
               FROM patient_links patient
               LEFT JOIN appointments appointment
                 ON appointment.patient_link_id=patient.id
               WHERE patient.is_active=1
                 AND NOT EXISTS (
                     SELECT 1 FROM appointments future
                     WHERE future.patient_link_id=patient.id
                       AND future.status='scheduled'
                       AND datetime(future.scheduled_at)>
                           datetime('now','+3 hours','+30 minutes')
                 )
               GROUP BY patient.id,patient.full_name,patient.enrolled_at
               HAVING date(COALESCE(
                         MAX(CASE WHEN appointment.status='done'
                                  THEN appointment.scheduled_at END),
                         patient.enrolled_at
                      ))<=date(?)
               ORDER BY COALESCE(last_done,patient.enrolled_at),patient.id""",
            (cutoff,),
        ).fetchall()
        created = []
        duplicates = 0
        for row in rows:
            source_rule = f"growth:inactive:{int(row['id'])}:{period}"
            task_id = self._create_once(
                patient_link_id=int(row["id"]),
                reason="inactive_patient_recall",
                detail=(
                    f"بیمار غیرفعال: {row['full_name']}؛ آخرین مراجعه/ثبت: "
                    f"{row['last_done'] or row['enrolled_at']}"
                ),
                source_rule=source_rule,
                source_event="inactive_patient_recall",
                assigned_to=assigned_to,
            )
            if task_id is None:
                duplicates += 1
            else:
                created.append(task_id)
        return {
            "eligible": len(rows),
            "created": len(created),
            "duplicates": duplicates,
            "task_ids": created,
            "inactive_days": days,
        }

    def preview(self, *, inactive_days: int = 180) -> dict:
        # Preview uses the same source queries but never writes. Counts remain explicit
        # so the UI can show what a run would create.
        days = max(int(inactive_days), 30)
        cutoff = (self._now().date() - timedelta(days=days)).isoformat()
        no_shows = int(
            self.db.execute(
                """SELECT COUNT(*) AS count FROM appointments appointment
                   WHERE appointment.status='no_show'
                     AND NOT EXISTS (
                       SELECT 1 FROM followup_tasks task
                       WHERE task.source_rule=('growth:no-show:'||appointment.id)
                         AND task.status='open'
                     )"""
            ).fetchone()["count"]
            or 0
        )
        cancellations = int(
            self.db.execute(
                """SELECT COUNT(*) AS count FROM appointments appointment
                   WHERE appointment.status='cancelled'
                     AND NOT EXISTS (
                       SELECT 1 FROM appointments future
                       WHERE future.patient_link_id=appointment.patient_link_id
                         AND future.status='scheduled'
                         AND datetime(future.scheduled_at)>
                             datetime('now','+3 hours','+30 minutes')
                     )
                     AND NOT EXISTS (
                       SELECT 1 FROM followup_tasks task
                       WHERE task.source_rule=('growth:cancelled:'||appointment.id)
                         AND task.status='open'
                     )"""
            ).fetchone()["count"]
            or 0
        )
        inactive = int(
            self.db.execute(
                """SELECT COUNT(*) AS count FROM (
                     SELECT patient.id,patient.enrolled_at,
                            MAX(CASE WHEN appointment.status='done'
                                     THEN appointment.scheduled_at END) AS last_done
                     FROM patient_links patient
                     LEFT JOIN appointments appointment
                       ON appointment.patient_link_id=patient.id
                     WHERE patient.is_active=1
                       AND NOT EXISTS (
                         SELECT 1 FROM appointments future
                         WHERE future.patient_link_id=patient.id
                           AND future.status='scheduled'
                           AND datetime(future.scheduled_at)>
                               datetime('now','+3 hours','+30 minutes')
                       )
                     GROUP BY patient.id,patient.enrolled_at
                     HAVING date(COALESCE(last_done,patient.enrolled_at))<=date(?)
                   ) candidates""",
                (cutoff,),
            ).fetchone()["count"]
            or 0
        )
        return {
            "no_show": no_shows,
            "cancelled": cancellations,
            "inactive": inactive,
            "inactive_days": days,
        }

    def run_all(
        self,
        *,
        inactive_days: int = 180,
        assigned_to: str | None = None,
    ) -> dict:
        return {
            "no_show": self.recover_no_shows(assigned_to=assigned_to),
            "cancelled": self.recover_cancellations(assigned_to=assigned_to),
            "inactive": self.recall_inactive_patients(
                inactive_days=inactive_days,
                assigned_to=assigned_to,
            ),
        }


__all__ = ["GrowthAutomationService"]
