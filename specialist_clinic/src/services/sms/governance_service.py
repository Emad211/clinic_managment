"""SMS purpose, consent and recipient policy used by every governed send path."""
from __future__ import annotations

from dataclasses import dataclass
import re

from src.adapters.sqlite.sms_governance_repo import (
    SmsGovernanceConflict,
    SmsGovernanceRepository,
    SmsGovernanceValidationError,
)


_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


class SmsConsentDenied(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SmsConsentDecision:
    patient_link_id: int
    purpose: str
    decision: str
    event_id: int
    allowed: bool
    source_code: str


def canonicalize_iran_mobile(value: str | None) -> str:
    raw = str(value or "").translate(_DIGITS).strip()
    compact = re.sub(r"[^0-9+]", "", raw)
    if compact.startswith("0098"):
        compact = "0" + compact[4:]
    elif compact.startswith("+98"):
        compact = "0" + compact[3:]
    elif compact.startswith("98") and len(compact) == 12:
        compact = "0" + compact[2:]
    elif compact.startswith("9") and len(compact) == 10:
        compact = "0" + compact
    if not re.fullmatch(r"09\d{9}", compact):
        raise SmsGovernanceValidationError("شمارهٔ موبایل معتبر نیست")
    return compact


class SmsGovernanceService:
    PURPOSE_LABELS = {
        "CARE": "پیام‌های مراقبتی و خدماتی",
        "MARKETING": "پیام‌های عمومی و تبلیغاتی",
    }
    PURPOSE_PRESENTATION = {
        "CARE": {
            "description": (
                "پیام‌های مرتبط با ادامهٔ مراقبت و خدمات درمانگاه؛ مانند یادآوری نوبت، "
                "پیگیری درمان، آزمایش، دارو یا اطلاع‌رسانی ضروری پرونده."
            ),
            "examples": "نوبت، آزمایش، دارو، پیگیری درمان و تغییر ضروری برنامهٔ مراجعه",
            "enabled_status": "دریافت می‌کند",
            "disabled_status": "دریافت نمی‌کند",
            "enabled_help": "درمانگاه می‌تواند پیام‌های مراقبتی و خدماتی لازم را برای بیمار ارسال کند.",
            "disabled_help": (
                "ارسال این پیام‌ها متوقف است؛ ممکن است بیمار یادآوری‌های نوبت یا پیگیری درمان را دریافت نکند."
            ),
            "grant_action": "فعال‌کردن پیام‌های مراقبتی",
            "revoke_action": "توقف پیام‌های مراقبتی",
        },
        "MARKETING": {
            "description": (
                "پیام‌های غیرضروری و عمومی؛ مانند معرفی خدمات، کمپین‌ها، برنامه‌های آموزشی عمومی یا تخفیف‌ها."
            ),
            "examples": "معرفی خدمات، کمپین، تخفیف و اطلاع‌رسانی عمومی",
            "enabled_status": "دریافت می‌کند",
            "disabled_status": "دریافت نمی‌کند",
            "enabled_help": "بیمار اجازه داده است پیام‌های عمومی و تبلیغاتی درمانگاه را دریافت کند.",
            "disabled_help": (
                "پیام‌های عمومی و تبلیغاتی ارسال نمی‌شوند؛ این انتخاب روی پیام‌های مراقبتی و نوبت اثری ندارد."
            ),
            "grant_action": "فعال‌کردن پیام‌های عمومی و تبلیغاتی",
            "revoke_action": "توقف پیام‌های عمومی و تبلیغاتی",
        },
    }
    SOURCE_LABELS = {
        "NOT_RECORDED_CONSERVATIVE_DEFAULT": "وضعیت اولیه و محافظه‌کارانهٔ سامانه",
        "LEGACY_CARE_RELATIONSHIP": "رابطهٔ مراقبتی موجود با درمانگاه",
        "CARE_RELATIONSHIP_DEFAULT": "رابطهٔ مراقبتی موجود با درمانگاه",
        "LEGACY_NO_MARKETING_OPT_IN": "رضایت تبلیغاتی صریح ثبت نشده است",
        "NO_MARKETING_OPT_IN": "رضایت تبلیغاتی صریح ثبت نشده است",
        "LEGACY_GLOBAL_OPT_OUT": "انصراف کلی ثبت‌شده در پروندهٔ قبلی",
        "CLINIC_STAFF_RECORDED": "ثبت‌شده توسط کارکنان درمانگاه",
        "PATIENT_EXPLICIT_OPT_IN": "رضایت صریح بیمار",
        "PATIENT_REQUEST": "درخواست مستقیم بیمار",
    }
    REASON_LABELS = {
        "PATIENT_REQUEST": "درخواست بیمار",
        "PATIENT_EXPLICIT_OPT_IN": "رضایت صریح بیمار",
        "LEGACY_CARE_RELATIONSHIP": "رابطهٔ مراقبتی موجود",
        "CARE_RELATIONSHIP_DEFAULT": "رابطهٔ مراقبتی موجود",
        "LEGACY_NO_MARKETING_OPT_IN": "نبود رضایت صریح تبلیغاتی",
        "NO_MARKETING_OPT_IN": "نبود رضایت صریح تبلیغاتی",
        "LEGACY_GLOBAL_OPT_OUT": "انصراف کلی قبلی",
    }

    def __init__(self, repository: SmsGovernanceRepository | None = None):
        self.repository = repository or SmsGovernanceRepository()

    def summary(self, patient_link_id: int) -> dict[str, dict]:
        output: dict[str, dict] = {}
        for purpose in ("CARE", "MARKETING"):
            row = self.repository.current_consent(patient_link_id, purpose)
            if row is None:
                decision = "GRANTED" if purpose == "CARE" else "REVOKED"
                row = {
                    "id": None,
                    "patient_link_id": int(patient_link_id),
                    "purpose": purpose,
                    "decision": decision,
                    "source_code": "NOT_RECORDED_CONSERVATIVE_DEFAULT",
                    "recorded_at": None,
                    "reason_code": None,
                }
            allowed = row["decision"] == "GRANTED"
            presentation = self.PURPOSE_PRESENTATION[purpose]
            source_code = str(row.get("source_code") or "")
            reason_code = str(row.get("reason_code") or "")
            output[purpose] = {
                **row,
                "allowed": allowed,
                "label": self.PURPOSE_LABELS[purpose],
                "description": presentation["description"],
                "examples": presentation["examples"],
                "status_label": (
                    presentation["enabled_status"]
                    if allowed
                    else presentation["disabled_status"]
                ),
                "status_help": (
                    presentation["enabled_help"]
                    if allowed
                    else presentation["disabled_help"]
                ),
                "action_label": (
                    presentation["revoke_action"]
                    if allowed
                    else presentation["grant_action"]
                ),
                "source_label": self.SOURCE_LABELS.get(
                    source_code, "ثبت‌شده در سامانه"
                ),
                "reason_label": (
                    self.REASON_LABELS.get(reason_code, "دلیل ثبت‌شده")
                    if reason_code
                    else "دلیل جداگانه‌ای ثبت نشده است"
                ),
            }
        return output

    def decision(self, patient_link_id: int, purpose: str) -> SmsConsentDecision:
        normalized = str(purpose or "").strip().upper()
        rows = self.repository.ensure_patient_defaults(patient_link_id)
        row = rows.get(normalized)
        if not row:
            raise SmsGovernanceValidationError("invalid SMS purpose")
        return SmsConsentDecision(
            patient_link_id=int(patient_link_id),
            purpose=normalized,
            decision=str(row["decision"]),
            event_id=int(row["id"]),
            allowed=row["decision"] == "GRANTED",
            source_code=str(row["source_code"]),
        )

    def require_allowed(
        self,
        *,
        patient_link_id: int,
        purpose: str,
    ) -> SmsConsentDecision:
        decision = self.decision(patient_link_id, purpose)
        if not decision.allowed:
            raise SmsConsentDenied(
                f"SMS_{decision.purpose}_CONSENT_REVOKED"
            )
        return decision

    def record(
        self,
        *,
        patient_link_id: int,
        purpose: str,
        decision: str,
        actor_username: str,
        actor_user_id: int | None,
        source_code: str,
        idempotency_key: str,
        reason_code: str | None = None,
        note: str | None = None,
        expected_current_event_id: int | None = None,
    ) -> dict:
        return self.repository.append_consent(
            patient_link_id=patient_link_id,
            purpose=purpose,
            decision=decision,
            source_code=source_code,
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
            reason_code=reason_code,
            note=note,
            expected_current_event_id=expected_current_event_id,
        )

    def bind_outgoing_message(
        self,
        *,
        message_id: int,
        patient_link_id: int,
        purpose: str,
        recipient: str,
        provider_name: str,
        created_by: str,
        source_policy: str,
    ) -> dict:
        consent = self.require_allowed(
            patient_link_id=patient_link_id,
            purpose=purpose,
        )
        canonical = canonicalize_iran_mobile(recipient)
        return self.repository.bind_message(
            message_id=message_id,
            patient_link_id=patient_link_id,
            purpose=consent.purpose,
            consent_event_id=consent.event_id,
            consent_decision=consent.decision,
            allowed_at_submission=True,
            provider_name=provider_name,
            recipient_canonical=canonical,
            source_policy=source_policy,
            created_by=created_by,
        )


__all__ = [
    "SmsConsentDecision",
    "SmsConsentDenied",
    "SmsGovernanceConflict",
    "SmsGovernanceService",
    "SmsGovernanceValidationError",
    "canonicalize_iran_mobile",
]
