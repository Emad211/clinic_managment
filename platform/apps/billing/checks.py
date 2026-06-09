"""Deploy-time guard: never run the auto-approving payment simulator in prod.

Surfaces as an ERROR in `manage.py check` (and `check --deploy`) so a deploy with
DEBUG=False and no real ZARINPAL_MERCHANT_ID fails loudly instead of silently
granting free paid subscriptions (security audit, billing fail-open finding).
"""

import os

from django.conf import settings
from django.core.checks import Error, register


@register()
def billing_gateway_configured(app_configs, **kwargs):
    if settings.DEBUG:
        return []
    if os.getenv("ZARINPAL_MERCHANT_ID", "").strip():
        return []
    if os.getenv("BILLING_ALLOW_SIMULATED", "0") == "1":
        return []  # operator explicitly opted into the simulator
    return [
        Error(
            "No payment gateway configured for production: DEBUG is False and "
            "ZARINPAL_MERCHANT_ID is unset. Paid subscriptions would fail closed.",
            hint="Set ZARINPAL_MERCHANT_ID, or BILLING_ALLOW_SIMULATED=1 to allow "
            "the dev simulator on purpose.",
            id="billing.E001",
        )
    ]
