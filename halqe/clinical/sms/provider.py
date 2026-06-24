"""
clinical/sms/provider.py — SMS provider abstraction for the halqe platform.

Faithful port of specialist_clinic/src/services/sms/provider.py and
specialist_clinic/src/services/sms/kavenegar_provider.py.

Design
------
- SendResult: plain dataclass returned by every provider.
- SmsProvider: abstract base; subclasses implement send().
- NullProvider: simulation-only; logs to stdout, NEVER sends a real SMS.
  Used in all tests and as the default fallback when no API key is configured.
- KavenegarProvider: production provider (stdlib urllib; key in URL path).
- get_provider(): reads config from Django settings; returns NullProvider
  when no key is present (the practical default — Kavenegar account is
  KYC-blocked, code 430, until the clinic owner completes verification).

KAVENEGAR KYC GATE (code 430)
------------------------------
The live Kavenegar API key is valid, but the account has not completed
KYC/identity verification in the Kavenegar panel.  Until the owner
finishes this process, ALL real sends return HTTP 4xx with:
  {"return": {"status": 430, "message": "..."}}
which means "account not verified — complete KYC in the panel".
This is a KNOWN gate — NOT a code bug.  NullProvider is used in ALL
tests and in development.  The production path goes live only after KYC.

CRITICAL: NEVER send a real SMS in tests.
  - Tests must inject NullProvider directly (or via get_provider() with no key).
  - get_provider() returns NullProvider when no API key is configured.
  - KavenegarProvider is only constructed when an actual key is present.

Compliance note
---------------
SMS body must be sanitized by clinical.sms.compliance.sanitize() before sending.
Promotional words («رایگان», «تخفیف», …) are banned by Iranian operators.
Wallet credit framing («اعتبار هدیه») is the lawful alternative.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

from django.conf import settings


# ---------------------------------------------------------------------------
# SendResult
# ---------------------------------------------------------------------------

@dataclass
class SendResult:
    """Return value from SmsProvider.send()."""
    ok: bool
    provider_msgid: Optional[str] = None
    error: Optional[str] = None
    pending: bool = False
    # pending=True means the provider received the request but timed out before
    # returning a confirmation.  The message was MOST LIKELY sent — callers
    # MUST NOT retry (that would double-send).  Log it as 'pending', not 'failed'.


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class SmsProvider:
    """Abstract SMS provider.  All concrete providers implement send()."""

    def send(
        self,
        recipient: str,
        body: str,
        message_type: Optional[str] = None,
    ) -> SendResult:  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# NullProvider — simulation / test / default-when-no-key
# ---------------------------------------------------------------------------

class NullProvider(SmsProvider):
    """
    Simulation provider: logs to stdout, NEVER sends a real SMS.

    This is the ONLY provider used in tests and in development.
    It is also returned by get_provider() when no API key is configured.

    Returns SendResult(ok=True, provider_msgid='SIMULATED') so callers
    treat it as a successful send — but no HTTP request is ever made.
    """

    def send(
        self,
        recipient: str,
        body: str,
        message_type: Optional[str] = None,
    ) -> SendResult:
        # Windows cp1252 / encoding-safe log
        try:
            print(f"[NullSMS] -> {recipient}: {body}")
        except Exception:
            print(f"[NullSMS] -> {recipient}: <message>")
        return SendResult(ok=True, provider_msgid="SIMULATED")


# ---------------------------------------------------------------------------
# KavenegarProvider — production provider (stdlib urllib; key in URL path)
# ---------------------------------------------------------------------------

_KAVENEGAR_BASE = "https://api.kavenegar.com/v1"

# return.status → Persian message map (faithful port from specialist_clinic).
# Source: https://kavenegar.com/rest.html (docs/kavenegar_reference.md).
_KAVENEGAR_CODES: dict[int, str] = {
    200: "تأیید شد",
    400: "پارامترها ناقص هستند",
    401: "حساب کاربری غیرفعال است",
    402: "عملیات ناموفق بود",
    403: "کد شناسایی (API-Key) معتبر نیست",
    404: "متد نامشخص است",
    405: "متد Get/Post اشتباه است",
    406: "پارامترهای اجباری خالی ارسال شده‌اند",
    407: "دسترسی به اطلاعات مورد نظر برای شما امکان‌پذیر نیست (IP مجاز نشده)",
    409: "سرور قادر به پاسخ‌گویی نیست؛ کمی بعد دوباره تلاش کنید",
    411: "دریافت‌کننده نامعتبر است",
    412: "ارسال‌کننده نامعتبر است",
    413: "پیام خالی است یا طول پیام از حد مجاز بیشتر است",
    414: "حجم درخواست بیشتر از حد مجاز است (هر بار حداکثر ۲۰۰ رکورد)",
    416: "IP سرویس‌دهنده با IP ثبت‌شده مطابقت ندارد",
    418: "اعتبار حساب شما کافی نیست",
    422: "داده‌ها به‌دلیل وجود کاراکتر نامناسب قابل پردازش نیستند",
    424: "الگوی موردنظر یافت نشد یا تأیید نشده است",
    # 430 = KYC gate — the KNOWN blocker for this project.
    430: (
        "حساب کاربری در کاوه‌نگار احراز هویت نشده است "
        "(در پنل کاوه‌نگار احراز هویت را کامل کنید — KNOWN KYC gate)"
    ),
}


class KavenegarProvider(SmsProvider):
    """
    Kavenegar SMS provider.

    Auth: API key is part of the URL path (NOT a header):
      https://api.kavenegar.com/v1/{API-KEY}/sms/send.json

    Envelope:
      {"return": {"status": 200, "message": "..."},
       "entries": [{"messageid": 123, "status": 1, ...}]}

    return.status == 200 → ok; any other value → error (mapped to Persian).
    Timeout → pending=True (NOT failed) — the message was most likely sent;
    callers must NOT retry.

    Uses only stdlib (urllib) — no extra deps, works in the .exe build.

    KNOWN GATE: this account returns code 430 (KYC not completed) until the
    clinic owner finishes identity verification in the Kavenegar panel.
    """

    def __init__(
        self,
        api_key: str,
        sender: Optional[str] = None,
        timeout: int = 45,
    ):
        self.api_key = (api_key or "").strip()
        # sender: optional dedicated line. If blank, Kavenegar uses the account
        # default line (account/config defaultsender). Do not pass empty string.
        self.sender = (sender or "").strip() or None
        self.timeout = timeout

    def _request(
        self,
        method: str,
        payload: Optional[dict] = None,
        http_method: str = "POST",
    ) -> tuple[int, dict]:
        """Call a Kavenegar method; return (http_status, parsed_json_envelope)."""
        url = f"{_KAVENEGAR_BASE}/{self.api_key}/{method}.json"
        data = None
        if http_method == "POST":
            data = urllib.parse.urlencode(payload or {}).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=http_method)
        if data is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body_bytes = resp.read().decode("utf-8")
                return resp.status, (json.loads(body_bytes) if body_bytes else {})
        except urllib.error.HTTPError as exc:
            # Kavenegar returns the JSON envelope even on 4xx (including 430).
            try:
                body_bytes = exc.read().decode("utf-8")
                return exc.code, (json.loads(body_bytes) if body_bytes else {})
            except Exception:
                return exc.code, {}

    def send(
        self,
        recipient: str,
        body: str,
        message_type: Optional[str] = None,
    ) -> SendResult:
        """
        Send a single SMS via Kavenegar sms/send.

        message_type is intentionally IGNORED — Kavenegar has no type param
        on sms/send; the service line determines promotional vs. informational.
        """
        if not body or not body.strip():
            return SendResult(ok=False, error="متن پیام خالی است")

        payload = {"receptor": recipient, "message": body}
        if self.sender:
            payload["sender"] = self.sender

        try:
            _http, result = self._request("sms/send", payload)
        except (socket.timeout, TimeoutError):
            return SendResult(
                ok=False,
                pending=True,
                error=(
                    f"پاسخِ کاوه‌نگار در مهلت {self.timeout} ثانیه نرسید؛ "
                    "پیام احتمالاً ارسال شده است (در انتظار تأیید)."
                ),
            )
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                return SendResult(
                    ok=False,
                    pending=True,
                    error="پاسخِ کاوه‌نگار با تأخیر دریافت نشد (timeout)؛ احتمالاً ارسال شده است.",
                )
            return SendResult(ok=False, error=f"خطای ارتباط با کاوه‌نگار: {reason or exc}")
        except Exception as exc:
            return SendResult(ok=False, error=f"خطای ارتباط با کاوه‌نگار: {exc}")

        ret = (result or {}).get("return") or {}
        status = ret.get("status")
        if status == 200:
            entries = (result or {}).get("entries") or []
            msgid = None
            if isinstance(entries, list) and entries and isinstance(entries[0], dict):
                msgid = str(entries[0].get("messageid") or "")
            return SendResult(ok=True, provider_msgid=msgid or None)

        msg = _KAVENEGAR_CODES.get(status) or ret.get("message") or "خطای نامشخص از پنل کاوه‌نگار"
        return SendResult(ok=False, error=f"{msg} (کد {status})" if status else msg)

    def get_balance(self) -> Optional[int]:
        """
        Account remaining credit in Rials, or None on failure.

        Uses account/info (GET, read-only).  Does NOT send any SMS and does NOT
        consume credit.  Safe to use as a connectivity / key-validity check.
        """
        try:
            _http, result = self._request("account/info", http_method="GET")
            entries = (result or {}).get("entries") or {}
            if isinstance(entries, dict) and entries.get("remaincredit") is not None:
                return int(entries["remaincredit"])
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# compliance helpers (imported here for caller convenience)
# ---------------------------------------------------------------------------

def sanitize_body(text: str) -> str:
    """
    Auto-replace banned promotional words with compliant alternatives.

    Thin wrapper around clinical.sms.compliance.sanitize so callers only need
    to import from this module.
    """
    from clinical.sms.compliance import sanitize
    return sanitize(text)


# ---------------------------------------------------------------------------
# get_provider() — factory; falls back to NullProvider when no key configured
# ---------------------------------------------------------------------------

def get_provider() -> SmsProvider:
    """
    Return the configured SMS provider for the halqe platform.

    Configuration is read from Django settings:
      SMS_PROVIDER     : 'kavenegar' (default) | 'null'
      KAVENEGAR_API_KEY: str (required for Kavenegar)
      KAVENEGAR_SENDER : str (optional; uses account default if blank)
      KAVENEGAR_TIMEOUT: int seconds (default 45)

    Falls back to NullProvider when:
      - No KAVENEGAR_API_KEY is set (the practical default — KYC blocked)
      - SMS_PROVIDER is explicitly 'null'
      - Any exception occurs during provider construction

    KAVENEGAR KYC GATE: even with a valid key, Kavenegar returns code 430
    (KYC not completed) until the owner finishes verification.  NullProvider
    is the correct choice during development and testing.

    NEVER returns a real provider in tests — inject NullProvider directly:
        provider = NullProvider()
        result = provider.send(...)
    """
    try:
        provider_name = getattr(settings, "SMS_PROVIDER", "kavenegar").lower().strip()
        if provider_name == "null":
            return NullProvider()

        if provider_name == "kavenegar":
            api_key = (getattr(settings, "KAVENEGAR_API_KEY", None) or "").strip()
            if not api_key:
                # No key → NullProvider (KYC gate or not yet configured)
                return NullProvider()
            timeout = int(getattr(settings, "KAVENEGAR_TIMEOUT", 45) or 45)
            sender = (getattr(settings, "KAVENEGAR_SENDER", None) or "").strip() or None
            return KavenegarProvider(api_key=api_key, sender=sender, timeout=timeout)

    except Exception as exc:
        print(f"[sms] provider init failed, falling back to NullProvider: {exc}")

    return NullProvider()
