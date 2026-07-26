"""Validated, append-only contact-attempt recording for every follow-up task."""
from __future__ import annotations

from datetime import datetime

from src.adapters.sqlite.followup_operations_repo import (
    FollowupContactConflict,
    FollowupOperationsRepository,
)
from src.adapters.sqlite.followup_operations_schema import (
    CONTACT_CHANNELS,
    CONTACT_OUTCOMES,
)


CHANNEL_LABELS = {
    "PHONE": "تماس تلفنی",
    "SMS": "پیامک",
    "IN_PERSON": "حضوری",
    "SYSTEM": "رویداد سامانه",
    "OTHER": "سایر",
}
OUTCOME_LABELS = {
    "REACHED": "پاسخ داد",
    "NO_ANSWER": "پاسخ نداد",
    "BUSY": "مشغول بود",
    "WRONG_NUMBER": "شماره نادرست",
    "CALLBACK_REQUESTED": "درخواست تماس مجدد",
    "DECLINED": "تمایل نداشت",
    "BOOKED": "نوبت رزرو شد",
    "MESSAGE_SENT": "پیام ارسال شد",
    "MESSAGE_DELIVERED": "پیام تحویل شد",
    "OTHER": "سایر",
}


class FollowupContactValidationError(ValueError):
    pass


class FollowupContactService:
    def __init__(self, repository: FollowupOperationsRepository | None = None):
        self.repository = repository or FollowupOperationsRepository()

    def record(
        self,
        *,
        task_id: int,
        channel: str,
        outcome: str,
        actor_username: str,
        idempotency_key: str,
        actor_user_id: int | None = None,
        occurred_at: datetime | str | None = None,
        note: str | None = None,
        next_contact_at: datetime | str | None = None,
        journey_id: str | None = None,
    ) -> dict:
        normalized_channel = str(channel or "").strip().upper()
        normalized_outcome = str(outcome or "").strip().upper()
        if normalized_channel not in CONTACT_CHANNELS:
            raise FollowupContactValidationError("کانال تماس نامعتبر است")
        if normalized_outcome not in CONTACT_OUTCOMES:
            raise FollowupContactValidationError("نتیجهٔ تماس نامعتبر است")
        actor = str(actor_username or "").strip()
        if not actor:
            raise FollowupContactValidationError("ثبت‌کنندهٔ تماس الزامی است")
        if normalized_outcome == "CALLBACK_REQUESTED" and not next_contact_at:
            raise FollowupContactValidationError(
                "برای درخواست تماس مجدد، زمان تماس بعدی الزامی است"
            )
        if normalized_outcome in {"WRONG_NUMBER", "DECLINED"} and not note:
            raise FollowupContactValidationError(
                "برای این نتیجه، توضیح کوتاه الزامی است"
            )
        return self.repository.create_contact(
            task_id=int(task_id),
            channel=normalized_channel,
            outcome=normalized_outcome,
            actor_username=actor,
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
            note=note,
            next_contact_at=next_contact_at,
            journey_id=journey_id,
        )


__all__ = [
    "CHANNEL_LABELS",
    "OUTCOME_LABELS",
    "FollowupContactConflict",
    "FollowupContactService",
    "FollowupContactValidationError",
]
