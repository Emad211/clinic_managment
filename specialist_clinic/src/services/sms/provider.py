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
    """Return the configured SMS provider.

    Honors the ``sms_provider`` setting ('kavenegar' | 'mediana'). If the selected
    panel has no API key, falls back to whichever panel *does* have a key, and
    finally to the Null (simulation) provider. Kavenegar is the project's primary panel.
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
        print(f"[sms] provider init failed, falling back to Null: {e}")
    return NullProvider()
