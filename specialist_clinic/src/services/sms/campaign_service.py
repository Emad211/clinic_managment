"""Segment resolution + campaign sending."""
from __future__ import annotations

import random

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.sms_repo import SmsRepository
from src.adapters.sqlite.wallet_repo import WalletRepository
from src.services.sms.provider import get_provider
from src.services.sms.compliance import sanitize
from src.common.utils import iran_now

SEGMENTS = {
    'all': 'همه بیماران',
    'diabetes': 'بیماران دیابتی',
    'hypertension': 'بیماران فشار خون',
    'uncontrolled': 'بیماران کنترل‌نشده',
    'lapsed': 'بیماران بدون مراجعه اخیر',
    'refill_due': 'داروی رو به اتمام',
}


def resolve_segment(segment: str) -> list[dict]:
    """Return [{id, full_name, phone_number}] for a segment (only with a phone number)."""
    db = get_db()
    base = "SELECT DISTINCT p.id, p.full_name, p.phone_number, p.accounting_patient_id FROM patient_links p"
    where = "p.is_active=1 AND p.phone_number IS NOT NULL AND p.phone_number != ''"

    if segment == 'all':
        sql = f"{base} WHERE {where}"
        params = ()
    elif segment in ('diabetes', 'hypertension'):
        code = segment
        sql = (f"{base} JOIN patient_conditions pc ON pc.patient_link_id=p.id AND pc.is_active=1 "
               f"JOIN conditions c ON c.id=pc.condition_id "
               f"WHERE {where} AND c.code = ?")
        params = (code,)
    elif segment == 'uncontrolled':
        # latest hba1c > 8 OR latest systolic >= 140
        sql = f"""{base} WHERE {where} AND (
            (SELECT v.value FROM vital_readings v WHERE v.patient_link_id=p.id AND v.type='hba1c'
                ORDER BY v.measured_at DESC LIMIT 1) > 8
            OR
            (SELECT v.value FROM vital_readings v WHERE v.patient_link_id=p.id AND v.type='bp_systolic'
                ORDER BY v.measured_at DESC LIMIT 1) >= 140
        )"""
        params = ()
    elif segment == 'lapsed':
        # no vital reading in the last 90 days
        sql = f"""{base} WHERE {where} AND NOT EXISTS (
            SELECT 1 FROM vital_readings v WHERE v.patient_link_id=p.id
                AND v.measured_at >= datetime('now','+3 hours','+30 minutes','-90 days')
        )"""
        params = ()
    elif segment == 'refill_due':
        sql = f"""{base} JOIN patient_medications m ON m.patient_link_id=p.id AND m.is_active=1
            WHERE {where} AND m.refill_due_date IS NOT NULL
              AND m.refill_due_date <= date('now','+3 hours','+30 minutes','+7 days')"""
        params = ()
    else:
        return []

    return [dict(r) for r in db.execute(sql, params).fetchall()]


def _fa_num(n: int) -> str:
    s = f"{int(n):,}"
    return s.translate(str.maketrans('0123456789,', '۰۱۲۳۴۵۶۷۸۹،'))


def personalize(body: str, *, name: str, credit: int = 0, balance: int = 0) -> str:
    """Fill placeholders: {name}, {credit}, {balance} (credit/balance in Toman, Persian digits)."""
    out = (body or '')
    out = out.replace('{name}', name or 'بیمار')
    out = out.replace('{credit}', _fa_num(credit))
    out = out.replace('{balance}', _fa_num(balance))
    return out


def run_campaign(campaign_id: int) -> dict:
    """Send a campaign to its segment, logging each message. Returns counts.

    For wallet_credit campaigns, each recipient's wallet is credited and the
    message reports the {credit} and resulting {balance} — the compliant way to
    run a promotion without the banned words «تخفیف/رایگان».
    """
    repo = SmsRepository()
    campaign = repo.get_campaign(campaign_id)
    if not campaign:
        return {'error': 'campaign not found'}

    recipients = resolve_segment(campaign['segment'])

    # Holdout / control split for incrementality (only when holdout_percent > 0).
    # The control group is NOT sent and NOT credited; the full split is recorded so
    # the campaign's causal lift can be measured later (treated vs control revenue).
    holdout_pct = int(campaign.get('holdout_percent') or 0)
    control_ids = set()
    if holdout_pct > 0 and len(recipients) >= 2:
        n_control = max(1, round(len(recipients) * holdout_pct / 100.0))
        n_control = min(n_control, len(recipients) - 1)  # always keep at least one treated
        for r in random.sample(recipients, n_control):
            control_ids.add(r['id'])
        repo.record_audience(campaign_id, [
            (r['id'], r.get('accounting_patient_id'),
             'control' if r['id'] in control_ids else 'treated') for r in recipients])

    treated = [r for r in recipients if r['id'] not in control_ids]
    repo.update_campaign_status(campaign_id, 'sending', total_recipients=len(treated))

    is_credit = campaign.get('campaign_type') == 'wallet_credit'
    credit_amount = int(campaign.get('credit_amount') or 0)
    expires_at = None
    if is_credit and campaign.get('credit_expires_days'):
        try:
            exp = iran_now()
            from datetime import timedelta
            exp = exp + timedelta(days=int(campaign['credit_expires_days']))
            expires_at = exp.strftime('%Y-%m-%d')
        except Exception:
            expires_at = None

    # Reminders are service messages (Informational); everything else is promotional.
    msg_type = 'Informational' if campaign.get('campaign_type') == 'reminder' else 'PromotionalToCustomers'

    wallet = WalletRepository()
    provider = get_provider()
    sent = failed = pending = 0
    for r in treated:
        balance = 0
        if is_credit and credit_amount > 0:
            balance = wallet.adjust(
                r['id'], credit_amount, reason='campaign', campaign_id=campaign_id,
                note=campaign['name'], expires_at=expires_at, created_by='campaign',
            )
        body = sanitize(personalize(campaign['body'], name=r['full_name'],
                                    credit=credit_amount, balance=balance))
        msg_id = repo.add_message(
            campaign_id=campaign_id, patient_link_id=r['id'],
            recipient=r['phone_number'], body=body,
        )
        result = provider.send(r['phone_number'], body, message_type=msg_type)
        if result.ok:
            sent += 1
            repo.mark_message(msg_id, 'sent', provider_msgid=result.provider_msgid)
        elif getattr(result, 'pending', False):
            # Slow/absent panel response — likely sent; log as pending, not failed.
            pending += 1
            repo.mark_message(msg_id, 'pending', error=result.error)
        else:
            failed += 1
            repo.mark_message(msg_id, 'failed', error=result.error)

    repo.update_campaign_status(campaign_id, 'done',
                                total_recipients=len(treated), sent_count=sent, failed_count=failed)
    return {'total': len(treated), 'sent': sent, 'failed': failed, 'pending': pending,
            'control': len(control_ids)}


def send_single(patient_link_id: int, recipient: str, body: str, campaign_id: int = None,
                message_type: str = 'Informational') -> bool:
    """Send a one-off SMS (e.g. an appointment reminder) and log it.

    Defaults to 'Informational' since one-off sends are service messages.
    """
    repo = SmsRepository()
    msg_id = repo.add_message(campaign_id=campaign_id, patient_link_id=patient_link_id,
                              recipient=recipient, body=body)
    result = get_provider().send(recipient, body, message_type=message_type)
    if result.ok:
        repo.mark_message(msg_id, 'sent', provider_msgid=result.provider_msgid)
    elif getattr(result, 'pending', False):
        repo.mark_message(msg_id, 'pending', error=result.error)
    else:
        repo.mark_message(msg_id, 'failed', error=result.error)
    return result.ok
