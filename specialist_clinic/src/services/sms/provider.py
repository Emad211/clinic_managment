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


class SmsProvider:
    def send(self, recipient: str, body: str, message_type: Optional[str] = None) -> SendResult:  # pragma: no cover
        raise NotImplementedError


class NullProvider(SmsProvider):
    """Test/simulation provider: logs to console, never actually sends."""

    def send(self, recipient: str, body: str, message_type: Optional[str] = None) -> SendResult:
        # Console-encoding-safe log (Windows cp1252 can't print Persian).
        try:
            print(f"[NullSMS] -> {recipient}: {body}")
        except Exception:
            print(f"[NullSMS] -> {recipient}: <message>")
        return SendResult(ok=True, provider_msgid="SIMULATED")


def get_provider() -> SmsProvider:
    """Return the configured provider (Mediana if API key present, else Null)."""
    try:
        from src.adapters.sqlite.sms_repo import SmsRepository
        repo = SmsRepository()
        api_key = repo.get_setting('mediana_api_key')
        if api_key:
            from src.services.sms.mediana_provider import MedianaProvider
            return MedianaProvider(
                api_key=api_key,
                sending_number=repo.get_setting('mediana_sending_number'),
                default_type=repo.get_setting('mediana_message_type', 'PromotionalToCustomers'),
            )
    except Exception as e:
        print(f"[sms] provider init failed, falling back to Null: {e}")
    return NullProvider()
