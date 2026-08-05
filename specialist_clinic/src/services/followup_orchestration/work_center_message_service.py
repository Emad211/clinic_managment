"""Atomic, policy-aware message queueing for one Work Center episode.

Only the configured ``visit_invite`` CARE template is supported here. This service never
accepts free text and never sends directly; it creates an approval candidate and links it
to the existing Episode in one transaction.
"""
from __future__ import annotations

from datetime import datetime
import sqlite3

from src.adapters.sqlite.engagement_repo import EngagementRepository
from src.adapters.sqlite.followup_episode_repo import FollowupEpisodeRepository
from src.adapters.sqlite.followup_projection_repo import FollowupProjectionRepository
from src.adapters.sqlite.sms_governance_repo import SmsGovernanceRepository
from src.common.utils import iran_now, today_str
from src.security.permissions import Permission
from src.services.followup_orchestration.identity import canonical_hash
from src.services.followup_orchestration.projection_service import FollowupProjectionService
from src.services.sms.campaign_service import personalize
from src.services.sms.compliance import sanitize


class WorkCenterMessageError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class WorkCenterMessageService:
    EVENT_KEY = "visit_invite"

    def __init__(self, db: sqlite3.Connection, *, clock=None):
        self.db = db
        self.db.row_factory = sqlite3.Row
        self.clock = clock or iran_now
        self.repo = EngagementRepository()
        self.governance = SmsGovernanceRepository(db)

    def _now_text(self) -> str:
        value = self.clock()
        if value.tzinfo is not None:
            value = value.replace(tzinfo=None)
        return value.replace(microsecond=0).isoformat(sep=" ", timespec="seconds")

    def _task(self, episode_id: str) -> dict:
        row = self.db.execute(
            """SELECT task.id, task.patient_link_id
               FROM followup_episode_links link
               JOIN followup_tasks task
                 ON task.id=CAST(link.source_id AS INTEGER)
               WHERE link.episode_id=?
                 AND link.source_type IN ('ADMIN_TASK','CLINICAL_TASK')
               ORDER BY CASE link.relation_type WHEN 'PRIMARY' THEN 0 ELSE 1 END,
                        link.id
               LIMIT 1""",
            (str(episode_id),),
        ).fetchone()
        if not row:
            raise WorkCenterMessageError(
                "WORK_TASK_UNAVAILABLE",
                "این مسیر کار برای پیام به بیمار قابل استفاده نیست.",
            )
        return dict(row)

    def _candidate(self, patient_link_id: int) -> dict:
        patient = self.db.execute(
            """SELECT id, full_name, phone_number
               FROM patient_links WHERE id=? AND is_active=1""",
            (int(patient_link_id),),
        ).fetchone()
        if not patient or not str(patient["phone_number"] or "").strip():
            raise WorkCenterMessageError(
                "MESSAGE_PHONE_REQUIRED",
                "شمارهٔ معتبر برای بیمار ثبت نشده است.",
            )

        consent = self.governance.ensure_patient_defaults(
            int(patient_link_id),
            commit=False,
        ).get("CARE")
        if not consent or str(consent.get("decision") or "") != "GRANTED":
            raise WorkCenterMessageError(
                "MESSAGE_CONSENT_REQUIRED",
                "رضایت CARE بیمار اجازهٔ افزودن پیام را نمی‌دهد.",
            )

        config = self.repo.get_event(self.EVENT_KEY)
        if not config or not bool(config.get("is_active")):
            raise WorkCenterMessageError(
                "MESSAGE_EVENT_DISABLED",
                "دعوت ویزیت در تنظیمات پیام‌ها فعال نیست.",
            )
        if str(config.get("channel") or "").strip().lower() not in {"sms", "both"}:
            raise WorkCenterMessageError(
                "MESSAGE_CHANNEL_DISABLED",
                "کانال پیامک دعوت ویزیت در تنظیمات فعال نیست.",
            )
        template = str(config.get("sms_template") or "").strip()
        if not template:
            raise WorkCenterMessageError(
                "MESSAGE_TEMPLATE_REQUIRED",
                "متن مصوب دعوت ویزیت در تنظیمات ثبت نشده است.",
            )

        period_key = f"invite:{today_str()}"
        if self.repo.already_dispatched(
            int(patient_link_id), self.EVENT_KEY, period_key, "sms"
        ):
            raise WorkCenterMessageError(
                "MESSAGE_ALREADY_SENT",
                "دعوت امروز قبلاً برای بیمار ارسال شده است.",
            )
        if self.repo.in_cooldown(
            int(patient_link_id),
            self.EVENT_KEY,
            int(config.get("cooldown_days") or 0),
        ):
            raise WorkCenterMessageError(
                "MESSAGE_IN_COOLDOWN",
                "دعوت بیمار هنوز در بازهٔ عدم‌تکرار قرار دارد.",
            )
        body = sanitize(personalize(template, name=patient["full_name"]))
        if not body.strip():
            raise WorkCenterMessageError(
                "MESSAGE_TEMPLATE_EMPTY",
                "متن مصوب دعوت پس از آماده‌سازی خالی است.",
            )
        return {
            "patient_link_id": int(patient_link_id),
            "period_key": period_key,
            "message": body,
            "due_date": today_str(),
            "consent_event_id": int(consent["id"]),
        }

    def queue(
        self,
        episode_id: str,
        *,
        actor_username: str,
        actor_user_id: int,
        permissions: frozenset[Permission],
    ) -> dict:
        if Permission.SMS_APPROVAL_REVIEW not in permissions:
            raise WorkCenterMessageError(
                "MESSAGE_APPROVAL_PERMISSION_REQUIRED",
                "مجوز افزودن پیام به صف تأیید ثبت نشده است.",
            )
        task = self._task(episode_id)
        episode_repo = FollowupEpisodeRepository(self.db)

        self.db.execute("BEGIN IMMEDIATE")
        try:
            candidate = self._candidate(int(task["patient_link_id"]))
            existing = self.repo.find_approval(
                patient_link_id=candidate["patient_link_id"],
                event_key=self.EVENT_KEY,
                period_key=candidate["period_key"],
            )
            if existing:
                if str(existing["status"]) not in {"pending", "submitting", "approved"}:
                    raise WorkCenterMessageError(
                        "MESSAGE_ALREADY_DECIDED",
                        "دعوت امروز قبلاً بررسی شده و قابل صف‌کردن دوباره نیست.",
                    )
                approval_id = int(existing["id"])
                duplicate = True
            else:
                approval_id = self.repo.enqueue_approval(
                    candidate["patient_link_id"],
                    self.EVENT_KEY,
                    "sms",
                    candidate["due_date"],
                    candidate["message"],
                    candidate["period_key"],
                    commit=False,
                )
                if approval_id is None:
                    raise WorkCenterMessageError(
                        "MESSAGE_APPROVAL_CONFLICT",
                        "صف پیام هم‌زمان تغییر کرد؛ صفحه را تازه کنید.",
                    )
                duplicate = False

            approval = self.repo.get_approval(approval_id)
            if not approval:
                raise WorkCenterMessageError(
                    "MESSAGE_APPROVAL_UNAVAILABLE",
                    "رکورد صف پیام پس از ثبت قابل بازیابی نیست.",
                )
            timestamp = self._now_text()
            episode_repo.link_source_once(
                episode_id=str(episode_id),
                patient_link_id=candidate["patient_link_id"],
                source_type="ENGAGEMENT_APPROVAL",
                source_id=str(approval_id),
                source_revision=canonical_hash({
                    "id": int(approval["id"]),
                    "patient_link_id": int(approval["patient_link_id"]),
                    "event_key": str(approval["event_key"]),
                    "period_key": str(approval["period_key"]),
                }),
                relation_type="COMMUNICATION",
                actor_username=actor_username,
                linked_at=timestamp,
                recorded_at=timestamp,
                commit=False,
            )
            episode_repo.append_event_once(
                episode_id=str(episode_id),
                event_type="SMS_QUEUED",
                actor_username=actor_username,
                actor_user_id=int(actor_user_id),
                idempotency_key=(
                    f"work-center-sms-queued:{episode_id}:{approval_id}"
                ),
                effective_at=timestamp,
                recorded_at=timestamp,
                payload={
                    "approval_id": int(approval_id),
                    "event_key": self.EVENT_KEY,
                    "consent_event_id": candidate["consent_event_id"],
                },
                commit=False,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        result = {
            "task_id": int(task["id"]),
            "approval_id": int(approval_id),
            "queued": True,
            "duplicate": duplicate,
        }
        try:
            rows = FollowupProjectionService(self.db).build_rows(
                as_of_at=datetime.fromisoformat(self._now_text())
            )
            row = next(
                item for item in rows
                if str(item["episode_id"]) == str(episode_id)
            )
            FollowupProjectionRepository(
                self.db, install_schema=False
            ).upsert_one(row)
        except Exception as exc:
            result["projection_refreshed"] = False
            result["projection_refresh_error"] = type(exc).__name__
        else:
            result["projection_refreshed"] = True
            result["projection_refresh_error"] = None
        return result


__all__ = ["WorkCenterMessageError", "WorkCenterMessageService"]
