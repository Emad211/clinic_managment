import pytest

from apps.rx.models import InsurerLog, Prescription, PrescriptionItem

pytestmark = pytest.mark.django_db


def test_eprescription_workflow(auth_client, diabetic_patient):
    p = diabetic_patient

    # 1) start a draft
    r = auth_client.post(f"/patients/{p.id}/rx/new/", {"insurer": "tamin"})
    assert r.status_code == 302
    rx = Prescription.objects.get(patient=p)
    assert rx.status == "draft" and rx.channel == "webview" and rx.doctor_id
    assert InsurerLog.objects.filter(prescription=rx, action="draft_created").count() == 1

    # 2) detail page shows the WebView bridge to the insurer portal
    body = auth_client.get(f"/rx/{rx.id}/").content.decode()
    assert "ep.tamin.ir" in body

    # 3) add items
    auth_client.post(f"/rx/{rx.id}/add-item/", {"item_name": "متفورمین", "dose": "500", "count": "60"})
    auth_client.post(f"/rx/{rx.id}/add-item/", {"item_name": "HbA1c", "kind": "paraclinical"})
    assert PrescriptionItem.objects.filter(prescription=rx).count() == 2

    # 4) register with the insurer tracking code
    auth_client.post(f"/rx/{rx.id}/register/", {"tracking_code": "TRK-1"})
    rx.refresh_from_db()
    assert rx.status == "registered" and rx.tracking_code == "TRK-1" and rx.issued_at
    assert InsurerLog.objects.filter(prescription=rx, action="register", status="registered").count() == 1
