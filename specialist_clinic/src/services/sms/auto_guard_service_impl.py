"""FOUX-V1 FO-6 governed administrative CARE SMS automation.

This service has no scheduler or startup hook.  Publishing, collecting and executing
are explicit bounded actions.  Candidates contain hashes and immutable references,
not raw phone numbers, rendered bodies, patient names, free text or clinical values.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import os
import sqlite3
from typing import Callable

from flask import current_app

from src.adapters.sqlite.engagement_repo import EngagementRepository
from src.adapters.sqlite.sms_auto_guard_repo import (
    SmsAutoGuardConflict,
    SmsAutoGuardNotReady,
    SmsAutoGuardRepository,
)
from src.adapters.sqlite.sms_repo import SmsRepository
from src.common.utils import iran_now
from src.services.engagement_service import EngagementService
from src.services.followup_orchestration.identity import canonical_hash
from src.services.sms.campaign_service import personalize, send_single
from src.services.sms.compliance import sanitize
from src.services.sms.governance_service import (
    SmsConsentDenied,
    SmsGovernanceService,
    SmsGovernanceValidationError,
    canonicalize_iran_mobile,
)
from src.services.sms.guardrail_service import SmsGuardrailService
from src.services.sms.provider import (
    UnconfiguredProvider,
    get_provider,
    selected_provider_name,
)


POLICY_KEY = "FOUX-SMS-AUTO-GUARD-V1"
POLICY_VERSION = "1.0"
ALLOWLIST = ("appointment_reminder", "refill_due")
POLICY_LEVELS = {
    "appointment_reminder": "AUTO_GUARDED",
    "refill_due": "AUTO_GUARDED",
    "lapsed": "MANUAL_APPROVAL",
    "*": "CLINICIAN_ONLY",
}
DEFAULT_TTL_HOURS = 24
MIN_TTL_HOURS = 1
MAX_TTL_HOURS = 72
CLAIM_LEASE_MINUTES = 10


REASON_LABELS = {
    "FEATURE_DISABLED": "ارسال محافظت‌شده خاموش است",
    "POLICY_NOT_PUBLISHED": "سیاست منتشرشده وجود ندارد",
    "POLICY_CHANGED": "نسخهٔ سیاست تغییر کرده است",
    "POLICY_LEVEL_DENIED": "سطح سیاست اجازهٔ ارسال خودکار نمی‌دهد",
    "EVENT_NOT_ALLOWLISTED": "این رویداد در فهرست مجاز نیست",
    "PURPOSE_NOT_CARE": "هدف پیام CARE نیست",
    "PATIENT_UNAVAILABLE": "پروندهٔ بیمار در دسترس یا فعال نیست",
    "SOURCE_NOT_DUE": "رویداد یا دوره دیگر موعد ارسال ندارد",
    "SOURCE_CHANGED": "منبع رویداد از زمان ساخت نامزد تغییر کرده است",
    "CONSENT_REVOKED": "رضایت CARE معتبر نیست",
    "CONSENT_CHANGED": "نسخهٔ رضایت تغییر کرده است",
    "PHONE_INVALID": "شمارهٔ فعلی معتبر نیست",
    "PHONE_CHANGED": "شمارهٔ فعلی با snapshot یکسان نیست",
    "TEMPLATE_NOT_PUBLISHED": "قالب مصوب منتشر نشده است",
    "TEMPLATE_CHANGED": "نسخه یا محتوای قالب تغییر کرده است",
    "BODY_CHANGED": "متن بازتولیدشده با snapshot یکسان نیست",
    "CANDIDATE_EXPIRED": "اعتبار نامزد پایان یافته است",
    "CANDIDATE_SUPERSEDED": "نامزد با snapshot جدید جایگزین شده است",
    "QUIET_HOURS": "خارج از ساعت مجاز ارسال است",
    "DAILY_CAP": "سقف روزانهٔ بیمار تکمیل شده است",
    "COOLDOWN": "فاصلهٔ امن این رویداد کامل نشده است",
    "ALREADY_DISPATCHED": "این رویداد قبلاً ثبت ارسال شده است",
    "MESSAGE_ALREADY_EXISTS": "برای این نامزد قبلاً پیام ثبت شده است",
    "PROVIDER_CHANGED": "پنل انتخاب‌شده تغییر کرده است",
    "PROVIDER_UNCONFIGURED": "پنل انتخاب‌شده تنظیم نشده است",
    "IN_FLIGHT": "این نامزد هم‌اکنون در حال اجرا است",
    "SUBMITTED": "پیام قبلاً به پنل تحویل شده است",
    "PROVIDER_REJECTED": "پنل پیام را نپذیرفت",
    "PROVIDER_ERROR": "خطای پنل هنگام ارسال",
}


class SmsAutoGuardError(RuntimeError):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or REASON_LABELS.get(code, code))
        self.code = code
        self.message = message or REASON_LABELS.get(code, code)


class SmsAutoGuardDenied(SmsAutoGuardError):
    def __init__(
        self,
        code: str,
        *,
        revalidation_hash: str,
        evidence: dict | None = None,
    ):
        super().__init__(code)
        self.revalidation_hash = revalidation_hash
        self.evidence = evidence or {}


@dataclass(frozen=True, slots=True)
class RevalidatedCandidate:
    candidate: dict
    patient_link_id: int
    phone: str
    body: str
    event: dict
    event_config: dict
    provider_name: str
    revalidation_hash: str


def _hash_text(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _now(value: datetime | None = None) -> datetime:
    current = value or iran_now()
    if current.tzinfo is not None:
        current = current.replace(tzinfo=None)
    return current.replace(microsecond=0)


def _parse(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except (TypeError, ValueError):
        return None


def _json(value: object) -> dict:
    try:
        payload = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _flag_enabled() -> bool:
    try:
        return bool(current_app.config.get("FOLLOWUP_SMS_AUTO_GUARDED", False))
    except RuntimeError:
        return os.environ.get("FOLLOWUP_SMS_AUTO_GUARDED", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }


def _bounded_ttl(value: int | str | None) -> int:
    try:
        parsed = int(value or DEFAULT_TTL_HOURS)
    except (TypeError, ValueError) as exc:
        raise SmsAutoGuardError("INVALID_TTL", "TTL معتبر نیست") from exc
    if not MIN_TTL_HOURS <= parsed <= MAX_TTL_HOURS:
        raise SmsAutoGuardError(
            "INVALID_TTL",
            f"TTL باید بین {MIN_TTL_HOURS} و {MAX_TTL_HOURS} ساعت باشد",
        )
    return parsed


class SmsAutoGuardService:
    def __init__(
        self,
        db: sqlite3.Connection,
        *,
        sender: Callable[..., bool] = send_single,
    ):
        self.db = db
        self.db.row_factory = sqlite3.Row
        self.sender = sender
        self.sms = SmsRepository()
        self.engagement = EngagementRepository()
        self.engagement_service = EngagementService()
        self.governance = SmsGovernanceService()
        self.guardrail = SmsGuardrailService(self.sms)

    @staticmethod
    def _require_enabled() -> None:
        if not _flag_enabled():
            raise SmsAutoGuardError("FEATURE_DISABLED")

    @staticmethod
    def policy_payload(ttl_hours: int = DEFAULT_TTL_HOURS) -> dict:
        ttl = _bounded_ttl(ttl_hours)
        return {
            "allowlist": list(ALLOWLIST),
            "candidate_ttl_hours": ttl,
            "free_text_allowed": False,
            "policy_levels": dict(POLICY_LEVELS),
            "policy_version": POLICY_VERSION,
            "purpose": "CARE",
            "scheduler_enabled": False,
        }

    @staticmethod
    def _render_body(
        *,
        template_text: str,
        patient_name: str,
        event: dict,
    ) -> str:
        body = personalize(str(template_text), name=str(patient_name or "بیمار"))
        body = body.replace("{detail}", str(event.get("detail") or ""))
        if (
            str(event.get("event_key")) == "appointment_reminder"
            and event.get("detail")
            and "{detail}" not in str(template_text)
        ):
            body = f"{body.rstrip()} {event['detail']}"
        return sanitize(body)

    @staticmethod
    def _source_hash(event: dict) -> str:
        return canonical_hash(
            {
                "due_date": event.get("due_date"),
                "event_key": str(event.get("event_key") or ""),
                "period_key": str(event.get("period_key") or ""),
                "detail_hash": _hash_text(str(event.get("detail") or "")),
            }
        )

    @staticmethod
    def _snapshot_hash(
        *,
        patient_link_id: int,
        event_key: str,
        period_key: str,
        policy_version_id: int,
        template_version_id: int,
        consent_event_id: int,
        phone_hash: str,
        source_hash: str,
        body_hash: str,
        provider_name: str,
    ) -> str:
        return canonical_hash(
            {
                "body_hash": body_hash,
                "consent_event_id": int(consent_event_id),
                "event_key": event_key,
                "patient_link_id": int(patient_link_id),
                "period_key": period_key,
                "phone_hash": phone_hash,
                "policy_version_id": int(policy_version_id),
                "provider_name": provider_name,
                "purpose": "CARE",
                "source_hash": source_hash,
                "template_version_id": int(template_version_id),
            }
        )

    def publish_current_contract(
        self,
        *,
        actor_username: str,
        ttl_hours: int = DEFAULT_TTL_HOURS,
        now: datetime | None = None,
    ) -> dict:
        self._require_enabled()
        current = _now(now)
        repo = SmsAutoGuardRepository(self.db, ensure=True)
        policy, policy_created = repo.publish_policy(
            policy_key=POLICY_KEY,
            purpose="CARE",
            policy=self.policy_payload(ttl_hours),
            actor_username=actor_username,
            created_at=current,
        )
        templates: dict[str, dict] = {}
        created = 0
        for event_key in ALLOWLIST:
            config = self.engagement.get_event(event_key)
            if (
                not config
                or not config.get("is_active")
                or str(config.get("channel")) not in {"sms", "both"}
                or not str(config.get("sms_template") or "").strip()
            ):
                raise SmsAutoGuardError(
                    "TEMPLATE_NOT_PUBLISHED",
                    f"قالب فعال و قابل‌ارسال برای {event_key} وجود ندارد",
                )
            template, was_created = repo.publish_template(
                event_key=event_key,
                policy_version_id=int(policy["id"]),
                template_text=str(config["sms_template"]),
                message_type="Informational",
                actor_username=actor_username,
                approved_at=current,
            )
            templates[event_key] = template
            created += int(was_created)
        return {
            "policy_id": int(policy["id"]),
            "policy_version": int(policy["version"]),
            "policy_created": policy_created,
            "templates_created": created,
            "template_ids": {
                key: int(value["id"]) for key, value in templates.items()
            },
        }

    def _current_contract(
        self, repo: SmsAutoGuardRepository
    ) -> tuple[dict, dict[str, dict], dict]:
        policy = repo.latest_policy(POLICY_KEY)
        if not policy:
            raise SmsAutoGuardError("POLICY_NOT_PUBLISHED")
        payload = _json(policy.get("policy_json"))
        if payload.get("allowlist") != list(ALLOWLIST):
            raise SmsAutoGuardError("POLICY_CHANGED")
        if payload.get("purpose") != "CARE":
            raise SmsAutoGuardError("PURPOSE_NOT_CARE")
        templates = {}
        for event_key in ALLOWLIST:
            template = repo.latest_template(event_key)
            if not template:
                raise SmsAutoGuardError("TEMPLATE_NOT_PUBLISHED")
            templates[event_key] = template
        return policy, templates, payload

    def collect_candidates(
        self,
        *,
        actor_username: str,
        limit: int = 100,
        patient_ids: list[int] | None = None,
        now: datetime | None = None,
    ) -> dict:
        self._require_enabled()
        current = _now(now)
        repo = SmsAutoGuardRepository(self.db, ensure=True)
        policy, templates, policy_payload = self._current_contract(repo)
        ttl = _bounded_ttl(policy_payload.get("candidate_ttl_hours"))
        bounded = min(max(int(limit), 1), 500)
        clauses = ["is_active=1", "COALESCE(enrolled_by,'') != 'seed'"]
        params: list[object] = []
        if patient_ids:
            ids = list(dict.fromkeys(int(value) for value in patient_ids))[:bounded]
            marks = ",".join("?" for _ in ids)
            clauses.append(f"id IN ({marks})")
            params.extend(ids)
        params.append(bounded)
        patients = self.db.execute(
            """SELECT id, full_name, phone_number FROM patient_links
               WHERE """
            + " AND ".join(clauses)
            + " ORDER BY id LIMIT ?",
            params,
        ).fetchall()
        provider_name = selected_provider_name()
        counters: Counter[str] = Counter()
        candidate_ids: list[int] = []
        for patient in patients:
            patient_id = int(patient["id"])
            try:
                consent = self.governance.decision(patient_id, "CARE")
                if not consent.allowed:
                    counters["CONSENT_REVOKED"] += 1
                    continue
                phone = canonicalize_iran_mobile(patient["phone_number"])
            except (SmsGovernanceValidationError, ValueError):
                counters["PHONE_INVALID"] += 1
                continue
            events, configs = self.engagement_service.collect_due_events(patient_id)
            for event in events:
                event_key = str(event.get("event_key") or "")
                if event_key not in ALLOWLIST:
                    continue
                config = configs.get(event_key) or {}
                if str(config.get("channel")) not in {"sms", "both"}:
                    counters["CHANNEL_NOT_SMS"] += 1
                    continue
                if self.engagement.already_dispatched(
                    patient_id,
                    event_key,
                    str(event["period_key"]),
                    "sms",
                ):
                    counters["ALREADY_DISPATCHED"] += 1
                    continue
                if self.engagement.in_cooldown(
                    patient_id,
                    event_key,
                    int(config.get("cooldown_days") or 0),
                ):
                    counters["COOLDOWN"] += 1
                    continue
                template = templates[event_key]
                expected_template_hash = repo.template_digest(
                    event_key=event_key,
                    policy_version_id=int(policy["id"]),
                    template_text=str(config.get("sms_template") or ""),
                    message_type="Informational",
                )
                if str(template["content_hash"]) != expected_template_hash:
                    counters["TEMPLATE_CHANGED"] += 1
                    continue
                body = self._render_body(
                    template_text=str(template["template_text"]),
                    patient_name=str(patient["full_name"] or ""),
                    event=event,
                )
                if not body.strip():
                    counters["EMPTY_BODY"] += 1
                    continue
                phone_hash = _hash_text(phone)
                source_hash = self._source_hash(event)
                body_hash = _hash_text(body)
                snapshot_hash = self._snapshot_hash(
                    patient_link_id=patient_id,
                    event_key=event_key,
                    period_key=str(event["period_key"]),
                    policy_version_id=int(policy["id"]),
                    template_version_id=int(template["id"]),
                    consent_event_id=int(consent.event_id),
                    phone_hash=phone_hash,
                    source_hash=source_hash,
                    body_hash=body_hash,
                    provider_name=provider_name,
                )
                candidate, created = repo.create_or_reuse_candidate(
                    patient_link_id=patient_id,
                    event_key=event_key,
                    period_key=str(event["period_key"]),
                    policy_version_id=int(policy["id"]),
                    template_version_id=int(template["id"]),
                    consent_event_id=int(consent.event_id),
                    phone_hash=phone_hash,
                    source_hash=source_hash,
                    body_hash=body_hash,
                    provider_name=provider_name,
                    snapshot_hash=snapshot_hash,
                    actor_username=actor_username,
                    created_at=current,
                    expires_at=current + timedelta(hours=ttl),
                )
                candidate_ids.append(int(candidate["id"]))
                counters["created" if created else "reused"] += 1
        return {
            "patients_scanned": len(patients),
            "candidate_ids": candidate_ids,
            "counts": dict(sorted(counters.items())),
            "expires_in_hours": ttl,
        }

    def _deny(
        self,
        *,
        candidate: dict,
        code: str,
        evidence: dict,
    ) -> SmsAutoGuardDenied:
        digest = canonical_hash(
            {
                "candidate_id": int(candidate["id"]),
                "code": code,
                "evidence": evidence,
                "snapshot_hash": str(candidate["snapshot_hash"]),
            }
        )
        return SmsAutoGuardDenied(
            code,
            revalidation_hash=digest,
            evidence=evidence,
        )

    def _find_due_event(self, patient_id: int, candidate: dict) -> tuple[dict, dict] | None:
        events, configs = self.engagement_service.collect_due_events(patient_id)
        for event in events:
            if (
                str(event.get("event_key")) == str(candidate["event_key"])
                and str(event.get("period_key")) == str(candidate["period_key"])
            ):
                return event, configs.get(str(candidate["event_key"])) or {}
        return None

    def revalidate(
        self,
        candidate_id: int,
        *,
        now: datetime | None = None,
    ) -> RevalidatedCandidate:
        current = _now(now)
        repo = SmsAutoGuardRepository(self.db)
        candidate = repo.get_candidate(candidate_id)
        if not candidate:
            raise SmsAutoGuardError("CANDIDATE_NOT_FOUND")
        if not _flag_enabled():
            raise self._deny(
                candidate=candidate,
                code="FEATURE_DISABLED",
                evidence={"feature_enabled": False},
            )
        state = repo.state(candidate_id, now=current)
        if state["code"] == "EXPIRED":
            raise self._deny(
                candidate=candidate,
                code="CANDIDATE_EXPIRED",
                evidence={"expires_at": str(candidate["expires_at"])},
            )
        if state["code"] == "SUPERSEDED":
            raise self._deny(
                candidate=candidate,
                code="CANDIDATE_SUPERSEDED",
                evidence={"state": state["code"]},
            )
        if state["code"] == "SUBMITTED":
            raise self._deny(
                candidate=candidate,
                code="SUBMITTED",
                evidence={"state": state["code"]},
            )
        if state["code"] == "IN_FLIGHT":
            raise self._deny(
                candidate=candidate,
                code="IN_FLIGHT",
                evidence={"state": state["code"]},
            )

        policy, templates, policy_payload = self._current_contract(repo)
        event_key = str(candidate["event_key"])
        if event_key not in ALLOWLIST:
            raise self._deny(
                candidate=candidate,
                code="EVENT_NOT_ALLOWLISTED",
                evidence={"event_key": event_key},
            )
        if policy_payload.get("policy_levels", {}).get(event_key) != "AUTO_GUARDED":
            raise self._deny(
                candidate=candidate,
                code="POLICY_LEVEL_DENIED",
                evidence={"event_key": event_key},
            )
        if int(policy["id"]) != int(candidate["policy_version_id"]):
            raise self._deny(
                candidate=candidate,
                code="POLICY_CHANGED",
                evidence={"policy_version_id": int(policy["id"])},
            )
        if str(candidate["purpose"]) != "CARE":
            raise self._deny(
                candidate=candidate,
                code="PURPOSE_NOT_CARE",
                evidence={"purpose": str(candidate["purpose"])},
            )

        patient = self.db.execute(
            """SELECT id, full_name, phone_number, is_active
               FROM patient_links WHERE id=?""",
            (int(candidate["patient_link_id"]),),
        ).fetchone()
        if not patient or not int(patient["is_active"] or 0):
            raise self._deny(
                candidate=candidate,
                code="PATIENT_UNAVAILABLE",
                evidence={"patient_available": False},
            )
        patient_id = int(patient["id"])
        try:
            consent = self.governance.require_allowed(
                patient_link_id=patient_id,
                purpose="CARE",
            )
        except SmsConsentDenied:
            raise self._deny(
                candidate=candidate,
                code="CONSENT_REVOKED",
                evidence={"consent_allowed": False},
            )
        if int(consent.event_id) != int(candidate["consent_event_id"]):
            raise self._deny(
                candidate=candidate,
                code="CONSENT_CHANGED",
                evidence={"consent_event_id": int(consent.event_id)},
            )
        try:
            phone = canonicalize_iran_mobile(patient["phone_number"])
        except (SmsGovernanceValidationError, ValueError):
            raise self._deny(
                candidate=candidate,
                code="PHONE_INVALID",
                evidence={"phone_valid": False},
            )
        phone_hash = _hash_text(phone)
        if phone_hash != str(candidate["phone_hash"]):
            raise self._deny(
                candidate=candidate,
                code="PHONE_CHANGED",
                evidence={"phone_hash": phone_hash},
            )

        found = self._find_due_event(patient_id, candidate)
        if not found:
            raise self._deny(
                candidate=candidate,
                code="SOURCE_NOT_DUE",
                evidence={"period_key": str(candidate["period_key"])},
            )
        event, event_config = found
        if str(event_config.get("channel")) not in {"sms", "both"}:
            raise self._deny(
                candidate=candidate,
                code="POLICY_LEVEL_DENIED",
                evidence={"channel": str(event_config.get("channel"))},
            )
        source_hash = self._source_hash(event)
        if source_hash != str(candidate["source_hash"]):
            raise self._deny(
                candidate=candidate,
                code="SOURCE_CHANGED",
                evidence={"source_hash": source_hash},
            )

        template = templates[event_key]
        expected_template_hash = repo.template_digest(
            event_key=event_key,
            policy_version_id=int(policy["id"]),
            template_text=str(event_config.get("sms_template") or ""),
            message_type="Informational",
        )
        if (
            int(template["id"]) != int(candidate["template_version_id"])
            or str(template["content_hash"]) != expected_template_hash
        ):
            raise self._deny(
                candidate=candidate,
                code="TEMPLATE_CHANGED",
                evidence={
                    "template_version_id": int(template["id"]),
                    "template_hash": str(template["content_hash"]),
                },
            )
        body = self._render_body(
            template_text=str(template["template_text"]),
            patient_name=str(patient["full_name"] or ""),
            event=event,
        )
        body_hash = _hash_text(body)
        if body_hash != str(candidate["body_hash"]):
            raise self._deny(
                candidate=candidate,
                code="BODY_CHANGED",
                evidence={"body_hash": body_hash},
            )

        current_provider = selected_provider_name()
        if current_provider != str(candidate["provider_name"]):
            raise self._deny(
                candidate=candidate,
                code="PROVIDER_CHANGED",
                evidence={"provider_name": current_provider},
            )
        provider = get_provider(current_provider)
        if isinstance(provider, UnconfiguredProvider):
            raise self._deny(
                candidate=candidate,
                code="PROVIDER_UNCONFIGURED",
                evidence={"provider_name": current_provider},
            )
        if self.guardrail.is_outside_allowed_hours(current):
            raise self._deny(
                candidate=candidate,
                code="QUIET_HOURS",
                evidence={"allowed_window": self.guardrail.allowed_window()},
            )
        submitted_today = self.guardrail.submitted_today(patient_id)
        daily_cap = self.guardrail.daily_cap()
        if submitted_today >= daily_cap:
            raise self._deny(
                candidate=candidate,
                code="DAILY_CAP",
                evidence={
                    "daily_cap": daily_cap,
                    "submitted_today": submitted_today,
                },
            )
        if self.engagement.in_cooldown(
            patient_id,
            event_key,
            int(event_config.get("cooldown_days") or 0),
        ):
            raise self._deny(
                candidate=candidate,
                code="COOLDOWN",
                evidence={"event_key": event_key},
            )
        if self.engagement.already_dispatched(
            patient_id,
            event_key,
            str(candidate["period_key"]),
            "sms",
        ):
            raise self._deny(
                candidate=candidate,
                code="ALREADY_DISPATCHED",
                evidence={"period_key": str(candidate["period_key"])},
            )
        if repo.message_for_candidate(candidate_id):
            raise self._deny(
                candidate=candidate,
                code="MESSAGE_ALREADY_EXISTS",
                evidence={"message_exists": True},
            )

        revalidation_hash = canonical_hash(
            {
                "body_hash": body_hash,
                "candidate_id": int(candidate_id),
                "consent_event_id": int(consent.event_id),
                "phone_hash": phone_hash,
                "policy_version_id": int(policy["id"]),
                "provider_name": current_provider,
                "source_hash": source_hash,
                "template_version_id": int(template["id"]),
                "validated_at": current.isoformat(sep=" "),
            }
        )
        return RevalidatedCandidate(
            candidate=candidate,
            patient_link_id=patient_id,
            phone=phone,
            body=body,
            event=event,
            event_config=event_config,
            provider_name=current_provider,
            revalidation_hash=revalidation_hash,
        )

    def execute_candidate(
        self,
        candidate_id: int,
        *,
        actor_username: str,
        now: datetime | None = None,
    ) -> dict:
        current = _now(now)
        repo = SmsAutoGuardRepository(self.db, ensure=True)
        candidate = repo.get_candidate(candidate_id)
        if not candidate:
            return {"ok": False, "reason": "CANDIDATE_NOT_FOUND"}
        try:
            validated = self.revalidate(candidate_id, now=current)
        except SmsAutoGuardDenied as denied:
            repo.deny(
                candidate_id=candidate_id,
                reason_code=denied.code,
                revalidation_hash=denied.revalidation_hash,
                actor_username=actor_username,
                recorded_at=current,
                payload=denied.evidence,
            )
            return {
                "ok": False,
                "candidate_id": candidate_id,
                "reason": denied.code,
            }
        except (SmsAutoGuardError, SmsAutoGuardNotReady) as exc:
            code = getattr(exc, "code", "NOT_READY")
            digest = canonical_hash(
                {"candidate_id": candidate_id, "reason": code}
            )
            repo.deny(
                candidate_id=candidate_id,
                reason_code=code,
                revalidation_hash=digest,
                actor_username=actor_username,
                recorded_at=current,
            )
            return {"ok": False, "candidate_id": candidate_id, "reason": code}

        try:
            attempt = repo.claim(
                candidate_id=candidate_id,
                revalidation_hash=validated.revalidation_hash,
                actor_username=actor_username,
                claimed_at=current,
                lease_minutes=CLAIM_LEASE_MINUTES,
            )
        except SmsAutoGuardConflict as exc:
            return {
                "ok": False,
                "candidate_id": candidate_id,
                "reason": str(exc),
            }
        idempotency_key = f"fo6:auto:{candidate_id}:{attempt}"
        try:
            accepted = self.sender(
                validated.patient_link_id,
                validated.phone,
                validated.body,
                message_type="Informational",
                idempotency_key=idempotency_key,
                source_type="fo6_auto_guard",
                source_ref=str(candidate_id),
                purpose="CARE",
                created_by=actor_username,
                override_quiet=False,
            )
        except Exception as exc:
            repo.finish_attempt(
                candidate_id=candidate_id,
                attempt_no=attempt,
                accepted=False,
                reason_code="PROVIDER_ERROR",
                revalidation_hash=validated.revalidation_hash,
                actor_username=actor_username,
                recorded_at=current,
                payload={"error_type": type(exc).__name__},
            )
            return {
                "ok": False,
                "candidate_id": candidate_id,
                "reason": "PROVIDER_ERROR",
            }

        message = self.sms.get_message_by_idempotency(idempotency_key) or {}
        message_id = int(message["id"]) if message.get("id") else None
        if accepted:
            self.engagement.record_dispatch(
                validated.patient_link_id,
                str(candidate["event_key"]),
                str(candidate["period_key"]),
                "sms",
                message_id,
                status="accepted",
            )
            repo.finish_attempt(
                candidate_id=candidate_id,
                attempt_no=attempt,
                accepted=True,
                reason_code="PROVIDER_ACCEPTED",
                revalidation_hash=validated.revalidation_hash,
                actor_username=actor_username,
                recorded_at=current,
                message_id=message_id,
                payload={"provider_name": validated.provider_name},
            )
            return {
                "ok": True,
                "candidate_id": candidate_id,
                "message_id": message_id,
            }
        repo.finish_attempt(
            candidate_id=candidate_id,
            attempt_no=attempt,
            accepted=False,
            reason_code="PROVIDER_REJECTED",
            revalidation_hash=validated.revalidation_hash,
            actor_username=actor_username,
            recorded_at=current,
            message_id=message_id,
            payload={
                "delivery_status": message.get("delivery_status"),
                "retryable": bool(message.get("retryable")),
            },
        )
        return {
            "ok": False,
            "candidate_id": candidate_id,
            "message_id": message_id,
            "reason": "PROVIDER_REJECTED",
        }

    def execute_pending(
        self,
        *,
        actor_username: str,
        limit: int = 20,
        now: datetime | None = None,
    ) -> dict:
        self._require_enabled()
        current = _now(now)
        repo = SmsAutoGuardRepository(self.db, ensure=True)
        candidates = repo.list_candidates(limit=min(max(int(limit), 1), 100), now=current)
        results = []
        for candidate in reversed(candidates):
            if candidate["state"] != "AVAILABLE":
                continue
            results.append(
                self.execute_candidate(
                    int(candidate["id"]),
                    actor_username=actor_username,
                    now=current,
                )
            )
            if len(results) >= int(limit):
                break
        return {
            "attempted": len(results),
            "accepted": sum(int(bool(item.get("ok"))) for item in results),
            "denied_or_failed": sum(int(not item.get("ok")) for item in results),
            "results": results,
        }

    def status(self, *, limit: int = 100, now: datetime | None = None) -> dict:
        repo = SmsAutoGuardRepository(self.db)
        if not repo.ready():
            return {
                "storage_ready": False,
                "feature_enabled": _flag_enabled(),
                "candidates": [],
                "decisions": [],
            }
        return {
            "storage_ready": True,
            "feature_enabled": _flag_enabled(),
            "policy": repo.latest_policy(POLICY_KEY),
            "templates": {
                key: repo.latest_template(key) for key in ALLOWLIST
            },
            "candidates": repo.list_candidates(limit=limit, now=_now(now)),
            "decisions": repo.decision_events(limit=limit),
        }


__all__ = [
    "ALLOWLIST",
    "DEFAULT_TTL_HOURS",
    "MAX_TTL_HOURS",
    "MIN_TTL_HOURS",
    "POLICY_KEY",
    "POLICY_LEVELS",
    "REASON_LABELS",
    "SmsAutoGuardDenied",
    "SmsAutoGuardError",
    "SmsAutoGuardService",
]
