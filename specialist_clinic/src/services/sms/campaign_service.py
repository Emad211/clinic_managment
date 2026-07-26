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
    """Send one campaign with immutable purpose/consent snapshots per message."""
    repo = SmsRepository()
    campaign = repo.get_campaign(campaign_id)
    if not campaign:
        return {"error": "campaign not found"}

    token = uuid.uuid4().hex
    if not repo.claim_campaign(campaign_id, token):
        return {"error": "campaign already running", "duplicate": True}

    purpose = _purpose_for_campaign(campaign)
    recipients = resolve_segment(campaign["segment"], purpose=purpose)
    holdout_percent = int(campaign.get("holdout_percent") or 0)
    control_ids: set[int] = set()
    existing_audience = repo.get_audience(campaign_id)
    if existing_audience:
        control_ids = {
            int(row["patient_link_id"])
            for row in existing_audience
            if row["grp"] == "control"
        }
    elif holdout_percent > 0 and len(recipients) >= 2:
        count = max(1, round(len(recipients) * holdout_percent / 100.0))
        count = min(count, len(recipients) - 1)
        control_ids = {int(row["id"]) for row in random.sample(recipients, count)}
        repo.record_audience(
            campaign_id,
            [
                (
                    row["id"],
                    row.get("accounting_patient_id"),
                    "control" if row["id"] in control_ids else "treated",
                )
                for row in recipients
            ],
        )
    treated = [row for row in recipients if int(row["id"]) not in control_ids]
    repo.update_campaign_status(
        campaign_id,
        "sending",
        total_recipients=len(treated),
    )

    is_credit = campaign.get("campaign_type") == "wallet_credit"
    credit_amount = int(campaign.get("credit_amount") or 0)
    expires_at = None
    if is_credit and campaign.get("credit_expires_days"):
        try:
            from datetime import timedelta

            expires_at = (
                iran_now() + timedelta(days=int(campaign["credit_expires_days"]))
            ).strftime("%Y-%m-%d")
        except Exception:
            expires_at = None

    message_type = (
        "Informational" if purpose == "CARE" else "PromotionalToCustomers"
    )
    wallet = WalletRepository()
    provider = get_provider()
    if isinstance(provider, UnconfiguredProvider):
        repo.release_campaign(campaign_id, token, campaign.get("status") or "draft")
        return {"error": "provider not configured", "reason": "provider_unconfigured"}
    provider_name = provider.provider_name
    governance = SmsGovernanceService()
    dispatch = SmsDispatchRepository()
    claimed: list[tuple[int, str, str, str]] = []
    consent_skipped = invalid_phone = 0
    try:
        for recipient in treated:
            patient_id = int(recipient["id"])
            try:
                consent = governance.require_allowed(
                    patient_link_id=patient_id,
                    purpose=purpose,
                )
                phone = canonicalize_iran_mobile(recipient["phone_number"])
            except SmsConsentDenied:
                consent_skipped += 1
                continue
            except ValueError:
                invalid_phone += 1
                continue

            balance = 0
            key = f"campaign:{campaign_id}:patient:{patient_id}"
            # Wallet compensation/state-machine hardening is deliberately left to A6;
            # this existing behaviour is not used as proof of collection or campaign ROI.
            if is_credit and credit_amount > 0:
                balance = wallet.adjust(
                    patient_id,
                    credit_amount,
                    reason="campaign",
                    campaign_id=campaign_id,
                    note=campaign["name"],
                    expires_at=expires_at,
                    created_by="campaign",
                    idempotency_key=f"wallet:{key}",
                )
            body = sanitize(
                personalize(
                    campaign["body"],
                    name=recipient["full_name"],
                    credit=credit_amount,
                    balance=balance,
                )
            )
            message_id, _created = dispatch.create_message(
                campaign_id=campaign_id,
                patient_link_id=patient_id,
                recipient=phone,
                body=body,
                provider_name=provider_name,
                idempotency_key=key,
                source_type="campaign",
                source_ref=str(campaign_id),
                purpose=purpose,
                consent_event_id=consent.event_id,
                consent_decision=consent.decision,
                source_policy="CAMPAIGN_PURPOSE_V1",
                created_by=str(campaign.get("created_by") or "campaign"),
            )
            if dispatch.claim_submission(message_id):
                claimed.append((message_id, key, phone, body))

        accepted = failed = pending = 0
        for start in range(0, len(claimed), 100):
            chunk = claimed[start : start + 100]
            result = provider.send_batch(
                [
                    OutgoingSms(ref_id=key, recipient=phone, body=body)
                    for _message_id, key, phone, body in chunk
                ],
                message_type=message_type,
            )
            by_ref = {item.ref_id: item for item in result.items}
            for message_id, key, _phone, _body in chunk:
                item = by_ref.get(key)
                if item is None:
                    dispatch.record_submission(
                        message_id,
                        ok=False,
                        pending=True,
                        delivery_status="SubmissionUnknown",
                        error="پاسخ متناظر از سرویس‌دهنده دریافت نشد",
                    )
                    pending += 1
                    continue
                dispatch.record_submission(
                    message_id,
                    ok=item.ok,
                    pending=item.pending,
                    provider_request_id=item.provider_request_id,
                    provider_msgid=item.provider_msgid,
                    delivery_status=item.delivery_status,
                    error=item.error,
                    retryable=item.retryable,
                )
                accepted += int(item.ok)
                pending += int(item.pending)
                failed += int(not item.ok and not item.pending)
        repo.refresh_campaign_counts(campaign_id)
        return {
            "total": len(treated),
            "accepted": accepted,
            # Compatibility key; explicitly means provider acceptance, not delivery.
            "sent": accepted,
            "failed": failed,
            "pending": pending,
            "control": len(control_ids),
            "consent_skipped": consent_skipped,
            "invalid_phone": invalid_phone,
            "purpose": purpose,
        }
    finally:
        repo.release_campaign(campaign_id, token, "done")


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
