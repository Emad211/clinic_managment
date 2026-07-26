"""SMS provider abstraction and exact provider resolution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


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
    """Test/simulation provider: logs to console, never calls an external panel."""

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
        return SendResult(ok=True, provider_msgid="SIMULATED")


class UnconfiguredProvider(SmsProvider):
    """Production-safe provider when the requested panel is not configured."""

    def __init__(self, provider_name: str | None = None):
        self.provider_name = provider_name

    def send(
        self,
        recipient: str,
        body: str,
        message_type: Optional[str] = None,
    ) -> SendResult:
        label = f" ({self.provider_name})" if self.provider_name else ""
        return SendResult(
            ok=False,
            retryable=True,
            delivery_status="RetryableFailure",
            error=f"پنل پیامک فعال تنظیم نشده است{label}",
        )


def get_provider(
    provider_name: str | None = None,
    *,
    allow_fallback: bool | None = None,
) -> SmsProvider:
    """Return a provider.

    With ``provider_name`` the resolution is exact and never falls back to a different
    panel. Without it, configured preference/fallback behavior is preserved for new sends.
    """
    exact = provider_name is not None
    if allow_fallback is None:
        allow_fallback = not exact
    requested = str(provider_name or "").strip().lower()
    try:
        from src.adapters.sqlite.sms_repo import SmsRepository

        repo = SmsRepository()
        kav_key = (repo.get_setting("kavenegar_api_key") or "").strip()
        med_key = (repo.get_setting("mediana_api_key") or "").strip()
        preference = (repo.get_setting("sms_provider") or "").strip().lower()

        def timeout(key: str) -> int:
            try:
                return int(repo.get_setting(key, "45") or 45)
            except (TypeError, ValueError):
                return 45

        def kavenegar() -> SmsProvider:
            from src.services.sms.kavenegar_provider import KavenegarProvider

            return KavenegarProvider(
                api_key=kav_key,
                sender=repo.get_setting("kavenegar_sender"),
                timeout=timeout("kavenegar_timeout"),
            )

        def mediana() -> SmsProvider:
            from src.services.sms.mediana_provider import MedianaProvider

            return MedianaProvider(
                api_key=med_key,
                sending_number=repo.get_setting("mediana_sending_number"),
                default_type=repo.get_setting(
                    "mediana_message_type", "PromotionalToCustomers"
                ),
                timeout=timeout("mediana_timeout"),
            )

        if requested in {"null", "simulated"}:
            return NullProvider()
        if requested == "kavenegar":
            return kavenegar() if kav_key else UnconfiguredProvider("kavenegar")
        if requested == "mediana":
            return mediana() if med_key else UnconfiguredProvider("mediana")
        if exact:
            return UnconfiguredProvider(requested or "unknown")

        if preference not in {"kavenegar", "mediana"}:
            preference = "kavenegar" if kav_key else ("mediana" if med_key else "")
        if preference == "kavenegar" and kav_key:
            return kavenegar()
        if preference == "mediana" and med_key:
            return mediana()
        if allow_fallback:
            if kav_key:
                return kavenegar()
            if med_key:
                return mediana()
    except Exception as exc:
        print(f"[sms] provider init failed: {exc}")

    try:
        from flask import current_app

        if current_app.config.get("TESTING"):
            return NullProvider()
    except Exception:
        pass
    return UnconfiguredProvider(requested or None)
