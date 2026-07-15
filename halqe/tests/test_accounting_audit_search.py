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


def _conninfo() -> str:
    return (
        f"host='{PG_HOST}' port='{PG_PORT}' user='{PG_USER}' "
        f"password='{PG_PASSWORD}' dbname='{TEST_DB}'"
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
def accounting_audit_ready(django_db_setup):
    manager_password = "audit-manager-secret"
    reception_password = "audit-reception-secret"
    manager_hash = bcrypt.hashpw(manager_password.encode(), bcrypt.gensalt())
    reception_hash = bcrypt.hashpw(reception_password.encode(), bcrypt.gensalt())
    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO platform.tenants(id,name,is_active)
            VALUES(2,'Audit tenant two',TRUE) ON CONFLICT(id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO platform.users(
                tenant_id,username,password_hash,role,app,full_name,is_active,failed_attempts
            ) VALUES
                (1,'accounting_audit_manager',%s,'manager','accounting','مدیر رویداد',TRUE,0),
                (1,'accounting_audit_reception',%s,'reception','accounting','پذیرش رویداد',TRUE,0)
            ON CONFLICT(tenant_id,username) DO UPDATE SET
                password_hash=EXCLUDED.password_hash,
                role=EXCLUDED.role,
                app=EXCLUDED.app,
                full_name=EXCLUDED.full_name,
                is_active=TRUE,
                failed_attempts=0,
                locked_until=NULL
            """,
            (manager_hash, reception_hash),
        )
        manager_id = conn.execute(
            """
            SELECT id FROM platform.users
            WHERE tenant_id=1 AND username='accounting_audit_manager'
            """
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO accounting.patients(id,tenant_id,name,family_name)
            VALUES
                (920001,1,'بیمار','آلفا'),
                (999002,2,'بیمار','tenant دیگر')
            ON CONFLICT(id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO accounting.invoices(
                id,tenant_id,patient_id,status,total_amount,work_date,shift,
                opened_at,opened_by,pricing_version
            ) VALUES
                (910001,1,920001,'closed',120000,'2099-01-01','morning',
                 '2099-01-01 07:45:00+03:30','accounting_audit_manager','legacy'),
                (999001,2,999002,'closed',999999,'2099-01-01','morning',
                 '2099-01-01 07:45:00+03:30','other-audit-user','legacy')
            ON CONFLICT(id) DO NOTHING
            """
        )
        conn.execute(
            """
            DELETE FROM accounting.activity_logs
            WHERE (tenant_id=1 AND username='accounting_audit_manager')
               OR (tenant_id=2 AND username='other-audit-user')
            """
        )
        conn.execute(
            """
            INSERT INTO accounting.activity_logs(
                tenant_id,user_id,username,action_type,action_category,description,
                target_type,target_id,target_name,invoice_id,patient_id,patient_name,
                amount,old_value,new_value,ip_address,user_agent,created_at
            ) VALUES
                (1,%s,'accounting_audit_manager','invoice_create','invoice',
                 'ایجاد فاکتور آزمایشی','invoice',910001,'فاکتور آزمایشی',910001,
                 920001,'بیمار آلفا',120000,NULL,'open','127.0.0.1','audit-test',
                 '2099-01-01 08:00:00+03:30'),
                (1,%s,'accounting_audit_manager','item_payment_set','invoice',
                 'پرداخت کارت بیمار آلفا','visit',930001,'ویزیت آزمایشی',910001,
                 920001,'بیمار آلفا',120000,'unpaid','paid','127.0.0.1','audit-test',
                 '2099-01-01 09:00:00+03:30'),
                (1,%s,'accounting_audit_manager','payroll_settings_upsert','configuration',
                 'تنظیم قرارداد کادر درمان','payroll',940001,'قرارداد مصنوعی',NULL,
                 NULL,NULL,0,'old','new','127.0.0.1','audit-test',
                 '2099-01-02 10:00:00+03:30'),
                (2,NULL,'other-audit-user','invoice_create','invoice',
                 'نباید در tenant یک دیده شود','invoice',999001,'فاکتور tenant دیگر',
                 999001,NULL,NULL,999999,NULL,NULL,NULL,NULL,
                 '2099-01-01 08:30:00+03:30')
            """,
            (manager_id, manager_id, manager_id),
        )
    return {
        "manager_password": manager_password,
        "reception_password": reception_password,
    }


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_manager_can_page_and_filter_audit_rows(accounting_audit_ready):
    token = _login(
        "accounting_audit_manager", accounting_audit_ready["manager_password"]
    )
    headers = _auth(token)
    response = _client().get(
        "/accounting/audit/logs?date_from=2099-01-01&date_to=2099-01-02&page_size=2",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["total_pages"] == 2
    assert [row["action_type"] for row in body["rows"]] == [
        "payroll_settings_upsert",
        "item_payment_set",
    ]
    assert {row["action_category"] for row in body["category_summary"]} == {
        "invoice",
        "configuration",
    }
    assert "invoice_create" in body["filter_options"]["action_types"]
    assert not any(row["username"] == "other-audit-user" for row in body["rows"])

    filtered = _client().get(
        "/accounting/audit/logs?date_from=2099-01-01&date_to=2099-01-02"
        "&action_category=invoice&invoice_id=910001&search_text=آلفا",
        headers=headers,
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 2
    assert {row["action_type"] for row in filtered.json()["rows"]} == {
        "invoice_create",
        "item_payment_set",
    }


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_audit_is_manager_only_and_validation_fails_closed(accounting_audit_ready):
    reception = _login(
        "accounting_audit_reception", accounting_audit_ready["reception_password"]
    )
    denied = _client().get(
        "/accounting/audit/logs?date_from=2099-01-01&date_to=2099-01-02",
        headers=_auth(reception),
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "forbidden"

    manager = _login(
        "accounting_audit_manager", accounting_audit_ready["manager_password"]
    )
    too_large = _client().get(
        "/accounting/audit/logs?date_from=2098-01-01&date_to=2099-01-02",
        headers=_auth(manager),
    )
    assert too_large.status_code == 422
    assert too_large.json()["code"] == "report_range_too_large"

    invalid_size = _client().get(
        "/accounting/audit/logs?page_size=101",
        headers=_auth(manager),
    )
    assert invalid_size.status_code == 422
    assert invalid_size.json()["code"] == "invalid_audit_page_size"
