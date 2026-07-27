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
    provider_name = "mediana"

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
            headers={"X-API-KEY": self.api_key, "Content-Type": "application/json",
                     "User-Agent": "SpecialistClinic/1.0"},
            timeout=self.timeout,
        )
        try:
            parsed = response.json() if response.content else {}
        except ValueError:
            parsed = {}
        return response.status_code, parsed

    def _get(self, path: str) -> tuple[int, dict]:
        response = requests.get(
            BASE_URL + path,
            headers={"X-API-KEY": self.api_key, "Accept": "application/json",
                     "User-Agent": "SpecialistClinic/1.0"},
            timeout=self.timeout,
        )
        try:
            parsed = response.json() if response.content else {}
        except ValueError:
            parsed = {}
        return response.status_code, parsed

    @staticmethod
    def _errors(payload: dict) -> list[dict]:
        if not isinstance(payload, dict):
            return []
        containers = [payload]
        for key in ("Meta", "meta", "Data", "data"):
            value = payload.get(key)
            if isinstance(value, dict):
                containers.append(value)
        for container in containers:
            value = _field(container, "Errors")
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    @classmethod
    def _error_message(cls, payload: dict) -> str:
        first = cls._errors(payload)
        source = first[0] if first else payload
        code = _field(source, "ErrorCode")
        message = _field(source, "Message") or _field(source, "ErrorMessage")
        try:
            numeric = int(code) if code is not None else None
        except (TypeError, ValueError):
            numeric = None
        mapped = ERROR_CODES.get(numeric)
        if mapped:
            return f"{mapped} (کد {numeric})"
        return str(message or "خطای نامشخص از پنل مدیانا")

    @staticmethod
    def _status_payload(payload: dict) -> tuple[str | None, int | None, str | None]:
        item = payload
        for key in ("Data", "data", "Result", "result"):
            value = payload.get(key) if isinstance(payload, dict) else None
            if isinstance(value, dict):
                item = value
                break
        status = _field(item, "Status") or _field(item, "StatusText")
        status_int = (_field(item, "StatusInt") or _field(item, "StatusId")
                      or _field(item, "StatusCode"))
        provider_msgid = (_field(item, "SmsItemId") or _field(item, "SmsId")
                          or _field(item, "MessageId"))
        try:
            status_int = int(status_int) if status_int is not None else None
        except (TypeError, ValueError):
            status_int = None
        return (
            str(status).strip() if status else None,
            status_int,
            str(provider_msgid).strip() if provider_msgid else None,
        )

    def send(self, recipient: str, body: str,
             message_type: str | None = None) -> SendResult:
        if not body or not body.strip():
            return SendResult(ok=False, error="متن پیام خالی است")
        selected_type = message_type if message_type in VALID_TYPES else self.default_type
        if self.sending_number:
            payload = {
                "sendingNumber": self.sending_number,
                "recipients": [recipient],
                "messageText": body,
                "sendSmsType": "SendSmsNormalWithNumber",
            }
        else:
            payload = {
                "recipients": [recipient],
                "messageText": body,
                "sendSmsType": "SendSmsNormalWithType",
                "messageType": selected_type,
            }
        try:
            http_status, result = self._post(SEND_SMS_PATH, payload)
        except (requests.Timeout, socket.timeout, TimeoutError):
            return SendResult(
                ok=False,
                pending=True,
                delivery_status="SubmissionUnknown",
                error="نتیجه ثبت پیام در مدیانا نامشخص است؛ retry خودکار نمی‌شود",
            )
        except requests.RequestException as exc:
            return SendResult(
                ok=False,
                retryable=True,
                delivery_status="RetryableFailure",
                error=f"خطای ارتباط با مدیانا: {exc}",
            )
        if http_status < 200 or http_status >= 300:
            error = self._error_message(result)
            if not result:
                error = f"HTTP {http_status}: پاسخ نامعتبر از پنل مدیانا"
            else:
                error = f"HTTP {http_status}: {error}"
            return SendResult(ok=False, delivery_status="Failed", error=error)
        errors = self._errors(result)
        if errors:
            code = _field(errors[0], "ErrorCode")
            try:
                numeric = int(code)
            except (TypeError, ValueError):
                numeric = None
            retryable = numeric in {1042, 1062}
            return SendResult(
                ok=False,
                retryable=retryable,
                delivery_status="RetryableFailure" if retryable else "Failed",
                error=self._error_message(result),
            )
        data = _field(result, "Data", {})
        request_id = (_field(data, "RequestId") or _field(data, "SendRequestId")
                      or _field(result, "RequestId") or _field(result, "SendRequestId"))
        provider_msgid = None
        items = _field(data, "SmsItems") if isinstance(data, dict) else None
        if isinstance(items, list) and items:
            provider_msgid = (_field(items[0], "SmsItemId") or _field(items[0], "SmsId")
                              or _field(items[0], "MessageId"))
        elif isinstance(data, list) and data:
            provider_msgid = (_field(data[0], "SmsItemId") or _field(data[0], "SmsId")
                              or _field(data[0], "MessageId"))
        elif isinstance(data, dict):
            provider_msgid = (_field(data, "SmsItemId") or _field(data, "SmsId")
                              or _field(data, "MessageId"))
        status, status_int, detected_msgid = self._status_payload(data or result)
        return SendResult(
            ok=True,
            provider_request_id=str(request_id).strip() if request_id else None,
            provider_msgid=(
                str(provider_msgid).strip() if provider_msgid else detected_msgid
            ),
            delivery_status=status or "Accepted",
            delivery_status_int=status_int,
        )

    def send_batch(self, messages: list[OutgoingSms],
                   message_type: str | None = None) -> BatchSendResult:
        # Preserve message-level idempotency and response matching by using the base
        # implementation until Mediana's array response is proven stable in production.
        return super().send_batch(messages, message_type)

    def fetch_delivery(self, *, request_id: str | None = None,
                       message_id: str | None = None) -> list[DeliveryUpdate]:
        if request_id:
            path = REQUEST_STATUS_PATH.format(request_id=request_id)
        elif message_id:
            path = ITEM_STATUS_PATH.format(message_id=message_id)
        else:
            return []
        http_status, payload = self._get(path)
        if http_status < 200 or http_status >= 300:
            raise RuntimeError(self._error_message(payload))
        data = _field(payload, "Data", payload)
        nested = _field(data, "SmsItems") if isinstance(data, dict) else None
        items = nested if isinstance(nested, list) else data if isinstance(data, list) else [data]
        updates = []
        for item in items:
            if not isinstance(item, dict):
                continue
            status = _field(item, "Status") or _field(item, "StatusText") or "StatusUnknown"
            status_int = (_field(item, "StatusInt") or _field(item, "StatusId")
                          or _field(item, "StatusCode"))
            try:
                status_int = int(status_int) if status_int is not None else None
            except (TypeError, ValueError):
                status_int = None
            delivered_at = _field(item, "DeliveredAt") or _field(item, "DeliveryDate")
            updates.append(
                DeliveryUpdate(
                    provider_request_id=(
                        str(_field(item, "RequestId") or request_id).strip()
                        if (_field(item, "RequestId") or request_id)
                        else None
                    ),
                    provider_msgid=(
                        str(_field(item, "SmsItemId") or _field(item, "SmsId")
                            or _field(item, "MessageId") or message_id).strip()
                        if (_field(item, "SmsItemId") or _field(item, "SmsId")
                            or _field(item, "MessageId") or message_id)
                        else None
                    ),
                    recipient=(
                        str(_field(item, "Recipient") or _field(item, "Receptor")).strip()
                        if (_field(item, "Recipient") or _field(item, "Receptor"))
                        else None
                    ),
                    status=str(status),
                    status_int=status_int,
                    delivered_at=str(delivered_at) if delivered_at else None,
                )
            )
        return updates

    def get_balance(self) -> int | None:
        try:
            status, payload = self._get(BALANCE_PATH)
            if status < 200 or status >= 300:
                return None
            value = _field(payload, "Balance")
            if value is None:
                value = _field(_field(payload, "Data", {}), "Balance")
            return int(value) if value is not None else None
        except Exception:
            return None


__all__ = ["MedianaProvider"]
