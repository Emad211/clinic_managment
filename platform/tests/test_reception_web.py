"""Reception desk web UI (ACCOUNTING.md phase 3): role gating + the open ->
add-item -> pay -> close flow, plus manager tariff management."""
import pytest

from apps.accounting.models import Invoice, Tariff

pytestmark = pytest.mark.django_db


@pytest.fixture
def visit_tariff(clinic):
    return Tariff.objects.create(clinic=clinic, kind="visit", name="ویزیت عمومی", amount_rial=3_000_000)


def test_reception_blocked_for_doctor(doctor_client):
    r = doctor_client.get("/reception/")
    assert r.status_code == 302 and "dashboard" in r["Location"]


def test_reception_open_for_manager(auth_client):
    assert auth_client.get("/reception/").status_code == 200


def test_open_invoice_from_desk(auth_client, diabetic_patient):
    r = auth_client.post("/reception/", {"national_id": diabetic_patient.national_id, "shift": "morning"})
    assert r.status_code == 302
    inv = Invoice.objects.get(patient=diabetic_patient)
    assert inv.status == "open" and "/invoices/" in r["Location"]


def test_open_invoice_unknown_patient_shows_error(auth_client):
    r = auth_client.post("/reception/", {"national_id": "NOPE", "shift": "morning"}, follow=True)
    assert "یافت نشد" in r.content.decode()
    assert Invoice.objects.count() == 0


def test_full_desk_flow(auth_client, diabetic_patient, visit_tariff):
    auth_client.post("/reception/", {"national_id": diabetic_patient.national_id, "shift": "morning"})
    inv = Invoice.objects.get(patient=diabetic_patient)

    # add a visit from the tariff (self-pay)
    auth_client.post(f"/invoices/{inv.id}/add-item/", {"tariff_id": str(visit_tariff.id)})
    inv.refresh_from_db()
    assert inv.total_rial == 3_000_000

    body = auth_client.get(f"/invoices/{inv.id}/").content.decode()
    assert "ویزیت عمومی" in body

    # pay it -> paid
    auth_client.post(f"/invoices/{inv.id}/pay/", {"amount": "3000000", "method": "cash"})
    inv.refresh_from_db()
    assert inv.paid_rial == 3_000_000 and inv.status == "paid"

    # closed invoice no longer accepts items
    auth_client.post(f"/invoices/{inv.id}/close/")
    auth_client.post(f"/invoices/{inv.id}/add-item/", {"tariff_id": str(visit_tariff.id)})
    inv.refresh_from_db()
    assert inv.visits.count() == 1  # the second add was refused (status=paid)


def test_invoice_open_from_patient_page(auth_client, diabetic_patient):
    r = auth_client.post(f"/patients/{diabetic_patient.id}/invoice/new/", {"shift": "evening"})
    assert r.status_code == 302
    assert Invoice.objects.filter(patient=diabetic_patient, shift="evening").exists()


def test_tariffs_manager_only(doctor_client):
    r = doctor_client.get("/tariffs/")
    assert r.status_code == 302 and "dashboard" in r["Location"]


def test_manager_adds_tariff(auth_client, clinic):
    auth_client.post("/tariffs/", {
        "action": "add", "kind": "procedure", "name": "نوار قلب", "amount": "2000000",
    })
    assert Tariff.objects.filter(clinic=clinic, name="نوار قلب", amount_rial=2_000_000).exists()
