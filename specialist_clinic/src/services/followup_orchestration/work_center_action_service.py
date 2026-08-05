"""Narrow authoritative actions for one Work Center episode.

This service does not invent a generic workflow. It resolves the task already linked to
an Episode and delegates to the existing administrative, clinical, plan and booking
services. The disposable projection is refreshed only after a successful source write.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import sqlite3

from src.adapters.sqlite.clinical_care_loop_repo import ClinicalCareLoopRepository
from src.adapters.sqlite.encounter_plan_commitment_repo import (
    EncounterPlanCommitmentRepository,
)
from src.adapters.sqlite.followup_projection_repo import FollowupProjectionRepository
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.common.utils import iran_now
from src.security.permissions import Permission
from src.services.clinical_care_loop_service import ClinicalCareLoopService
from src.services.encounter_plan_commitment_service import (
    EncounterPlanCommitmentService,
)
from src.services.followup_booking_service import FollowupBookingService
from src.services.followup_orchestration.projection_service import (
    FollowupProjectionService,
)


class WorkCenterActionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class WorkCenterActionService:
    def __init__(self, db: sqlite3.Connection, *, clock=None):
        self.db = db
        self.db.row_factory = sqlite3.Row
        self.clock = clock or iran_now

    def _task(self, episode_id: str) -> dict:
        row = self.db.execute(
            """SELECT task.*, link.source_type, link.relation_type
               FROM followup_episode_links link
               JOIN followup_tasks task
                 ON task.id=CAST(link.source_id AS INTEGER)
               WHERE link.episode_id=?
                 AND link.source_type IN ('ADMIN_TASK','CLINICAL_TASK')
               ORDER BY CASE link.relation_type WHEN 'PRIMARY' THEN 0 ELSE 1 END,
                        CASE link.source_type WHEN 'CLINICAL_TASK' THEN 0 ELSE 1 END,
                        link.id
               LIMIT 1""",
            (str(episode_id),),
        ).fetchone()
        if not row:
            raise WorkCenterActionError(
                "WORK_TASK_UNAVAILABLE",
                "این مسیر کار قابل اقدام ندارد.",
            )
        return dict(row)

    @staticmethod
    def _kind(task: dict) -> str:
        engine = str(task.get("source_engine") or "").strip()
        if engine == "clinical_v2":
            return "clinical"
        if engine == "encounter_plan":
            return "plan"
        return "administrative"

    @staticmethod
    def _required_transition_permission(kind: str) -> Permission:
        if kind == "clinical":
            return Permission.CLINICAL_TASK_TRANSITION
        if kind == "plan":
            return Permission.FOLLOWUP_PLAN_TRANSITION
        return Permission.FOLLOWUP_ADMIN_MANAGE

    def describe(
        self,
        episode_id: str,
        *,
        permissions: frozenset[Permission],
    ) -> dict:
        try:
            task = self._task(episode_id)
        except WorkCenterActionError as error:
            return {
                "available": False,
                "reason": error.message,
                "can_defer": False,
                "can_book": False,
                "can_complete": False,
            }
        kind = self._kind(task)
        transition_permission = self._required_transition_permission(kind)
        current_due = task.get("due_date")
        expected_event_id = None
        if kind == "clinical":
            current = ClinicalCareLoopRepository(self.db).current_task(int(task["id"]))
            current_due = current.get("current_due_at") or current_due
            expected_event_id = int(current["current_event_id"])
        elif kind == "plan":
            current = EncounterPlanCommitmentRepository(self.db).current_for_task(
                int(task["id"])
            )
            current_due = (current or {}).get("current_due_at") or current_due
            expected_event_id = (
                int(current["current_event_id"]) if current else None
            )
        now = self._naive_now()
        return {
            "available": True,
            "task_id": int(task["id"]),
            "patient_link_id": int(task["patient_link_id"]),
            "kind": kind,
            "kind_label": {
                "administrative": "کار اداری",
                "clinical": "پیگیری بالینی",
                "plan": "اقدام برنامه درمان",
            }[kind],
            "current_due_at": current_due,
            "expected_task_event_id": expected_event_id,
            "can_defer": transition_permission in permissions,
            "can_book": (
                Permission.FOLLOWUP_BOOK_APPOINTMENT in permissions
                and transition_permission in permissions
            ),
            "can_complete": (
                kind == "administrative"
                and Permission.FOLLOWUP_ADMIN_MANAGE in permissions
            ),
            "suggested_booking_at": (
                now + timedelta(days=1)
            ).replace(hour=9, minute=0, second=0, microsecond=0),
        }

    def _naive_now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is not None:
            value = value.replace(tzinfo=None)
        return value.replace(microsecond=0)

    def _normalize_future(self, value: datetime | str) -> str:
        try:
            parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise WorkCenterActionError(
                "INVALID_DUE_AT",
                "زمان انتخاب‌شده معتبر نیست.",
            ) from exc
        if parsed.tzinfo is not None:
            parsed = parsed.replace(tzinfo=None)
        parsed = parsed.replace(microsecond=0)
        if parsed <= self._naive_now():
            raise WorkCenterActionError(
                "DUE_AT_NOT_FUTURE",
                "زمان اقدام بعدی باید در آینده باشد.",
            )
        return parsed.isoformat(sep=" ", timespec="seconds")

    def _with_projection_refresh(self, episode_id: str, result: dict) -> dict:
        """Never turn a committed source mutation into a false failure message.

        The projection is disposable. If its refresh fails after the authoritative
        mutation committed, return success plus a PHI-free refresh warning so the UI can
        ask for a reload without implying that the action itself was rolled back.
        """
        output = dict(result)
        try:
            self.refresh_projection(episode_id)
        except Exception as exc:  # Source already committed; preserve truthful outcome.
            output["projection_refreshed"] = False
            output["projection_refresh_error"] = type(exc).__name__
        else:
            output["projection_refreshed"] = True
            output["projection_refresh_error"] = None
        return output

    def defer(
        self,
        episode_id: str,
        *,
        due_at: datetime | str,
        actor_username: str,
        actor_user_id: int,
        permissions: frozenset[Permission],
        idempotency_key: str,
        note: str | None = None,
    ) -> dict:
        task = self._task(episode_id)
        kind = self._kind(task)
        required = self._required_transition_permission(kind)
        if required not in permissions:
            raise WorkCenterActionError(
                "DEFER_PERMISSION_REQUIRED",
                "مجوز تعویق این نوع کار وجود ندارد.",
            )
        due_text = self._normalize_future(due_at)
        task_id = int(task["id"])
        if kind == "administrative":
            result = FollowupRepository(self.db).defer(
                task_id,
                due_at=due_text,
                assigned_to=actor_username,
            )
        elif kind == "clinical":
            repository = ClinicalCareLoopRepository(self.db)
            current = repository.current_task(task_id)
            event = ClinicalCareLoopService(
                repository=repository,
                clock=self.clock,
            ).transition(
                task_id,
                transition="defer",
                expected_current_event_id=int(current["current_event_id"]),
                actor_username=actor_username,
                actor_user_id=int(actor_user_id),
                due_at=due_text,
                note=note or "تعویق از مرکز کارها",
            )
            result = {"task_id": task_id, "due_at": event["due_at"]}
        else:
            repository = EncounterPlanCommitmentRepository(self.db)
            current = repository.current_for_task(task_id)
            if not current:
                raise WorkCenterActionError(
                    "PLAN_TASK_UNAVAILABLE",
                    "اقدام برنامه درمان پیدا نشد.",
                )
            event = EncounterPlanCommitmentService(
                db=self.db,
                repository=repository,
                clock=self.clock,
            ).transition(
                task_id=task_id,
                transition="reschedule",
                expected_current_event_id=int(current["current_event_id"]),
                actor_username=actor_username,
                actor_user_id=int(actor_user_id),
                idempotency_key=str(idempotency_key),
                due_at=due_text,
                note=note or "تغییر موعد از مرکز کارها",
            )
            result = {"task_id": task_id, "due_at": event["due_at"]}
        return self._with_projection_refresh(episode_id, result)

    def book(
        self,
        episode_id: str,
        *,
        scheduled_at: datetime | str,
        actor_username: str,
        actor_user_id: int,
        permissions: frozenset[Permission],
        idempotency_key: str,
    ) -> dict:
        task = self._task(episode_id)
        kind = self._kind(task)
        required = self._required_transition_permission(kind)
        if Permission.FOLLOWUP_BOOK_APPOINTMENT not in permissions or required not in permissions:
            raise WorkCenterActionError(
                "BOOK_PERMISSION_REQUIRED",
                "مجوز رزرو نوبت برای این نوع کار وجود ندارد.",
            )
        scheduled_text = self._normalize_future(scheduled_at)
        result = FollowupBookingService(db=self.db, clock=self.clock).book(
            patient_link_id=int(task["patient_link_id"]),
            task_ids=[int(task["id"])],
            scheduled_at=scheduled_text,
            actor_username=actor_username,
            actor_user_id=int(actor_user_id),
            idempotency_key=str(idempotency_key),
            episode_id=str(episode_id),
        )
        return self._with_projection_refresh(episode_id, result)

    def complete_administrative(
        self,
        episode_id: str,
        *,
        actor_username: str,
        permissions: frozenset[Permission],
        note: str | None = None,
    ) -> dict:
        task = self._task(episode_id)
        if self._kind(task) != "administrative":
            raise WorkCenterActionError(
                "EVIDENCE_REQUIRED",
                "این کار فقط با مسیر نتیجه و شاهد معتبر تکمیل می‌شود.",
            )
        if Permission.FOLLOWUP_ADMIN_MANAGE not in permissions:
            raise WorkCenterActionError(
                "COMPLETE_PERMISSION_REQUIRED",
                "مجوز تکمیل این کار وجود ندارد.",
            )
        FollowupRepository(self.db).resolve(
            int(task["id"]),
            "done",
            note or f"تکمیل از مرکز کارها توسط {actor_username}",
        )
        return self._with_projection_refresh(
            episode_id,
            {
                "task_id": int(task["id"]),
                "patient_link_id": int(task["patient_link_id"]),
                "status": "done",
            },
        )

    def refresh_projection(self, episode_id: str) -> dict:
        current = self._naive_now()
        rows = FollowupProjectionService(self.db).build_rows(as_of_at=current)
        row = next(
            (item for item in rows if str(item["episode_id"]) == str(episode_id)),
            None,
        )
        if row is None:
            raise WorkCenterActionError(
                "PROJECTION_REFRESH_FAILED",
                "اقدام ثبت شد اما نمای کار نیازمند بازخوانی است.",
            )
        return FollowupProjectionRepository(
            self.db,
            install_schema=False,
        ).upsert_one(row)


__all__ = ["WorkCenterActionError", "WorkCenterActionService"]
