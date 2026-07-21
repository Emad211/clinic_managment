"""Mediana delivery reconciliation; polling never resubmits a message."""
from collections import defaultdict
import logging

from src.adapters.sqlite.sms_repo import SmsRepository
from src.services.sms.provider import get_provider

logger = logging.getLogger(__name__)

STATUS_LABELS = {
    'Queued': 'در صف', 'Submitting': 'در حال ثبت', 'PendingApproval': 'در انتظار تأیید',
    'WaitingForSend': 'در انتظار ارسال', 'Sending': 'در حال ارسال',
    'SendToOperator': 'تحویل به اپراتور', 'Sent': 'ارسال‌شده', 'Delivered': 'تحویل‌شده',
    'NumberBlackListed': 'لیست سیاه شماره', 'OperatorBlackList': 'لیست سیاه اپراتور',
    'Undelivered': 'تحویل‌نشده', 'Failed': 'ناموفق', 'Canceled': 'لغوشده',
    'RetryableFailure': 'قابل ادامه', 'SubmissionUnknown': 'نتیجه ارسال نامشخص',
    'StatusUnknown': 'وضعیت نامشخص',
}

IN_FLIGHT_STATUSES = {
    'Queued', 'Submitting', 'PendingApproval', 'WaitingForSend',
    'Sending', 'SendToOperator', 'Sent',
}
FAILED_STATUSES = {
    'NumberBlackListed', 'OperatorBlackList', 'Undelivered', 'Failed', 'Canceled',
}
UNKNOWN_STATUSES = {'RetryableFailure', 'SubmissionUnknown', 'StatusUnknown'}


def delivery_summary(rows) -> dict:
    """Return report KPIs for the exact filtered rows shown to the user."""
    result = {'total': 0, 'delivered': 0, 'in_flight': 0, 'failed': 0, 'unknown': 0}
    for row in rows or []:
        status = row.get('delivery_status') or 'Queued'
        result['total'] += 1
        if status == 'Delivered':
            result['delivered'] += 1
        elif status in FAILED_STATUSES:
            result['failed'] += 1
        elif status in UNKNOWN_STATUSES:
            result['unknown'] += 1
        else:
            result['in_flight'] += 1
    return result


class DeliveryService:
    def __init__(self, provider=None, repo=None):
        self.provider = provider or get_provider()
        self.repo = repo or SmsRepository()

    def reconcile(self, *, limit=100, message_ids=None, campaign_id=None):
        affected = set(self.repo.expire_stale_delivery())
        messages = self.repo.due_delivery_messages(
            limit=limit, message_ids=message_ids, campaign_id=campaign_id)
        groups = defaultdict(list)
        for message in messages:
            key = ('request', message['provider_request_id']) if message.get('provider_request_id') \
                else ('item', message['provider_msgid'])
            groups[key].append(message)
        checked = updated = errors = 0
        for (kind, identifier), rows in groups.items():
            try:
                updates = self.provider.fetch_delivery(
                    request_id=identifier if kind == 'request' else None,
                    message_id=identifier if kind == 'item' else None)
                checked += len(rows)
                for row in rows:
                    match = next((u for u in updates if
                                  (u.provider_msgid and str(u.provider_msgid) == str(row.get('provider_msgid')))
                                  or (u.recipient and str(u.recipient) == str(row.get('recipient')))), None)
                    if match is None and len(rows) == 1 and len(updates) == 1:
                        match = updates[0]
                    if match:
                        self.repo.apply_delivery(row['id'], match.status, match.status_int,
                                                 match.delivered_at, match.provider_msgid)
                        updated += 1
                    affected.add(row.get('campaign_id'))
            except Exception:
                errors += len(rows)
                logger.exception("Mediana delivery lookup failed for %s %s", kind, identifier)
        for cid in affected:
            if cid:
                self.repo.refresh_campaign_counts(cid)
        return {'checked': checked, 'updated': updated, 'errors': errors}


def status_label(value):
    return STATUS_LABELS.get(value, value or 'نامشخص')
