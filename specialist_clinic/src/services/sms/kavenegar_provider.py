"""Kavenegar SMS provider adapter (https://api.kavenegar.com).

Auth differs from Mediana: the API key is part of the **URL path**, not a header:

    https://api.kavenegar.com/v1/{API-KEY}/sms/send.json

A single SMS is sent with POST to ``sms/send`` and a form-urlencoded body
``{receptor, message, sender?}``. Kavenegar always answers with the envelope::

    {"return": {"status": 200, "message": "..."},
     "entries": [{"messageid": 123, "status": 1, "statustext": "...", ...}]}

``return.status == 200`` means accepted; any other value is an error whose code
is mapped to a Persian message below. ``entries[0].messageid`` is the provider id.

Uses only the Python stdlib (urllib) so the packaged .exe needs no extra deps.
See ``docs/kavenegar_reference.md`` for the full API reference.
"""
from __future__ import annotations

import json
import socket
import urllib.parse
import urllib.request
import urllib.error

from src.services.sms.provider import SmsProvider, SendResult

BASE_URL = "https://api.kavenegar.com/v1"

# General API result codes (the `return.status` field) -> Persian messages.
# Source: https://kavenegar.com/rest.html (see docs/kavenegar_reference.md).
RETURN_CODES = {
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
    415: "اندیس شروع بزرگ‌تر از تعداد کل پیام‌ها است",
    416: "IP سرویس‌دهنده با IP ثبت‌شده مطابقت ندارد",
    417: "تاریخ ارسال اشتباه است (گذشته یا فرمت نادرست)",
    418: "اعتبار حساب شما کافی نیست",
    422: "داده‌ها به‌دلیل وجود کاراکتر نامناسب قابل پردازش نیستند",
    424: "الگوی موردنظر یافت نشد یا تأیید نشده است",
    426: "استفاده از این متد نیازمند سرویس پیشرفته است",
    428: "ارسال کد از طریق تماس صوتی نیازمند عددی‌بودن توکن است",
    430: "حساب کاربری در کاوه‌نگار احراز هویت نشده است (در پنل احراز هویت را کامل کنید)",
    431: "ساختار کد صحیح نیست",
    432: "پارامتر کد در متن پیام یافت نشد",
}


class KavenegarProvider(SmsProvider):
    def __init__(self, api_key: str, sender: str | None = None, timeout: int = 45):
        self.api_key = (api_key or "").strip()
        # Optional dedicated/service line. If blank, Kavenegar uses the account
        # default line configured in the panel (account/config defaultsender).
        self.sender = (sender or "").strip() or None
        self.timeout = timeout

    def _request(self, method: str, payload: dict | None = None,
                 http_method: str = "POST") -> tuple[int, dict]:
        """Call a Kavenegar method; return (http_status, parsed_json_envelope)."""
        url = f"{BASE_URL}/{self.api_key}/{method}.json"
        data = None
        if http_method == "POST":
            data = urllib.parse.urlencode(payload or {}).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=http_method)
        if data is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
                return resp.status, (json.loads(body) if body else {})
        except urllib.error.HTTPError as e:
            # Kavenegar returns the JSON envelope even on 4xx; the real code is in return.status.
            try:
                body = e.read().decode("utf-8")
                return e.code, (json.loads(body) if body else {})
            except Exception:
                return e.code, {}

    def send(self, recipient: str, body: str, message_type: str | None = None) -> SendResult:
        if not body or not body.strip():
            return SendResult(ok=False, error="متن پیام خالی است")

        # Kavenegar has no Informational/Promotional "type" on sms/send — the LINE
        # determines service vs advertising — so `message_type` is intentionally ignored.
        payload = {"receptor": recipient, "message": body}
        if self.sender:
            payload["sender"] = self.sender

        try:
            _http, result = self._request("sms/send", payload)
        except (socket.timeout, TimeoutError):
            # Like Mediana, Kavenegar may ACCEPT the SMS but answer slowly. A timeout
            # means we never saw the response — the message was most likely sent, so
            # report PENDING (not failed) and do NOT retry (a retry would double-send).
            return SendResult(ok=False, pending=True,
                              error=f"پاسخِ کاوه‌نگار در مهلت {self.timeout} ثانیه نرسید؛ پیام احتمالاً ارسال شده است (در انتظار تأیید).")
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", None)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                return SendResult(ok=False, pending=True,
                                  error="پاسخِ کاوه‌نگار با تأخیر دریافت نشد (timeout)؛ پیام احتمالاً ارسال شده است (در انتظار تأیید).")
            # A real connection failure (refused/DNS/unreachable) — never reached the panel.
            return SendResult(ok=False, error=f"خطای ارتباط با کاوه‌نگار: {reason or e}")
        except Exception as e:
            return SendResult(ok=False, error=f"خطای ارتباط با کاوه‌نگار: {e}")

        ret = (result or {}).get("return") or {}
        status = ret.get("status")
        if status == 200:
            entries = (result or {}).get("entries") or []
            msgid = None
            if isinstance(entries, list) and entries and isinstance(entries[0], dict):
                msgid = str(entries[0].get("messageid") or "")
            return SendResult(ok=True, provider_msgid=msgid or None)

        # Error: prefer our mapped Persian text, fall back to the panel's own message.
        msg = RETURN_CODES.get(status) or ret.get("message") or "خطای نامشخص از پنل کاوه‌نگار"
        return SendResult(ok=False, error=f"{msg} (کد {status})" if status else msg)

    def get_balance(self) -> int | None:
        """Account remaining credit in Rials, or None on failure.

        Calls the read-only ``account/info`` method — it does NOT send any SMS and
        does NOT cost credit, so it is safe to use as a connectivity/key check.
        """
        try:
            _http, result = self._request("account/info", http_method="GET")
            entries = (result or {}).get("entries") or {}
            if isinstance(entries, dict) and entries.get("remaincredit") is not None:
                return int(entries.get("remaincredit"))
        except Exception:
            pass
        return None
