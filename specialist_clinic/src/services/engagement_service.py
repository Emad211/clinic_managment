"""Administrative engagement event collection, approval and dispatch.

Clinical Engine v2 follow-up tasks are projected separately by
``ClinicalV2FollowupService``.  This service deliberately has no import or fallback to a
clinical rule engine: appointment reminders, refill/lapsed worklists, invoice outreach
and approved SMS must continue independently of clinical-engine rollout state.
"""
from __future__ import annotations

import hashlib
import json

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.engagement_repo import EngagementRepository
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.adapters.sqlite.sms_repo import SmsRepository
from src.common.utils import (
    format_jalali_date,
    iran_now,
    today_str,
)
from src.services.sms.campaign_service import personalize, send_single
from src.services.sms.compliance import sanitize


QUIET_START_DEFAULT = "08:00"
QUIET_END_DEFAULT = "21:00"
DAILY_CAP_DEFAULT = 1

REASON_BY_EVENT = {
    "lapsed": "lapsed",
    "uncontrolled": "uncontrolled",
    "appointment_reminder": "visit_due",
    "refill_due": "refill",
}


class EngagementService:
    def __init__(self):
        self.repo = EngagementRepository()
        self.fu = FollowupRepository()
        self.sms = SmsRepository()

    def _quiet_now(self) -> bool:
        start = self.sms.get_setting(
            "engagement_quiet_start",
            QUIET_START_DEFAULT,
        )
        end = self.sms.get_setting(
            "engagement_quiet_end",
            QUIET_END_DEFAULT,
        )
        now = iran_now().strftime("%H:%M")
        return not (start <= now <= end)

    def _daily_cap(self) -> int:
        try:
            return int(
                self.sms.get_setting(
                    "engagement_daily_cap",
                    DAILY_CAP_DEFAULT,
                )
            )
        except (TypeError, ValueError):
            return DAILY_CAP_DEFAULT

    def _provider_ready(self) -> bool:
        if self.sms.provider_configured():
            return True
        try:
            from flask import current_app

            return bool(current_app.config.get("TESTING"))
        except Exception:
            return False

    def collect_due_events(self, patient_link_id: int) -> tuple[list[dict], dict]:
        """Return administrative due events and their channel configuration."""
        db = get_db()
        config = {
            event["event_key"]: event
            for event in self.repo.active_events()
        }
        events: list[dict] = []
        month = iran_now().strftime("%Y-%m")

        if "appointment_reminder" in config:
            lead = int(
                config["appointment_reminder"].get("lead_days") or 0
            )
            rows = db.execute(
                """SELECT id, scheduled_at FROM appointments
                   WHERE patient_link_id=? AND status='scheduled'
                     AND date(scheduled_at) BETWEEN
                         date('now','+3 hours','+30 minutes')
                         AND date(
                             'now','+3 hours','+30 minutes', ?
                         )""",
                (patient_link_id, f"+{lead} days"),
            ).fetchall()
            for row in rows:
                scheduled = row["scheduled_at"] or ""
                day = (
                    format_jalali_date(scheduled)
                    if scheduled
                    else ""
                )
                clock = (
                    scheduled[11:16]
                    if len(scheduled) >= 16
                    else ""
                )
                events.append(
                    {
                        "event_key": "appointment_reminder",
                        "period_key": f"appt:{row['id']}",
                        "detail": f"نوبت {day} ساعت {clock}".strip(),
                        "due_date": scheduled[:10] or None,
                    }
                )

        if "refill_due" in config:
            lead = int(config["refill_due"].get("lead_days") or 0)
            rows = db.execute(
                """SELECT id, drug_name, refill_due_date
                   FROM patient_medications
                   WHERE patient_link_id=? AND is_active=1
                     AND refill_due_date IS NOT NULL
                     AND refill_due_date <= date(
                         'now','+3 hours','+30 minutes', ?
                     )""",
                (patient_link_id, f"+{lead} days"),
            ).fetchall()
            for row in rows:
                events.append(
                    {
                        "event_key": "refill_due",
                        "period_key": (
                            f"refill:{row['id']}:"
                            f"{row['refill_due_date']}"
                        ),
                        "detail": f"داروی {row['drug_name']}",
                    }
                )

        if "lapsed" in config:
            row = db.execute(
                """SELECT NOT EXISTS(
                       SELECT 1 FROM vital_readings vital
                       WHERE vital.patient_link_id=?
                         AND vital.measured_at >= datetime(
                             'now','+3 hours','+30 minutes','-120 days'
                         )
                   ) AS missing""",
                (patient_link_id,),
            ).fetchone()
            if row["missing"]:
                events.append(
                    {
                        "event_key": "lapsed",
                        "period_key": f"lapsed:{month}",
                        "detail": "بیش از ۴ ماه بدون ثبت شاخص",
                    }
                )

        # This legacy descriptive worklist signal remains isolated from Clinical
        # Engine output and never sends treatment advice. It will be retired when
        # parallel clinical indicators are consolidated in the dedicated tranche.
        if "uncontrolled" in config:
            from src.adapters.sqlite.clinical_rules_repo import (
                ClinicalRulesRepository,
            )

            rules = ClinicalRulesRepository()
            hba1c_danger = (
                (rules.get("hba1c") or {}).get("danger") or 8
            )
            systolic_danger = (
                (rules.get("bp_systolic") or {}).get("danger") or 140
            )
            row = db.execute(
                """SELECT 1 FROM patient_links patient
                   WHERE patient.id=? AND (
                       (
                           SELECT vital.value FROM vital_readings vital
                           WHERE vital.patient_link_id=patient.id
                             AND vital.type='hba1c'
                           ORDER BY vital.measured_at DESC LIMIT 1
                       ) >= ?
                       OR (
                           SELECT vital.value FROM vital_readings vital
                           WHERE vital.patient_link_id=patient.id
                             AND vital.type='bp_systolic'
                           ORDER BY vital.measured_at DESC LIMIT 1
                       ) >= ?
                   )""",
                (
                    patient_link_id,
                    hba1c_danger,
                    systolic_danger,
                ),
            ).fetchone()
            if row:
                events.append(
                    {
                        "event_key": "uncontrolled",
                        "period_key": f"unctrl:{month}",
                        "detail": (
                            "آخرین شاخص‌ها خارج از محدودهٔ کنترل"
                        ),
                    }
                )

        return events, config

    def dispatch_patient(
        self,
        patient_link_id: int,
        dry_run: bool = False,
        worklist_only: bool = False,
    ) -> dict:
        db = get_db()
        patient = db.execute(
            """SELECT id, full_name, phone_number, sms_opt_out
               FROM patient_links WHERE id=?""",
            (patient_link_id,),
        ).fetchone()
        result = {
            "sms": 0,
            "worklist": 0,
            "skipped": 0,
            "queued": 0,
        }
        if not patient:
            return result
        events, config = self.collect_due_events(patient_link_id)
        opted_out = bool(patient["sms_opt_out"])
        has_phone = bool(patient["phone_number"])

        for event in events:
            event_config = config[event["event_key"]]
            channel = event_config["channel"]
            if channel == "off":
                continue
            period_key = event["period_key"]

            if channel in {"worklist", "both"} and not (
                self.repo.already_dispatched(
                    patient_link_id,
                    event["event_key"],
                    period_key,
                    "worklist",
                )
            ):
                reason = REASON_BY_EVENT.get(
                    event["event_key"],
                    "manual",
                )
                if dry_run:
                    result["worklist"] += 1
                else:
                    task_id = None
                    if not self.fu.exists_open(
                        patient_link_id,
                        reason,
                    ):
                        task_id = self.fu.create(
                            patient_link_id,
                            reason=reason,
                            detail=event["detail"],
                            due_date=today_str(),
                            source_event=event["event_key"],
                        )
                    self.repo.record_dispatch(
                        patient_link_id,
                        event["event_key"],
                        period_key,
                        "worklist",
                        task_id,
                    )
                    result["worklist"] += int(
                        task_id is not None
                    )

            if worklist_only or channel not in {"sms", "both"}:
                continue
            if opted_out or not has_phone:
                result["skipped"] += 1
                continue
            if self.repo.already_dispatched(
                patient_link_id,
                event["event_key"],
                period_key,
                "sms",
            ):
                continue
            if self.repo.in_cooldown(
                patient_link_id,
                event["event_key"],
                event_config.get("cooldown_days") or 0,
            ):
                result["skipped"] += 1
                continue

            template = event_config.get("sms_template") or ""
            body = personalize(
                template,
                name=patient["full_name"],
            ).replace("{detail}", event.get("detail") or "")
            if (
                event["event_key"] == "appointment_reminder"
                and event.get("detail")
                and "{detail}" not in template
            ):
                body = f"{body.rstrip()} {event['detail']}"
            body = sanitize(body)
            if not body.strip():
                continue
            if dry_run:
                result["queued"] += 1
            else:
                approval_id = self.repo.enqueue_approval(
                    patient_link_id,
                    event["event_key"],
                    "sms",
                    event.get("due_date"),
                    body,
                    period_key,
                )
                result["queued"] += int(
                    approval_id is not None
                )
        return result

    def run_all(
        self,
        dry_run: bool = False,
        worklist_only: bool = False,
    ) -> dict:
        rows = get_db().execute(
            """SELECT id FROM patient_links
               WHERE is_active=1
                 AND COALESCE(enrolled_by,'') != 'seed'"""
        ).fetchall()
        aggregate = {
            "sms": 0,
            "worklist": 0,
            "skipped": 0,
            "queued": 0,
            "patients": 0,
        }
        for row in rows:
            result = self.dispatch_patient(
                row["id"],
                dry_run=dry_run,
                worklist_only=worklist_only,
            )
            for key in ("sms", "worklist", "skipped", "queued"):
                aggregate[key] += result[key]
            aggregate["patients"] += 1
        if not dry_run:
            self.sms.set_setting(
                "engagement_last_run_at",
                iran_now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            self.sms.set_setting(
                "engagement_last_result",
                json.dumps(aggregate, ensure_ascii=False),
            )
            self.sms.set_setting("engagement_last_error", "")
        return aggregate

    def approve(
        self,
        approval_id: int,
        decided_by: str,
        message: str | None = None,
        override: bool = False,
    ) -> dict:
        db = get_db()
        approval = self.repo.get_approval(approval_id)
        if not approval or approval.get("status") != "pending":
            return {"ok": False, "reason": "not_pending"}
        if self._quiet_now() and not override:
            return {"ok": False, "reason": "quiet"}
        if self.repo.sms_count_today(
            approval["patient_link_id"]
        ) >= self._daily_cap():
            return {"ok": False, "reason": "daily_cap"}
        patient = db.execute(
            """SELECT id, full_name, phone_number, sms_opt_out
               FROM patient_links WHERE id=?""",
            (approval["patient_link_id"],),
        ).fetchone()
        if (
            not patient
            or not patient["phone_number"]
            or patient["sms_opt_out"]
        ):
            self.repo.set_status(
                approval_id,
                "rejected",
                decided_by,
            )
            return {"ok": False, "reason": "opt_out"}
        body = (
            sanitize(message.strip())
            if message and message.strip()
            else approval["message"] or ""
        )
        if not body.strip():
            return {"ok": False, "reason": "empty"}
        if not self._provider_ready():
            return {"ok": False, "reason": "provider_unconfigured"}
        if not self.repo.claim_approval(approval_id):
            return {"ok": False, "reason": "not_pending"}

        idempotency_key = f"engagement:approval:{approval_id}"
        try:
            accepted = send_single(
                approval["patient_link_id"],
                patient["phone_number"],
                body,
                message_type="Informational",
                idempotency_key=idempotency_key,
                source_type="engagement",
                source_ref=str(approval_id),
            )
        except Exception as exc:
            self.repo.finish_approval(
                approval_id,
                "pending",
                error=str(exc),
            )
            return {
                "ok": False,
                "reason": "provider_error",
                "error": str(exc),
            }

        message_row = (
            self.sms.get_message_by_idempotency(idempotency_key) or {}
        )
        message_id = message_row.get("id")
        if accepted:
            self.repo.record_dispatch(
                approval["patient_link_id"],
                approval["event_key"],
                approval["period_key"] or "",
                "sms",
                message_id,
                status="accepted",
            )
            self.repo.finish_approval(
                approval_id,
                "approved",
                decided_by=decided_by,
                sms_message_id=message_id,
                sent=True,
            )
            return {"ok": True, "message_id": message_id}

        error = (
            message_row.get("error")
            or "سرویس‌دهنده پیام را نپذیرفت"
        )
        delivery = message_row.get("delivery_status")
        if delivery == "SubmissionUnknown":
            final_status, reason = "unknown", "submission_unknown"
        elif message_row.get("retryable"):
            final_status, reason = "pending", "retryable_failure"
        else:
            final_status, reason = "failed", "provider_rejected"
        self.repo.finish_approval(
            approval_id,
            final_status,
            decided_by=decided_by,
            sms_message_id=message_id,
            error=error,
        )
        if final_status != "pending":
            self.repo.record_dispatch(
                approval["patient_link_id"],
                approval["event_key"],
                approval["period_key"] or "",
                "sms",
                message_id,
                status=final_status,
            )
        return {
            "ok": False,
            "reason": reason,
            "error": error,
            "message_id": message_id,
        }

    def reject(self, approval_id: int, decided_by: str) -> None:
        self.repo.set_status(approval_id, "rejected", decided_by)

    def enqueue_event_for_patient(
        self,
        patient_link_id: int,
        event_key: str,
        period_key: str,
        detail: str | None = None,
    ) -> int | None:
        db = get_db()
        patient = db.execute(
            """SELECT id, full_name, phone_number, sms_opt_out
               FROM patient_links WHERE id=?""",
            (patient_link_id,),
        ).fetchone()
        if (
            not patient
            or patient["sms_opt_out"]
            or not patient["phone_number"]
        ):
            return None
        config = self.repo.get_event(event_key)
        if (
            not config
            or not config.get("is_active")
            or config.get("channel") == "off"
        ):
            return None
        if self.repo.already_dispatched(
            patient_link_id,
            event_key,
            period_key,
            "sms",
        ):
            return None
        if self.repo.in_cooldown(
            patient_link_id,
            event_key,
            config.get("cooldown_days") or 0,
        ):
            return None
        body = personalize(
            config.get("sms_template") or "",
            name=patient["full_name"],
        )
        if detail:
            body = body.replace("{detail}", detail)
        body = sanitize(body)
        if not body.strip():
            return None
        return self.repo.enqueue_approval(
            patient_link_id,
            event_key,
            "sms",
            None,
            body,
            period_key,
        )

    def enqueue_invite(
        self,
        patient_link_id: int,
        message: str | None = None,
    ) -> int | None:
        patient = get_db().execute(
            """SELECT id, full_name, phone_number, sms_opt_out
               FROM patient_links WHERE id=?""",
            (patient_link_id,),
        ).fetchone()
        if (
            not patient
            or patient["sms_opt_out"]
            or not patient["phone_number"]
        ):
            return None
        event = self.repo.get_event("visit_invite") or {}
        template = message or event.get("sms_template") or (
            "سلام {name} عزیز، برای ادامهٔ روند درمان لطفاً جهت "
            "تعیینِ نوبتِ ویزیت با کلینیک تماس بگیرید."
        )
        body = sanitize(
            personalize(template, name=patient["full_name"])
        )
        period_key = f"invite:{today_str()}"
        return self.repo.enqueue_approval(
            patient_link_id,
            "visit_invite",
            "sms",
            today_str(),
            body,
            period_key,
        )

    def enqueue_control_room_invite(
        self,
        patient_link_id: int,
        message: str,
    ) -> int | None:
        patient = get_db().execute(
            """SELECT id, full_name, phone_number, sms_opt_out
               FROM patient_links WHERE id=?""",
            (patient_link_id,),
        ).fetchone()
        if (
            not patient
            or patient["sms_opt_out"]
            or not patient["phone_number"]
        ):
            return None
        body = sanitize(
            personalize(message, name=patient["full_name"])
        )
        if not body.strip():
            return None
        digest = hashlib.sha256(
            body.encode("utf-8")
        ).hexdigest()[:12]
        period_key = f"control-room:{today_str()}:{digest}"
        return self.repo.enqueue_approval(
            patient_link_id,
            "control_room_invite",
            "sms",
            today_str(),
            body,
            period_key,
        )
