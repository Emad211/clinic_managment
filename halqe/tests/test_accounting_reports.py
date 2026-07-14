"""PostgreSQL characterization tests for unified accounting reports."""
from __future__ import annotations

import os
import bcrypt
import psycopg
import pytest
from ninja.testing import TestClient
from config.api import api

PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = os.environ.get("PG_PORT", "55432")
TEST_DB = os.environ.get("PG_TEST_DB", "halqe_app_test")
PG_USER = os.environ.get("PG_USER", "postgres")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "validate_only")
PG_APP_USER = os.environ.get("PG_APP_USER", "platform_login_test")
PG_APP_PASSWORD = os.environ.get("PG_APP_PASSWORD", "test_pw")


def _conninfo(user=PG_USER, password=PG_PASSWORD):
    return f"host='{PG_HOST}' port='{PG_PORT}' user='{user}' password='{password}' dbname='{TEST_DB}'"


def _client():
    return TestClient(api)


def _login(username: str, password: str):
    response = _client().post(
        "/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


@pytest.fixture(scope="session")
def accounting_report_ready(django_db_setup):
    manager_password = "report-manager-secret"
    reception_password = "report-reception-secret"
    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO platform.tenants (id, name, is_active)
            VALUES (2, 'Report other tenant', TRUE)
            ON CONFLICT (id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO platform.users
                (tenant_id, username, password_hash, role, app, full_name,
                 is_active, failed_attempts)
            VALUES
                (1, 'accounting_report_manager', %s, 'manager', 'accounting',
                 'مدیر گزارش حسابداری', TRUE, 0),
                (1, 'accounting_report_reception', %s, 'reception', 'accounting',
                 'پذیرش گزارش تست', TRUE, 0)
            ON CONFLICT (tenant_id, username) DO UPDATE SET
                password_hash=EXCLUDED.password_hash, role=EXCLUDED.role,
                app='accounting', full_name=EXCLUDED.full_name, is_active=TRUE,
                failed_attempts=0, locked_until=NULL
            """,
            (
                bcrypt.hashpw(manager_password.encode(), bcrypt.gensalt()),
                bcrypt.hashpw(reception_password.encode(), bcrypt.gensalt()),
            ),
        )
        conn.execute(
            """
            INSERT INTO accounting.patients
                (id, tenant_id, name, family_name, national_id, phone_number)
            VALUES
                (880001, 1, 'بیمار', 'گزارش', '0013546791', '09120000111'),
                (880002, 2, 'بیمار', 'tenant دیگر', '0013546805', '09120000222')
            ON CONFLICT (id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO accounting.medical_staff
                (id, tenant_id, full_name, staff_type, is_active)
            VALUES
                (880101, 1, 'دکتر گزارش', 'doctor', TRUE),
                (880102, 1, 'پرستار گزارش', 'nurse', TRUE),
                (880201, 2, 'دکتر tenant دیگر', 'doctor', TRUE)
            ON CONFLICT (id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO accounting.payroll_settings
                (tenant_id, staff_id, base_morning)
            VALUES (1, 880101, 100000)
            ON CONFLICT (tenant_id, staff_id) DO UPDATE
              SET base_morning=EXCLUDED.base_morning
            """
        )
        conn.execute(
            """
            INSERT INTO accounting.invoices
                (id, tenant_id, patient_id, doctor_id, nurse_id, status,
                 insurance_type, total_amount, work_date, shift,
                 opened_by, opened_by_name, closed_by, closed_by_name,
                 opened_at, closed_at, pricing_version)
            VALUES
                (880010, 1, 880001, 880101, 880102, 'closed', 'بیمه پایه گزارش',
                 210000, '2099-07-10', 'morning', 'accounting_report_reception',
                 'پذیرش گزارش تست', 'accounting_report_manager',
                 'مدیر گزارش حسابداری', '2099-07-10 08:00:00+03:30',
                 '2099-07-10 09:00:00+03:30', 'halqe_visit_procedure_v1'),
                (880011, 1, 880001, 880101, 880102, 'open', 'آزاد',
                 30000, '2099-07-11', 'evening', 'accounting_report_reception',
                 'پذیرش گزارش تست', NULL, NULL,
                 '2099-07-11 16:00:00+03:30', NULL, 'halqe_visit_v1'),
                (880020, 2, 880002, 880201, NULL, 'closed', 'بیمه tenant دیگر',
                 9900000, '2099-07-10', 'morning', 'other_user', 'کاربر دیگر',
                 'other_manager', 'مدیر دیگر', '2099-07-10 08:00:00+03:30',
                 '2099-07-10 09:00:00+03:30', 'halqe_visit_v1')
            ON CONFLICT (id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO accounting.visits
                (id, tenant_id, patient_id, doctor_name, visit_date, shift,
                 work_date, insurance_type, status, price, payment_status,
                 reception_user, invoice_id, doctor_id)
            VALUES
                (880110, 1, 880001, 'دکتر گزارش', '2099-07-10 08:10:00+03:30',
                 'morning', '2099-07-10', 'بیمه پایه گزارش', 'done', 100000,
                 'paid', 'accounting_report_reception', 880010, 880101),
                (880120, 2, 880002, 'دکتر tenant دیگر', '2099-07-10 08:10:00+03:30',
                 'morning', '2099-07-10', 'بیمه tenant دیگر', 'done', 9900000,
                 'paid', 'other_user', 880020, 880201)
            ON CONFLICT (id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO accounting.injections
                (id, tenant_id, patient_id, injection_type, injection_date,
                 shift, work_date, count, unit_price, total_price,
                 patient_amount, insurance_amount, covered_by_insurance,
                 reception_user, invoice_id, doctor_id, nurse_id)
            VALUES (880210, 1, 880001, 'تزریق گزارش',
                    '2099-07-10 08:20:00+03:30', 'morning', '2099-07-10',
                    1, 50000, 50000, 20000, 30000, TRUE,
                    'accounting_report_reception', 880010, 880101, 880102)
            ON CONFLICT (id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO accounting.procedures
                (id, tenant_id, patient_id, procedure_type, procedure_date,
                 shift, work_date, price, patient_amount, insurance_amount,
                 covered_by_insurance, reception_user, invoice_id,
                 performer_type, performer_id, doctor_id)
            VALUES (880310, 1, 880001, 'پروسیجر گزارش',
                    '2099-07-10 08:30:00+03:30', 'morning', '2099-07-10',
                    80000, 80000, 0, FALSE, 'accounting_report_reception',
                    880010, 'doctor', 880101, 880101)
            ON CONFLICT (id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO accounting.consumables_ledger
                (id, tenant_id, patient_id, item_name, category, quantity,
                 unit_price, total_cost, patient_provided, is_exception,
                 usage_date, shift, work_date, reception_user, invoice_id,
                 doctor_id, nurse_id)
            VALUES
                (880410, 1, 880001, 'گاز گزارش', 'supply', 1, 12000, 12000,
                 FALSE, FALSE, '2099-07-10 08:40:00+03:30', 'morning',
                 '2099-07-10', 'accounting_report_reception', 880010, 880101, 880102),
                (880411, 1, 880001, 'داروی آورده بیمار', 'drug', 1, 999000, 999000,
                 TRUE, FALSE, '2099-07-10 08:45:00+03:30', 'morning',
                 '2099-07-10', 'accounting_report_reception', 880010, 880101, 880102)
            ON CONFLICT (id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO accounting.invoice_item_payments
                (tenant_id, invoice_id, item_type, item_id, payment_type, is_paid)
            VALUES
                (1, 880010, 'visit', 880110, 'card', TRUE),
                (1, 880010, 'injection', 880210, 'insurance', TRUE),
                (1, 880010, 'procedure', 880310, 'cash', TRUE),
                (1, 880010, 'consumable', 880410, NULL, FALSE)
            ON CONFLICT (tenant_id, invoice_id, item_type, item_id)
            DO UPDATE SET payment_type=EXCLUDED.payment_type, is_paid=EXCLUDED.is_paid
            """
        )
    return {"manager": manager_password, "reception": reception_password}


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_overview_preserves_legacy_revenue_and_tenant_boundary(accounting_report_ready):
    response = _client().get(
        "/accounting/reports/overview?date_from=2099-07-10&date_to=2099-07-12",
        headers=_login("accounting_report_manager", accounting_report_ready["manager"]),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["invoices"] == {
        "total": 2, "open": 1, "closed": 1,
        "unique_patients": 1, "total_liability": 240000,
    }
    assert body["revenue"]["visit"] == {"count": 1, "amount": 100000}
    assert body["revenue"]["nursing"] == {"count": 1, "amount": 50000}
    assert body["revenue"]["procedure"] == {"count": 1, "amount": 80000}
    assert body["revenue"]["operating_revenue"] == 230000
    assert body["consumables"] == {"count": 1, "amount": 12000}
    assert body["payments"] == {"items": 4, "paid_items": 3, "unpaid_items": 1}
    assert {row["id"] for row in body["recent_invoices"]} == {880010, 880011}


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_report_filters_and_service_projection(accounting_report_ready):
    headers = _login("accounting_report_manager", accounting_report_ready["manager"])
    invoices = _client().get(
        "/accounting/reports/invoices?date_from=2099-07-10&date_to=2099-07-12&status=closed",
        headers=headers,
    )
    assert invoices.status_code == 200, invoices.text
    assert [row["id"] for row in invoices.json()["rows"]] == [880010]
    services = _client().get(
        "/accounting/reports/services?date_from=2099-07-10&date_to=2099-07-12",
        headers=headers,
    )
    assert services.status_code == 200, services.text
    body = services.json()
    assert set(body["summary"]) == {"visit", "nursing", "procedure", "consumable"}
    assert not any(row["service_name"] == "داروی آورده بیمار" for row in body["rows"])
    assert next(row for row in body["rows"] if row["service_type"] == "consumable")["included_in_revenue"] is False


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_reports_are_manager_only_and_validation_fails_closed(accounting_report_ready):
    denied = _client().get(
        "/accounting/reports/overview",
        headers=_login("accounting_report_reception", accounting_report_ready["reception"]),
    )
    assert denied.status_code == 403
    manager = _login("accounting_report_manager", accounting_report_ready["manager"])
    assert _client().get(
        "/accounting/reports/invoices?status=deleted", headers=manager
    ).status_code == 422
    assert _client().get(
        "/accounting/reports/overview?date_from=2020-01-01&date_to=2026-07-10",
        headers=manager,
    ).status_code == 422


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_platform_read_port_is_select_only_for_reporting_tables(accounting_report_ready):
    with psycopg.connect(_conninfo(PG_APP_USER, PG_APP_PASSWORD), autocommit=True) as conn:
        conn.execute("SELECT set_config('app.current_tenant', '1', false)")
        assert conn.execute(
            "SELECT COUNT(*) FROM accounting.medical_staff WHERE tenant_id=1"
        ).fetchone()[0] >= 2
        assert conn.execute(
            "SELECT COUNT(*) FROM accounting.payroll_settings WHERE tenant_id=1"
        ).fetchone()[0] >= 1
        assert conn.execute(
            "SELECT COUNT(*) FROM accounting.invoice_item_payments WHERE tenant_id=1"
        ).fetchone()[0] >= 4
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "UPDATE accounting.medical_staff SET full_name=full_name WHERE id=880101"
            )
