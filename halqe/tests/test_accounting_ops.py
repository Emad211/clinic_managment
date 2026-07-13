"""Accounting migration tests: reception, payment and paid-only close.

The suite exercises the real PostgreSQL permission boundary and keeps the
legacy money rules fail-closed while item families are moved incrementally.
"""
from __future__ import annotations

import os

import bcrypt
import psycopg
import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import override_settings
from ninja.testing import TestClient

from accounting_ops.service import list_open_invoices
from accounting_ops.write_port import _accounting_credentials
from config.api import api


PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = os.environ.get("PG_PORT", "55432")
TEST_DB = os.environ.get("PG_TEST_DB", "halqe_app_test")
PG_SU_USER = os.environ.get("PG_USER", "postgres")
PG_SU_PASSWORD = os.environ.get("PG_PASSWORD", "validate_only")
ACCOUNTING_USER = os.environ.get("PG_ACCOUNTING_USER", "accounting_login_test")
ACCOUNTING_PASSWORD = os.environ.get(
    "PG_ACCOUNTING_PASSWORD", "accounting_test_pw"
)

os.environ.setdefault("PG_ACCOUNTING_USER", ACCOUNTING_USER)
os.environ.setdefault("PG_ACCOUNTING_PASSWORD", ACCOUNTING_PASSWORD)


def _conninfo(user: str, password: str, dbname: str = TEST_DB) -> str:
    return (
        f"host='{PG_HOST}' port='{PG_PORT}' user='{user}' "
        f"password='{password}' dbname='{dbname}'"
    )


def _client() -> TestClient:
    return TestClient(api)


def _login(username: str, password: str) -> str:
    response = _client().post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _open_visit(
    client: TestClient,
    token: str,
    *,
    national_id: str,
    family_name: str,
    insurance_type: str = "تامین اجتماعی",
    supplementary: str | None = None,
):
    response = client.post(
        "/accounting/invoices/visit",
        headers=_auth(token),
        json={
            "patient": {
                "name": "بیمار",
                "family_name": family_name,
                "national_id": national_id,
                "phone_number": "09121111111",
                "is_foreign": False,
            },
            "insurance_type": insurance_type,
            "supplementary_insurance": supplementary,
            "notes": "ویزیت مهاجرت حسابداری",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@override_settings(PRODUCTION=True)
def test_production_requires_explicit_accounting_password(monkeypatch):
    monkeypatch.delenv("PG_ACCOUNTING_PASSWORD", raising=False)
    monkeypatch.setenv("PG_APP_PASSWORD", "clinical-password-is-not-enough")
    with pytest.raises(ImproperlyConfigured, match="PG_ACCOUNTING_PASSWORD"):
        _accounting_credentials()


@override_settings(PRODUCTION=True)
def test_production_rejects_documented_accounting_placeholder(monkeypatch):
    monkeypatch.setenv("PG_ACCOUNTING_PASSWORD", "accounting_change_me")
    with pytest.raises(ImproperlyConfigured, match="placeholder"):
        _accounting_credentials()


@pytest.fixture(scope="session")
def accounting_ready(django_db_setup):
    """Create the writer login and seed neutral tariffs + receptionist/shift."""
    password = "reception-secret"
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

    call_command(
        "ensure_accounting_role",
        login_role=ACCOUNTING_USER,
        login_password=ACCOUNTING_PASSWORD,
        verbosity=0,
    )

    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as conn:
        conn.execute(
            """
            INSERT INTO platform.tenants (id, name, is_active)
            VALUES (2, 'درمانگاه حسابداری دوم', TRUE)
            ON CONFLICT (id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO accounting.visit_tariffs
                (tenant_id, insurance_type, tariff_price, is_active,
                 is_supplementary, is_base_tariff)
            VALUES
                (1, 'آزاد', 200000, TRUE, FALSE, TRUE),
                (1, 'تامین اجتماعی', 85000, TRUE, FALSE, FALSE),
                (1, 'تکمیلی تست', 20000, TRUE, TRUE, FALSE)
            ON CONFLICT (tenant_id, insurance_type) DO UPDATE SET
                tariff_price=EXCLUDED.tariff_price,
                is_active=EXCLUDED.is_active,
                is_supplementary=EXCLUDED.is_supplementary,
                is_base_tariff=EXCLUDED.is_base_tariff
            """
        )
        conn.execute(
            """
            INSERT INTO platform.users
                (tenant_id, username, password_hash, role, app, full_name,
                 is_active, failed_attempts)
            VALUES (1, 'reception_test', %s, 'reception', 'accounting',
                    'پذیرش تست', TRUE, 0)
            ON CONFLICT (tenant_id, username) DO UPDATE SET
                password_hash=EXCLUDED.password_hash,
                role='reception', app='accounting', full_name='پذیرش تست',
                is_active=TRUE, failed_attempts=0, locked_until=NULL
            """,
            (password_hash,),
        )
        user_id = conn.execute(
            "SELECT id FROM platform.users "
            "WHERE tenant_id=1 AND username='reception_test'"
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO accounting.user_active_shift
                (tenant_id, user_id, active_shift, work_date, shift_started_at)
            VALUES (1, %s, 'night', '2026-07-12', now())
            ON CONFLICT (tenant_id, user_id) DO UPDATE SET
                active_shift=EXCLUDED.active_shift,
                work_date=EXCLUDED.work_date,
                shift_started_at=EXCLUDED.shift_started_at
            """,
            (user_id,),
        )

    return {
        "username": "reception_test",
        "password": password,
        "user_id": int(user_id),
    }


@override_settings(PRODUCTION=True)
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_accounting_api_is_fail_closed_when_writer_secret_is_missing(
    accounting_ready, monkeypatch
):
    token = _login(accounting_ready["username"], accounting_ready["password"])
    monkeypatch.delenv("PG_ACCOUNTING_PASSWORD", raising=False)
    response = _client().get(
        "/accounting/invoices/open",
        headers=_auth(token),
    )
    assert response.status_code == 503
    assert response.json()["code"] == "accounting_unavailable"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_staff_role_cannot_access_accounting(seed_data, accounting_ready):
    token = _login("testuser", seed_data["test_password"])
    response = _client().get(
        "/accounting/invoices/open",
        headers=_auth(token),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_visit_invoice_requires_settlement_before_close_and_is_audited(
    accounting_ready,
):
    token = _login(accounting_ready["username"], accounting_ready["password"])
    client = _client()
    opened = _open_visit(
        client,
        token,
        national_id="2170415981",
        family_name="حسابی",
    )
    invoice_id = opened["id"]

    assert opened["status"] == "open"
    assert opened["pricing_version"] == "halqe_visit_v1"
    assert opened["total_amount"] == 85000
    assert opened["visit_price"] == 85000
    assert opened["shift"] == "night"
    assert opened["work_date"] == "2026-07-12"
    assert list_open_invoices(tenant_id=2)["items"] == []

    financials = client.get(
        f"/accounting/invoices/{invoice_id}/financials",
        headers=_auth(token),
    )
    assert financials.status_code == 200, financials.text
    assert financials.json() == {
        "invoice_id": invoice_id,
        "total_amount": 85000,
        "paid_amount": 0,
        "remaining_amount": 85000,
        "all_items_paid": False,
        "payment_type": None,
    }

    blocked = client.post(
        f"/accounting/invoices/{invoice_id}/close",
        headers=_auth(token),
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "invoice_unpaid_items"

    invalid = client.post(
        f"/accounting/invoices/{invoice_id}/settle-all",
        headers=_auth(token),
        json={"payment_type": "crypto"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "invalid_payment_type"

    settled = client.post(
        f"/accounting/invoices/{invoice_id}/settle-all",
        headers=_auth(token),
        json={"payment_type": "card"},
    )
    assert settled.status_code == 200, settled.text
    assert settled.json()["paid_amount"] == 85000
    assert settled.json()["remaining_amount"] == 0
    assert settled.json()["all_items_paid"] is True
    assert settled.json()["payment_type"] == "card"

    closed_response = client.post(
        f"/accounting/invoices/{invoice_id}/close",
        headers=_auth(token),
    )
    assert closed_response.status_code == 200, closed_response.text
    assert closed_response.json()["status"] == "closed"
    assert closed_response.json()["closed_by"] == accounting_ready["username"]

    repeated = client.post(
        f"/accounting/invoices/{invoice_id}/close",
        headers=_auth(token),
    )
    assert repeated.status_code == 409
    assert repeated.json()["code"] == "invoice_already_closed"

    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as conn:
        visit = conn.execute(
            "SELECT price, notes FROM accounting.visits "
            "WHERE tenant_id=1 AND invoice_id=%s",
            (invoice_id,),
        ).fetchone()
        assert (int(visit[0]), visit[1]) == (85000, "ویزیت مهاجرت حسابداری")
        actions = conn.execute(
            "SELECT action_type FROM accounting.activity_logs "
            "WHERE tenant_id=1 AND invoice_id=%s ORDER BY id",
            (invoice_id,),
        ).fetchall()
        assert [row[0] for row in actions] == [
            "invoice_create",
            "invoice_settle",
            "invoice_close",
        ]


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_individual_visit_payment_can_be_reversed_before_close(accounting_ready):
    token = _login(accounting_ready["username"], accounting_ready["password"])
    client = _client()
    opened = _open_visit(
        client,
        token,
        national_id="0001001000",
        family_name="پرداخت آیتمی",
        insurance_type="آزاد",
    )
    path = (
        f"/accounting/invoices/{opened['id']}/items/visit/"
        f"{opened['visit_id']}/payment"
    )
    paid = client.post(path, headers=_auth(token), json={
        "payment_type": "cash", "is_paid": True
    })
    assert paid.status_code == 200, paid.text
    assert paid.json()["all_items_paid"] is True
    assert paid.json()["payment_type"] == "cash"

    reversed_payment = client.post(path, headers=_auth(token), json={
        "payment_type": None, "is_paid": False
    })
    assert reversed_payment.status_code == 200, reversed_payment.text
    assert reversed_payment.json()["paid_amount"] == 0
    assert reversed_payment.json()["all_items_paid"] is False

    blocked = client.post(
        f"/accounting/invoices/{opened['id']}/close",
        headers=_auth(token),
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "invoice_unpaid_items"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_postgres_trigger_rejects_direct_unpaid_close(accounting_ready):
    token = _login(accounting_ready["username"], accounting_ready["password"])
    opened = _open_visit(
        _client(),
        token,
        national_id="0013546759",
        family_name="گیت دیتابیس",
        insurance_type="آزاد",
    )
    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as conn:
        with pytest.raises(psycopg.errors.CheckViolation, match="unpaid"):
            conn.execute(
                "UPDATE accounting.invoices SET status='closed' "
                "WHERE tenant_id=1 AND id=%s",
                (opened["id"],),
            )
        state = conn.execute(
            "SELECT status, closed_at FROM accounting.invoices "
            "WHERE tenant_id=1 AND id=%s",
            (opened["id"],),
        ).fetchone()
        assert state == ("open", None)


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_supplementary_overrides_primary_and_patient_is_upserted(accounting_ready):
    token = _login(accounting_ready["username"], accounting_ready["password"])
    client = _client()
    national_id = "2110530979"
    first = _open_visit(
        client,
        token,
        national_id=national_id,
        family_name="تطبیق",
    )
    assert first["total_amount"] == 85000

    second = client.post(
        "/accounting/invoices/visit",
        headers=_auth(token),
        json={
            "patient": {
                "name": "سارا",
                "family_name": "تطبیق‌شده",
                "national_id": national_id,
                "phone_number": "09126666666",
                "is_foreign": False,
            },
            "insurance_type": "تامین اجتماعی",
            "supplementary_insurance": "تکمیلی تست",
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["total_amount"] == 20000
    assert second.json()["patient_full_name"] == "سارا تطبیق‌شده"

    search = client.get(
        f"/accounting/patients/search?q={national_id}&limit=10",
        headers=_auth(token),
    )
    assert search.status_code == 200
    assert len(search.json()) == 1
    assert search.json()[0]["phone_number"] == "09126666666"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_missing_tariff_rolls_back_patient_and_invoice(accounting_ready):
    token = _login(accounting_ready["username"], accounting_ready["password"])
    response = _client().post(
        "/accounting/invoices/visit",
        headers=_auth(token),
        json={
            "patient": {
                "name": "بیمار",
                "family_name": "Rollback",
                "national_id": "0440253519",
                "phone_number": "09122222222",
                "is_foreign": False,
            },
            "insurance_type": "بیمه ناشناخته",
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "tariff_not_found"

    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM accounting.patients "
            "WHERE tenant_id=1 AND national_id='0440253519'"
        ).fetchone()[0] == 0


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_unported_item_family_blocks_settlement_and_close(accounting_ready):
    token = _login(accounting_ready["username"], accounting_ready["password"])
    client = _client()
    opened = _open_visit(
        client,
        token,
        national_id="0001000004",
        family_name="محافظت مالی",
        insurance_type="آزاد",
    )
    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as conn:
        conn.execute(
            """
            INSERT INTO accounting.injections
                (tenant_id, patient_id, injection_type, total_price,
                 patient_amount, invoice_id)
            VALUES (1, %s, 'تزریق تست', 50000, 50000, %s)
            """,
            (opened["patient_id"], opened["id"]),
        )

    settle = client.post(
        f"/accounting/invoices/{opened['id']}/settle-all",
        headers=_auth(token),
        json={"payment_type": "card"},
    )
    assert settle.status_code == 409
    assert settle.json()["code"] == "unsupported_invoice_items"

    close = client.post(
        f"/accounting/invoices/{opened['id']}/close",
        headers=_auth(token),
    )
    assert close.status_code == 409
    assert close.json()["code"] == "unsupported_invoice_items"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_legacy_pricing_invoice_stays_on_old_path(accounting_ready):
    token = _login(accounting_ready["username"], accounting_ready["password"])
    client = _client()
    opened = _open_visit(
        client,
        token,
        national_id="2170415981",
        family_name="قدیمی",
        insurance_type="آزاد",
    )
    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as conn:
        conn.execute(
            "UPDATE accounting.invoices SET pricing_version='legacy' "
            "WHERE tenant_id=1 AND id=%s",
            (opened["id"],),
        )

    response = client.post(
        f"/accounting/invoices/{opened['id']}/settle-all",
        headers=_auth(token),
        json={"payment_type": "card"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "legacy_invoice_close_blocked"


def test_accounting_login_is_confined_to_accounting(accounting_ready):
    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as super_conn:
        flags = super_conn.execute(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
            "FROM pg_roles WHERE rolname=%s",
            (ACCOUNTING_USER,),
        ).fetchone()
        assert flags == (False, False, False, False, False)
        memberships = super_conn.execute(
            """
            SELECT parent.rolname
            FROM pg_auth_members m
            JOIN pg_roles parent ON parent.oid=m.roleid
            JOIN pg_roles child ON child.oid=m.member
            WHERE child.rolname=%s ORDER BY parent.rolname
            """,
            (ACCOUNTING_USER,),
        ).fetchall()
        assert [row[0] for row in memberships] == ["accounting_app"]

    with psycopg.connect(
        _conninfo(ACCOUNTING_USER, ACCOUNTING_PASSWORD), autocommit=True
    ) as conn:
        conn.execute("SELECT COUNT(*) FROM accounting.patients").fetchone()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT COUNT(*) FROM clinical.patient_links").fetchone()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT password_hash FROM platform.users LIMIT 1").fetchone()
