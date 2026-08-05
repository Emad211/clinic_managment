"""Narrow authoritative actions for one Work Center episode.

This is intentionally not a generic workflow engine. It resolves the task already linked
to an Episode and delegates to existing domain services. Every automated continuation is
based on a committed source mutation; the disposable projection is refreshed afterwards.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import sqlite3

from src.adapters.sqlite.clinical_care_loop_repo import ClinicalCareLoopRepository
from src.adapters.sqlite.encounter_plan_commitment_repo import (
    EncounterPlanCommitmentRepository,
)
from src.adapters.sqlite.followup_episode_repo import FollowupEpisodeRepository
from src.adapters.sqlite.followup_projection_repo import FollowupProjectionRepository
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.common.utils import iran_now, today_str
from src.security.permissions import Permission
from src.services.encounter_plan_commitment_service import (
    EncounterPlanCommitmentService,
)
from src.services.engagement_service import EngagementService
from src.services.followup_booking_service import FollowupBookingService
from src.services.followup_orchestration.identity import canonical_hash
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

    @staticmethod
    def _idempotency_key(value: object) -> str:
        key = str(value or "").strip()
        if len(key) < 16:
            raise WorkCenterActionError(
                "INVALID_IDEMPOTENCY_KEY",
                "شناسهٔ یکتای اقدام معتبر نیست؛ صفحه را تازه کنید.",
            )
        return key

    def _naive_now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is not None:
            value = value.replace(tzinfo=None)
        return value.replace(microsecond=0)

    def _now_text(self) -> str:
        return self._naive_now().isoformat(sep=" ", timespec="seconds")

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

    def _existing_episode_action(
        self,
        *,
        episode_id: str,
        event_type: str,
        idempotency_key: str,
        request_payload: dict,
    ) -> dict | None:
        row = self.db.execute(
            """SELECT * FROM followup_episode_events
               WHERE idempotency_key=?""",
            (idempotency_key,),
        ).fetchone()
        if not row:
            return None
        if (
            str(row["episode_id"]) != str(episode_id)
            or str(row["event_type"]) != str(event_type)
        ):
            raise WorkCenterActionError(
                "ACTION_IDEMPOTENCY_SCOPE_MISMATCH",
                "شناسهٔ این اقدام قبلاً برای عملیات دیگری استفاده شده است.",
            )
        try:
            payload = json.loads(str(row["payload_json"] or "{}"))
        except json.JSONDecodeError as exc:
            raise WorkCenterActionError(
                "ACTION_AUDIT_CORRUPTED",
                "سابقهٔ اقدام قابل اعتبارسنجی نیست.",
            ) from exc
        if payload.get("request_hash") != canonical_hash(request_payload):
            raise WorkCenterActionError(
                "ACTION_IDEMPOTENCY_CONFLICT",
                "این شناسه با ورودی متفاوت قبلاً ثبت شده است.",
            )
        return payload

    def _append_episode_action(
        self,
        *,
        repository: FollowupEpisodeRepository,
        episode_id: str,
        event_type: str,
        idempotency_key: str,
        request_payload: dict,
        result_payload: dict,
        actor_username: str,
        actor_user_id: int | None,
    ) -> dict:
        payload = {
            "request_hash": canonical_hash(request_payload),
            **result_payload,
        }
        repository.append_event_once(
            episode_id=str(episode_id),
            event_type=event_type,
            actor_username=actor_username,
            actor_user_id=int(actor_user_id) if actor_user_id else None,
            idempotency_key=idempotency_key,
            effective_at=self._now_text(),
            recorded_at=self._now_text(),
            payload=payload,
            commit=False,
        )
        return payload

    def _with_projection_refresh(self, episode_id: str, result: dict) -> dict:
        """Keep a committed source mutation truthful if cache refresh later fails."""
        output = dict(result)
        try:
            self.refresh_projection(episode_id)
        except Exception as exc:
            output["projection_refreshed"] = False
            output["projection_refresh_error"] = type(exc).__name__
        else:
            output["projection_refreshed"] = True
            output["projection_refresh_error"] = None
        return output

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
                "can_message": False,
                "can_complete": False,
                "can_complete_clinical": False,
                "can_complete_plan": False,
            }
        kind = self._kind(task)
        transition_permission = self._required_transition_permission(kind)
        current_due = task.get("due_date")
        expected_event_id = None
        task_contract = None
        plan_context = None
        if kind == "clinical":
            current = ClinicalCareLoopRepository(self.db).current_task(int(task["id"]))
            current_due = current.get("current_due_at") or current_due
            expected_event_id = int(current["current_event_id"])
            task_contract = current.get("task_contract")
        elif kind == "plan":
            current = EncounterPlanCommitmentRepository(self.db).current_for_task(
                int(task["id"])
            )
            current_due = (current or {}).get("current_due_at") or current_due
            expected_event_id = (
                int(current["current_event_id"]) if current else None
            )
            plan_context = current
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
            "task_contract": task_contract,
            "plan_context": plan_context,
            "can_defer": transition_permission in permissions,
            "can_book": (
                Permission.FOLLOWUP_BOOK_APPOINTMENT in permissions
                and transition_permission in permissions
            ),
            "can_message": Permission.SMS_VIEW in permissions,
            "can_complete": (
                kind == "administrative"
                and Permission.FOLLOWUP_ADMIN_MANAGE in permissions
            ),
            "can_complete_clinical": (
                kind == "clinical"
                and Permission.CLINICAL_OUTCOME_RECORD in permissions
                and Permission.CLINICAL_TASK_TRANSITION in permissions
            ),
            "can_complete_plan": (
                kind == "plan"
                and Permission.FOLLOWUP_PLAN_TRANSITION in permissions
            ),
            "suggested_booking_at": (
                now + timedelta(days=1)
            ).replace(hour=9, minute=0, second=0, microsecond=0),
        }

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
        key = self._idempotency_key(idempotency_key)
        request_payload = {
            "action": "DEFER",
            "task_id": task_id,
            "kind": kind,
            "due_at": due_text,
            "note": str(note or "").strip(),
        }

        if kind == "plan":
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
                idempotency_key=key,
                due_at=due_text,
                note=note or "تغییر موعد از مرکز کارها",
            )
            return self._with_projection_refresh(
                episode_id,
                {
                    "task_id": task_id,
                    "due_at": event["due_at"],
                    "duplicate": bool(event.get("duplicate")),
                },
            )

        episode_repository = FollowupEpisodeRepository(self.db)
        clinical_repository = (
            ClinicalCareLoopRepository(self.db) if kind == "clinical" else None
        )
        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self._existing_episode_action(
                episode_id=episode_id,
                event_type="ACTION_DUE_CHANGED",
                idempotency_key=key,
                request_payload=request_payload,
            )
            if prior:
                self.db.commit()
                return self._with_projection_refresh(
                    episode_id,
                    {
                        "task_id": task_id,
                        "due_at": prior["due_at"],
                        "duplicate": True,
                    },
                )
            if kind == "administrative":
                result = FollowupRepository(self.db).defer(
                    task_id,
                    due_at=due_text,
                    assigned_to=actor_username,
                    commit=False,
                )
            else:
                current = clinical_repository.current_task(task_id)
                event = clinical_repository.append_task_event(
                    task_id,
                    event_type="DEFERRED",
                    expected_current_event_id=int(current["current_event_id"]),
                    actor_username=actor_username,
                    actor_user_id=int(actor_user_id),
                    due_at=due_text,
                    note=note or "تعویق از مرکز کارها",
                    recorded_at=self._naive_now(),
                    commit=False,
                )
                result = {"task_id": task_id, "due_at": event["due_at"]}
            self._append_episode_action(
                repository=episode_repository,
                episode_id=episode_id,
                event_type="ACTION_DUE_CHANGED",
                idempotency_key=key,
                request_payload=request_payload,
                result_payload={
                    "task_id": task_id,
                    "due_at": result["due_at"],
                    "kind": kind,
                },
                actor_username=actor_username,
                actor_user_id=actor_user_id,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self._with_projection_refresh(
            episode_id,
            {**result, "duplicate": False},
        )

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
            idempotency_key=self._idempotency_key(idempotency_key),
            episode_id=str(episode_id),
        )
        return self._with_projection_refresh(episode_id, result)

    def complete_administrative(
        self,
        episode_id: str,
        *,
        actor_username: str,
        permissions: frozenset[Permission],
        actor_user_id: int | None = None,
        idempotency_key: str | None = None,
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
        task_id = int(task["id"])
        key = self._idempotency_key(
            idempotency_key
            or f"work-center-admin-complete:{episode_id}:{task_id}"
        )
        clean_note = str(note or "").strip()
        request_payload = {
            "action": "COMPLETE_ADMINISTRATIVE",
            "task_id": task_id,
            "note": clean_note,
        }
        episode_repository = FollowupEpisodeRepository(self.db)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self._existing_episode_action(
                episode_id=episode_id,
                event_type="ADMINISTRATIVE_GOAL_MET",
                idempotency_key=key,
                request_payload=request_payload,
            )
            if prior:
                self.db.commit()
                return self._with_projection_refresh(
                    episode_id,
                    {
                        "task_id": task_id,
                        "patient_link_id": int(task["patient_link_id"]),
                        "status": "done",
                        "duplicate": True,
                    },
                )
            FollowupRepository(self.db).resolve(
                task_id,
                "done",
                clean_note or f"تکمیل از مرکز کارها توسط {actor_username}",
                commit=False,
            )
            self._append_episode_action(
                repository=episode_repository,
                episode_id=episode_id,
                event_type="ADMINISTRATIVE_GOAL_MET",
                idempotency_key=key,
                request_payload=request_payload,
                result_payload={"task_id": task_id, "status": "done"},
                actor_username=actor_username,
                actor_user_id=actor_user_id,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self._with_projection_refresh(
            episode_id,
            {
                "task_id": task_id,
                "patient_link_id": int(task["patient_link_id"]),
                "status": "done",
                "duplicate": False,
            },
        )

    def complete_clinical(
        self,
        episode_id: str,
        *,
        actor_username: str,
        actor_user_id: int,
        permissions: frozenset[Permission],
        idempotency_key: str,
        outcome_type: str,
        fact_key: str | None = None,
        value=None,
        unit: str | None = None,
        verification: str = "CONFIRMED",
        observed_at: datetime | str | None = None,
        note: str | None = None,
    ) -> dict:
        task = self._task(episode_id)
        if self._kind(task) != "clinical":
            raise WorkCenterActionError(
                "CLINICAL_TASK_REQUIRED",
                "این مسیر یک پیگیری بالینی نیست.",
            )
        if not {
            Permission.CLINICAL_OUTCOME_RECORD,
            Permission.CLINICAL_TASK_TRANSITION,
        } <= permissions:
            raise WorkCenterActionError(
                "CLINICAL_COMPLETION_PERMISSION_REQUIRED",
                "مجوز ثبت شاهد و تکمیل پیگیری بالینی وجود ندارد.",
            )
        key = self._idempotency_key(idempotency_key)
        task_id = int(task["id"])
        observed = observed_at or self._now_text()
        request_payload = {
            "action": "COMPLETE_CLINICAL",
            "task_id": task_id,
            "outcome_type": str(outcome_type or "").strip().upper(),
            "fact_key": str(fact_key or "").strip() or None,
            "value": value if value not in (None, "") else None,
            "unit": str(unit or "").strip() or None,
            "verification": str(verification or "CONFIRMED").strip().upper(),
            "observed_at": str(observed),
            "note": str(note or "").strip(),
        }
        episode_repository = FollowupEpisodeRepository(self.db)
        clinical_repository = ClinicalCareLoopRepository(self.db)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self._existing_episode_action(
                episode_id=episode_id,
                event_type="EPISODE_CLOSED",
                idempotency_key=key,
                request_payload=request_payload,
            )
            if prior:
                self.db.commit()
                return self._with_projection_refresh(
                    episode_id,
                    {
                        "task_id": task_id,
                        "outcome_event_id": int(prior["outcome_event_id"]),
                        "task_event_id": int(prior["task_event_id"]),
                        "status": "COMPLETED",
                        "duplicate": True,
                    },
                )
            current = clinical_repository.current_task(task_id)
            source_record_id = (
                "work-center:" + canonical_hash(
                    {"episode_id": str(episode_id), "idempotency_key": key}
                )[:48]
            )
            outcome = clinical_repository.record_outcome(
                task_id,
                outcome_type=request_payload["outcome_type"],
                fact_key=request_payload["fact_key"],
                value=request_payload["value"],
                unit=request_payload["unit"],
                verification=request_payload["verification"],
                observed_at=request_payload["observed_at"],
                source_system="work_center",
                source_record_id=source_record_id,
                note=request_payload["note"] or None,
                actor_username=actor_username,
                actor_user_id=int(actor_user_id),
                recorded_at=self._naive_now(),
                commit=False,
            )
            task_event = clinical_repository.append_task_event(
                task_id,
                event_type="COMPLETED",
                expected_current_event_id=int(current["current_event_id"]),
                actor_username=actor_username,
                actor_user_id=int(actor_user_id),
                outcome_event_id=int(outcome["id"]),
                note=request_payload["note"] or "تکمیل با شاهد از مرکز کارها",
                recorded_at=self._naive_now(),
                commit=False,
            )
            episode_repository.link_source_once(
                episode_id=str(episode_id),
                patient_link_id=int(task["patient_link_id"]),
                source_type="CLINICAL_OUTCOME",
                source_id=str(outcome["id"]),
                source_revision=canonical_hash(
                    {
                        "id": int(outcome["id"]),
                        "task_id": task_id,
                        "content_hash": str(outcome["content_hash"]),
                    }
                ),
                relation_type="OUTCOME",
                actor_username=actor_username,
                linked_at=self._now_text(),
                recorded_at=self._now_text(),
                commit=False,
            )
            self._append_episode_action(
                repository=episode_repository,
                episode_id=episode_id,
                event_type="EPISODE_CLOSED",
                idempotency_key=key,
                request_payload=request_payload,
                result_payload={
                    "task_id": task_id,
                    "outcome_event_id": int(outcome["id"]),
                    "task_event_id": int(task_event["id"]),
                    "status": "COMPLETED",
                },
                actor_username=actor_username,
                actor_user_id=actor_user_id,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self._with_projection_refresh(
            episode_id,
            {
                "task_id": task_id,
                "outcome_event_id": int(outcome["id"]),
                "task_event_id": int(task_event["id"]),
                "status": "COMPLETED",
                "duplicate": False,
            },
        )

    def complete_plan(
        self,
        episode_id: str,
        *,
        actor_username: str,
        actor_user_id: int,
        permissions: frozenset[Permission],
        idempotency_key: str,
        evidence_type: str,
        evidence_ref: str,
        outcome_code: str,
        note: str | None = None,
    ) -> dict:
        task = self._task(episode_id)
        if self._kind(task) != "plan":
            raise WorkCenterActionError(
                "PLAN_TASK_REQUIRED",
                "این مسیر اقدام برنامه درمان نیست.",
            )
        if Permission.FOLLOWUP_PLAN_TRANSITION not in permissions:
            raise WorkCenterActionError(
                "PLAN_COMPLETION_PERMISSION_REQUIRED",
                "مجوز تکمیل اقدام برنامه درمان وجود ندارد.",
            )
        task_id = int(task["id"])
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
            transition="complete",
            expected_current_event_id=int(current["current_event_id"]),
            actor_username=actor_username,
            actor_user_id=int(actor_user_id),
            idempotency_key=self._idempotency_key(idempotency_key),
            evidence_type=evidence_type,
            evidence_ref=evidence_ref,
            outcome_code=outcome_code,
            note=note,
        )
        return self._with_projection_refresh(
            episode_id,
            {
                "task_id": task_id,
                "status": str(event["status"]),
                "event_id": int(event["id"]),
                "duplicate": bool(event.get("duplicate")),
            },
        )

    def queue_visit_invite(
        self,
        episode_id: str,
        *,
        actor_username: str,
        actor_user_id: int,
        permissions: frozenset[Permission],
    ) -> dict:
        task = self._task(episode_id)
        if Permission.SMS_VIEW not in permissions:
            raise WorkCenterActionError(
                "MESSAGE_PERMISSION_REQUIRED",
                "مجوز افزودن پیام به صف وجود ندارد.",
            )
        patient_id = int(task["patient_link_id"])
        approval_id = EngagementService().enqueue_invite(patient_id)
        period_key = f"invite:{today_str()}"
        if approval_id is None:
            row = self.db.execute(
                """SELECT * FROM engagement_approvals
                   WHERE patient_link_id=? AND event_key='visit_invite'
                     AND period_key=?""",
                (patient_id, period_key),
            ).fetchone()
            if not row:
                raise WorkCenterActionError(
                    "MESSAGE_NOT_ELIGIBLE",
                    "شماره، رضایت پیام یا تنظیمات ارسال برای این بیمار آماده نیست.",
                )
            approval = dict(row)
            if approval["status"] not in {"pending", "submitting", "approved"}:
                raise WorkCenterActionError(
                    "MESSAGE_ALREADY_DECIDED",
                    "پیام امروز قبلاً بررسی شده و قابل افزودن دوباره نیست.",
                )
            approval_id = int(approval["id"])
            duplicate = True
        else:
            approval = dict(
                self.db.execute(
                    "SELECT * FROM engagement_approvals WHERE id=?",
                    (int(approval_id),),
                ).fetchone()
            )
            duplicate = False

        episode_repository = FollowupEpisodeRepository(self.db)
        linked = True
        try:
            self.db.execute("BEGIN IMMEDIATE")
            episode_repository.link_source_once(
                episode_id=str(episode_id),
                patient_link_id=patient_id,
                source_type="ENGAGEMENT_APPROVAL",
                source_id=str(approval_id),
                source_revision=canonical_hash(
                    {
                        "id": int(approval["id"]),
                        "patient_link_id": int(approval["patient_link_id"]),
                        "event_key": str(approval["event_key"]),
                        "period_key": str(approval["period_key"]),
                    }
                ),
                relation_type="COMMUNICATION",
                actor_username=actor_username,
                linked_at=self._now_text(),
                recorded_at=self._now_text(),
                commit=False,
            )
            episode_repository.append_event_once(
                episode_id=str(episode_id),
                event_type="SMS_QUEUED",
                actor_username=actor_username,
                actor_user_id=int(actor_user_id),
                idempotency_key=(
                    f"work-center-sms-queued:{episode_id}:{int(approval_id)}"
                ),
                effective_at=self._now_text(),
                recorded_at=self._now_text(),
                payload={"approval_id": int(approval_id), "event_key": "visit_invite"},
                commit=False,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            linked = False
        return self._with_projection_refresh(
            episode_id,
            {
                "task_id": int(task["id"]),
                "approval_id": int(approval_id),
                "queued": True,
                "duplicate": duplicate,
                "episode_linked": linked,
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
