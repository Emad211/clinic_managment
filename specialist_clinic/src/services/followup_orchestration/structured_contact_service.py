"""FO-5 structured contact, retry and escalation orchestration.

The authoritative contact occurrence remains ``followup_contact_events``. This
service links that append-only row to the Episode and records only PHI-minimized
operational decisions in the Episode event stream. It does not send SMS, mutate
appointments, complete clinical work, or write to the accounting database.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import sqlite3
from typing import Iterable

from src.adapters.sqlite.followup_episode_repo import (
    FollowupEpisodeConflict,
    FollowupEpisodeRepository,
)
from src.adapters.sqlite.followup_operations_repo import (
    FollowupContactConflict,
    FollowupOperationsRepository,
)
from src.common.utils import iran_now
from src.security.permissions import Permission, resolved_permissions
from src.services.followup_orchestration.identity import canonical_hash
from src.services.followup_orchestration.ownership_service import (
    FollowupOwnershipService,
)


POLICY_VERSION = "FOUX-CONTACT-V1"
RETRY_THRESHOLD = 3
SUPPORTED_OUTCOMES = (
    "REACHED",
    "NO_ANSWER",
    "BUSY",
    "CALLBACK_REQUESTED",
    "PHONE_INVALID",
    "APPOINTMENT_BOOKED",
    "DECLINED",
    "ESCALATED_TO_PHYSICIAN",
    "OTHER",
)
OUTCOME_LABELS = {
    "REACHED": "تماس موفق",
    "NO_ANSWER": "پاسخ نداد",
    "BUSY": "خط مشغول بود",
    "CALLBACK_REQUESTED": "درخواست تماس مجدد",
    "PHONE_INVALID": "شماره نامعتبر است",
    "APPOINTMENT_BOOKED": "بیمار اعلام کرد نوبت ثبت شده است",
    "DECLINED": "بیمار ادامهٔ پیگیری را نپذیرفت",
    "ESCALATED_TO_PHYSICIAN": "برای بررسی پزشک ارجاع شد",
    "OTHER": "نتیجهٔ دیگر",
}
NEXT_ACTION_LABELS = {
    "CONTINUE_CURRENT_PATH": "ادامهٔ مسیر فعلی",
    "CALLBACK_AT_TIME": "تماس مجدد در زمان ثبت‌شده",
    "MANAGER_REVIEW_UNREACHABLE": "بررسی مدیر به‌دلیل عدم دسترسی",
    "FIX_CONTACT_DATA": "اصلاح اطلاعات تماس",
    "WAIT_FOR_APPOINTMENT": "بررسی وضعیت نوبت در مسیر حاکم",
    "MANAGER_REVIEW_DECLINED": "بررسی مدیر دربارهٔ انصراف بیمار",
    "PHYSICIAN_REVIEW": "بررسی پزشک",
    "MANAGER_REVIEW_OTHER": "بررسی نتیجهٔ تماس توسط مدیر",
}
LEGACY_OUTCOME_MAP = {
    "REACHED": "REACHED",
    "NO_ANSWER": "NO_ANSWER",
    "BUSY": "BUSY",
    "CALLBACK_REQUESTED": "CALLBACK_REQUESTED",
    "PHONE_INVALID": "WRONG_NUMBER",
    "APPOINTMENT_BOOKED": "BOOKED",
    "DECLINED": "DECLINED",
    "ESCALATED_TO_PHYSICIAN": "OTHER",
    "OTHER": "OTHER",
}
RETRY_OUTCOMES = frozenset({"NO_ANSWER", "BUSY"})


class FollowupStructuredContactError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _event_payload(row: sqlite3.Row | dict | None) -> dict:
    if not row:
        return {}
    try:
        value = json.loads(str(row["payload_json"] or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _as_local_naive(value: datetime | str | None) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(
                str(value).strip().replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise FollowupStructuredContactError(
                "INVALID_CALLBACK_AT",
                "زمان تماس مجدد معتبر نیست.",
            ) from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(iran_now().tzinfo).replace(tzinfo=None)
    return parsed.replace(microsecond=0)


def _text(value: datetime | None) -> str | None:
    return value.isoformat(sep=" ", timespec="seconds") if value else None


def _normalize_expected(value: object) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise FollowupStructuredContactError(
            "INVALID_EXPECTED_EVENT",
            "نسخهٔ فرم معتبر نیست؛ صفحه را تازه کنید.",
        ) from exc
    return max(parsed, 0)


def _normalize_outcome(value: object) -> str:
    outcome = str(value or "").strip().upper()
    if outcome not in SUPPORTED_OUTCOMES:
        raise FollowupStructuredContactError(
            "INVALID_CONTACT_OUTCOME",
            "نتیجهٔ تماس انتخاب‌شده معتبر نیست.",
        )
    return outcome


class FollowupStructuredContactService:
    """Serialize FO-5 contact decisions through one database transaction."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.db.row_factory = sqlite3.Row
        # Read-model methods must not run schema DDL or commit. Repositories
        # that ensure storage are instantiated only on the mutation path.
        self.ownership = FollowupOwnershipService(db)

    def _projection(self, episode_id: str) -> sqlite3.Row:
        row = self.db.execute(
            """SELECT episode_id, patient_link_id, state_class
               FROM followup_work_item_projection WHERE episode_id=?""",
            (str(episode_id),),
        ).fetchone()
        if not row:
            raise FollowupStructuredContactError(
                "CONTACT_PROJECTION_UNAVAILABLE",
                "این مسیر در نمای جاری موجود نیست؛ ابتدا نمای یکپارچه را بازسازی کنید.",
            )
        return row

    def _task_id(self, episode_id: str) -> int | None:
        row = self.db.execute(
            """SELECT source_id
               FROM followup_episode_links
               WHERE episode_id=?
                 AND source_type IN ('ADMIN_TASK','CLINICAL_TASK')
               ORDER BY CASE relation_type WHEN 'PRIMARY' THEN 0 ELSE 1 END, id
               LIMIT 1""",
            (str(episode_id),),
        ).fetchone()
        return int(row[0]) if row else None

    def _task_ids(self, episode_ids: Iterable[str]) -> dict[str, int]:
        ids = list(dict.fromkeys(str(value) for value in episode_ids if str(value)))
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        rows = self.db.execute(
            f"""SELECT episode_id, source_id, relation_type, id
                FROM followup_episode_links
                WHERE episode_id IN ({marks})
                  AND source_type IN ('ADMIN_TASK','CLINICAL_TASK')
                ORDER BY episode_id,
                         CASE relation_type WHEN 'PRIMARY' THEN 0 ELSE 1 END,
                         id""",
            ids,
        ).fetchall()
        result: dict[str, int] = {}
        for row in rows:
            result.setdefault(str(row["episode_id"]), int(row["source_id"]))
        return result

    def _latest_contact_events(self, episode_ids: Iterable[str]) -> dict[str, dict]:
        ids = list(dict.fromkeys(str(value) for value in episode_ids if str(value)))
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        rows = self.db.execute(
            f"""WITH ranked AS (
                    SELECT episode_id, id, effective_at, payload_json,
                           ROW_NUMBER() OVER (
                               PARTITION BY episode_id ORDER BY id DESC
                           ) AS recency_rank
                    FROM followup_episode_events
                    WHERE episode_id IN ({marks})
                      AND event_type='CONTACT_RECORDED'
                )
                SELECT * FROM ranked WHERE recency_rank=1""",
            ids,
        ).fetchall()
        return {str(row["episode_id"]): dict(row) for row in rows}

    @staticmethod
    def _empty_summary(task_id: int | None) -> dict:
        return {
            "available": task_id is not None,
            "task_id": task_id,
            "has_contact": False,
            "contact_event_id": None,
            "contact_count": 0,
            "failed_attempt_count": 0,
            "last_contact_at": None,
            "structured_outcome": None,
            "outcome_label": None,
            "next_action_code": None,
            "next_action_label": None,
            "callback_at": None,
            "escalated": False,
        }

    def _summary_from_event(self, task_id: int | None, row: dict | None) -> dict:
        summary = self._empty_summary(task_id)
        if not row:
            return summary
        payload = _event_payload(row)
        outcome = str(payload.get("structured_outcome") or "").upper()
        next_action = str(payload.get("next_action_code") or "").upper()
        summary.update(
            {
                "has_contact": True,
                "contact_event_id": payload.get("contact_event_id"),
                "contact_count": int(payload.get("contact_count") or 0),
                "failed_attempt_count": int(
                    payload.get("failed_attempt_count") or 0
                ),
                "last_contact_at": str(row.get("effective_at") or "") or None,
                "structured_outcome": outcome or None,
                "outcome_label": OUTCOME_LABELS.get(
                    outcome, "نتیجهٔ تماس ثبت‌شده"
                ),
                "next_action_code": next_action or None,
                "next_action_label": NEXT_ACTION_LABELS.get(
                    next_action, "ادامهٔ مسیر فعلی"
                ),
                "callback_at": payload.get("callback_at"),
                "escalated": bool(payload.get("escalated")),
            }
        )
        return summary

    def summary(self, episode_id: str) -> dict:
        task_id = self._task_id(episode_id)
        event = self._latest_contact_events([episode_id]).get(str(episode_id))
        return self._summary_from_event(task_id, event)

    def decorate_items(self, items: list[dict]) -> list[dict]:
        ids = [str(item["episode_id"]) for item in items]
        task_ids = self._task_ids(ids)
        events = self._latest_contact_events(ids)
        for item in items:
            episode_id = str(item["episode_id"])
            item["contact"] = self._summary_from_event(
                task_ids.get(episode_id),
                events.get(episode_id),
            )
        return items

    @staticmethod
    def _permissions(actor: sqlite3.Row | dict) -> frozenset[Permission]:
        return resolved_permissions(actor)

    def capabilities(
        self,
        *,
        episode_id: str,
        actor: sqlite3.Row | dict,
    ) -> dict:
        task_id = self._task_id(episode_id)
        projection = self._projection(episode_id)
        if str(projection["state_class"]) == "TERMINAL":
            return {
                "can_record": False,
                "reason": "مسیر پایان‌یافته قابل ثبت تماس نیست.",
                "task_id": task_id,
            }
        if task_id is None:
            return {
                "can_record": False,
                "reason": "این مسیر تسک قابل‌تماس ندارد.",
                "task_id": None,
            }
        permissions = self._permissions(actor)
        is_admin = Permission.FOLLOWUP_ADMIN_MANAGE in permissions
        can_contact = Permission.FOLLOWUP_CONTACT_RECORD in permissions
        if not (is_admin or can_contact):
            return {
                "can_record": False,
                "reason": "مجوز ثبت نتیجهٔ تماس برای این حساب وجود ندارد.",
                "task_id": task_id,
            }
        state = self.ownership.state(episode_id)
        actor_id = int(actor["id"])
        if not is_admin and state.owner_user_id != actor_id:
            return {
                "can_record": False,
                "reason": "ابتدا این مورد را برای رسیدگی دریافت کنید.",
                "task_id": task_id,
            }
        return {"can_record": True, "reason": None, "task_id": task_id}

    def _require_actor(
        self,
        *,
        episode_id: str,
        actor: sqlite3.Row | dict,
    ) -> int:
        projection = self._projection(episode_id)
        if str(projection["state_class"]) == "TERMINAL":
            raise FollowupStructuredContactError(
                "TERMINAL_CONTACT_MUTATION",
                "مسیر پایان‌یافته قابل ثبت تماس نیست.",
            )
        task_id = self._task_id(episode_id)
        if task_id is None:
            raise FollowupStructuredContactError(
                "CONTACT_TASK_UNAVAILABLE",
                "برای این مسیر تسک قابل‌تماس پیدا نشد.",
            )
        permissions = self._permissions(actor)
        is_admin = Permission.FOLLOWUP_ADMIN_MANAGE in permissions
        if Permission.FOLLOWUP_CONTACT_RECORD not in permissions and not is_admin:
            raise FollowupStructuredContactError(
                "CONTACT_PERMISSION_REQUIRED",
                "مجوز ثبت نتیجهٔ تماس برای این حساب وجود ندارد.",
            )
        state = self.ownership.state(episode_id)
        if not is_admin and state.owner_user_id != int(actor["id"]):
            raise FollowupStructuredContactError(
                "CONTACT_OWNER_REQUIRED",
                "فقط مسئول فعلی یا مدیر می‌تواند نتیجهٔ تماس را ثبت کند.",
            )
        return task_id

    def _request_hash(
        self,
        *,
        episode_id: str,
        task_id: int,
        outcome: str,
        callback_input: str | None,
        note: str | None,
    ) -> str:
        return canonical_hash(
            {
                "episode_id": str(episode_id),
                "task_id": int(task_id),
                "structured_outcome": outcome,
                "callback_input": str(callback_input or "").strip() or None,
                "note_sha256": (
                    hashlib.sha256(note.encode("utf-8")).hexdigest()
                    if note
                    else None
                ),
                "policy_version": POLICY_VERSION,
            }
        )

    def _existing_replay(
        self,
        *,
        episode_id: str,
        event_key: str,
        request_hash: str,
    ) -> dict | None:
        row = self.db.execute(
            """SELECT episode_id, payload_json
               FROM followup_episode_events WHERE idempotency_key=?""",
            (event_key,),
        ).fetchone()
        if not row:
            return None
        payload = _event_payload(row)
        if (
            str(row["episode_id"]) != str(episode_id)
            or str(payload.get("request_hash") or "") != request_hash
        ):
            raise FollowupStructuredContactError(
                "CONTACT_IDEMPOTENCY_CONFLICT",
                "شناسهٔ تکرار قبلاً برای نتیجهٔ تماس دیگری استفاده شده است.",
            )
        return self.summary(episode_id)

    def _contact_counts(self, task_id: int) -> tuple[int, int]:
        rows = self.db.execute(
            """SELECT outcome FROM followup_contact_events
               WHERE task_id=? ORDER BY occurred_at DESC, id DESC""",
            (int(task_id),),
        ).fetchall()
        failed = 0
        for row in rows:
            if str(row["outcome"]) not in {"NO_ANSWER", "BUSY"}:
                break
            failed += 1
        return len(rows), failed

    def _already_escalated(self, episode_id: str, reason_code: str) -> bool:
        rows = self.db.execute(
            """SELECT payload_json FROM followup_episode_events
               WHERE episode_id=? AND event_type='ESCALATED'""",
            (str(episode_id),),
        ).fetchall()
        return any(
            str(_event_payload(row).get("reason_code") or "") == reason_code
            for row in rows
        )

    def record(
        self,
        *,
        episode_id: str,
        actor: sqlite3.Row | dict,
        structured_outcome: object,
        expected_event_id: object,
        idempotency_key: str,
        callback_at: datetime | str | None = None,
        note: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        outcome = _normalize_outcome(structured_outcome)
        key = str(idempotency_key or "").strip()
        if len(key) < 16:
            raise FollowupStructuredContactError(
                "CONTACT_IDEMPOTENCY_REQUIRED",
                "شناسهٔ امن ثبت تماس وجود ندارد؛ صفحه را تازه کنید.",
            )
        normalized_note = str(note or "").strip() or None
        if normalized_note and len(normalized_note) > 1000:
            raise FollowupStructuredContactError(
                "CONTACT_NOTE_TOO_LONG",
                "توضیح تماس باید کوتاه‌تر از ۱۰۰۰ نویسه باشد.",
            )
        if outcome == "OTHER" and not normalized_note:
            raise FollowupStructuredContactError(
                "CONTACT_NOTE_REQUIRED",
                "برای نتیجهٔ «سایر» یک توضیح کوتاه ثبت کنید.",
            )

        current_time = _as_local_naive(now or iran_now()) or datetime.now()
        callback_input = str(callback_at or "").strip() or None
        requested_callback = _as_local_naive(callback_at)
        callback_allowed = outcome in RETRY_OUTCOMES or outcome == "CALLBACK_REQUESTED"
        if requested_callback and not callback_allowed:
            raise FollowupStructuredContactError(
                "CALLBACK_NOT_ALLOWED",
                "برای این نتیجه، زمان تماس مجدد نباید ثبت شود.",
            )
        if outcome == "CALLBACK_REQUESTED" and requested_callback is None:
            raise FollowupStructuredContactError(
                "CALLBACK_REQUIRED",
                "زمان تماس مجدد را مشخص کنید.",
            )
        if requested_callback and requested_callback <= current_time:
            raise FollowupStructuredContactError(
                "CALLBACK_NOT_FUTURE",
                "زمان تماس مجدد باید در آینده باشد.",
            )

        task_id = self._task_id(episode_id)
        if task_id is None:
            raise FollowupStructuredContactError(
                "CONTACT_TASK_UNAVAILABLE",
                "برای این مسیر تسک قابل‌تماس پیدا نشد.",
            )
        request_hash = self._request_hash(
            episode_id=episode_id,
            task_id=task_id,
            outcome=outcome,
            callback_input=callback_input,
            note=normalized_note,
        )
        record_event_key = f"fo5-contact-recorded:{key}"
        replay = self._existing_replay(
            episode_id=episode_id,
            event_key=record_event_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return replay

        expected = _normalize_expected(expected_event_id)
        actor_username = str(actor["username"])
        actor_user_id = int(actor["id"])
        contact_source_key = f"fo5-contact-source:{key}"
        # Storage is ensured only on the POST path. GET list/detail stay read-only.
        episode_repo = FollowupEpisodeRepository(self.db)
        contact_repo = FollowupOperationsRepository(self.db)

        try:
            self.db.execute("BEGIN IMMEDIATE")
            task_id = self._require_actor(episode_id=episode_id, actor=actor)
            current_head = episode_repo.current_event(episode_id)
            current_head_id = int(current_head["id"]) if current_head else 0
            if current_head_id != expected:
                raise FollowupStructuredContactError(
                    "STALE_CONTACT_FORM",
                    "مسیر از زمان بازشدن صفحه تغییر کرده است؛ صفحه را تازه کنید.",
                )

            prior_contact_count, prior_failed_attempts = self._contact_counts(task_id)
            failed_attempt_count = (
                prior_failed_attempts + 1
                if outcome in RETRY_OUTCOMES
                else 0
            )
            next_action = "CONTINUE_CURRENT_PATH"
            route_role: str | None = None
            escalation_reason: str | None = None

            if outcome in RETRY_OUTCOMES:
                if failed_attempt_count >= RETRY_THRESHOLD:
                    # Do not persist a callback on the threshold attempt. The
                    # authoritative append-only row must match escalation state.
                    requested_callback = None
                    next_action = "MANAGER_REVIEW_UNREACHABLE"
                    route_role = "MANAGER"
                    escalation_reason = "UNREACHABLE_THRESHOLD"
                else:
                    if outcome == "NO_ANSWER" and requested_callback is None:
                        requested_callback = current_time + timedelta(days=1)
                    elif outcome == "BUSY" and requested_callback is None:
                        requested_callback = current_time + timedelta(hours=2)
                    next_action = "CALLBACK_AT_TIME"
            elif outcome == "CALLBACK_REQUESTED":
                next_action = "CALLBACK_AT_TIME"
            elif outcome == "PHONE_INVALID":
                next_action = "FIX_CONTACT_DATA"
                route_role = "RECEPTION"
            elif outcome == "APPOINTMENT_BOOKED":
                next_action = "WAIT_FOR_APPOINTMENT"
            elif outcome == "DECLINED":
                next_action = "MANAGER_REVIEW_DECLINED"
                route_role = "MANAGER"
            elif outcome == "ESCALATED_TO_PHYSICIAN":
                next_action = "PHYSICIAN_REVIEW"
                route_role = "PHYSICIAN"
                escalation_reason = "CONTACT_ESCALATED_TO_PHYSICIAN"
            elif outcome == "OTHER":
                next_action = "MANAGER_REVIEW_OTHER"
                route_role = "MANAGER"

            callback_text = _text(requested_callback)
            contact = contact_repo.create_contact(
                task_id=task_id,
                channel="PHONE",
                outcome=LEGACY_OUTCOME_MAP[outcome],
                actor_username=actor_username,
                actor_user_id=actor_user_id,
                occurred_at=current_time,
                note=normalized_note,
                next_contact_at=requested_callback,
                idempotency_key=contact_source_key,
                journey_id=None,
                commit=False,
            )
            episode_repo.link_source_once(
                episode_id=episode_id,
                patient_link_id=int(contact["patient_link_id"]),
                source_type="CONTACT_EVENT",
                source_id=str(contact["id"]),
                source_revision=str(contact["content_hash"]),
                relation_type="CONTACT",
                actor_username=actor_username,
                linked_at=current_time,
                recorded_at=current_time,
                commit=False,
            )
            contact_count = prior_contact_count + 1

            already_escalated = bool(
                escalation_reason
                and self._already_escalated(episode_id, escalation_reason)
            )
            should_append_escalation = bool(
                escalation_reason and not already_escalated
            )
            should_route = bool(
                route_role
                and (
                    outcome not in RETRY_OUTCOMES
                    or should_append_escalation
                )
            )
            escalated = bool(escalation_reason)

            contact_payload = {
                "policy_version": POLICY_VERSION,
                "request_hash": request_hash,
                "contact_event_id": int(contact["id"]),
                "task_id": int(task_id),
                "structured_outcome": outcome,
                "legacy_outcome": str(contact["outcome"]),
                "channel": "PHONE",
                "next_action_code": next_action,
                "callback_at": callback_text,
                "contact_count": contact_count,
                "failed_attempt_count": failed_attempt_count,
                "note_present": bool(normalized_note),
                "escalated": escalated,
            }
            episode_repo.append_event_once(
                episode_id=episode_id,
                event_type="CONTACT_RECORDED",
                actor_username=actor_username,
                actor_user_id=actor_user_id,
                idempotency_key=record_event_key,
                payload=contact_payload,
                effective_at=current_time,
                recorded_at=current_time,
                commit=False,
            )

            if callback_text:
                episode_repo.append_event_once(
                    episode_id=episode_id,
                    event_type="WAITING_STARTED",
                    actor_username=actor_username,
                    actor_user_id=actor_user_id,
                    idempotency_key=f"fo5-contact-wait:{key}",
                    payload={
                        "reason_code": "CONTACT_CALLBACK",
                        "callback_at": callback_text,
                        "next_action_code": next_action,
                        "contact_event_id": int(contact["id"]),
                    },
                    effective_at=current_time,
                    recorded_at=current_time,
                    commit=False,
                )

            if should_append_escalation:
                episode_repo.append_event_once(
                    episode_id=episode_id,
                    event_type="ESCALATED",
                    actor_username=actor_username,
                    actor_user_id=actor_user_id,
                    idempotency_key=(
                        f"fo5-contact-escalate:{episode_id}:{escalation_reason}"
                    ),
                    payload={
                        "reason_code": escalation_reason,
                        "contact_event_id": int(contact["id"]),
                        "failed_attempt_count": failed_attempt_count,
                        "target_role": route_role,
                    },
                    effective_at=current_time,
                    recorded_at=current_time,
                    commit=False,
                )

            if should_route:
                current_ownership = self.ownership.state(episode_id)
                route_reason = escalation_reason or {
                    "PHONE_INVALID": "CONTACT_PHONE_INVALID",
                    "DECLINED": "CONTACT_DECLINED",
                    "OTHER": "CONTACT_OTHER_REVIEW",
                }.get(outcome, "CONTACT_POLICY_ROUTE")
                episode_repo.append_event_once(
                    episode_id=episode_id,
                    event_type="ROUTED",
                    actor_username=actor_username,
                    actor_user_id=actor_user_id,
                    idempotency_key=f"fo5-contact-route:{key}",
                    payload={
                        "action": "ROUTE",
                        "owner_role": route_role,
                        "owner_user_id": None,
                        "previous_owner_role": current_ownership.owner_role,
                        "previous_owner_user_id": current_ownership.owner_user_id,
                        "reason_code": route_reason,
                    },
                    effective_at=current_time,
                    recorded_at=current_time,
                    commit=False,
                )

            self.db.commit()
        except FollowupStructuredContactError:
            self.db.rollback()
            raise
        except FollowupContactConflict as exc:
            self.db.rollback()
            raise FollowupStructuredContactError(
                "CONTACT_SOURCE_CONFLICT",
                "ثبت تکراری تماس با اطلاعات متفاوت ممکن نیست.",
            ) from exc
        except FollowupEpisodeConflict as exc:
            self.db.rollback()
            raise FollowupStructuredContactError(
                "CONTACT_EPISODE_CONFLICT",
                "اتصال تماس به این مسیر با ثبت قبلی سازگار نیست.",
            ) from exc
        except LookupError as exc:
            self.db.rollback()
            raise FollowupStructuredContactError(
                "CONTACT_SOURCE_UNAVAILABLE",
                "منبع لازم برای ثبت تماس در دسترس نیست.",
            ) from exc
        except (sqlite3.Error, ValueError) as exc:
            self.db.rollback()
            raise FollowupStructuredContactError(
                "CONTACT_WRITE_FAILED",
                "ثبت تماس انجام نشد؛ صفحه را تازه کنید و دوباره تلاش کنید.",
            ) from exc
        except Exception:
            self.db.rollback()
            raise

        return self.summary(episode_id)


__all__ = [
    "FollowupStructuredContactError",
    "FollowupStructuredContactService",
    "NEXT_ACTION_LABELS",
    "OUTCOME_LABELS",
    "POLICY_VERSION",
    "RETRY_THRESHOLD",
    "SUPPORTED_OUTCOMES",
]
