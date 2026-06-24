"""
Step 11 — Prescription model + write-path tests.

Coverage matrix:

SERVICE LAYER (unit/integration, direct service calls):
  1.  create encounter → add free prescription with 2 items → read back:
        mode='free', encounter_id set, items linked, patient_link_id derived.
  2.  Sealed encounter (completed) → EncounterSealed raised.
  3.  mode='insurance' → InsurancePrescriptionNotSupported raised.
  4.  Item with invalid frequency → PrescriptionItemValidationError before DB.
  5.  Item with quantity <= 0 → PrescriptionItemValidationError before DB.
  6.  Item with empty drug_name → PrescriptionItemValidationError.
  7.  Item with invalid route → PrescriptionItemValidationError.
  8.  Item with duration_days <= 0 → PrescriptionItemValidationError.
  9.  Deleting the prescription cascades to items (DB ON DELETE CASCADE).
  10. Tenant isolation: encounter of another tenant → EncounterNotFound.

ENDPOINT LAYER (via ninja TestClient):
  11. POST /encounters/{id}/prescriptions → 201 + PrescriptionOut (happy path).
  12. POST without JWT → 401.
  13. Sealed encounter via endpoint → 409 encounter_sealed.
  14. mode='insurance' via endpoint → 422 insurance_prescription_not_supported.
  15. Bad frequency via endpoint → 422 validation_error.

All tests use @pytest.mark.django_db(transaction=True).
Never writes to accounting.*; no real SMS.
"""
import pytest
import psycopg
import os

from ninja.testing import TestClient
from config.api import api
from clinical.encounter_service import (
    create_encounter,
    complete_encounter,
    add_prescription_to_encounter,
    EncounterSealed,
    InsurancePrescriptionNotSupported,
    PrescriptionItemValidationError,
    EncounterNotFound,
)
from clinical.models import Prescription, PrescriptionItem


# ---------------------------------------------------------------------------
# Helpers shared with encounter API tests
# ---------------------------------------------------------------------------

def _client() -> TestClient:
    return TestClient(api)


def _get_token(seed) -> str:
    resp = _client().post(
        "/auth/login",
        json={"username": "testuser", "password": seed["test_password"]},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _assert_error_contract(body: dict, expected_code: str) -> None:
    assert "detail" in body and body["detail"], f"Missing detail: {body}"
    assert "code" in body, f"Missing code: {body}"
    assert body["code"] == expected_code, (
        f"Expected code={expected_code!r}, got {body['code']!r}: {body}"
    )


# ---------------------------------------------------------------------------
# 1. Happy path: create encounter → add free prescription with 2 items
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_add_free_prescription_happy_path(seed_clinical_data):
    """
    Create an encounter → add a free prescription with 2 items.
    Verify: mode='free', encounter_id set, items linked, patient_link derived.
    """
    link_id = seed_clinical_data["link_id"]
    tenant_id = 1

    enc = create_encounter(
        patient_link_id=link_id,
        tenant_id=tenant_id,
        encounter_type="visit",
        created_by="testuser",
    )

    rx = add_prescription_to_encounter(
        enc.id,
        tenant_id,
        kind="chronic",
        items=[
            {
                "drug_name": "متفورمین",
                "drug_class": "metformin",
                "dose_value": 500.0,
                "dose_unit": "mg",
                "frequency": "bid",
                "route": "oral",
                "quantity": 60,
                "duration_days": 30,
                "instructions": "با غذا",
            },
            {
                "drug_name": "آملودیپین",
                "drug_class": "ccb",
                "dose_value": 5.0,
                "dose_unit": "mg",
                "frequency": "od",
                "route": "oral",
                "quantity": 30,
                "duration_days": 30,
            },
        ],
        mode="free",
        created_by="testuser",
    )

    # Prescription header assertions
    assert rx.id is not None
    assert rx.mode == "free"
    assert rx.encounter_id == enc.id
    assert rx.patient_link_id == link_id
    assert rx.tenant_id == tenant_id
    assert rx.kind == "chronic"

    # Items round-trip
    items = list(
        PrescriptionItem.objects.filter(
            prescription_id=rx.id, tenant_id=tenant_id
        ).order_by("id")
    )
    assert len(items) == 2

    first = items[0]
    assert first.drug_name == "متفورمین"
    assert first.frequency == "bid"
    assert first.route == "oral"
    assert int(first.quantity) == 60
    assert int(first.duration_days) == 30

    second = items[1]
    assert second.drug_name == "آملودیپین"
    assert second.frequency == "od"


# ---------------------------------------------------------------------------
# 2. Sealed encounter → EncounterSealed
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_prescription_on_completed_encounter_raises_sealed(seed_clinical_data):
    """
    Adding a prescription to a completed encounter raises EncounterSealed.
    """
    link_id = seed_clinical_data["link_id"]
    tenant_id = 1

    enc = create_encounter(
        patient_link_id=link_id,
        tenant_id=tenant_id,
        encounter_type="visit",
    )
    complete_encounter(enc.id, tenant_id)

    with pytest.raises(EncounterSealed):
        add_prescription_to_encounter(
            enc.id,
            tenant_id,
            kind="acute",
            items=[{"drug_name": "ایبوپروفن"}],
            mode="free",
        )


# ---------------------------------------------------------------------------
# 3. mode='insurance' → InsurancePrescriptionNotSupported
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_insurance_mode_raises_not_supported(seed_clinical_data):
    """
    Passing mode='insurance' raises InsurancePrescriptionNotSupported
    (the insurance/MV3 bridge track is blocked).
    """
    link_id = seed_clinical_data["link_id"]
    tenant_id = 1

    enc = create_encounter(
        patient_link_id=link_id,
        tenant_id=tenant_id,
        encounter_type="visit",
    )

    with pytest.raises(InsurancePrescriptionNotSupported):
        add_prescription_to_encounter(
            enc.id,
            tenant_id,
            kind="acute",
            items=[{"drug_name": "آزیترومایسین"}],
            mode="insurance",
        )

    # Guard fires BEFORE any DB write — no prescription row must exist
    count = Prescription.objects.filter(
        encounter_id=enc.id, tenant_id=tenant_id
    ).count()
    assert count == 0, "Insurance guard must prevent DB write"


# ---------------------------------------------------------------------------
# 4. Invalid frequency → PrescriptionItemValidationError (service layer)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_invalid_frequency_raises_validation_error(seed_clinical_data):
    """
    An item with an invalid frequency value raises PrescriptionItemValidationError
    before hitting the DB.
    """
    link_id = seed_clinical_data["link_id"]
    tenant_id = 1

    enc = create_encounter(
        patient_link_id=link_id,
        tenant_id=tenant_id,
        encounter_type="visit",
    )

    with pytest.raises(PrescriptionItemValidationError, match="frequency"):
        add_prescription_to_encounter(
            enc.id,
            tenant_id,
            kind="acute",
            items=[{"drug_name": "آزیترومایسین", "frequency": "thrice_a_week"}],
            mode="free",
        )


# ---------------------------------------------------------------------------
# 5. quantity <= 0 → PrescriptionItemValidationError
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_quantity_zero_raises_validation_error(seed_clinical_data):
    """Item with quantity=0 raises PrescriptionItemValidationError."""
    link_id = seed_clinical_data["link_id"]
    tenant_id = 1

    enc = create_encounter(
        patient_link_id=link_id,
        tenant_id=tenant_id,
        encounter_type="visit",
    )

    with pytest.raises(PrescriptionItemValidationError, match="quantity"):
        add_prescription_to_encounter(
            enc.id,
            tenant_id,
            kind="acute",
            items=[{"drug_name": "پاراستامول", "quantity": 0}],
            mode="free",
        )


# ---------------------------------------------------------------------------
# 6. Empty drug_name → PrescriptionItemValidationError
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_empty_drug_name_raises_validation_error(seed_clinical_data):
    """Item with empty drug_name raises PrescriptionItemValidationError."""
    link_id = seed_clinical_data["link_id"]
    tenant_id = 1

    enc = create_encounter(
        patient_link_id=link_id,
        tenant_id=tenant_id,
        encounter_type="visit",
    )

    with pytest.raises(PrescriptionItemValidationError, match="drug_name"):
        add_prescription_to_encounter(
            enc.id,
            tenant_id,
            kind="acute",
            items=[{"drug_name": "   "}],   # blank-only
            mode="free",
        )


# ---------------------------------------------------------------------------
# 7. Invalid route → PrescriptionItemValidationError
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_invalid_route_raises_validation_error(seed_clinical_data):
    """Item with invalid route raises PrescriptionItemValidationError."""
    link_id = seed_clinical_data["link_id"]
    tenant_id = 1

    enc = create_encounter(
        patient_link_id=link_id,
        tenant_id=tenant_id,
        encounter_type="visit",
    )

    with pytest.raises(PrescriptionItemValidationError, match="route"):
        add_prescription_to_encounter(
            enc.id,
            tenant_id,
            kind="acute",
            items=[{"drug_name": "لوراتادین", "route": "rectal"}],  # not in allowed set
            mode="free",
        )


# ---------------------------------------------------------------------------
# 8. duration_days <= 0 → PrescriptionItemValidationError
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_duration_days_zero_raises_validation_error(seed_clinical_data):
    """Item with duration_days=-1 raises PrescriptionItemValidationError."""
    link_id = seed_clinical_data["link_id"]
    tenant_id = 1

    enc = create_encounter(
        patient_link_id=link_id,
        tenant_id=tenant_id,
        encounter_type="visit",
    )

    with pytest.raises(PrescriptionItemValidationError, match="duration_days"):
        add_prescription_to_encounter(
            enc.id,
            tenant_id,
            kind="acute",
            items=[{"drug_name": "ابوپروفن", "duration_days": -1}],
            mode="free",
        )


# ---------------------------------------------------------------------------
# 9. Cascade delete: deleting prescription removes items
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_delete_prescription_cascades_to_items(seed_clinical_data):
    """
    Deleting a Prescription row cascades to its PrescriptionItem rows
    (DB ON DELETE CASCADE on fk_prescription_items_prescription).
    """
    link_id = seed_clinical_data["link_id"]
    tenant_id = 1

    enc = create_encounter(
        patient_link_id=link_id,
        tenant_id=tenant_id,
        encounter_type="visit",
    )

    rx = add_prescription_to_encounter(
        enc.id,
        tenant_id,
        kind="test_cascade",
        items=[
            {"drug_name": "دارو-الف"},
            {"drug_name": "دارو-ب"},
        ],
        mode="free",
    )

    rx_id = rx.id
    item_count_before = PrescriptionItem.objects.filter(
        prescription_id=rx_id, tenant_id=tenant_id
    ).count()
    assert item_count_before == 2

    # Delete the prescription header
    Prescription.objects.filter(id=rx_id, tenant_id=tenant_id).delete()

    # Items must be gone (CASCADE)
    item_count_after = PrescriptionItem.objects.filter(
        prescription_id=rx_id, tenant_id=tenant_id
    ).count()
    assert item_count_after == 0, (
        f"Expected 0 items after cascade delete, found {item_count_after}"
    )


# ---------------------------------------------------------------------------
# 10. Tenant isolation: wrong tenant → EncounterNotFound
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_prescription_wrong_tenant_raises_not_found(seed_clinical_data):
    """
    Attempting to add a prescription to an encounter owned by tenant 1
    from tenant 2's context raises EncounterNotFound (same message as
    'not found' — callers cannot probe other tenants' data).
    """
    link_id = seed_clinical_data["link_id"]
    tenant_id = 1

    enc = create_encounter(
        patient_link_id=link_id,
        tenant_id=tenant_id,
        encounter_type="visit",
    )

    with pytest.raises(EncounterNotFound):
        add_prescription_to_encounter(
            enc.id,
            tenant_id=2,       # wrong tenant
            kind="acute",
            items=[{"drug_name": "دارو-بیگانه"}],
            mode="free",
        )


# ---------------------------------------------------------------------------
# 11. Endpoint happy path: POST → 201 + PrescriptionOut
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_create_prescription_endpoint_returns_201(seed_clinical_data):
    """
    POST /encounters/{id}/prescriptions with valid free prescription → 201.
    Response shape: id, tenant_id, patient_link_id, encounter_id, kind, mode,
    issued_at, items_structured.
    """
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])
    link_id = seed_clinical_data["link_id"]
    client = _client()

    # Create an encounter first
    enc_resp = client.post(
        f"/patients/{uuid}/encounters",
        json={"encounter_type": "visit"},
        headers=_auth(token),
    )
    assert enc_resp.status_code == 201, f"Encounter create failed: {enc_resp.text}"
    enc_id = enc_resp.json()["id"]

    # Add prescription
    rx_resp = client.post(
        f"/encounters/{enc_id}/prescriptions",
        json={
            "kind": "chronic",
            "mode": "free",
            "items": [
                {
                    "drug_name": "متفورمین",
                    "dose_value": 500.0,
                    "dose_unit": "mg",
                    "frequency": "bid",
                    "route": "oral",
                    "quantity": 60,
                    "duration_days": 30,
                },
                {
                    "drug_name": "لیزینوپریل",
                    "dose_value": 10.0,
                    "dose_unit": "mg",
                    "frequency": "od",
                    "route": "oral",
                    "quantity": 30,
                    "duration_days": 30,
                },
            ],
        },
        headers=_auth(token),
    )
    assert rx_resp.status_code == 201, f"Expected 201, got {rx_resp.status_code}: {rx_resp.text}"
    body = rx_resp.json()

    # Shape assertions
    for field in ("id", "tenant_id", "patient_link_id", "encounter_id",
                  "kind", "mode", "issued_at", "items_structured"):
        assert field in body, f"Missing field '{field}' in PrescriptionOut: {body}"

    assert body["mode"] == "free"
    assert body["encounter_id"] == enc_id
    assert body["patient_link_id"] == link_id
    assert body["kind"] == "chronic"
    assert isinstance(body["id"], int)

    # Items
    items = body["items_structured"]
    assert len(items) == 2
    drug_names = {item["drug_name"] for item in items}
    assert "متفورمین" in drug_names
    assert "لیزینوپریل" in drug_names
    for item in items:
        assert item["prescription_id"] == body["id"]
        assert item["tenant_id"] == 1


# ---------------------------------------------------------------------------
# 12. No JWT → 401
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_prescription_endpoint_requires_jwt(seed_clinical_data):
    """POST /encounters/{id}/prescriptions without JWT → 401."""
    client = _client()
    resp = client.post(
        "/encounters/999/prescriptions",
        json={"kind": "acute", "items": [{"drug_name": "دارو"}]},
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# 13. Sealed encounter via endpoint → 409 encounter_sealed
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_prescription_on_sealed_encounter_endpoint_returns_409(seed_clinical_data):
    """
    POST /encounters/{id}/prescriptions after completing the encounter
    → 409 with code='encounter_sealed'.
    """
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])
    client = _client()

    # Create + complete encounter
    enc_resp = client.post(
        f"/patients/{uuid}/encounters",
        json={"encounter_type": "visit"},
        headers=_auth(token),
    )
    assert enc_resp.status_code == 201
    enc_id = enc_resp.json()["id"]

    client.post(f"/encounters/{enc_id}/complete", json={}, headers=_auth(token))

    rx_resp = client.post(
        f"/encounters/{enc_id}/prescriptions",
        json={"kind": "chronic", "items": [{"drug_name": "دارو-بعد-ویزیت"}]},
        headers=_auth(token),
    )
    assert rx_resp.status_code == 409, f"Expected 409: {rx_resp.text}"
    _assert_error_contract(rx_resp.json(), "encounter_sealed")


# ---------------------------------------------------------------------------
# 14. mode='insurance' via endpoint → 422 insurance_prescription_not_supported
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_insurance_mode_endpoint_returns_422(seed_clinical_data):
    """
    POST /encounters/{id}/prescriptions with mode='insurance'
    → 422 with code='insurance_prescription_not_supported'.
    """
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])
    client = _client()

    enc_resp = client.post(
        f"/patients/{uuid}/encounters",
        json={"encounter_type": "visit"},
        headers=_auth(token),
    )
    assert enc_resp.status_code == 201
    enc_id = enc_resp.json()["id"]

    rx_resp = client.post(
        f"/encounters/{enc_id}/prescriptions",
        json={
            "kind": "insurance_test",
            "mode": "insurance",
            "items": [{"drug_name": "دارو-بیمه"}],
        },
        headers=_auth(token),
    )
    assert rx_resp.status_code == 422, f"Expected 422: {rx_resp.text}"
    _assert_error_contract(rx_resp.json(), "insurance_prescription_not_supported")


# ---------------------------------------------------------------------------
# 15. Bad frequency via endpoint → 422 validation_error
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_bad_frequency_endpoint_returns_422(seed_clinical_data):
    """
    POST /encounters/{id}/prescriptions with invalid frequency
    → 422 with code='validation_error'.
    """
    token = _get_token(seed_clinical_data)
    uuid = str(seed_clinical_data["patient_uuid"])
    client = _client()

    enc_resp = client.post(
        f"/patients/{uuid}/encounters",
        json={"encounter_type": "visit"},
        headers=_auth(token),
    )
    assert enc_resp.status_code == 201
    enc_id = enc_resp.json()["id"]

    rx_resp = client.post(
        f"/encounters/{enc_id}/prescriptions",
        json={
            "kind": "acute",
            "items": [{"drug_name": "سفالکسین", "frequency": "five_times_a_day"}],
        },
        headers=_auth(token),
    )
    assert rx_resp.status_code == 422, f"Expected 422: {rx_resp.text}"
    _assert_error_contract(rx_resp.json(), "validation_error")
