"""Characterization tests for the legacy-faithful payroll preview."""
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


def _conninfo():
    return f"host='{PG_HOST}' port='{PG_PORT}' user='{PG_USER}' password='{PG_PASSWORD}' dbname='{TEST_DB}'"


def _client():
    return TestClient(api)


def _login(password: str):
    response = _client().post(
        "/auth/login",
        json={"username": "payroll_report_manager", "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


@pytest.fixture(scope="session")
def accounting_payroll_ready(django_db_setup):
    password = "payroll-manager-secret"
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO platform.users
                (tenant_id, username, password_hash, role, app, full_name,
                 is_active, failed_attempts)
            VALUES (1, 'payroll_report_manager', %s, 'manager', 'accounting',
                    'مدیر حقوق تست', TRUE, 0)
            ON CONFLICT (tenant_id, username) DO UPDATE SET
                password_hash=EXCLUDED.password_hash, role='manager', app='accounting',
                full_name=EXCLUDED.full_name, is_active=TRUE, failed_attempts=0,
                locked_until=NULL
            """,
            (password_hash,),
        )
        conn.execute(
            """
            INSERT INTO accounting.patients
                (id, tenant_id, name, family_name, national_id)
            VALUES (881001, 1, 'بیمار', 'حقوق', '0013546813')
            ON CONFLICT (id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO accounting.medical_staff
                (id, tenant_id, full_name, staff_type, is_active)
            VALUES
                (881101, 1, 'دکتر حقوق', 'doctor', TRUE),
                (881102, 1, 'پرستار حقوق', 'nurse', TRUE)
            ON CONFLICT (id) DO UPDATE SET is_active=TRUE
            """
        )
        conn.execute(
            """
            INSERT INTO accounting.payroll_settings
                (tenant_id, staff_id, base_morning, base_evening, base_night,
                 visit_fee, injection_percent, procedure_percent, tax_percent,
                 nursing_percent, nurse_procedure_percent)
            VALUES
                (1, 881101, 100000, 200000, 300000, 20000, 30, 40, 10, 0, 0),
                (1, 881102, 50000, 60000, 70000, 0, 0, 0, 0, 6, 35)
            ON CONFLICT (tenant_id, staff_id) DO UPDATE SET
                base_morning=EXCLUDED.base_morning,
                base_evening=EXCLUDED.base_evening,
                base_night=EXCLUDED.base_night,
                visit_fee=EXCLUDED.visit_fee,
                injection_percent=EXCLUDED.injection_percent,
                procedure_percent=EXCLUDED.procedure_percent,
                tax_percent=EXCLUDED.tax_percent,
                nursing_percent=EXCLUDED.nursing_percent,
                nurse_procedure_percent=EXCLUDED.nurse_procedure_percent
            """
        )
        conn.execute(
            """
            INSERT INTO accounting.invoices
                (id, tenant_id, patient_id, doctor_id, nurse_id, status,
                 total_amount, work_date, shift, opened_by, pricing_version)
            VALUES
                (881010, 1, 881001, 881101, 881102, 'closed', 170000,
                 '2026-07-10', 'morning', 'payroll_report_manager',
                 'halqe_visit_procedure_v1'),
                (881011, 1, 881001, 881101, NULL, 'open', 0,
                 '2026-07-11', 'evening', 'payroll_report_manager',
                 'halqe_visit_v1')
            ON CONFLICT (id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO accounting.visits
                (id, tenant_id, patient_id, doctor_name, visit_date, shift,
                 work_date, status, price, payment_status, reception_user,
                 invoice_id, doctor_id)
            VALUES
                (881110, 1, 881001, 'دکتر حقوق', '2026-07-10 08:00:00+03:30',
                 'morning', '2026-07-10', 'done', 20000, 'paid',
                 'payroll_report_manager', 881010, 881101),
                (881111, 1, 881001, 'دکتر حقوق', '2026-07-11 16:00:00+03:30',
                 'evening', '2026-07-11', 'pending', 20000, 'unpaid',
                 'payroll_report_manager', 881011, 881101)
            ON CONFLICT (id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO accounting.injections
                (id, tenant_id, patient_id, injection_type, injection_date,
                 shift, work_date, count, unit_price, total_price,
                 patient_amount, insurance_amount, reception_user, invoice_id,
                 doctor_id, nurse_id)
            VALUES (881210, 1, 881001, 'تزریق حقوق',
                    '2026-07-10 08:20:00+03:30', 'morning', '2026-07-10',
                    1, 50000, 50000, 50000, 0, 'payroll_report_manager',
                    881010, 881101, 881102)
            ON CONFLICT (id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO accounting.procedures
                (id, tenant_id, patient_id, procedure_type, procedure_date,
                 shift, work_date, price, patient_amount, insurance_amount,
                 reception_user, invoice_id, performer_type, performer_id,
                 doctor_id, nurse_id)
            VALUES (881310, 1, 881001, 'پروسیجر حقوق',
                    '2026-07-10 08:30:00+03:30', 'morning', '2026-07-10',
                    100000, 100000, 0, 'payroll_report_manager', 881010,
                    'nurse', 881102, 881101, 881102)
            ON CONFLICT (id) DO NOTHING
            """
        )
    return password


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_payroll_matches_legacy_doctor_formula(accounting_payroll_ready):
    response = _client().get(
        "/accounting/reports/payroll?date_from=2026-07-10&date_to=2026-07-11&staff_id=881101",
        headers=_login(accounting_payroll_ready),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    doctor = body["rows"][0]
    assert doctor["shift_counts"] == {"morning": 1, "evening": 1, "night": 0}
    assert doctor["gross_salary"] == pytest.approx(375000)
    assert doctor["tax_amount"] == pytest.approx(37500)
    assert doctor["net_salary"] == pytest.approx(337500)
    assert next(d for d in doctor["details"] if d["code"] == "visits")["count"] == 1
    assert body["summary"]["staff_count"] == 1


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_payroll_matches_legacy_nurse_formula(accounting_payroll_ready):
    response = _client().get(
        "/accounting/reports/payroll?date_from=2026-07-10&date_to=2026-07-11&staff_id=881102",
        headers=_login(accounting_payroll_ready),
    )
    assert response.status_code == 200, response.text
    nurse = response.json()["rows"][0]
    assert nurse["shift_counts"] == {"morning": 1, "evening": 0, "night": 0}
    assert nurse["gross_salary"] == pytest.approx(88000)
    assert nurse["tax_amount"] == 0
    assert nurse["net_salary"] == pytest.approx(88000)


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_payroll_filters_are_fail_closed(accounting_payroll_ready):
    headers = _login(accounting_payroll_ready)
    doctor = _client().get(
        "/accounting/reports/payroll?date_from=2026-07-10&date_to=2026-07-11&staff_id=881101&staff_type=doctor&shift=morning",
        headers=headers,
    )
    assert doctor.status_code == 200, doctor.text
    assert [row["id"] for row in doctor.json()["rows"]] == [881101]
    assert doctor.json()["rows"][0]["shift_counts"] == {
        "morning": 1, "evening": 0, "night": 0
    }
    invalid = _client().get(
        "/accounting/reports/payroll?staff_type=accountant", headers=headers
    )
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "invalid_staff_type"
