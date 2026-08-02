"""Versioned, deterministic FO-2 shadow next-action policy.

The policy describes operational state only. It never mutates a source, accepts a
clinical recommendation, completes a task, sends SMS or books an appointment.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

POLICY_VERSION = "FOUX-NEXT-ACTION-V1"
_IRAN_TZ = timezone(timedelta(hours=3, minutes=30))
_TERMINAL_TASK = frozenset({"DONE", "DISMISSED", "COMPLETED", "NOT_DONE", "ENTERED_IN_ERROR"})
_TERMINAL_COMMITMENT = frozenset({"COMPLETED", "CANCELLED", "ENTERED_IN_ERROR"})
_SMS_DELIVERED = frozenset({"DELIVERED"})
_SMS_PENDING = frozenset(
    {
        "PENDING",
        "PENDINGAPPROVAL",
        "WAITINGFORSEND",
        "SENDING",
        "SENDTOOPERATOR",
        "SENT",
        "SUBMISSIONUNKNOWN",
        "UNKNOWN",
    }
)
_SMS_FAILED = frozenset({"FAILED", "REJECTED", "UNDELIVERED", "EXPIRED"})


def _dt(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_IRAN_TZ).replace(tzinfo=None)
    return parsed


def _text(value: datetime | None) -> str | None:
    return value.isoformat(sep=" ", timespec="seconds") if value else None


def _states(snapshot: dict, source_type: str) -> list[dict]:
    return [
        state
        for state in snapshot.get("sources") or []
        if state.get("source_type") == source_type
    ]


def _latest(states: list[dict]) -> dict | None:
    if not states:
        return None
    return max(states, key=lambda row: (row.get("event_at") or "", row.get("source_id") or ""))


def _first_time(values: list[str | None]) -> datetime | None:
    parsed = [_dt(value) for value in values if value]
    return min((value for value in parsed if value is not None), default=None)


def _reason(episode: dict) -> tuple[str, str, str]:
    semantic = str(episode.get("semantic_key") or "")
    episode_type = str(episode.get("episode_type") or "")
    if semantic.startswith("engagement:"):
        code = semantic.split(":", 1)[1].upper() or "ENGAGEMENT"
        labels = {
            "APPOINTMENT_REMINDER": "یادآوری نوبت",
            "REFILL_DUE": "پیگیری تمدید دارو",
            "LAPSED": "پیگیری عدم مراجعه",
            "VISIT_INVITE": "دعوت به مراجعه",
        }
        return code, labels.get(code, "پیگیری ارتباط با بیمار"), "رویداد پیگیری اداری شناسایی شده است."
    if episode_type == "CLINICAL_TASK":
        return "CLINICAL_TASK", "پیگیری بالینی", "تسک از مسیر حاکم Clinical Engine ایجاد شده است."
    if episode_type == "ENCOUNTER_COMMITMENT":
        return "ENCOUNTER_COMMITMENT", "تعهد طرح مراقبت", "تعهد ثبت‌شده در Encounter نیازمند دنبال‌کردن است."
    return "ADMIN_FOLLOWUP", "پیگیری اداری", "یک تسک اداری باز برای بیمار وجود دارد."


def _role(snapshot: dict, *, blocked: bool = False) -> str:
    if blocked:
        return "MANAGER"
    episode = snapshot["episode"]
    episode_type = str(episode.get("episode_type") or "")
    semantic = str(episode.get("semantic_key") or "").lower()
    contact = _latest(_states(snapshot, "CONTACT_EVENT"))
    if contact and contact.get("status") == "WRONG_NUMBER":
        return "RECEPTION"
    if episode_type in {"ADMIN_FOLLOWUP", "ENGAGEMENT"}:
        return "RECEPTION"
    if episode_type == "ENCOUNTER_COMMITMENT":
        commitment = _latest(_states(snapshot, "ENCOUNTER_COMMITMENT")) or {}
        kind = str((commitment.get("details") or {}).get("commitment_type") or "").upper()
        if kind in {"MEDICATION_REVIEW", "REFERRAL_CHECK"}:
            return "PHYSICIAN"
        return "NURSING"
    if episode_type == "CLINICAL_TASK":
        if any(token in semantic for token in ("medication", "referral", "physician")):
            return "PHYSICIAN"
        return "NURSING"
    return "MANAGER"


@dataclass(frozen=True, slots=True)
class ProjectionDecision:
    reason_code: str
    reason_label: str
    why_created: str
    current_state: str
    state_class: str
    next_action_code: str | None
    next_action_label: str | None
    waiting_reason_code: str | None
    waiting_reason_label: str | None
    blocked_reason_code: str | None
    blocked_reason_label: str | None
    owner_role_proposal: str | None
    action_due_at: str | None
    target_at: str | None
    priority: int
    sla_state: str
    sms_state: str | None
    appointment_state: str | None
    evidence_state: str | None
    state_detail: dict

    def as_dict(self) -> dict:
        return {
            "reason_code": self.reason_code,
            "reason_label": self.reason_label,
            "why_created": self.why_created,
            "current_state": self.current_state,
            "state_class": self.state_class,
            "next_action_code": self.next_action_code,
            "next_action_label": self.next_action_label,
            "waiting_reason_code": self.waiting_reason_code,
            "waiting_reason_label": self.waiting_reason_label,
            "blocked_reason_code": self.blocked_reason_code,
            "blocked_reason_label": self.blocked_reason_label,
            "owner_role_proposal": self.owner_role_proposal,
            "action_due_at": self.action_due_at,
            "target_at": self.target_at,
            "priority": self.priority,
            "sla_state": self.sla_state,
            "sms_state": self.sms_state,
            "appointment_state": self.appointment_state,
            "evidence_state": self.evidence_state,
            "state_detail": self.state_detail,
        }


class FollowupNextActionPolicy:
    version = POLICY_VERSION

    @staticmethod
    def _sla(
        state_class: str,
        action_due_at: datetime | None,
        as_of: datetime,
    ) -> str:
        if state_class == "TERMINAL":
            return "TERMINAL"
        if state_class == "BLOCKED":
            return "BLOCKED"
        if state_class == "WAITING":
            return "WAITING"
        if action_due_at is None:
            return "DUE_UNKNOWN"
        if action_due_at < as_of:
            return "OVERDUE"
        if action_due_at.date() == as_of.date():
            return "DUE_TODAY"
        return "FUTURE"

    def decide(
        self,
        snapshot: dict,
        *,
        as_of_at: str | datetime,
    ) -> ProjectionDecision:
        as_of = _dt(as_of_at)
        if as_of is None:
            raise ValueError("as_of_at is required")
        episode = snapshot["episode"]
        reason_code, reason_label, why_created = _reason(episode)
        sources = snapshot.get("sources") or []
        action_due = _first_time([state.get("action_due_at") for state in sources])
        target = _first_time([state.get("target_at") for state in sources])
        sms = _latest(_states(snapshot, "SMS_MESSAGE"))
        appointment = _latest(_states(snapshot, "APPOINTMENT"))
        outcome = _latest(_states(snapshot, "CLINICAL_OUTCOME"))
        contact = _latest(_states(snapshot, "CONTACT_EVENT"))
        approval = _latest(_states(snapshot, "ENGAGEMENT_APPROVAL"))
        clinical = _latest(_states(snapshot, "CLINICAL_TASK"))
        commitment = _latest(_states(snapshot, "ENCOUNTER_COMMITMENT"))
        admin = _latest(_states(snapshot, "ADMIN_TASK"))
        sms_state = str(sms.get("status")) if sms else None
        appointment_state = str(appointment.get("status")) if appointment else None
        evidence_state = str(outcome.get("status")) if outcome else None

        def make(
            *,
            current_state: str,
            state_class: str,
            code: str | None = None,
            label: str | None = None,
            detail: dict | None = None,
            due: datetime | None = action_due,
            target_time: datetime | None = target,
            role: str | None = None,
        ) -> ProjectionDecision:
            next_code = code if state_class == "ACTION_REQUIRED" else None
            next_label = label if state_class == "ACTION_REQUIRED" else None
            waiting_code = code if state_class == "WAITING" else None
            waiting_label = label if state_class == "WAITING" else None
            blocked_code = code if state_class == "BLOCKED" else None
            blocked_label = label if state_class == "BLOCKED" else None
            owner = None if state_class == "TERMINAL" else (role or _role(snapshot, blocked=state_class == "BLOCKED"))
            base_priority = {
                "BLOCKED": 900,
                "ACTION_REQUIRED": 600,
                "WAITING": 300,
                "TERMINAL": 0,
            }[state_class]
            sla = self._sla(state_class, due, as_of)
            if sla == "OVERDUE":
                base_priority += 100
            return ProjectionDecision(
                reason_code=reason_code,
                reason_label=reason_label,
                why_created=why_created,
                current_state=current_state,
                state_class=state_class,
                next_action_code=next_code,
                next_action_label=next_label,
                waiting_reason_code=waiting_code,
                waiting_reason_label=waiting_label,
                blocked_reason_code=blocked_code,
                blocked_reason_label=blocked_label,
                owner_role_proposal=owner,
                action_due_at=_text(due),
                target_at=_text(target_time),
                priority=min(base_priority, 1000),
                sla_state=sla,
                sms_state=sms_state,
                appointment_state=appointment_state,
                evidence_state=evidence_state,
                state_detail=detail or {},
            )

        errors = list(snapshot.get("errors") or [])
        if not sources:
            errors.append("EPISODE_HAS_NO_SOURCE_LINKS")
        if errors:
            return make(
                current_state="SOURCE_STATE_BLOCKED",
                state_class="BLOCKED",
                code="SOURCE_STATE_UNAVAILABLE",
                label="منبع پیگیری ناقص یا ناسازگار است؛ مدیر بررسی کند.",
                detail={"error_codes": sorted(set(errors))},
                role="MANAGER",
            )

        if contact and contact.get("status") == "WRONG_NUMBER":
            return make(
                current_state="CONTACT_DATA_INVALID",
                state_class="BLOCKED",
                code="CONTACT_DATA_INVALID",
                label="شماره تماس نیازمند اصلاح است.",
                detail={"source": "CONTACT_EVENT"},
                role="RECEPTION",
            )

        if contact and contact.get("status") == "CALLBACK_REQUESTED":
            callback_at = _dt(contact.get("action_due_at"))
            if callback_at is None:
                return make(
                    current_state="CALLBACK_TIME_MISSING",
                    state_class="BLOCKED",
                    code="CALLBACK_TIME_MISSING",
                    label="زمان تماس مجدد ثبت نشده است.",
                    detail={"source": "CONTACT_EVENT"},
                    role="RECEPTION",
                )
            if callback_at > as_of:
                return make(
                    current_state="WAITING_CALLBACK",
                    state_class="WAITING",
                    code="WAITING_FOR_CALLBACK_DATE",
                    label="تا زمان تماس مجدد منتظر بمانید.",
                    due=callback_at,
                    detail={"source": "CONTACT_EVENT"},
                )
            return make(
                current_state="CALLBACK_DUE",
                state_class="ACTION_REQUIRED",
                code="CALL_PATIENT",
                label="اکنون با بیمار تماس بگیرید.",
                due=callback_at,
                detail={"source": "CONTACT_EVENT"},
            )

        if approval and approval.get("status") in {"PENDING", "SUBMITTING"}:
            return make(
                current_state="SMS_REVIEW_REQUIRED",
                state_class="ACTION_REQUIRED",
                code="REVIEW_SMS",
                label="متن پیام را بازبینی و دربارهٔ ارسال تصمیم بگیرید.",
                detail={"approval_status": approval.get("status")},
                role="RECEPTION",
            )

        if sms:
            retryable = bool((sms.get("details") or {}).get("retryable"))
            if sms.get("status") in _SMS_FAILED and not retryable:
                return make(
                    current_state="SMS_PERMANENT_FAILURE",
                    state_class="ACTION_REQUIRED",
                    code="CALL_PATIENT",
                    label="پیام نرسیده است؛ با بیمار تماس بگیرید.",
                    detail={"sms_status": sms.get("status")},
                    role="RECEPTION",
                )
            if sms.get("status") in _SMS_PENDING or retryable:
                return make(
                    current_state="SMS_STATUS_PENDING",
                    state_class="WAITING",
                    code="WAITING_FOR_SMS_STATUS",
                    label="وضعیت نهایی پیام هنوز مشخص نشده است.",
                    detail={"sms_status": sms.get("status"), "retryable": retryable},
                )

        if appointment:
            status = str(appointment.get("status") or "").upper()
            scheduled_at = _dt(appointment.get("target_at"))
            if status == "NO_SHOW":
                return make(
                    current_state="APPOINTMENT_NO_SHOW",
                    state_class="ACTION_REQUIRED",
                    code="FOLLOW_UP_NO_SHOW",
                    label="بیمار مراجعه نکرده است؛ پیگیری کنید.",
                    due=as_of,
                    target_time=scheduled_at,
                    role="RECEPTION",
                )
            if status == "CANCELLED":
                return make(
                    current_state="APPOINTMENT_CANCELLED",
                    state_class="ACTION_REQUIRED",
                    code="REBOOK_APPOINTMENT",
                    label="نوبت لغو شده است؛ زمان جدید هماهنگ کنید.",
                    due=as_of,
                    target_time=scheduled_at,
                    role="RECEPTION",
                )

        if clinical and str(clinical.get("status")) in _TERMINAL_TASK:
            return make(
                current_state=f"CLINICAL_{clinical.get('status')}",
                state_class="TERMINAL",
                detail={"source": "CLINICAL_TASK"},
            )
        if commitment and str(commitment.get("status")) in _TERMINAL_COMMITMENT:
            return make(
                current_state=f"COMMITMENT_{commitment.get('status')}",
                state_class="TERMINAL",
                detail={"source": "ENCOUNTER_COMMITMENT"},
            )
        if admin and str(admin.get("status")) in _TERMINAL_TASK:
            return make(
                current_state=f"ADMIN_{admin.get('status')}",
                state_class="TERMINAL",
                detail={"source": "ADMIN_TASK"},
            )
        if not admin and not clinical and not commitment:
            if approval and approval.get("status") in {"REJECTED", "CANCELLED"}:
                return make(
                    current_state="ENGAGEMENT_CANCELLED",
                    state_class="TERMINAL",
                    detail={"source": "ENGAGEMENT_APPROVAL"},
                )

        if clinical and outcome:
            return make(
                current_state="CLINICAL_EVIDENCE_AVAILABLE",
                state_class="ACTION_REQUIRED",
                code="REVIEW_CLINICAL_EVIDENCE",
                label="شاهد ثبت شده است؛ نتیجه را بررسی و از مسیر بالینی تصمیم بگیرید.",
                detail={"verification": outcome.get("status")},
                role="NURSING",
            )

        if appointment and str(appointment.get("status") or "").upper() == "DONE":
            code = "RECORD_CLINICAL_EVIDENCE" if clinical else "REVIEW_VISIT_OUTCOME"
            label = (
                "مراجعه انجام شده است؛ شاهد بالینی معتبر ثبت کنید."
                if clinical
                else "مراجعه انجام شده است؛ نتیجهٔ پیگیری اداری را ثبت کنید."
            )
            return make(
                current_state="APPOINTMENT_COMPLETED_REVIEW_REQUIRED",
                state_class="ACTION_REQUIRED",
                code=code,
                label=label,
                due=as_of,
                target_time=_dt(appointment.get("target_at")),
            )

        if appointment and str(appointment.get("status") or "").upper() == "SCHEDULED":
            scheduled_at = _dt(appointment.get("target_at"))
            if scheduled_at and scheduled_at >= as_of:
                return make(
                    current_state="WAITING_APPOINTMENT",
                    state_class="WAITING",
                    code="WAITING_FOR_APPOINTMENT",
                    label="نوبت ثبت شده است؛ تا زمان مراجعه منتظر بمانید.",
                    due=scheduled_at,
                    target_time=scheduled_at,
                )
            return make(
                current_state="APPOINTMENT_STATUS_REVIEW_DUE",
                state_class="ACTION_REQUIRED",
                code="CONFIRM_APPOINTMENT_OUTCOME",
                label="زمان نوبت گذشته است؛ وضعیت مراجعه را مشخص کنید.",
                due=as_of,
                target_time=scheduled_at,
                role="RECEPTION",
            )

        if clinical:
            return make(
                current_state=f"CLINICAL_{clinical.get('status')}",
                state_class="ACTION_REQUIRED",
                code="CONTINUE_CLINICAL_FOLLOWUP",
                label="پیگیری بالینی را طبق قرارداد تسک ادامه دهید.",
                detail={"clinical_status": clinical.get("status")},
                role="NURSING",
            )

        if commitment:
            kind = str((commitment.get("details") or {}).get("commitment_type") or "")
            return make(
                current_state=f"COMMITMENT_{commitment.get('status')}",
                state_class="ACTION_REQUIRED",
                code="CONTINUE_PLAN_COMMITMENT",
                label="تعهد ثبت‌شده در طرح مراقبت را دنبال کنید.",
                detail={"commitment_type": kind},
                role=_role(snapshot),
            )

        if sms and sms.get("status") in _SMS_DELIVERED and action_due and action_due > as_of:
            return make(
                current_state="SMS_DELIVERED_WAITING_TARGET",
                state_class="WAITING",
                code="WAITING_FOR_PATIENT_OR_TARGET",
                label="پیام تحویل شده است؛ تا موعد اقدام بعدی منتظر بمانید.",
                due=action_due,
            )

        if admin:
            if action_due and action_due > as_of:
                return make(
                    current_state="ADMIN_WAITING_DUE_DATE",
                    state_class="WAITING",
                    code="WAITING_UNTIL_ACTION_DUE",
                    label="موعد اقدام هنوز نرسیده است.",
                    due=action_due,
                    role="RECEPTION",
                )
            return make(
                current_state="ADMIN_CONTACT_REQUIRED",
                state_class="ACTION_REQUIRED",
                code="CONTACT_PATIENT",
                label="با بیمار تماس بگیرید و نتیجه را ثبت کنید.",
                due=action_due or as_of,
                role="RECEPTION",
            )

        if sms and sms.get("status") in _SMS_DELIVERED:
            return make(
                current_state="SMS_DELIVERED_NO_OPERATIONAL_TASK",
                state_class="WAITING",
                code="WAITING_FOR_PATIENT_RESPONSE",
                label="پیام تحویل شده است؛ منتظر پاسخ یا موعد بعدی بمانید.",
            )

        return make(
            current_state="POLICY_STATE_UNRESOLVED",
            state_class="BLOCKED",
            code="POLICY_STATE_UNRESOLVED",
            label="وضعیت پیگیری با policy فعلی قابل تعیین نیست؛ مدیر بررسی کند.",
            detail={"source_types": sorted({row.get('source_type') for row in sources})},
            role="MANAGER",
        )


__all__ = [
    "POLICY_VERSION",
    "FollowupNextActionPolicy",
    "ProjectionDecision",
]
