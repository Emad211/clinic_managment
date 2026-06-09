"""Regression tests for the security-audit hardening (multi-agent audit).

Covers: rx_add_item license gate + prescription state-machine, billing fail-closed
+ plan binding, web is_active revocation, and session-key rotation on login.
"""
import bcrypt
import pytest

from apps.billing.models import Plan, Subscription
from apps.rx.models import Prescription, PrescriptionItem

pytestmark = pytest.mark.django_db


def _draft_rx(patient, doctor, status="draft"):
    return Prescription.objects.create(
        clinic=patient.clinic, patient=patient, doctor=doctor,
        insurer="tamin", status=status, channel="webview",
    )


# ── rx_add_item: license gate + state-machine ──────────────────────────────

def test_rx_add_item_blocked_for_unlicensed(auth_client, doctor, diabetic_patient):
    rx = _draft_rx(diabetic_patient, doctor)
    r = auth_client.post(f"/rx/{rx.id}/add-item/", {"item_name": "متفورمین"}, follow=True)
    assert PrescriptionItem.objects.filter(prescription=rx).count() == 0
    assert "پروانهٔ نظام‌پزشکی" in r.content.decode()


def test_rx_add_item_allowed_for_licensed(doctor_client, doctor, diabetic_patient):
    rx = _draft_rx(diabetic_patient, doctor)
    doctor_client.post(f"/rx/{rx.id}/add-item/", {"item_name": "متفورمین", "dose": "500"})
    assert PrescriptionItem.objects.filter(prescription=rx).count() == 1


def test_rx_add_item_refused_after_registered(doctor_client, doctor, diabetic_patient):
    rx = _draft_rx(diabetic_patient, doctor, status="registered")
    r = doctor_client.post(f"/rx/{rx.id}/add-item/", {"item_name": "X"}, follow=True)
    assert PrescriptionItem.objects.filter(prescription=rx).count() == 0
    assert "قابل ویرایش نیست" in r.content.decode()


def test_rx_register_refused_when_already_registered(doctor_client, doctor, diabetic_patient):
    rx = _draft_rx(diabetic_patient, doctor, status="registered")
    rx.tracking_code = "ORIG"
    rx.save(update_fields=["tracking_code"])
    doctor_client.post(f"/rx/{rx.id}/register/", {"tracking_code": "HIJACK"})
    rx.refresh_from_db()
    assert rx.tracking_code == "ORIG"  # not overwritten


# ── billing: fail closed in production + plan binding ──────────────────────

def test_billing_fails_closed_without_gateway_in_prod(clinic, monkeypatch):
    from apps.billing import services

    monkeypatch.setattr(services.settings, "DEBUG", False)
    monkeypatch.delenv("BILLING_ALLOW_SIMULATED", raising=False)
    monkeypatch.delenv("ZARINPAL_MERCHANT_ID", raising=False)

    assert isinstance(services.get_gateway(), services.FailClosedGateway)
    plan = Plan.objects.create(code="clinic", name="x", price_rial=60_000_000)
    payment, url = services.subscribe(clinic, plan, "http://x/cb")
    assert url == ""  # no payment URL -> user cannot proceed
    assert services.confirm_payment(payment) is False
    assert not Subscription.objects.filter(clinic=clinic, plan=plan, status="active").exists()


def test_billing_check_flags_unconfigured_prod(monkeypatch):
    from apps.billing import checks

    monkeypatch.setattr(checks.settings, "DEBUG", False)
    monkeypatch.delenv("BILLING_ALLOW_SIMULATED", raising=False)
    monkeypatch.delenv("ZARINPAL_MERCHANT_ID", raising=False)
    errs = checks.billing_gateway_configured(None)
    assert any(e.id == "billing.E001" for e in errs)


def test_payment_is_bound_to_plan(clinic):
    from apps.billing import services

    plan = Plan.objects.create(code="clinic", name="x", price_rial=60_000_000)
    payment, _ = services.subscribe(clinic, plan, "http://x/cb")
    assert payment.plan_id == plan.id  # plan bound at request time, not re-derived


# ── web session: is_active revocation + session-key rotation ───────────────

def test_deactivated_user_loses_web_access(auth_client, manager):
    assert auth_client.get("/patients/").status_code == 200
    manager.is_active = False
    manager.save(update_fields=["is_active"])
    r = auth_client.get("/patients/")
    assert r.status_code == 302 and "login" in r["Location"]


def test_login_rotates_session_key(client, manager):
    s = client.session
    s["probe"] = "1"
    s.save()
    pre = s.session_key
    r = client.post("/login/", {"clinic_slug": "test", "username": "mgr", "password": "secret"})
    assert r.status_code == 302
    assert client.session.session_key != pre  # fixation defeated
    assert client.session.get("user_id")
