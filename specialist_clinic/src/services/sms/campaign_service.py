"""Immutable audience resolution and guarded campaign submission."""
from __future__ import annotations

from datetime import timedelta
import random
import uuid

from src.adapters.sqlite.campaign_journey_attribution_repo import (
    CampaignJourneyAttributionRepository,
)
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.sms_repo import SmsRepository
from src.adapters.sqlite.wallet_repo import WalletRepository
from src.common.utils import iran_now
from src.services.sms.compliance import sanitize
from src.services.sms.provider import OutgoingSms, UnconfiguredProvider, get_provider


SEGMENTS = {
    'all': 'همه بیماران',
    'diabetes': 'بیماران دیابتی',
    'hypertension': 'بیماران فشار خون',
    'lapsed': 'بیماران بدون مراجعه اخیر',
    'refill_due': 'داروی رو به اتمام',
}


def resolve_segment(segment: str) -> list[dict]:
    """Resolve the current eligible cohort only before the first audience snapshot."""
    db = get_db()
    base = (
        "SELECT DISTINCT p.id, p.full_name, p.phone_number, "
        "p.accounting_patient_id FROM patient_links p"
    )
    where = (
        "p.is_active=1 AND p.sms_opt_out=0 "
        "AND COALESCE(p.enrolled_by,'') != 'seed' "
        "AND p.phone_number IS NOT NULL AND p.phone_number != ''"
    )
    if segment == 'all':
        sql, params = f"{base} WHERE {where}", ()
    elif segment in ('diabetes', 'hypertension'):
        sql = (
            f"{base} JOIN patient_conditions pc "
            "ON pc.patient_link_id=p.id AND pc.is_active=1 "
            "JOIN conditions c ON c.id=pc.condition_id "
            f"WHERE {where} AND c.code=?"
        )
        params = (segment,)
    elif segment == 'lapsed':
        sql = f"""{base} WHERE {where} AND NOT EXISTS (
            SELECT 1 FROM vital_readings vital
            WHERE vital.patient_link_id=p.id
              AND vital.measured_at >= datetime(
                  'now','+3 hours','+30 minutes','-120 days'
              )
        )"""
        params = ()
    elif segment == 'refill_due':
        sql = f"""{base} JOIN patient_medications medication
            ON medication.patient_link_id=p.id AND medication.is_active=1
            WHERE {where} AND medication.refill_due_date IS NOT NULL
              AND medication.refill_due_date <= date(
                  'now','+3 hours','+30 minutes','+7 days'
              )"""
        params = ()
    else:
        return []
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def _fa_num(number: int) -> str:
    value = f"{int(number):,}"
    return value.translate(str.maketrans('0123456789,', '۰۱۲۳۴۵۶۷۸۹،'))


def personalize(body: str, *, name: str, credit: int = 0, balance: int = 0) -> str:
    output = body or ''
    output = output.replace('{name}', name or 'بیمار')
    output = output.replace('{credit}', _fa_num(credit))
    output = output.replace('{balance}', _fa_num(balance))
    return output


def _audience(campaign: dict) -> tuple[list[dict], bool]:
    """Return immutable audience; create it exactly once from current segment state."""
    repository = CampaignJourneyAttributionRepository()
    existing = repository.audience_snapshot(int(campaign['id']))
    if existing:
        return existing, False
    recipients = resolve_segment(campaign['segment'])
    holdout_percent = int(campaign.get('holdout_percent') or 0)
    control_ids: set[int] = set()
    if holdout_percent > 0 and len(recipients) >= 2:
        count = max(1, round(len(recipients) * holdout_percent / 100.0))
        count = min(count, len(recipients) - 1)
        # Deterministic assignment before the immutable rows are written.
        sampler = random.Random(f"campaign:{int(campaign['id'])}")
        control_ids = {
            int(item['id']) for item in sampler.sample(recipients, count)
        }
    return repository.freeze_audience_once(
        campaign_id=int(campaign['id']),
        recipients=recipients,
        control_ids=control_ids,
        assigned_at=iran_now(),
    )


def run_campaign(campaign_id: int) -> dict:
    """Submit only the immutable treated cohort and report truthful final state."""
    repo = SmsRepository()
    campaign = repo.get_campaign(campaign_id)
    if not campaign:
        return {'error': 'campaign not found', 'reason': 'campaign_not_found'}

    token = uuid.uuid4().hex
    if not repo.claim_campaign(campaign_id, token):
        return {'error': 'campaign already running', 'duplicate': True}

    original_status = campaign.get('status') or 'draft'
    provider = get_provider()
    if isinstance(provider, UnconfiguredProvider):
        repo.release_campaign(campaign_id, token, original_status)
        return {'error': 'provider not configured', 'reason': 'provider_unconfigured'}

    final_status = 'failed'
    try:
        audience, _created = _audience(campaign)
        controls = [row for row in audience if row['grp'] == 'control']
        treated_snapshot = [row for row in audience if row['grp'] == 'treated']
        treated = [
            row for row in treated_snapshot
            if int(row.get('current_is_active') or 0) == 1
            and int(row.get('current_sms_opt_out') or 0) == 0
            and str(row.get('current_phone_number') or '').strip()
        ]
        skipped = len(treated_snapshot) - len(treated)
        repo.update_campaign_status(
            campaign_id,
            'sending',
            total_recipients=len(treated),
        )

        is_credit = campaign.get('campaign_type') == 'wallet_credit'
        credit_amount = int(campaign.get('credit_amount') or 0)
        expires_at = None
        if is_credit and campaign.get('credit_expires_days'):
            expires_at = (
                iran_now()
                + timedelta(days=int(campaign['credit_expires_days']))
            ).strftime('%Y-%m-%d')
        message_type = (
            'Informational'
            if campaign.get('campaign_type') == 'reminder'
            else 'PromotionalToCustomers'
        )
        wallet = WalletRepository()
        provider_name = (
            provider.__class__.__name__.replace('Provider', '').lower() or 'null'
        )
        claimed: list[dict] = []
        for recipient in treated:
            patient_id = int(recipient['patient_link_id'])
            key = f"campaign:{campaign_id}:patient:{patient_id}"
            current_balance = wallet.get_balance(patient_id)
            projected_balance = (
                current_balance + credit_amount
                if is_credit and credit_amount > 0
                else current_balance
            )
            body = sanitize(
                personalize(
                    campaign['body'],
                    name=(
                        recipient.get('current_full_name')
                        or recipient['full_name_snapshot']
                    ),
                    credit=credit_amount,
                    balance=projected_balance,
                )
            )
            phone = str(recipient['current_phone_number']).strip()
            message_id = repo.add_message(
                campaign_id=campaign_id,
                patient_link_id=patient_id,
                recipient=phone,
                body=body,
                provider=provider_name,
                idempotency_key=key,
                source_type='campaign',
                source_ref=str(campaign_id),
            )
            if repo.claim_message_attempt(message_id):
                claimed.append(
                    {
                        'message_id': message_id,
                        'key': key,
                        'patient_id': patient_id,
                        'phone': phone,
                        'body': body,
                    }
                )

        for offset in range(0, len(claimed), 100):
            chunk = claimed[offset:offset + 100]
            result = provider.send_batch(
                [
                    OutgoingSms(
                        ref_id=item['key'],
                        recipient=item['phone'],
                        body=item['body'],
                    )
                    for item in chunk
                ],
                message_type=message_type,
            )
            by_ref = {item.ref_id: item for item in result.items}
            for local in chunk:
                item = by_ref.get(local['key'])
                submission_ambiguous = item is None
                if item is None:
                    repo.mark_submission(
                        local['message_id'],
                        ok=False,
                        pending=True,
                        error='پاسخ متناظر از سرویس‌دهنده دریافت نشد',
                    )
                else:
                    repo.mark_submission(
                        local['message_id'],
                        ok=item.ok,
                        pending=item.pending,
                        provider_request_id=item.provider_request_id,
                        provider_msgid=item.provider_msgid,
                        delivery_status=item.delivery_status,
                        error=item.error,
                        retryable=item.retryable,
                    )
                # A credit mentioned in a possibly delivered message must exist. Definitive
                # provider rejection receives no credit. Idempotency prevents duplicate credit.
                accepted_or_unknown = submission_ambiguous or bool(
                    item and (item.ok or item.pending)
                )
                if is_credit and credit_amount > 0 and accepted_or_unknown:
                    wallet.adjust(
                        local['patient_id'],
                        credit_amount,
                        reason='campaign',
                        campaign_id=campaign_id,
                        note=campaign['name'],
                        expires_at=expires_at,
                        created_by='campaign',
                        idempotency_key=f"wallet:{local['key']}",
                    )

        repo.refresh_campaign_counts(campaign_id)
        counts = repo.get_campaign(campaign_id)
        pending = int(counts.get('pending_count') or 0)
        failed = int(counts.get('failed_count') or 0)
        if pending:
            final_status = 'submitted_pending'
        elif failed:
            final_status = 'completed_with_errors'
        else:
            final_status = 'done'
        return {
            'total': len(treated),
            'audience_total': len(audience),
            'sent': int(counts.get('sent_count') or 0),
            'failed': failed,
            'pending': pending,
            'control': len(controls),
            'skipped': skipped,
            'status': final_status,
        }
    except Exception as exc:
        final_status = 'failed'
        return {
            'error': str(exc),
            'reason': 'campaign_execution_failed',
            'status': final_status,
        }
    finally:
        repo.release_campaign(campaign_id, token, final_status)


def send_single(
    patient_link_id: int,
    recipient: str,
    body: str,
    campaign_id: int = None,
    message_type: str = 'Informational',
    idempotency_key: str = None,
    source_type: str = 'manual',
    source_ref: str = None,
) -> bool:
    repo = SmsRepository()
    provider = get_provider()
    provider_name = provider.__class__.__name__.replace('Provider', '').lower()
    message_id = repo.add_message(
        campaign_id=campaign_id,
        patient_link_id=patient_link_id,
        recipient=recipient,
        body=body,
        provider=provider_name,
        idempotency_key=idempotency_key,
        source_type=source_type,
        source_ref=source_ref,
    )
    if not repo.claim_message_attempt(message_id):
        return (repo.get_message(message_id) or {}).get('status') == 'sent'
    result = provider.send(recipient, body, message_type=message_type)
    repo.mark_submission(
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
    return result.ok
