"""Kavenegar SMS adapter with submission and read-only delivery lookup."""
from __future__ import annotations

from datetime import datetime
import json
import socket
import urllib.error
import urllib.parse
import urllib.request

from src.services.sms.provider import DeliveryUpdate, SendResult, SmsProvider


BASE_URL = "https://api.kavenegar.com/v1"

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
    414: "حجم درخواست بیشتر از حد مجاز است",
    415: "اندیس شروع بزرگ‌تر از تعداد کل پیام‌ها است",
    416: "IP سرویس‌دهنده با IP ثبت‌شده مطابقت ندارد",
    417: "تاریخ ارسال اشتباه است",
    418: "اعتبار حساب شما کافی نیست",
    422: "داده‌ها به‌دلیل وجود کاراکتر نامناسب قابل پردازش نیستند",
    424: "الگوی موردنظر یافت نشد یا تأیید نشده است",
    426: "استفاده از این متد نیازمند سرویس پیشرفته است",
    428: "ارسال کد از طریق تماس صوتی نیازمند عددی‌بودن توکن است",
    430: "حساب کاربری در کاوه‌نگار احراز هویت نشده است",
    431: "ساختار کد صحیح نیست",
    432: "پارامتر کد در متن پیام یافت نشد",
}

KAVENEGAR_DELIVERY_STATUS = {
    1: "Queued",
    2: "Scheduled",
    4: "SendToOperator",
    5: "SendToOperator",
    6: "Failed",
    10: "Delivered",
    11: "Undelivered",
    13: "Canceled",
    14: "NumberBlackListed",
    100: "StatusUnknown",
}


class KavenegarProvider(SmsProvider):
    provider_name = "kavenegar"

    def __init__(self, api_key: str, sender: str | None = None, timeout: int = 45):
        self.api_key = (api_key or "").strip()
        self.sender = (sender or "").strip() or None
        self.timeout = timeout

    def _request(
        self,
        method: str,
        payload: dict | None = None,
        http_method: str = "POST",
    ) -> tuple[int, dict]:
        url = f"{BASE_URL}/{self.api_key}/{method}.json"
        data = None
        if http_method == "POST":
            data = urllib.parse.urlencode(payload or {}).encode("utf-8")
        elif payload:
            url += "?" + urllib.parse.urlencode(payload)
        request = urllib.request.Request(url, data=data, method=http_method)
        if data is not None:
            request.add_header("Content-Type", "application/x-www-form-urlencoded")
        request.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                return response.status, (json.loads(body) if body else {})
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8")
                return exc.code, (json.loads(body) if body else {})
            except Exception:
                return exc.code, {}

    @staticmethod
    def _return_error(result: dict) -> str | None:
        envelope = (result or {}).get("return") or {}
        status = envelope.get("status")
        if status == 200:
            return None
        message = (
            RETURN_CODES.get(status)
            or envelope.get("message")
            or "خطای نامشخص از پنل کاوه‌نگار"
        )
        return f"{message} (کد {status})" if status else str(message)

    def send(
        self,
        recipient: str,
        body: str,
        message_type: str | None = None,
    ) -> SendResult:
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
                delivery_status="SubmissionUnknown",
                error=(
                    f"پاسخ کاوه‌نگار در مهلت {self.timeout} ثانیه نرسید؛ "
                    "برای جلوگیری از ارسال تکراری retry نمی‌شود"
                ),
            )
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                return SendResult(
                    ok=False,
                    pending=True,
                    delivery_status="SubmissionUnknown",
                    error="نتیجهٔ ثبت پیام در کاوه‌نگار نامشخص است",
                )
            return SendResult(
                ok=False,
                retryable=True,
                delivery_status="RetryableFailure",
                error=f"خطای ارتباط با کاوه‌نگار: {reason or exc}",
            )
        except Exception as exc:
            return SendResult(
                ok=False,
                retryable=True,
                delivery_status="RetryableFailure",
                error=f"خطای ارتباط با کاوه‌نگار: {exc}",
            )

        error = self._return_error(result)
        if error:
            return SendResult(ok=False, delivery_status="Failed", error=error)
        entries = (result or {}).get("entries") or []
        entry = entries[0] if isinstance(entries, list) and entries else {}
        message_id = str(entry.get("messageid") or "").strip() or None
        try:
            status_int = int(entry.get("status"))
        except (TypeError, ValueError):
            status_int = None
        status = KAVENEGAR_DELIVERY_STATUS.get(status_int, "Accepted")
        return SendResult(
            ok=True,
            provider_msgid=message_id,
            delivery_status=status,
            delivery_status_int=status_int,
        )

    def fetch_delivery(
        self,
        *,
        request_id: str | None = None,
        message_id: str | None = None,
    ) -> list[DeliveryUpdate]:
        identifier = str(message_id or request_id or "").strip()
        if not identifier:
            return []
        _http, result = self._request(
            "sms/status",
            {"messageid": identifier},
            http_method="GET",
        )
        error = self._return_error(result)
        if error:
            raise RuntimeError(error)
        entries = (result or {}).get("entries") or []
        if not isinstance(entries, list):
            return []
        updates: list[DeliveryUpdate] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                status_int = int(entry.get("status"))
            except (TypeError, ValueError):
                status_int = None
            status = KAVENEGAR_DELIVERY_STATUS.get(status_int, "StatusUnknown")
            updates.append(
                DeliveryUpdate(
                    provider_request_id=None,
                    provider_msgid=str(entry.get("messageid") or "").strip() or identifier,
                    recipient=str(entry.get("receptor") or "").strip() or None,
                    status=status,
                    status_int=status_int,
                    delivered_at=(
                        datetime.now().isoformat(sep=" ", timespec="seconds")
                        if status == "Delivered"
                        else None
                    ),
                )
            )
        return updates

    def get_balance(self) -> int | None:
        try:
            _http, result = self._request("account/info", http_method="GET")
            if self._return_error(result):
                return None
            entries = (result or {}).get("entries") or {}
            if isinstance(entries, dict) and entries.get("remaincredit") is not None:
                return int(entries.get("remaincredit"))
        except Exception:
            pass
        return None


__all__ = [
    "KAVENEGAR_DELIVERY_STATUS",
    "KavenegarProvider",
]
