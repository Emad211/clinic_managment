"""Subscription billing via ZarinPal (docs/TECH_STACK.md).

Gateway is chosen at runtime: with ZARINPAL_MERCHANT_ID configured the real
ZarinPal v4 API is used (sandbox or prod by ZARINPAL_SANDBOX); otherwise a
SimulatedGateway auto-approves so the flow is fully exercisable in dev/CI —
same NullProvider pattern as SMS.

Flow: subscribe() creates a pending Payment + a payment URL; the user pays on
ZarinPal; the callback verifies and then activates/extends the Subscription.
Amounts are Rial (BIGINT), matching Plan.price_rial.
"""

import json
import os
import urllib.error
import urllib.request
import uuid
from datetime import timedelta

from django.utils import timezone

from apps.billing.models import Payment, Subscription

_BASE_PROD = "https://api.zarinpal.com/pg/v4/payment"
_BASE_SANDBOX = "https://sandbox.zarinpal.com/pg/v4/payment"
_STARTPAY = "https://www.zarinpal.com/pg/StartPay/"


def _post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


class SimulatedGateway:
    name = "simulated"

    def request(self, amount_rial, callback_url, description):
        authority = "SIM-" + uuid.uuid4().hex[:24]
        # Point straight back at our callback with a success marker.
        sep = "&" if "?" in callback_url else "?"
        return {"authority": authority, "url": f"{callback_url}{sep}Authority={authority}&Status=OK"}

    def verify(self, amount_rial, authority):
        return {"ok": True, "ref_id": "SIMREF-" + authority[-8:]}


class ZarinPalGateway:
    name = "zarinpal"

    def __init__(self, merchant_id, sandbox=False):
        self.merchant_id = merchant_id
        self.base = _BASE_SANDBOX if sandbox else _BASE_PROD

    def request(self, amount_rial, callback_url, description):
        try:
            data = _post(self.base + "/request.json", {
                "merchant_id": self.merchant_id, "amount": int(amount_rial),
                "callback_url": callback_url, "description": description,
            })
            authority = (data.get("data") or {}).get("authority")
            if authority:
                return {"authority": authority, "url": _STARTPAY + authority}
        except (urllib.error.URLError, ValueError, TimeoutError):
            pass
        return {"authority": "", "url": ""}

    def verify(self, amount_rial, authority):
        try:
            data = _post(self.base + "/verify.json", {
                "merchant_id": self.merchant_id, "amount": int(amount_rial),
                "authority": authority,
            })
            d = data.get("data") or {}
            if d.get("code") in (100, 101):
                return {"ok": True, "ref_id": str(d.get("ref_id", ""))}
        except (urllib.error.URLError, ValueError, TimeoutError):
            pass
        return {"ok": False, "ref_id": ""}


def get_gateway():
    mid = os.getenv("ZARINPAL_MERCHANT_ID", "").strip()
    if mid:
        return ZarinPalGateway(mid, os.getenv("ZARINPAL_SANDBOX", "0") == "1")
    return SimulatedGateway()


def _activate_subscription(clinic, plan):
    today = timezone.localdate()
    days = 365 if plan.period == "yearly" else 30
    sub, _ = Subscription.objects.update_or_create(
        clinic=clinic, plan=plan,
        defaults={"status": "active", "period_start": today,
                  "period_end": today + timedelta(days=days)},
    )
    return sub


def subscribe(clinic, plan, callback_url):
    """Start a subscription. Free plans activate immediately; paid plans create a
    pending Payment and return a gateway URL. Returns (payment, redirect_url)."""
    if plan.price_rial <= 0:
        _activate_subscription(clinic, plan)
        return None, None
    payment = Payment.objects.create(
        clinic=clinic, amount_rial=plan.price_rial, gateway=get_gateway().name,
        status="pending",
    )
    res = get_gateway().request(
        plan.price_rial, f"{callback_url}?payment={payment.id}",
        f"اشتراک {plan.name}",
    )
    payment.authority = res.get("authority", "")
    payment.save(update_fields=["authority", "updated_at"])
    # stash the plan on the payment via a lightweight convention (subscription FK
    # is set on success); we resolve plan from amount+pending on callback.
    return payment, res.get("url", "")


def confirm_payment(payment, plan):
    """Verify a payment and, on success, activate the subscription."""
    res = get_gateway().verify(payment.amount_rial, payment.authority)
    if res.get("ok"):
        sub = _activate_subscription(payment.clinic, plan)
        payment.status = "paid"
        payment.ref_id = res.get("ref_id", "")
        payment.subscription = sub
        payment.save(update_fields=["status", "ref_id", "subscription", "updated_at"])
        return True
    payment.status = "failed"
    payment.save(update_fields=["status", "updated_at"])
    return False
