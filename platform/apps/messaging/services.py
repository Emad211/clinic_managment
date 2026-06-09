"""SMS sending (Mediana) with a NullProvider fallback — ported in spirit from
specialist_clinic/src/services/sms/.

Provider is chosen at runtime: if a Mediana API key is configured (env
MEDIANA_API_KEY for now; per-tenant clinic_setting later) the real provider is
used, otherwise a NullProvider simulates the send (status='simulated'). A small
compliance layer rewrites banned promotional words; patient wallet credit is the
lawful substitute for "discount/free". Every send is recorded as an SmsMessage.
"""

import json
import os
import urllib.error
import urllib.request

from django.utils import timezone

from apps.messaging.models import SmsMessage

MEDIANA_URL = "https://api.mediana.ir/sms/v1/send/sms"

# Banned promo words -> compliant rewrites (mirrors compliance.py intent).
_BANNED = {
    "رایگان": "هدیهٔ باشگاه",
    "مجانی": "هدیهٔ باشگاه",
    "تخفیف": "اعتبار کیف‌پول",
    "ارزان": "مقرون‌به‌صرفه",
}


def comply(text: str) -> str:
    for bad, good in _BANNED.items():
        text = text.replace(bad, good)
    return text


class NullProvider:
    """Simulated send (no key configured) — for dev and graceful degradation."""

    name = "null"

    def send(self, to: str, body: str) -> dict:
        return {"status": "simulated", "id": ""}


class MedianaProvider:
    name = "mediana"

    def __init__(self, api_key: str, sender: str = ""):
        self.api_key = api_key
        self.sender = sender

    def send(self, to: str, body: str) -> dict:
        payload = json.dumps({
            "recipients": [to],
            "message": body,
            "sending_type": "webservice",
            **({"line_number": self.sender} if self.sender else {}),
        }).encode("utf-8")
        req = urllib.request.Request(
            MEDIANA_URL, data=payload, method="POST",
            headers={"Content-Type": "application/json", "X-API-KEY": self.api_key},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8") or "{}")
            return {"status": "sent", "id": str(data.get("id", ""))}
        except (urllib.error.URLError, ValueError, TimeoutError):
            return {"status": "failed", "id": ""}


def get_provider():
    key = os.getenv("MEDIANA_API_KEY", "").strip()
    if key:
        return MedianaProvider(key, os.getenv("MEDIANA_SENDER", ""))
    return NullProvider()


def send_sms(clinic, to, body, patient=None, campaign=None) -> SmsMessage:
    """Send (or simulate) one SMS and record it. Returns the SmsMessage."""
    body = comply(body or "")
    provider = get_provider()
    try:
        result = provider.send(to or "", body)
    except Exception:
        result = {"status": "failed", "id": ""}
    status = result.get("status", "failed")
    return SmsMessage.objects.create(
        clinic=clinic, patient=patient, campaign=campaign,
        to_number=to or "", body=body, status=status,
        provider_message_id=result.get("id", ""),
        sent_at=timezone.now() if status in ("sent", "simulated", "delivered") else None,
    )
