"""Deterministic, PHI-minimized Unified Follow-up Timeline.

The Timeline combines Episode events with current source-state snapshots. It
intentionally omits free notes, SMS bodies and clinical values. FO-5 contact
events expose only their structured outcome, callback and operational next action.
"""
from __future__ import annotations

from datetime import datetime
import json
import sqlite3

from src.services.followup_orchestration.source_state import (
    FollowupSourceStateReader,
)
from src.services.followup_orchestration.structured_contact_service import (
    NEXT_ACTION_LABELS,
    OUTCOME_LABELS,
)


EPISODE_EVENT_LABELS = {
    "EPISODE_OPENED": "مسیر پیگیری ایجاد شد",
    "SOURCE_LINKED": "یک منبع معتبر به مسیر متصل شد",
    "ROUTED": "صف مسئول مسیر تغییر کرد",
    "CLAIMED": "مسیر برای رسیدگی دریافت شد",
    "ASSIGNED": "مسئول مسیر تغییر کرد",
    "ACTION_DUE_CHANGED": "زمان اقدام تغییر کرد",
    "TARGET_CHANGED": "زمان هدف تغییر کرد",
    "WAITING_STARTED": "مسیر وارد انتظار شد",
    "WAITING_ENDED": "انتظار مسیر پایان یافت",
    "CONTACT_RECORDED": "نتیجهٔ تماس ثبت شد",
    "SMS_QUEUED": "پیام در صف قرار گرفت",
    "SMS_SENT": "پیام ارسال شد",
    "SMS_DELIVERED": "تحویل پیام تأیید شد",
    "SMS_FAILED": "ارسال یا تحویل پیام ناموفق بود",
    "APPOINTMENT_BOOKED": "نوبت ثبت شد",
    "APPOINTMENT_CANCELLED": "نوبت لغو شد",
    "APPOINTMENT_NO_SHOW": "عدم مراجعه ثبت شد",
    "EVIDENCE_SUGGESTED": "شاهدی برای بازبینی پیشنهاد شد",
    "ESCALATED": "مسیر برای بررسی بالاتر علامت‌گذاری شد",
    "ADMINISTRATIVE_GOAL_MET": "هدف اداری مسیر محقق شد",
    "EPISODE_CLOSED": "مسیر پیگیری بسته شد",
    "ENTERED_IN_ERROR": "رویداد به‌عنوان ثبت اشتباه مشخص شد",
}
SOURCE_LABELS = {
    "ADMIN_TASK": "پیگیری اداری",
    "CLINICAL_TASK": "پیگیری بالینی",
    "ENCOUNTER_COMMITMENT": "تعهد طرح ویزیت",
    "ENGAGEMENT_APPROVAL": "صف تأیید پیام",
    "SMS_MESSAGE": "پیامک",
    "APPOINTMENT": "نوبت",
    "CONTACT_EVENT": "تماس",
    "CLINICAL_OUTCOME": "شاهد نتیجهٔ بالینی",
}
STATUS_LABELS = {
    "OPEN": "باز",
    "ASSIGNED": "واگذارشده",
    "SCHEDULED": "زمان‌بندی‌شده",
    "IN_PROGRESS": "در حال انجام",
    "DEFERRED": "به‌تعویق‌افتاده",
    "COMPLETED": "تکمیل‌شده",
    "DONE": "انجام‌شده",
    "DISMISSED": "ردشده",
    "CANCELLED": "لغوشده",
    "DELIVERED": "تحویل‌شده",
    "SENT": "ارسال‌شده",
    "PENDING": "در انتظار",
    "APPROVED": "تأییدشده",
    "REJECTED": "ردشده",
    "FAILED": "ناموفق",
    "UNAVAILABLE": "منبع در دسترس نیست",
    "REACHED": "تماس موفق",
    "NO_ANSWER": "پاسخ نداد",
    "BUSY": "خط مشغول بود",
    "WRONG_NUMBER": "شماره نامعتبر",
    "CALLBACK_REQUESTED": "درخواست تماس مجدد",
    "DECLINED": "عدم پذیرش ادامهٔ پیگیری",
    "BOOKED": "نوبت اعلام‌شده",
    "OTHER": "نتیجهٔ دیگر",
}


def _payload(value: object) -> dict:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _time_key(value: object) -> tuple[int, str]:
    rendered = str(value or "").strip()
    if not rendered:
        return (1, "9999-12-31 23:59:59")
    try:
        parsed = datetime.fromisoformat(rendered.replace("Z", "+00:00"))
        return (0, parsed.isoformat(timespec="seconds"))
    except ValueError:
        return (0, rendered)


def _episode_presentation(event_type: str, data: dict) -> tuple[str, str]:
    title = EPISODE_EVENT_LABELS.get(event_type, "رویداد مسیر پیگیری")
    subtitle = "تاریخچهٔ افزایشی مسیر"

    if event_type == "CONTACT_RECORDED":
        outcome = str(data.get("structured_outcome") or "").upper()
        next_action = str(data.get("next_action_code") or "").upper()
        title = f"نتیجهٔ تماس: {OUTCOME_LABELS.get(outcome, 'ثبت شد')}"
        subtitle = (
            "اقدام بعدی: "
            + NEXT_ACTION_LABELS.get(next_action, "ادامهٔ مسیر فعلی")
        )
        callback_at = str(data.get("callback_at") or "").strip()
        if callback_at:
            subtitle += f" — تماس مجدد: {callback_at}"
    elif event_type == "WAITING_STARTED" and (
        str(data.get("reason_code") or "") == "CONTACT_CALLBACK"
    ):
        title = "تماس مجدد زمان‌بندی شد"
        callback_at = str(data.get("callback_at") or "").strip()
        subtitle = (
            f"زمان تماس مجدد: {callback_at}"
            if callback_at
            else "در انتظار تماس مجدد"
        )
    elif event_type == "ESCALATED":
        reason = str(data.get("reason_code") or "")
        if reason == "UNREACHABLE_THRESHOLD":
            title = "پس از چند تلاش، بیمار در دسترس نبود"
            subtitle = "مورد برای بررسی مدیر عملیات ارجاع شد."
        elif reason == "CONTACT_ESCALATED_TO_PHYSICIAN":
            title = "تماس برای بررسی پزشک ارجاع شد"
            subtitle = "این ارجاع فقط عملیاتی است و تصمیم بالینی ایجاد نمی‌کند."
    elif event_type == "ROUTED":
        reason = str(data.get("reason_code") or "")
        if reason == "CONTACT_PHONE_INVALID":
            title = "مسیر برای اصلاح اطلاعات تماس به پذیرش ارجاع شد"
            subtitle = "شمارهٔ نامعتبر ثبت شد؛ ارسال پیام یا تماس مجدد اجرا نشد."
        elif reason == "UNREACHABLE_THRESHOLD":
            title = "مسیر به صف مدیر عملیات منتقل شد"
            subtitle = "علت: عدم دسترسی پس از تعداد تلاش مجاز"
        elif reason == "CONTACT_ESCALATED_TO_PHYSICIAN":
            title = "مسیر به صف بررسی پزشک منتقل شد"
            subtitle = "بدون تولید تصمیم یا نتیجهٔ بالینی"
    return title, subtitle


class FollowupTimelineService:
    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.db.row_factory = sqlite3.Row

    def _table(self, name: str) -> bool:
        return bool(
            self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            ).fetchone()
        )

    def build(self, episode_id: str) -> dict | None:
        if not self._table("followup_episodes"):
            return None
        episode_row = self.db.execute(
            "SELECT * FROM followup_episodes WHERE episode_id=?",
            (str(episode_id),),
        ).fetchone()
        if not episode_row:
            return None
        episode = dict(episode_row)
        snapshot = FollowupSourceStateReader(self.db).snapshot(episode)
        nodes: list[dict] = []

        if self._table("followup_episode_events"):
            events = self.db.execute(
                """SELECT id, event_type, effective_at, recorded_at,
                          actor_username, content_hash, payload_json
                   FROM followup_episode_events
                   WHERE episode_id=?
                   ORDER BY effective_at, recorded_at, id""",
                (str(episode_id),),
            ).fetchall()
            for event in events:
                event_type = str(event["event_type"])
                data = _payload(event["payload_json"])
                title, subtitle = _episode_presentation(event_type, data)
                audit = {
                    "event_id": int(event["id"]),
                    "event_type": event_type,
                    "actor": str(event["actor_username"]),
                    "content_hash": str(event["content_hash"]),
                }
                # Expose only bounded operational codes. Free note text never
                # leaves the authoritative contact row.
                for key in (
                    "structured_outcome",
                    "next_action_code",
                    "callback_at",
                    "reason_code",
                    "target_role",
                    "contact_event_id",
                    "failed_attempt_count",
                    "note_present",
                ):
                    if key in data:
                        audit[key] = data.get(key)
                nodes.append(
                    {
                        "kind": "EPISODE_EVENT",
                        "occurred_at": str(event["effective_at"]),
                        "recorded_at": str(event["recorded_at"]),
                        "title": title,
                        "subtitle": subtitle,
                        "status_label": None,
                        "source_label": (
                            "تماس"
                            if event_type in {
                                "CONTACT_RECORDED",
                                "WAITING_STARTED",
                            }
                            and (
                                event_type == "CONTACT_RECORDED"
                                or data.get("reason_code") == "CONTACT_CALLBACK"
                            )
                            else "مسیر پیگیری"
                        ),
                        "warning": bool(
                            event_type == "ESCALATED"
                            or (
                                event_type == "ROUTED"
                                and data.get("reason_code")
                                in {
                                    "CONTACT_PHONE_INVALID",
                                    "UNREACHABLE_THRESHOLD",
                                }
                            )
                        ),
                        "audit": audit,
                    }
                )

        for source in snapshot["sources"]:
            source_type = str(source["source_type"])
            status = str(source["status"] or "UNAVAILABLE").upper()
            error_code = source.get("error_code")
            nodes.append(
                {
                    "kind": "SOURCE_STATE",
                    "occurred_at": source.get("event_at"),
                    "recorded_at": source.get("event_at"),
                    "title": (
                        "منبع نیازمند بررسی است"
                        if error_code
                        else "آخرین وضعیت منبع ثبت شد"
                    ),
                    "subtitle": SOURCE_LABELS.get(source_type, "منبع مرتبط"),
                    "status_label": STATUS_LABELS.get(status, "وضعیت ثبت‌شده"),
                    "source_label": SOURCE_LABELS.get(source_type, "منبع مرتبط"),
                    "warning": bool(error_code),
                    "audit": {
                        "source_type": source_type,
                        "source_id": str(source["source_id"]),
                        "relation_type": str(source["relation_type"]),
                        "source_revision": str(source["source_revision"]),
                        "status": status,
                        "error_code": error_code,
                    },
                }
            )

        nodes.sort(
            key=lambda node: (
                _time_key(node.get("occurred_at")),
                0 if node["kind"] == "EPISODE_EVENT" else 1,
                str(node["audit"]),
            )
        )
        return {
            "episode": snapshot["episode"],
            "items": nodes,
            "errors": snapshot["errors"],
            "source_count": snapshot["source_count"],
            "source_fingerprint": snapshot["source_fingerprint"],
            "last_source_event_at": snapshot["last_source_event_at"],
        }


__all__ = [
    "EPISODE_EVENT_LABELS",
    "FollowupTimelineService",
    "SOURCE_LABELS",
    "STATUS_LABELS",
]
