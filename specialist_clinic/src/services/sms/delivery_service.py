"""Provider-affine delivery reconciliation; polling never resubmits a message."""
from __future__ import annotations

from collections import defaultdict
import logging

from src.adapters.sqlite.sms_dispatch_repo import SmsDispatchRepository
from src.adapters.sqlite.sms_repo import SmsRepository
from src.services.sms.provider import UnconfiguredProvider, get_provider


logger = logging.getLogger(__name__)

STATUS_LABELS = {
    "Accepted": "پذیرفته‌شده توسط پنل",
    "Queued": "در صف",
    "Submitting": "در حال ثبت",
    "Scheduled": "زمان‌بندی‌شده",
    "PendingApproval": "در انتظار تأیید پنل",
    "WaitingForSend": "در انتظار ارسال",
    "Sending": "در حال ارسال",
    "SendToOperator": "تحویل به اپراتور",
    "Sent": "ارسال‌شده توسط اپراتور",
    "Delivered": "تحویل‌شده به گیرنده",
    "NumberBlackListed": "لیست سیاه شماره",
    "OperatorBlackList": "لیست سیاه اپراتور",
    "Undelivered": "تحویل‌نشده",
    "Failed": "ناموفق",
    "Canceled": "لغوشده",
    "RetryableFailure": "خطای موقت قابل تلاش",
    "SubmissionUnknown": "نتیجهٔ ثبت نامشخص",
    "StatusUnknown": "وضعیت نهایی نامشخص",
    "LegacyUnknown": "وضعیت قدیمی نامشخص",
}

IN_FLIGHT_STATUSES = {
    "Accepted",
    "Queued",
    "Submitting",
    "Scheduled",
    "PendingApproval",
    "WaitingForSend",
    "Sending",
    "SendToOperator",
    "Sent",
}
FAILED_STATUSES = {
    "NumberBlackListed",
    "OperatorBlackList",
    "Undelivered",
    "Failed",
    "Canceled",
}
UNKNOWN_STATUSES = {
    "RetryableFailure",
    "SubmissionUnknown",
    "StatusUnknown",
    "LegacyUnknown",
}


def delivery_summary(rows) -> dict:
    """Return honest KPIs for the exact rows shown to the user."""
    result = {
        "total": 0,
        "accepted": 0,
        "delivered": 0,
        "in_flight": 0,
        "failed": 0,
        "unknown": 0,
    }
    for row in rows or []:
        status = row.get("delivery_status") or "LegacyUnknown"
        result["total"] += 1
        if status == "Delivered":
            result["delivered"] += 1
        elif status == "Accepted":
            result["accepted"] += 1
            result["in_flight"] += 1
        elif status in FAILED_STATUSES:
            result["failed"] += 1
        elif status in UNKNOWN_STATUSES:
            result["unknown"] += 1
        else:
            result["in_flight"] += 1
    return result


class DeliveryService:
    def __init__(self, *, dispatch=None, legacy_repo=None, provider_factory=None):
        self.dispatch = dispatch or SmsDispatchRepository()
        self.legacy_repo = legacy_repo or SmsRepository()
        self.provider_factory = provider_factory or get_provider

    def reconcile(self, *, limit=100, message_ids=None, campaign_id=None):
        affected = set(self.dispatch.expire_stale_delivery())
        messages = self.dispatch.due_delivery_messages(
            limit=limit,
            message_ids=message_ids,
            campaign_id=campaign_id,
        )
        groups = defaultdict(list)
        for message in messages:
            identifier = (
                message.get("provider_request_id")
                or message.get("provider_msgid")
            )
            if not identifier:
                continue
            kind = "request" if message.get("provider_request_id") else "item"
            groups[(str(message["provider"]).lower(), kind, str(identifier))].append(
                message
            )

        checked = updated = errors = 0
        provider_errors: dict[str, int] = defaultdict(int)
        for (provider_name, kind, identifier), rows in groups.items():
            provider = self.provider_factory(provider_name)
            if isinstance(provider, UnconfiguredProvider):
                count = len(rows)
                errors += count
                provider_errors[provider_name] += count
                logger.error(
                    "SMS delivery provider unavailable provider=%s messages=%s",
                    provider_name,
                    count,
                )
                continue
            try:
                updates = provider.fetch_delivery(
                    request_id=identifier if kind == "request" else None,
                    message_id=identifier if kind == "item" else None,
                )
                checked += len(rows)
                for row in rows:
                    match = next(
                        (
                            update
                            for update in updates
                            if (
                                update.provider_msgid
                                and str(update.provider_msgid)
                                == str(row.get("provider_msgid"))
                            )
                            or (
                                update.recipient
                                and str(update.recipient)
                                == str(row.get("recipient_canonical") or row.get("recipient"))
                            )
                        ),
                        None,
                    )
                    if match is None and len(rows) == 1 and len(updates) == 1:
                        match = updates[0]
                    if match:
                        self.dispatch.record_delivery(
                            int(row["id"]),
                            status=match.status,
                            status_int=match.status_int,
                            delivered_at=match.delivered_at,
                            provider_msgid=match.provider_msgid,
                        )
                        updated += 1
                    if row.get("campaign_id"):
                        affected.add(int(row["campaign_id"]))
            except Exception:
                count = len(rows)
                errors += count
                provider_errors[provider_name] += count
                logger.exception(
                    "SMS delivery lookup failed provider=%s kind=%s identifier=%s",
                    provider_name,
                    kind,
                    identifier,
                )

        for campaign_id_value in affected:
            self.legacy_repo.refresh_campaign_counts(campaign_id_value)
        return {
            "checked": checked,
            "updated": updated,
            "errors": errors,
            "provider_errors": dict(provider_errors),
        }


def status_label(value):
    return STATUS_LABELS.get(value, value or "نامشخص")


__all__ = [
    "DeliveryService",
    "FAILED_STATUSES",
    "IN_FLIGHT_STATUSES",
    "STATUS_LABELS",
    "UNKNOWN_STATUSES",
    "delivery_summary",
    "status_label",
]
