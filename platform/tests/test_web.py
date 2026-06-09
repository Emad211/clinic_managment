import pytest

from apps.chronic.models import ClinicalRule, SuggestionLog

pytestmark = pytest.mark.django_db


def test_dashboard_requires_login():
    from django.test import Client
    r = Client().get("/dashboard/")
    assert r.status_code == 302 and "login" in r["Location"]


def test_dashboard_renders(auth_client, diabetic_patient):
    r = auth_client.get("/dashboard/")
    assert r.status_code == 200
    assert "داشبورد کلینیک" in r.content.decode()


def test_patient_detail_shows_suggestions(auth_client, diabetic_patient):
    r = auth_client.get(f"/patients/{diabetic_patient.id}/")
    body = r.content.decode()
    assert r.status_code == 200
    assert "پیشنهادهای بالینی" in body
    assert "تأیید با پزشک" in body  # the safety disclaimer


def test_acknowledge_writes_suggestionlog(doctor_client, diabetic_patient):
    doctor_client.post(f"/patients/{diabetic_patient.id}/ack/", {"rule_code": "T2-DX-01"})
    logs = SuggestionLog.objects.filter(patient=diabetic_patient, rule_code="T2-DX-01")
    assert logs.exclude(acknowledged_at__isnull=True).count() == 1
    # idempotent
    doctor_client.post(f"/patients/{diabetic_patient.id}/ack/", {"rule_code": "T2-DX-01"})
    assert logs.exclude(acknowledged_at__isnull=True).count() == 1


def test_acknowledge_blocked_without_license(auth_client, diabetic_patient):
    """An unlicensed user (the manager fixture) cannot sign a clinical decision —
    the shield: the system suggests, a LICENSED physician decides (REGULATORY §6)."""
    r = auth_client.post(
        f"/patients/{diabetic_patient.id}/ack/", {"rule_code": "T2-DX-01"}, follow=True
    )
    assert SuggestionLog.objects.filter(
        patient=diabetic_patient, rule_code="T2-DX-01"
    ).exclude(acknowledged_at__isnull=True).count() == 0
    assert "پروانهٔ نظام‌پزشکی" in r.content.decode()


def test_patient_detail_hides_ack_for_unlicensed(auth_client, diabetic_patient):
    body = auth_client.get(f"/patients/{diabetic_patient.id}/").content.decode()
    assert "🔒 تأیید" in body  # locked instead of an actionable button


def test_patient_detail_shows_ack_for_licensed(doctor_client, diabetic_patient):
    body = doctor_client.get(f"/patients/{diabetic_patient.id}/").content.decode()
    assert "🔒 تأیید" not in body


def test_api_patients_guarded():
    from django.test import Client
    assert Client().get("/api/patients/").status_code == 401


def test_health():
    from django.test import Client
    r = Client().get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
