"""Mediana SMS provider adapter (https://api.mediana.ir).

Auth: header `X-API-KEY: <key>`.
Send a single normal SMS via POST /sms/v1/send/sms using either:
  - a dedicated sending number  -> SendSmsNormalWithNumber
  - or a message type           -> SendSmsNormalWithType  (Informational | PromotionalToCustomers | PromotionalAll)

Uses ``requests`` because Python's urllib receives intermittent ArvanCloud 502
responses for this API while requests/curl use the same endpoint successfully.
"""
from __future__ import annotations

import json
import socket
import requests

from src.services.sms.provider import (
    SmsProvider, SendResult, OutgoingSms, BatchSendResult, BatchItemResult,
    DeliveryUpdate,
)

BASE_URL = "https://api.mediana.ir"
SEND_SMS_PATH = "/sms/v1/send/sms"
BALANCE_PATH = "/sms/v1/account/balance"
SEND_ARRAY_PATH = "/sms/v1/send/array"
REQUEST_STATUS_PATH = "/sms/v1/send-requests/status/{request_id}"
ITEM_STATUS_PATH = "/sms/v1/send-requests/status/sms-item/{message_id}"

# Map Mediana numeric error codes -> Persian messages (from the API docs).
ERROR_CODES = {
    1032: "برنامه فعالی یافت نشد",
    1033: "برنامه قابلیت API ندارد",
    1034: "برنامه قابلیت الگو ندارد",
    1035: "برنامه قابلیت خط اختصاصی ندارد",
    1041: "دریافت‌کننده نامعتبر است",
    1042: "موجودی کیف پول پنل کافی نیست",
    1043: "تعداد دریافت‌کنندگان بیش از حد مجاز است",
    1046: "پارامترهای ورودی نامعتبر هستند",
    1047: "شماره در لیست سیاه قرار دارد",
    1048: "WebEngage فعال نشده است",
    1051: "کمپین منقضی شده است",
    1061: "خط فعالی یافت نشد",
    1062: "خط در این ساعت قابل استفاده نیست",
    1071: "نشانی URL در الگو شناسایی شد",
    1072: "الگو توسط مدیر رد شده است",
    1073: "الگو متعلق به شماره ارسال دیگری است",
    1074: "متن پیام خالی است",
    1075: "درخواست پیام یافت نشد",
    1076: "الگو خالی است",
    1081: "کد پستی تأیید نشده است",
    1082: "کد ملی تأیید نشده است",
    1083: "شماره موبایل تایید نشده است",
    1084: "پروفایل پنل کامل نشده است",
    1093: "دریافت‌کننده‌ای یافت نشد",
    1101: "شماره ارسال یافت نشد",
    1102: "شماره ارسال منقضی شده است",
    1021: "خطای ناشناخته در پنل",
}

VALID_TYPES = {"Informational", "PromotionalToCustomers", "PromotionalAll"}


def _field(mapping: dict, name: str, default=None):
    """Read Mediana fields in both documented PascalCase and live camelCase."""
    if not isinstance(mapping, dict):
        return default
    return mapping.get(name, mapping.get(name[:1].lower() + name[1:], default))


class MedianaProvider(SmsProvider):
    def __init__(self, api_key: str, sending_number: str | None = None,
                 default_type: str = "PromotionalToCustomers", timeout: int = 45):
        self.api_key = api_key
        self.sending_number = (sending_number or "").strip() or None
        self.default_type = default_type if default_type in VALID_TYPES else "PromotionalToCustomers"
        self.timeout = timeout

    def _post(self, path: str, payload: dict) -> tuple[int, dict]:
        url = BASE_URL + path
        response = requests.post(
            url,
            json=payload,
            headers={
                "Accept": "application/json",
                "X-API-KEY": self.api_key,
                "User-Agent": "SpecialistClinic/1.0",
            },
            timeout=self.timeout,
        )
        try:
            result = response.json() if response.content else {}
        except (requests.exceptions.JSONDecodeError, json.JSONDecodeError, ValueError):
            # Cloud/proxy failures may be HTML. Keep only the useful HTTP status.
            result = {
                "meta": {
                    "errorMessage": f"مدیانا پاسخ نامعتبر HTTP {response.status_code} برگرداند"
                }
            }
        return response.status_code, result

    def _get(self, path: str) -> tuple[int, dict]:
        response = requests.get(
            BASE_URL + path,
            headers={"Accept": "application/json", "X-API-KEY": self.api_key,
                     "User-Agent": "SpecialistClinic/1.0"},
            timeout=self.timeout,
        )
        try:
            result = response.json() if response.content else {}
        except (requests.exceptions.JSONDecodeError, json.JSONDecodeError, ValueError):
            result = {"meta": {"errorMessage":
                      f"مدیانا پاسخ نامعتبر HTTP {response.status_code} برگرداند"}}
        return response.status_code, result

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
        except (requests.exceptions.Timeout, socket.timeout, TimeoutError):
            # Mediana frequently ACCEPTS the SMS but answers slowly. A timeout here
            # means we never saw the response — the message was most likely sent, so
            # report PENDING (not failed) and do NOT retry (a retry would double-send).
            return SendResult(ok=False, pending=True,
                              error=f"پاسخِ پنل در مهلت {self.timeout} ثانیه نرسید؛ پیام احتمالاً ارسال شده است (در انتظار تأیید).")
        except requests.exceptions.ConnectionError as e:
            return SendResult(ok=False, error=f"خطای ارتباط با مدیانا: {e}")
        except Exception as e:
            return SendResult(ok=False, error=f"خطای ارتباط با مدیانا: {e}")

        if status == 401:
            return SendResult(ok=False, error="کلید API نامعتبر است (۴۰۱)")
        if status >= 400:
            return SendResult(ok=False, error=f"{self._extract_error(result)} (HTTP {status})")

        data = (result or {}).get("data") or {}
        if not _field(data, "Succeed", False):
            return SendResult(ok=False, error=_field(data, "Message") or self._extract_error(result))

        # Prefer the per-item id, else the request code.
        msgid = None
        items = _field(data, "SmsItems", []) or []
        if items and isinstance(items[0], dict):
            msgid = str(_field(items[0], "SmsItemId", "") or "")
        if not msgid:
            msgid = str(_field(data, "RequestCode") or _field(data, "RequestId") or "")
        return SendResult(
            ok=True,
            provider_msgid=msgid or None,
            provider_request_id=str(_field(data, "RequestCode") or _field(data, "RequestId") or "") or None,
            delivery_status=_field(data, "Status") or "PendingApproval",
            delivery_status_int=_field(data, "StatusInt"),
        )

    def send_batch(self, messages: list[OutgoingSms], message_type: str | None = None) -> BatchSendResult:
        if not messages:
            return BatchSendResult(items=[])
        mtype = message_type if message_type in VALID_TYPES else self.default_type
        payload = {
            "Requests": [
                {"RefId": m.ref_id, "TextMessage": m.body, "Recipients": [m.recipient]}
                for m in messages
            ]
        }
        if self.sending_number:
            payload["SendingNumber"] = self.sending_number
        else:
            payload["Type"] = mtype
        try:
            status, result = self._post(SEND_ARRAY_PATH, payload)
        except requests.exceptions.Timeout:
            return BatchSendResult(
                items=[BatchItemResult(ref_id=m.ref_id, ok=False, pending=True,
                                       error="پاسخ مدیانا نرسید؛ برای جلوگیری از تکرار، ارسال خودکار نمی‌شود")
                       for m in messages], pending=True)
        except requests.exceptions.ConnectionError as exc:
            return BatchSendResult(
                items=[BatchItemResult(ref_id=m.ref_id, ok=False, pending=True,
                                       error=f"نتیجه اتصال به مدیانا نامشخص است: {exc}") for m in messages],
                error=str(exc))
        if status == 401 or status >= 400:
            error = "کلید API نامعتبر است (۴۰۱)" if status == 401 else f"{self._extract_error(result)} (HTTP {status})"
            # A gateway may fail after Mediana accepted the body; never auto-resend.
            retryable = False
            return BatchSendResult(items=[BatchItemResult(
                ref_id=m.ref_id, ok=False, error=error, retryable=retryable) for m in messages], error=error)

        data = (result or {}).get("data") or {}
        ref_codes = _field(data, "RefCodes", []) or []
        if not ref_codes:
            error = _field(data, "Message") or self._extract_error(result)
            raw = str(result)
            retryable = '1042' in raw
            return BatchSendResult(items=[BatchItemResult(
                ref_id=m.ref_id, ok=False, error=error, retryable=retryable,
                delivery_status='RetryableFailure' if retryable else 'Failed') for m in messages],
                error=error)
        by_ref = {str(_field(item, "RefId", "")): item for item in ref_codes if isinstance(item, dict)}
        items = []
        for message in messages:
            item = by_ref.get(message.ref_id)
            if not item:
                items.append(BatchItemResult(
                    ref_id=message.ref_id, ok=False, pending=True,
                    error="مدیانا برای این گیرنده شناسه برنگرداند؛ ارسال مجدد خودکار متوقف شد"))
                continue
            request_id = str(_field(item, "Code", "") or "") or None
            items.append(BatchItemResult(
                ref_id=message.ref_id, ok=bool(request_id), provider_request_id=request_id,
                delivery_status="PendingApproval" if request_id else None,
                pending=not bool(request_id),
                error=None if request_id else "شناسه درخواست مدیانا خالی است",
            ))
        return BatchSendResult(items=items)

    def fetch_delivery(self, *, request_id: str | None = None,
                       message_id: str | None = None) -> list[DeliveryUpdate]:
        if not request_id and not message_id:
            return []
        path = (REQUEST_STATUS_PATH.format(request_id=request_id) if request_id
                else ITEM_STATUS_PATH.format(message_id=message_id))
        status_code, result = self._get(path)
        if status_code >= 400:
            raise requests.HTTPError(f"Mediana delivery HTTP {status_code}")
        data = (result or {}).get("data") or {}
        raw_items = _field(data, "SmsItems", None)
        if raw_items is None:
            # Request-level responses can briefly contain only processing metadata.
            # That is not an item delivery status and must not overwrite the last state.
            raw_items = [] if request_id else [data]
        updates = []
        for item in raw_items or []:
            if not isinstance(item, dict):
                continue
            updates.append(DeliveryUpdate(
                provider_request_id=request_id,
                provider_msgid=str(_field(item, "SmsItemId", "") or "") or message_id,
                recipient=str(_field(item, "Recipient", "") or "") or None,
                status=str(_field(item, "Status", "Unknown") or "Unknown"),
                status_int=_field(item, "StatusInt"),
                delivered_at=_field(item, "DeliveryDateTime"),
            ))
        return updates

    def get_balance(self) -> int | None:
        """Return the panel wallet balance, or None on failure."""
        try:
            response = requests.get(
                BASE_URL + BALANCE_PATH,
                headers={
                    "X-API-KEY": self.api_key,
                    "Accept": "application/json",
                    "User-Agent": "SpecialistClinic/1.0",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()
            return int(((result or {}).get("data") or {}).get("balance"))
        except (requests.RequestException, ValueError, TypeError):
            return None
