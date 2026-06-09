from apps.billing.models import Payment, Plan, Subscription
from apps.billing.services import confirm_payment, subscribe
from apps.messaging.models import SmsMessage
from apps.messaging.services import comply, send_sms


def test_compliance_rewrite():
    out = comply("ویزیت رایگان با تخفیف")
    assert "رایگان" not in out and "تخفیف" not in out


def test_sms_nullprovider_records(clinic):
    msg = send_sms(clinic, "09120000000", "یادآوری")
    assert msg.status == "simulated" and msg.sent_at is not None
    assert SmsMessage.objects.count() == 1


def test_free_plan_activates_immediately(clinic):
    free = Plan.objects.create(code="free", name="رایگان", price_rial=0, period="yearly")
    payment, url = subscribe(clinic, free, "http://x/cb")
    assert payment is None and url is None
    assert Subscription.objects.filter(clinic=clinic, plan=free, status="active").exists()


def test_paid_plan_simulated_gateway(clinic):
    plan = Plan.objects.create(code="clinic", name="کلینیک", price_rial=60_000_000, period="yearly")
    payment, url = subscribe(clinic, plan, "http://x/cb")
    assert payment.status == "pending" and url  # gateway URL returned
    ok = confirm_payment(payment, plan)
    assert ok
    payment.refresh_from_db()
    assert payment.status == "paid" and payment.ref_id
    assert Subscription.objects.filter(clinic=clinic, plan=plan, status="active").exists()
