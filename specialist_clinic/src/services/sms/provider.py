"""SMS provider abstraction.

Concrete providers (e.g. Mediana) implement `send`. This keeps the rest of
the app provider-agnostic so a different panel can be plugged in later.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class SendResult:
    ok: bool
    provider_msgid: Optional[str] = None
    error: Optional[str] = None
    pending: bool = False   # submitted, but the panel's response timed out / was unclear
                            # (likely sent) — callers should log it as pending, NOT failed
    provider_request_id: Optional[str] = None
    delivery_status: Optional[str] = None
    delivery_status_int: Optional[int] = None
    retryable: bool = False


@dataclass
class OutgoingSms:
    ref_id: str
    recipient: str
    body: str


@dataclass
class BatchItemResult:
    ref_id: str
    ok: bool
    provider_request_id: Optional[str] = None
    provider_msgid: Optional[str] = None
    delivery_status: Optional[str] = None
    error: Optional[str] = None
    pending: bool = False
    retryable: bool = False


@dataclass
class DeliveryUpdate:
    provider_request_id: Optional[str]
    provider_msgid: Optional[str]
    recipient: Optional[str]
    status: str
    status_int: Optional[int] = None
    delivered_at: Optional[str] = None


@dataclass
class BatchSendResult:
    items: list[BatchItemResult]
    error: Optional[str] = None
    pending: bool = False


class SmsProvider:
    def send(self, recipient: str, body: str, message_type: Optional[str] = None) -> SendResult:  # pragma: no cover
        raise NotImplementedError

    def send_batch(self, messages: list[OutgoingSms], message_type: Optional[str] = None) -> BatchSendResult:
        items = []
        for message in messages:
            result = self.send(message.recipient, message.body, message_type)
            items.append(BatchItemResult(
                ref_id=message.ref_id, ok=result.ok,
                provider_request_id=result.provider_request_id,
                provider_msgid=result.provider_msgid,
                delivery_status=result.delivery_status,
                error=result.error, pending=result.pending, retryable=result.retryable,
            ))
        return BatchSendResult(items=items)

    def fetch_delivery(self, *, request_id: str | None = None,
                       message_id: str | None = None) -> list[DeliveryUpdate]:
        return []


class NullProvider(SmsProvider):
    """Test/simulation provider: logs to console, never actually sends."""

    def send(self, recipient: str, body: str, message_type: Optional[str] = None) -> SendResult:
        # Console-encoding-safe log (Windows cp1252 can't print Persian).
        try:
            print(f"[NullSMS] -> {recipient}: {body}")
        except Exception:
            print(f"[NullSMS] -> {recipient}: <message>")
        return SendResult(ok=True, provider_msgid="SIMULATED")


class UnconfiguredProvider(SmsProvider):
    """Production-safe provider used when no real SMS panel is configured."""

    def send(self, recipient: str, body: str, message_type: Optional[str] = None) -> SendResult:
        return SendResult(
            ok=False, retryable=True, delivery_status="RetryableFailure",
            error="پنل پیامک فعال تنظیم نشده است",
        )


def get_provider() -> SmsProvider:
    """Return the configured SMS provider.

    Honors the ``sms_provider`` setting ('kavenegar' | 'mediana'). If the selected
    panel has no API key, falls back to whichever panel *does* have a key, and
    In tests it falls back to NullProvider. A real application never reports a
    simulated send as successful when no panel is configured.
    """
    try:
        from src.adapters.sqlite.sms_repo import SmsRepository
        repo = SmsRepository()
        kav_key = (repo.get_setting('kavenegar_api_key') or '').strip()
        med_key = (repo.get_setting('mediana_api_key') or '').strip()
        pref = (repo.get_setting('sms_provider') or '').strip().lower()
        if pref not in ('kavenegar', 'mediana'):
            pref = 'kavenegar' if kav_key else ('mediana' if med_key else '')

        def _timeout(key: str) -> int:
            try:
                return int(repo.get_setting(key, '45') or 45)
            except (TypeError, ValueError):
                return 45

        def _kavenegar() -> SmsProvider:
            from src.services.sms.kavenegar_provider import KavenegarProvider
            return KavenegarProvider(
                api_key=kav_key,
                sender=repo.get_setting('kavenegar_sender'),
                timeout=_timeout('kavenegar_timeout'),
            )

        def _mediana() -> SmsProvider:
            from src.services.sms.mediana_provider import MedianaProvider
            return MedianaProvider(
                api_key=med_key,
                sending_number=repo.get_setting('mediana_sending_number'),
                default_type=repo.get_setting('mediana_message_type', 'PromotionalToCustomers'),
                timeout=_timeout('mediana_timeout'),
            )

        if pref == 'kavenegar' and kav_key:
            return _kavenegar()
        if pref == 'mediana' and med_key:
            return _mediana()
        # Selected panel isn't configured → use whichever has a key.
        if kav_key:
            return _kavenegar()
        if med_key:
            return _mediana()
    except Exception as e:
        print(f"[sms] provider init failed: {e}")
    try:
        from flask import current_app
        if current_app.config.get('TESTING'):
            return NullProvider()
    except Exception:
        pass
    return UnconfiguredProvider()
