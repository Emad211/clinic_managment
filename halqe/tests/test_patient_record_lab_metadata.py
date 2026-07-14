"""Adversarial tests for standalone patient-record laboratory entries."""
from __future__ import annotations

import uuid

import pytest
from ninja.testing import TestClient

from clinical.models import LabResult
from clinical.record_models import LabTestCatalog
from config.api import api
from platform_core.tenant_context import set_tenant_guc


def _client() -> TestClient:
    return TestClient(api)


def _auth(seed_data) -> dict[str, str]:
    response = _client().post(
        "/auth/login",
        json={"username": "testuser", "password": seed_data["test_password"]},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _catalog(*, active: bool = True) -> LabTestCatalog:
    set_tenant_guc(1)
    suffix = uuid.uuid4().hex
    return LabTestCatalog.objects.create(
        tenant_id=1,
        test_key=f"record_catalog_{suffix}",
        name_fa=f"آزمایش کانونیک {suffix}",
        unit="mg/dL",
        ref_low=10,
        ref_high=20,
        category="other",
        display_order=9999,
        is_active=active,
    )


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_catalog_lab_ignores_tampered_name_unit_and_reference_range(seed_data):
    catalog = _catalog()
    response = _client().post(
        f"/patients/{seed_data['patient_uuid']}/record/labs",
        headers=_auth(seed_data),
        json={
            "test_key": catalog.test_key,
            "test_name": "نام جعل‌شده",
            "value": 14.5,
            "unit": "evil-unit",
            "ref_low": -999,
            "ref_high": 999,
            "notes": "درخواست adversarial",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["test_name"] == catalog.name_fa
    assert payload["unit"] == catalog.unit
    assert payload["ref_low"] == catalog.ref_low
    assert payload["ref_high"] == catalog.ref_high

    set_tenant_guc(1)
    stored = LabResult.objects.get(
        tenant_id=1,
        patient_link_id=seed_data["link_id"],
        id=payload["id"],
    )
    assert stored.test_name == catalog.name_fa
    assert stored.unit == "mg/dL"
    assert stored.ref_low == pytest.approx(10)
    assert stored.ref_high == pytest.approx(20)


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_free_text_lab_keeps_explicit_snapshot_metadata(seed_data):
    response = _client().post(
        f"/patients/{seed_data['patient_uuid']}/record/labs",
        headers=_auth(seed_data),
        json={
            "test_key": None,
            "test_name": "آزمایش آزاد تست",
            "value": 3.25,
            "unit": "custom-unit",
            "ref_low": 1.5,
            "ref_high": 4.5,
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["test_key"] is None
    assert payload["test_name"] == "آزمایش آزاد تست"
    assert payload["unit"] == "custom-unit"
    assert payload["ref_low"] == pytest.approx(1.5)
    assert payload["ref_high"] == pytest.approx(4.5)


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_inactive_catalog_key_is_rejected_even_with_complete_client_metadata(seed_data):
    catalog = _catalog(active=False)
    response = _client().post(
        f"/patients/{seed_data['patient_uuid']}/record/labs",
        headers=_auth(seed_data),
        json={
            "test_key": catalog.test_key,
            "test_name": catalog.name_fa,
            "value": 12,
            "unit": catalog.unit,
            "ref_low": catalog.ref_low,
            "ref_high": catalog.ref_high,
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"

    set_tenant_guc(1)
    assert not LabResult.objects.filter(
        tenant_id=1,
        patient_link_id=seed_data["link_id"],
        test_key=catalog.test_key,
    ).exists()
