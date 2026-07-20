from src.services.sms.mediana_provider import MedianaProvider, SEND_SMS_PATH, SEND_ARRAY_PATH
from src.services.sms.provider import OutgoingSms
import requests


class _Response:
    def __init__(self, payload=None, status=200, content=b"json"):
        self._payload = payload
        self.status_code = status
        self.content = content

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def raise_for_status(self):
        return None


def test_send_matches_mediana_normal_sms_contract(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return _Response({
            "data": {
                "Succeed": True,
                "RequestId": 12,
                "Message": "ok",
                "Status": "Completed",
                "SmsItems": [{"SmsItemId": "item-42", "Recipient": "09929315456"}],
            }
        })

    monkeypatch.setattr("requests.post", fake_post)
    provider = MedianaProvider("secret", default_type="Informational", timeout=17)

    result = provider.send("09929315456", "پیام تست")

    assert captured["url"].endswith(SEND_SMS_PATH)
    assert captured["headers"]["X-API-KEY"] == "secret"
    assert captured["headers"]["User-Agent"] == "SpecialistClinic/1.0"
    assert captured["json"] == {
        "type": "Informational",
        "recipients": ["09929315456"],
        "messageText": "پیام تست",
    }
    assert captured["timeout"] == 17
    assert result.ok is True
    assert result.provider_msgid == "item-42"


def test_send_accepts_live_camel_case_response(monkeypatch):
    monkeypatch.setattr(
        "requests.post",
        lambda *_args, **_kwargs: _Response({
            "meta": {"code": "OK", "errorMessage": None},
            "data": {
                "succeed": True,
                "requestId": 142877506,
                "requestCode": "142877506",
                "message": "در حال ساخت",
                "status": "PendingApproval",
                "smsItems": [{
                    "smsItemId": "989929315456_142877506",
                    "recipient": "989929315456",
                }],
            },
        }),
    )

    result = MedianaProvider("secret").send("09929315456", "پیام تست")

    assert result.ok is True
    assert result.provider_msgid == "989929315456_142877506"


def test_html_gateway_error_keeps_http_status(monkeypatch):
    monkeypatch.setattr(
        "requests.post",
        lambda *_args, **_kwargs: _Response(ValueError("not json"), status=502),
    )

    result = MedianaProvider("secret").send("09929315456", "پیام تست")

    assert result.ok is False
    assert "HTTP 502" in result.error
    assert "نامعتبر" in result.error


def test_balance_uses_requests_transport(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured.update(url=url, **kwargs)
        return _Response({"data": {"balance": 498314}})

    monkeypatch.setattr("requests.get", fake_get)

    assert MedianaProvider("secret", timeout=12).get_balance() == 498314
    assert captured["headers"]["X-API-KEY"] == "secret"
    assert captured["timeout"] == 12


def test_batch_maps_pascal_and_camel_case(monkeypatch):
    captured = {}
    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return _Response({"data": {"refCodes": [
            {"code": 91, "refId": "a", "mobiles": ["0911"]},
            {"Code": 92, "RefId": "b", "Mobiles": ["0912"]},
        ]}})
    monkeypatch.setattr("requests.post", fake_post)
    result = MedianaProvider("secret").send_batch([
        OutgoingSms("a", "0911", "یک"), OutgoingSms("b", "0912", "دو")], "Informational")
    assert captured['url'].endswith(SEND_ARRAY_PATH)
    assert [x.provider_request_id for x in result.items] == ['91', '92']
    assert captured['json']['Requests'][0]['RefId'] == 'a'


def test_delivery_status_request_and_item(monkeypatch):
    payloads = iter([
        {"data": {"smsItems": [{"smsItemId": "i1", "recipient": "0911",
                                  "status": "SendToOperator", "statusInt": 4}]}},
        {"data": {"SmsItemId": "i1", "Recipient": "0911",
                  "Status": "Delivered", "StatusInt": 6}},
    ])
    monkeypatch.setattr("requests.get", lambda *_a, **_k: _Response(next(payloads)))
    provider = MedianaProvider('secret')
    assert provider.fetch_delivery(request_id='r1')[0].status == 'SendToOperator'
    assert provider.fetch_delivery(message_id='i1')[0].status == 'Delivered'


def test_batch_blacklist_and_insufficient_balance(monkeypatch):
    messages = [OutgoingSms('a', '0911', 'test')]
    monkeypatch.setattr("requests.post", lambda *_a, **_k: _Response(
        {"meta": {"errors": [{"errorCode": 1047}]}, "data": {}}))
    black = MedianaProvider('secret').send_batch(messages).items[0]
    assert not black.ok and not black.retryable
    monkeypatch.setattr("requests.post", lambda *_a, **_k: _Response(
        {"meta": {"errors": [{"errorCode": 1042}]}, "data": {}}))
    funds = MedianaProvider('secret').send_batch(messages).items[0]
    assert funds.retryable and funds.delivery_status == 'RetryableFailure'


def test_batch_timeout_and_502_are_ambiguous_not_retryable(monkeypatch):
    messages = [OutgoingSms('a', '0911', 'test')]
    monkeypatch.setattr("requests.post", lambda *_a, **_k: (_ for _ in ()).throw(requests.Timeout()))
    timeout = MedianaProvider('secret').send_batch(messages).items[0]
    assert timeout.pending and not timeout.retryable
    monkeypatch.setattr("requests.post", lambda *_a, **_k: _Response({}, status=502))
    gateway = MedianaProvider('secret').send_batch(messages).items[0]
    assert not gateway.retryable
