import pytest

from apps.rx.models import InsurerLog, Prescription, PrescriptionItem

pytestmark = pytest.mark.django_db


def test_eprescription_workflow(doctor_client, diabetic_patient):
    p = diabetic_patient

    # 1) start a draft
    r = doctor_client.post(f"/patients/{p.id}/rx/new/", {"insurer": "tamin"})
    assert r.status_code == 302
    rx = Prescription.objects.get(patient=p)
    assert rx.status == "draft" and rx.channel == "webview" and rx.doctor_id
    assert InsurerLog.objects.filter(prescription=rx, action="draft_created").count() == 1

    # 2) detail page shows the WebView bridge to the insurer portal
    body = doctor_client.get(f"/rx/{rx.id}/").content.decode()
    assert "ep.tamin.ir" in body

    # 3) add items
    doctor_client.post(f"/rx/{rx.id}/add-item/", {"item_name": "متفورمین", "dose": "500", "count": "60"})
    doctor_client.post(f"/rx/{rx.id}/add-item/", {"item_name": "HbA1c", "kind": "paraclinical"})
    assert PrescriptionItem.objects.filter(prescription=rx).count() == 2

    # 4) register with the insurer tracking code
    doctor_client.post(f"/rx/{rx.id}/register/", {"tracking_code": "TRK-1"})
    rx.refresh_from_db()
    assert rx.status == "registered" and rx.tracking_code == "TRK-1" and rx.issued_at
    assert InsurerLog.objects.filter(prescription=rx, action="register", status="registered").count() == 1


def test_eprescription_blocked_without_license(auth_client, diabetic_patient):
    """An unlicensed user cannot issue an e-prescription (REGULATORY §6 shield)."""
    r = auth_client.post(
        f"/patients/{diabetic_patient.id}/rx/new/", {"insurer": "tamin"}, follow=True
    )
    assert Prescription.objects.filter(patient=diabetic_patient).count() == 0
    assert "پروانهٔ نظام‌پزشکی" in r.content.decode()
