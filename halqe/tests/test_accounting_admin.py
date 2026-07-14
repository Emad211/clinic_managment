"""PostgreSQL integration tests for accounting manager configuration."""
from __future__ import annotations

import os

import bcrypt
import psycopg
import pytest
from django.core.management import call_command
from ninja.testing import TestClient

from config.api import api


PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = os.environ.get("PG_PORT", "55432")
TEST_DB = os.environ.get("PG_TEST_DB", "halqe_app_test")
PG_SU_USER = os.environ.get("PG_USER", "postgres")
PG_SU_PASSWORD = os.environ.get("PG_PASSWORD", "validate_only")
ACCOUNTING_USER = os.environ.get("PG_ACCOUNTING_USER", "accounting_login_test")
ACCOUNTING_PASSWORD = os.environ.get("PG_ACCOUNTING_PASSWORD", "accounting_test_pw")

os.environ.setdefault("PG_ACCOUNTING_USER", ACCOUNTING_USER)
os.environ.setdefault("PG_ACCOUNTING_PASSWORD", ACCOUNTING_PASSWORD)


def _conninfo(user: str = PG_SU_USER, password: str = PG_SU_PASSWORD) -> str:
    return (
        f"host='{PG_HOST}' port='{PG_PORT}' user='{user}' "
        f"password='{password}' dbname='{TEST_DB}'"
    )


def _client() -> TestClient:
    return TestClient(api)


def _login(username: str, password: str) -> str:
    response = _client().post(
        "/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def accounting_admin_ready(django_db_setup):
    call_command(
        "ensure_accounting_role",
        login_role=ACCOUNTING_USER,
        login_password=ACCOUNTING_PASSWORD,
        verbosity=0,
    )
    manager_password = "accounting-manager-secret"
    reception_password = "accounting-reception-secret"
    manager_hash = bcrypt.hashpw(manager_password.encode(), bcrypt.gensalt())
    reception_hash = bcrypt.hashpw(reception_password.encode(), bcrypt.gensalt())

    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO platform.users
                (tenant_id, username, password_hash, role, app, full_name,
                 is_active, failed_attempts)
            VALUES
                (1, 'accounting_config_manager', %s, 'manager', 'accounting',
                 'مدیر تنظیمات حسابداری', TRUE, 0),
                (1, 'accounting_config_reception', %s, 'reception', 'accounting',
                 'پذیرش تنظیمات تست', TRUE, 0)
            ON CONFLICT (tenant_id, username) DO UPDATE SET
                password_hash=EXCLUDED.password_hash,
                role=EXCLUDED.role,
                app='accounting',
                full_name=EXCLUDED.full_name,
                is_active=TRUE,
                failed_attempts=0,
                locked_until=NULL
            """,
            (manager_hash, reception_hash),
        )
    return {
        "manager_username": "accounting_config_manager",
        "manager_password": manager_password,
        "reception_username": "accounting_config_reception",
        "reception_password": reception_password,
    }


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_only_manager_or_admin_can_access_configuration(accounting_admin_ready):
    reception = _login(
        accounting_admin_ready["reception_username"],
        accounting_admin_ready["reception_password"],
    )
    denied = _client().get(
        "/accounting/admin/config", headers=_auth(reception)
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "forbidden"

    manager = _login(
        accounting_admin_ready["manager_username"],
        accounting_admin_ready["manager_password"],
    )
    allowed = _client().get(
        "/accounting/admin/config", headers=_auth(manager)
    )
    assert allowed.status_code == 200, allowed.text
    assert {
        "staff", "insurance_schemes", "visit_tariffs", "catalogs",
        "exclusions", "payroll_settings"
    } <= set(allowed.json())


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_manager_can_build_complete_configuration_and_audit_it(accounting_admin_ready):
    token = _login(
        accounting_admin_ready["manager_username"],
        accounting_admin_ready["manager_password"],
    )
    client = _client()
    headers = _auth(token)

    staff_response = client.post(
        "/accounting/admin/staff",
        headers=headers,
        json={
            "full_name": "دکتر تنظیمات یکپارچه",
            "staff_type": "doctor",
            "is_active": True,
        },
    )
    assert staff_response.status_code == 201, staff_response.text
    staff_id = staff_response.json()["id"]

    scheme = client.post(
        "/accounting/admin/insurance-schemes",
        headers=headers,
        json={
            "code": "unified-base",
            "name": "بیمه پایه یکپارچه",
            "is_base": True,
            "is_supplementary": False,
            "is_active": True,
        },
    )
    assert scheme.status_code == 201, scheme.text

    tariff = client.post(
        "/accounting/admin/visit-tariffs",
        headers=headers,
        json={
            "insurance_type": "بیمه پایه یکپارچه",
            "insurance_scheme_id": scheme.json()["id"],
            "tariff_price": 135000,
            "nursing_tariff": 25000,
            "nursing_covers": True,
            "is_active": True,
            "is_base_tariff": True,
        },
    )
    assert tariff.status_code == 201, tariff.text

    nursing = client.post(
        "/accounting/admin/catalogs/nursing",
        headers=headers,
        json={"name": "تزریق تنظیمات یکپارچه", "price": 40000},
    )
    assert nursing.status_code == 201, nursing.text

    procedure = client.post(
        "/accounting/admin/catalogs/procedure",
        headers=headers,
        json={"name": "پانسمان تنظیمات یکپارچه", "price": 80000},
    )
    assert procedure.status_code == 201, procedure.text

    consumable = client.post(
        "/accounting/admin/catalogs/consumable",
        headers=headers,
        json={
            "name": "گاز تنظیمات یکپارچه",
            "price": 12000,
            "category": "supply",
        },
    )
    assert consumable.status_code == 201, consumable.text

    exclusion = client.post(
        "/accounting/admin/exclusions",
        headers=headers,
        json={
            "insurance_type": "بیمه پایه یکپارچه",
            "nursing_service_id": nursing.json()["id"],
            "note": "پرداخت توسط بیمار",
        },
    )
    assert exclusion.status_code == 201, exclusion.text

    payroll = client.post(
        "/accounting/admin/payroll-settings",
        headers=headers,
        json={
            "staff_id": staff_id,
            "base_morning": 500000,
            "base_evening": 600000,
            "base_night": 750000,
            "visit_fee": 25000,
            "injection_percent": 20.5,
            "procedure_percent": 30,
            "tax_percent": 5,
            "nursing_percent": 15,
            "nurse_procedure_percent": 25,
        },
    )
    assert payroll.status_code == 201, payroll.text
    assert payroll.json()["staff_name"] == "دکتر تنظیمات یکپارچه"
    assert payroll.json()["injection_percent"] == pytest.approx(20.5)

    config = client.get("/accounting/admin/config", headers=headers)
    assert config.status_code == 200, config.text
    body = config.json()
    assert any(row["id"] == staff_id for row in body["staff"])
    assert any(
        row["insurance_type"] == "بیمه پایه یکپارچه"
        for row in body["visit_tariffs"]
    )
    assert any(
        row["name"] == "تزریق تنظیمات یکپارچه"
        for row in body["catalogs"]["nursing"]
    )

    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        actions = {
            row[0]
            for row in conn.execute(
                """
                SELECT action_type FROM accounting.activity_logs
                WHERE tenant_id=1 AND action_category='configuration'
                  AND username='accounting_config_manager'
                """
            ).fetchall()
        }
    assert {
        "staff_upsert",
        "insurance_scheme_upsert",
        "visit_tariff_upsert",
        "nursing_catalog_upsert",
        "procedure_catalog_upsert",
        "consumable_catalog_upsert",
        "insurance_exclusion_upsert",
        "payroll_settings_upsert",
    } <= actions


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_validation_and_exclusion_uniqueness_fail_closed(accounting_admin_ready):
    token = _login(
        accounting_admin_ready["manager_username"],
        accounting_admin_ready["manager_password"],
    )
    client = _client()
    headers = _auth(token)

    negative = client.post(
        "/accounting/admin/catalogs/procedure",
        headers=headers,
        json={"name": "قیمت منفی نباید ثبت شود", "price": -1},
    )
    assert negative.status_code == 422
    assert negative.json()["code"] == "invalid_money"

    invalid_percent = client.post(
        "/accounting/admin/payroll-settings",
        headers=headers,
        json={"staff_id": 99999999, "tax_percent": 101},
    )
    assert invalid_percent.status_code == 422

    invalid_flags = client.post(
        "/accounting/admin/insurance-schemes",
        headers=headers,
        json={
            "code": "invalid-both",
            "name": "بیمه نامعتبر",
            "is_base": True,
            "is_supplementary": True,
        },
    )
    assert invalid_flags.status_code == 422


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_cross_tenant_staff_id_cannot_be_updated(accounting_admin_ready):
    token = _login(
        accounting_admin_ready["manager_username"],
        accounting_admin_ready["manager_password"],
    )
    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO accounting.medical_staff
                (id, tenant_id, full_name, staff_type, is_active)
            VALUES (991001, 2, 'پرستار tenant دیگر', 'nurse', TRUE)
            ON CONFLICT (id) DO NOTHING
            """
        )
    response = _client().post(
        "/accounting/admin/staff",
        headers=_auth(token),
        json={
            "id": 991001,
            "full_name": "تلاش برای تغییر",
            "staff_type": "doctor",
            "is_active": False,
        },
    )
    assert response.status_code == 404

    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        row = conn.execute(
            """
            SELECT full_name, staff_type, is_active
            FROM accounting.medical_staff
            WHERE tenant_id=2 AND id=991001
            """
        ).fetchone()
    assert row == ("پرستار tenant دیگر", "nurse", True)
