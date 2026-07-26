"""SMS provider abstraction and exact provider registry."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.services.sms.secret_resolver import get_sms_secret


@dataclass
class SendResult:
    ok: bool
    provider_msgid: Optional[str] = None
    error: Optional[str] = None
    pending: bool = False
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
    provider_name = "unknown"

    def send(
        self,
        recipient: str,
        body: str,
        message_type: Optional[str] = None,
    ) -> SendResult:  # pragma: no cover
        raise NotImplementedError

    def send_batch(
        self,
        messages: list[OutgoingSms],
        message_type: Optional[str] = None,
    ) -> BatchSendResult:
        items = []
        for message in messages:
            result = self.send(message.recipient, message.body, message_type)
            items.append(
                BatchItemResult(
                    ref_id=message.ref_id,
                    ok=result.ok,
                    provider_request_id=result.provider_request_id,
                    provider_msgid=result.provider_msgid,
                    delivery_status=result.delivery_status,
                    error=result.error,
                    pending=result.pending,
                    retryable=result.retryable,
                )
            )
        return BatchSendResult(items=items)

    def fetch_delivery(
        self,
        *,
        request_id: str | None = None,
        message_id: str | None = None,
    ) -> list[DeliveryUpdate]:
        return []


class NullProvider(SmsProvider):
    """Test-only simulation provider."""

    provider_name = "null"

    def send(
        self,
        recipient: str,
        body: str,
        message_type: Optional[str] = None,
    ) -> SendResult:
        try:
            print(f"[NullSMS] -> {recipient}: {body}")
        except Exception:
            print(f"[NullSMS] -> {recipient}: <message>")
        return SendResult(
            ok=True,
            provider_msgid="SIMULATED",
            delivery_status="Accepted",
        )


class UnconfiguredProvider(SmsProvider):
    """Production-safe provider when the requested panel has no credential."""

    provider_name = "unconfigured"

    def __init__(self, requested_name: str | None = None):
        self.requested_name = str(requested_name or "").strip().lower() or None

    def send(
        self,
        recipient: str,
        body: str,
        message_type: Optional[str] = None,
    ) -> SendResult:
        label = self.requested_name or "انتخاب‌شده"
        return SendResult(
            ok=False,
            retryable=True,
            delivery_status="RetryableFailure",
            error=f"پنل پیامک {label} تنظیم نشده است",
        )


def selected_provider_name() -> str:
    try:
        from src.adapters.sqlite.sms_repo import SmsRepository

        value = str(SmsRepository().get_setting("sms_provider", "kavenegar") or "")
        value = value.strip().lower()
        return value if value in {"kavenegar", "mediana"} else "kavenegar"
    except Exception:
        return "kavenegar"


def _timeout(repo, key: str) -> int:
    try:
        return min(max(int(repo.get_setting(key, "45") or 45), 10), 120)
    except (TypeError, ValueError):
        return 45


def get_provider(provider_name: str | None = None) -> SmsProvider:
    """Return exactly the requested/configured provider; never silently fail over.

    Delivery reconciliation passes the provider stored on each message. New sends use the
    selected provider. If its credential is absent, production fails closed instead of
    silently sending through a different panel.
    """
    requested = str(provider_name or selected_provider_name()).strip().lower()
    if requested not in {"kavenegar", "mediana"}:
        return UnconfiguredProvider(requested)

    secret = get_sms_secret(requested)
    if secret:
        from src.adapters.sqlite.sms_repo import SmsRepository

        repo = SmsRepository()
        if requested == "kavenegar":
            from src.services.sms.kavenegar_provider import KavenegarProvider

            return KavenegarProvider(
                api_key=secret,
                sender=repo.get_setting("kavenegar_sender"),
                timeout=_timeout(repo, "kavenegar_timeout"),
            )
        from src.services.sms.mediana_provider import MedianaProvider

        return MedianaProvider(
            api_key=secret,
            sending_number=repo.get_setting("mediana_sending_number"),
            default_type=repo.get_setting(
                "mediana_message_type", "PromotionalToCustomers"
            ),
            timeout=_timeout(repo, "mediana_timeout"),
        )

    try:
        from flask import current_app

        if current_app.config.get("TESTING"):
            return NullProvider()
    except Exception:
        pass
    return UnconfiguredProvider(requested)


__all__ = [
    "BatchItemResult",
    "BatchSendResult",
    "DeliveryUpdate",
    "NullProvider",
    "OutgoingSms",
    "SendResult",
    "SmsProvider",
    "UnconfiguredProvider",
    "get_provider",
    "selected_provider_name",
]
