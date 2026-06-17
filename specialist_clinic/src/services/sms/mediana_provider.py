"""Mediana SMS provider adapter (https://api.mediana.ir).

Auth: header `X-API-KEY: <key>`.
Send a single normal SMS via POST /sms/v1/send/sms using either:
  - a dedicated sending number  -> SendSmsNormalWithNumber
  - or a message type           -> SendSmsNormalWithType  (Informational | PromotionalToCustomers | PromotionalAll)

Uses only the Python stdlib (urllib) so the packaged .exe needs no extra deps.
"""
from __future__ import annotations

import json
import socket
import urllib.request
import urllib.error

from src.services.sms.provider import SmsProvider, SendResult

BASE_URL = "https://api.mediana.ir"
SEND_SMS_PATH = "/sms/v1/send/sms"
BALANCE_PATH = "/sms/v1/account/balance"

# Map Mediana numeric error codes -> Persian messages (from the API docs).
ERROR_CODES = {
    1041: "دریافت‌کننده نامعتبر است",
    1042: "موجودی کیف پول پنل کافی نیست",
    1043: "تعداد دریافت‌کنندگان بیش از حد مجاز است",
    1046: "پارامترهای ورودی نامعتبر هستند",
    1047: "شماره در لیست سیاه قرار دارد",
    1061: "خط فعالی یافت نشد",
    1074: "متن پیام خالی است",
    1083: "شماره موبایل تایید نشده است",
    1093: "دریافت‌کننده‌ای یافت نشد",
    1101: "شماره ارسال یافت نشد",
    1102: "شماره ارسال منقضی شده است",
    1021: "خطای ناشناخته در پنل",
}

VALID_TYPES = {"Informational", "PromotionalToCustomers", "PromotionalAll"}


class MedianaProvider(SmsProvider):
    def __init__(self, api_key: str, sending_number: str | None = None,
                 default_type: str = "PromotionalToCustomers", timeout: int = 45):
        self.api_key = api_key
        self.sending_number = (sending_number or "").strip() or None
        self.default_type = default_type if default_type in VALID_TYPES else "PromotionalToCustomers"
        self.timeout = timeout

    def _post(self, path: str, payload: dict) -> tuple[int, dict]:
        url = BASE_URL + path
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        req.add_header("X-API-KEY", self.api_key)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
                return resp.status, (json.loads(body) if body else {})
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8")
                return e.code, (json.loads(body) if body else {})
            except Exception:
                return e.code, {}

    @staticmethod
    def _extract_error(result: dict) -> str:
        meta = (result or {}).get("meta") or {}
        if meta.get("errorMessage"):
            return str(meta["errorMessage"])
        errs = meta.get("errors") or []
        parts = []
        for er in errs:
            if isinstance(er, dict):
                code = er.get("errorCode")
                if code in ERROR_CODES:
                    parts.append(ERROR_CODES[code])
                elif er.get("errors"):
                    parts.append("، ".join(map(str, er["errors"])))
                elif er.get("key"):
                    parts.append(str(er["key"]))
            else:
                parts.append(str(er))
        return "؛ ".join(parts) if parts else "خطای نامشخص از پنل مدیانا"

    def send(self, recipient: str, body: str, message_type: str | None = None) -> SendResult:
        if not body or not body.strip():
            return SendResult(ok=False, error="متن پیام خالی است")

        if self.sending_number:
            payload = {
                "sendingNumber": self.sending_number,
                "recipients": [recipient],
                "messageText": body,
            }
        else:
            mtype = message_type if message_type in VALID_TYPES else self.default_type
            payload = {
                "type": mtype,
                "recipients": [recipient],
                "messageText": body,
            }

        try:
            status, result = self._post(SEND_SMS_PATH, payload)
        except (socket.timeout, TimeoutError):
            # Mediana frequently ACCEPTS the SMS but answers slowly. A timeout here
            # means we never saw the response — the message was most likely sent, so
            # report PENDING (not failed) and do NOT retry (a retry would double-send).
            return SendResult(ok=False, pending=True,
                              error=f"پاسخِ پنل در مهلت {self.timeout} ثانیه نرسید؛ پیام احتمالاً ارسال شده است (در انتظار تأیید).")
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", None)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                return SendResult(ok=False, pending=True,
                                  error="پاسخِ پنل با تأخیر دریافت نشد (timeout)؛ پیام احتمالاً ارسال شده است (در انتظار تأیید).")
            # A real connection failure (refused/DNS/unreachable) — the request never
            # reached the panel, so this is a genuine failure.
            return SendResult(ok=False, error=f"خطای ارتباط با مدیانا: {reason or e}")
        except Exception as e:
            return SendResult(ok=False, error=f"خطای ارتباط با مدیانا: {e}")

        if status == 401:
            return SendResult(ok=False, error="کلید API نامعتبر است (۴۰۱)")
        if status >= 400:
            return SendResult(ok=False, error=self._extract_error(result))

        data = (result or {}).get("data") or {}
        if not data.get("Succeed", False):
            return SendResult(ok=False, error=data.get("Message") or self._extract_error(result))

        # Prefer the per-item id, else the request code.
        msgid = None
        items = data.get("SmsItems") or []
        if items and isinstance(items[0], dict):
            msgid = str(items[0].get("SmsItemId") or "")
        if not msgid:
            msgid = str(data.get("RequestCode") or data.get("RequestId") or "")
        return SendResult(ok=True, provider_msgid=msgid or None)

    def get_balance(self) -> int | None:
        """Return the panel wallet balance, or None on failure."""
        url = BASE_URL + BALANCE_PATH
        req = urllib.request.Request(url, method="GET")
        req.add_header("X-API-KEY", self.api_key)
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            return int(((result or {}).get("data") or {}).get("balance"))
        except Exception:
            return None
