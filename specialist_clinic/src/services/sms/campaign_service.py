"""Segment resolution and governed SMS sending."""
from __future__ import annotations

import random
import uuid

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.sms_dispatch_repo import SmsDispatchRepository
from src.adapters.sqlite.sms_repo import SmsRepository
from src.adapters.sqlite.wallet_repo import WalletRepository
from src.common.utils import iran_now
from src.services.sms.compliance import sanitize
from src.services.sms.governance_service import (
    SmsConsentDenied,
    SmsGovernanceService,
    canonicalize_iran_mobile,
)
from src.services.sms.guardrail_service import SmsGuardrailService
from src.services.sms.provider import (
    OutgoingSms,
    UnconfiguredProvider,
    get_provider,
)


SEGMENTS = {
    "all": "همه بیماران",
    "diabetes": "بیماران دیابتی",
    "hypertension": "بیماران فشار خون",
    "lapsed": "بیماران بدون مراجعه اخیر",
    "refill_due": "داروی رو به اتمام",
}


def _segment_rows(segment: str) -> list[dict]:
    db = get_db()
    base = (
        "SELECT DISTINCT p.id, p.full_name, p.phone_number, "
        "p.accounting_patient_id FROM patient_links p"
    )
    where = (
        "p.is_active=1 AND COALESCE(p.enrolled_by,'')!='seed' "
        "AND p.phone_number IS NOT NULL AND trim(p.phone_number)!=''"
    )
    if segment == "all":
        sql, params = f"{base} WHERE {where}", ()
    elif segment in {"diabetes", "hypertension"}:
        sql = (
            f"{base} JOIN patient_conditions pc ON pc.patient_link_id=p.id "
            "AND pc.is_active=1 JOIN conditions c ON c.id=pc.condition_id "
            f"WHERE {where} AND c.code=?"
        )
        params = (segment,)
    elif segment == "lapsed":
        sql = f"""{base} WHERE {where} AND NOT EXISTS (
            SELECT 1 FROM vital_readings vital
            WHERE vital.patient_link_id=p.id
              AND vital.measured_at>=datetime(
                  'now','+3 hours','+30 minutes','-120 days'
              )
        )"""
        params = ()
    elif segment == "refill_due":
        sql = f"""{base} JOIN patient_medications medication
            ON medication.patient_link_id=p.id AND medication.is_active=1
            WHERE {where} AND medication.refill_due_date IS NOT NULL
              AND medication.refill_due_date<=date(
                  'now','+3 hours','+30 minutes','+7 days'
              )"""
        params = ()
    else:
        return []
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def resolve_segment(segment: str, *, purpose: str = "MARKETING") -> list[dict]:
    """Return only patients currently eligible for this exact SMS purpose."""
    governance = SmsGovernanceService()
    recipients: list[dict] = []
    for row in _segment_rows(segment):
        try:
            governance.require_allowed(
                patient_link_id=int(row["id"]),
                purpose=purpose,
            )
            row["phone_number"] = canonicalize_iran_mobile(row["phone_number"])
        except (SmsConsentDenied, ValueError):
            continue
        recipients.append(row)
    return recipients


def _fa_num(number: int) -> str:
    rendered = f"{int(number):,}"
    return rendered.translate(str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹،"))


def personalize(
    body: str,
    *,
    name: str,
    credit: int = 0,
    balance: int = 0,
) -> str:
    output = body or ""
    output = output.replace("{name}", name or "بیمار")
    output = output.replace("{credit}", _fa_num(credit))
    output = output.replace("{balance}", _fa_num(balance))
    return output


def _purpose_for_campaign(campaign: dict) -> str:
    return "CARE" if campaign.get("campaign_type") == "reminder" else "MARKETING"


def run_campaign(campaign_id: int) -> dict:
    """Execute one campaign through the immutable A6 contract."""
    from src.services.sms.campaign_execution_service import (
        GovernedCampaignExecutionService,
    )

    return GovernedCampaignExecutionService().run(int(campaign_id))


def send_single(
    patient_link_id: int,
    recipient: str,
    body: str,
    campaign_id: int | None = None,
    message_type: str = "Informational",
    idempotency_key: str | None = None,
    source_type: str = "manual",
    source_ref: str | None = None,
    purpose: str = "CARE",
    created_by: str = "system:sms",
    override_quiet: bool = False,
) -> bool:
    """Send one governed SMS; return provider acceptance, never delivery."""
    key = str(idempotency_key or "").strip()
    if not key:
        raise ValueError("SMS idempotency_key is required")
    governance = SmsGovernanceService()
    consent = governance.require_allowed(
        patient_link_id=int(patient_link_id),
        purpose=purpose,
    )
    phone = canonicalize_iran_mobile(recipient)
    provider = get_provider()
    if isinstance(provider, UnconfiguredProvider):
        return False
    dispatch = SmsDispatchRepository()
    existing = dispatch.get_by_idempotency(key)
    if existing:
        return existing.get("status") in {"accepted", "delivered", "sent"}
    SmsGuardrailService().require_allowed(
        int(patient_link_id),
        override_quiet=override_quiet,
    )
    message_id, _created = dispatch.create_message(
        campaign_id=campaign_id,
        patient_link_id=int(patient_link_id),
        recipient=phone,
        body=str(body),
        provider_name=provider.provider_name,
        idempotency_key=key,
        source_type=source_type,
        source_ref=source_ref,
        purpose=str(purpose).upper(),
        consent_event_id=consent.event_id,
        consent_decision=consent.decision,
        source_policy="SINGLE_MESSAGE_PURPOSE_V1",
        created_by=created_by,
    )
    if not dispatch.claim_submission(message_id):
        row = dispatch.get(message_id) or {}
        return row.get("status") in {"accepted", "delivered"}
    result = provider.send(phone, body, message_type=message_type)
    dispatch.record_submission(
        message_id,
        ok=result.ok,
        pending=result.pending,
        provider_request_id=result.provider_request_id,
        provider_msgid=result.provider_msgid,
        delivery_status=result.delivery_status,
        delivery_status_int=result.delivery_status_int,
        error=result.error,
        retryable=result.retryable,
    )
    return bool(result.ok)


__all__ = [
    "SEGMENTS",
    "personalize",
    "resolve_segment",
    "run_campaign",
    "send_single",
]
