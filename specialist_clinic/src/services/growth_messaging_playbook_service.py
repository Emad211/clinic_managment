"""Growth messaging playbooks on top of the existing engagement approval pipeline.

No direct SMS path is introduced. Candidates are queued through EngagementService,
which applies the configured event, consent, cooldown and deduplication rules. Pending
approvals are rejected when the business condition is no longer true.
"""
from __future__ import annotations

from datetime import datetime
import sqlite3

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.engagement_repo import EngagementRepository
from src.adapters.sqlite.growth_message_playbook_schema import (
    ensure_growth_message_events,
)
from src.common.utils import format_jalali_date, iran_now
from src.services.engagement_service import EngagementService


_REASON_EVENT = {
    "no_show_recovery": "growth_no_show_recovery",
    "cancellation_recovery": "growth_cancellation_recovery",
    "inactive_patient_recall": "growth_inactive_recall",
    "waitlist_auto_booked_notification": "growth_waitlist_auto_booked",
    "waitlist_slot_offer": "growth_waitlist_offer",
}


class GrowthMessagingPlaybookService:
    def __init__(self, db: sqlite3.Connection | None = None):
        self.db = db or get_db()
        ensure_growth_message_events(self.db)
        self.repo = EngagementRepository()
        self.engagement = EngagementService()

    @staticmethod
    def _now() -> datetime:
        current = iran_now()
        if current.tzinfo is not None:
            current = current.replace(tzinfo=None)
        return current.replace(microsecond=0)

    @staticmethod
    def _appointment_detail(appointment: dict) -> str:
        scheduled = str(appointment.get("scheduled_at") or "")
        date_label = format_jalali_date(scheduled) if scheduled else ""
        clock = scheduled[11:16] if len(scheduled) >= 16 else ""
        return f"{date_label} ساعت {clock}".strip()

    def _future_appointment(self, patient_link_id: int) -> dict | None:
        row = self.db.execute(
            """SELECT * FROM appointments
               WHERE patient_link_id=? AND status='scheduled'
                 AND datetime(scheduled_at)>
                     datetime('now','+3 hours','+30 minutes')
               ORDER BY scheduled_at,id LIMIT 1""",
            (int(patient_link_id),),
        ).fetchone()
        return dict(row) if row else None

    def _completed_after(
        self,
        patient_link_id: int,
        created_at: str | None,
    ) -> dict | None:
        row = self.db.execute(
            """SELECT * FROM appointments
               WHERE patient_link_id=? AND status='done'
                 AND datetime(scheduled_at)>=
                     datetime(COALESCE(?, '1970-01-01'))
               ORDER BY scheduled_at DESC,id DESC LIMIT 1""",
            (int(patient_link_id), created_at),
        ).fetchone()
        return dict(row) if row else None

    def _waitlist_context(self, source_rule: str) -> dict | None:
        try:
            cancelled_id = int(str(source_rule).rsplit(":", 1)[-1])
        except (TypeError, ValueError):
            return None
        row = self.db.execute(
            """SELECT event.*,entry.status AS entry_status,
                      entry.patient_link_id,entry.id AS entry_id,
                      appointment.status AS cancelled_status
               FROM growth_slot_fill_events event
               JOIN growth_waitlist_entries entry
                 ON entry.id=event.waitlist_entry_id
               JOIN appointments appointment
                 ON appointment.id=event.cancelled_appointment_id
               WHERE event.cancelled_appointment_id=?
               ORDER BY event.id DESC LIMIT 1""",
            (cancelled_id,),
        ).fetchone()
        return dict(row) if row else None

    def _task_candidate(self, task: dict) -> dict:
        reason = str(task.get("reason") or "")
        event_key = _REASON_EVENT.get(reason)
        period_key = str(task.get("source_rule") or f"growth-task:{task['id']}")
        base = {
            "kind": "task",
            "task_id": int(task["id"]),
            "patient_link_id": int(task["patient_link_id"]),
            "event_key": event_key,
            "period_key": period_key,
            "detail": "",
            "eligible": False,
            "stop_reason": None,
        }
        if not event_key:
            return {**base, "stop_reason": "UNSUPPORTED_TASK"}

        if reason in {
            "no_show_recovery",
            "cancellation_recovery",
            "inactive_patient_recall",
        }:
            future = self._future_appointment(int(task["patient_link_id"]))
            if future:
                return {**base, "stop_reason": "BOOKED"}
            completed = self._completed_after(
                int(task["patient_link_id"]),
                task.get("created_at"),
            )
            if completed:
                return {**base, "stop_reason": "ATTENDED"}
            return {
                **base,
                "eligible": True,
                "detail": str(task.get("detail") or "").strip(),
            }

        if reason == "waitlist_auto_booked_notification":
            appointment_id = task.get("appointment_id")
            appointment = (
                self.db.execute(
                    "SELECT * FROM appointments WHERE id=?",
                    (int(appointment_id),),
                ).fetchone()
                if appointment_id
                else None
            )
            if not appointment:
                return {**base, "stop_reason": "APPOINTMENT_MISSING"}
            appointment = dict(appointment)
            if appointment["status"] != "scheduled":
                return {
                    **base,
                    "stop_reason": (
                        "ATTENDED"
                        if appointment["status"] == "done"
                        else "APPOINTMENT_NOT_ACTIVE"
                    ),
                }
            if datetime.fromisoformat(str(appointment["scheduled_at"])) <= self._now():
                return {**base, "stop_reason": "APPOINTMENT_PAST"}
            return {
                **base,
                "eligible": True,
                "detail": self._appointment_detail(appointment),
            }

        if reason == "waitlist_slot_offer":
            context = self._waitlist_context(period_key)
            if not context:
                return {**base, "stop_reason": "WAITLIST_CONTEXT_MISSING"}
            if context["entry_status"] == "BOOKED":
                return {**base, "stop_reason": "BOOKED"}
            if context["entry_status"] == "CANCELLED":
                return {**base, "stop_reason": "WAITLIST_CANCELLED"}
            if context["entry_status"] != "OFFERED":
                return {**base, "stop_reason": "WAITLIST_NOT_OFFERED"}
            if datetime.fromisoformat(str(context["slot_at"])) <= self._now():
                return {**base, "stop_reason": "SLOT_PAST"}
            return {
                **base,
                "eligible": True,
                "detail": self._appointment_detail(
                    {"scheduled_at": context["slot_at"]}
                ),
            }

        return {**base, "stop_reason": "UNSUPPORTED_TASK"}

    def _growth_task_candidates(self) -> list[dict]:
        reasons = tuple(_REASON_EVENT)
        marks = ",".join("?" for _ in reasons)
        rows = self.db.execute(
            f"""SELECT task.* FROM followup_tasks task
                WHERE task.status='open' AND task.reason IN ({marks})
                ORDER BY task.created_at,task.id""",
            reasons,
        ).fetchall()
        return [self._task_candidate(dict(row)) for row in rows]

    def _appointment_reminder_candidates(self) -> list[dict]:
        config = self.repo.get_event("appointment_reminder") or {}
        if not config.get("is_active") or config.get("channel") == "off":
            return []
        lead_days = max(int(config.get("lead_days") or 0), 0)
        rows = self.db.execute(
            """SELECT appointment.*
               FROM appointments appointment
               WHERE appointment.status='scheduled'
                 AND datetime(appointment.scheduled_at)>=
                     datetime('now','+3 hours','+30 minutes')
                 AND datetime(appointment.scheduled_at)<=datetime(
                     'now','+3 hours','+30 minutes', ?
                 )
               ORDER BY appointment.scheduled_at,appointment.id""",
            (f"+{lead_days} days",),
        ).fetchall()
        return [
            {
                "kind": "appointment",
                "appointment_id": int(row["id"]),
                "patient_link_id": int(row["patient_link_id"]),
                "event_key": "appointment_reminder",
                "period_key": f"appt:{int(row['id'])}",
                "detail": self._appointment_detail(dict(row)),
                "eligible": True,
                "stop_reason": None,
            }
            for row in rows
        ]

    def _cancel_pending(
        self,
        *,
        patient_link_id: int,
        event_key: str,
        period_key: str,
        decided_by: str,
    ) -> bool:
        approval = self.repo.find_approval(
            patient_link_id=int(patient_link_id),
            event_key=event_key,
            period_key=period_key,
        )
        if not approval or approval.get("status") != "pending":
            return False
        self.repo.set_status(
            int(approval["id"]),
            "rejected",
            decided_by,
        )
        return True

    def _cancel_stale_appointment_reminders(self, decided_by: str) -> int:
        rows = self.db.execute(
            """SELECT approval.*,appointment.status AS appointment_status,
                      appointment.scheduled_at
               FROM engagement_approvals approval
               LEFT JOIN appointments appointment
                 ON appointment.id=CAST(SUBSTR(approval.period_key,6) AS INTEGER)
               WHERE approval.status='pending'
                 AND approval.event_key='appointment_reminder'
                 AND approval.period_key LIKE 'appt:%'
                 AND (
                   appointment.id IS NULL
                   OR appointment.status<>'scheduled'
                   OR datetime(appointment.scheduled_at)<
                       datetime('now','+3 hours','+30 minutes')
                 )"""
        ).fetchall()
        for row in rows:
            self.repo.set_status(
                int(row["id"]),
                "rejected",
                decided_by,
            )
        return len(rows)

    def preview(self) -> dict:
        candidates = self._growth_task_candidates()
        reminders = self._appointment_reminder_candidates()
        return {
            "growth_eligible": sum(1 for item in candidates if item["eligible"]),
            "growth_stopped": sum(1 for item in candidates if not item["eligible"]),
            "appointment_reminders": len(reminders),
            "total_candidates": (
                sum(1 for item in candidates if item["eligible"])
                + len(reminders)
            ),
        }

    def run(self, *, actor_username: str) -> dict:
        queued = 0
        existing = 0
        skipped = 0
        stopped = 0
        stop_reasons: dict[str, int] = {}

        for candidate in self._growth_task_candidates():
            if not candidate["eligible"]:
                reason = str(candidate.get("stop_reason") or "STOPPED")
                stop_reasons[reason] = stop_reasons.get(reason, 0) + 1
                if self._cancel_pending(
                    patient_link_id=candidate["patient_link_id"],
                    event_key=candidate["event_key"],
                    period_key=candidate["period_key"],
                    decided_by="system:growth-stop-condition",
                ):
                    stopped += 1
                continue
            prior = self.repo.find_approval(
                patient_link_id=candidate["patient_link_id"],
                event_key=candidate["event_key"],
                period_key=candidate["period_key"],
            )
            if prior:
                existing += 1
                continue
            approval_id = self.engagement.enqueue_event_for_patient(
                candidate["patient_link_id"],
                candidate["event_key"],
                candidate["period_key"],
                candidate["detail"],
            )
            if approval_id:
                queued += 1
            else:
                skipped += 1

        for candidate in self._appointment_reminder_candidates():
            prior = self.repo.find_approval(
                patient_link_id=candidate["patient_link_id"],
                event_key=candidate["event_key"],
                period_key=candidate["period_key"],
            )
            if prior:
                existing += 1
                continue
            approval_id = self.engagement.enqueue_event_for_patient(
                candidate["patient_link_id"],
                candidate["event_key"],
                candidate["period_key"],
                candidate["detail"],
            )
            if approval_id:
                queued += 1
            else:
                skipped += 1

        stopped += self._cancel_stale_appointment_reminders(
            "system:growth-stop-condition"
        )
        return {
            "queued": queued,
            "existing": existing,
            "skipped": skipped,
            "stopped_pending": stopped,
            "stop_reasons": stop_reasons,
        }


__all__ = ["GrowthMessagingPlaybookService"]
