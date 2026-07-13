"""First accounting migration slice: reception -> visit invoice -> close.

The tests exercise the real PostgreSQL permission boundary:

* Django's normal ``platform_app`` login remains read-only on accounting.
* Accounting commands use a separate LOGIN role inheriting ``accounting_app``.
* That accounting role cannot read ``clinical.*`` or ``platform.users``.
* Patient upsert + invoice + visit + audit is one atomic transaction.
* Closing is idempotent and refuses unsupported item families until their exact
  production pricing rules are ported.
"""
from __future__ import annotations

import os

import bcrypt
import psycopg
import pytest
from ninja.testing import TestClient
from django.core.management import call_command
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

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

# accounting_ops.write_port resolves these lazily when an endpoint is called.
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
    """Create the dedicated test login and seed neutral tariffs + receptionist."""
    password = "reception-secret"
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

    # Exercise the real bootstrap command rather than reproducing its SQL here.
    call_command(
        "ensure_accounting_role",
        login_role=ACCOUNTING_USER,
        login_password=ACCOUNTING_PASSWORD,
        verbosity=0,
    )

    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as conn:
        # Tenant 2 exists only to prove that all service queries scope by tenant.
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

    return {"username": "reception_test", "password": password}


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
def test_visit_invoice_open_list_close_is_atomic_and_audited(accounting_ready):
    token = _login(accounting_ready["username"], accounting_ready["password"])
    client = _client()

    response = client.post(
        "/accounting/invoices/visit",
        headers=_auth(token),
        json={
            "patient": {
                "name": "مریم",
                "family_name": "حسابی",
                "national_id": "2170415981",
                "phone_number": "09121111111",
                "is_foreign": False,
            },
            "insurance_type": "تامین اجتماعی",
            "notes": "ویزیت مهاجرت حسابداری",
        },
    )
    assert response.status_code == 201, response.text
    opened = response.json()
    assert opened["status"] == "open"
    assert opened["pricing_version"] == "halqe_visit_v1"
    assert opened["patient_full_name"] == "مریم حسابی"
    assert opened["total_amount"] == 85000
    assert opened["visit_price"] == 85000
    invoice_id = opened["id"]

    listing = client.get(
        "/accounting/invoices/open?limit=100&offset=0",
        headers=_auth(token),
    )
    assert listing.status_code == 200, listing.text
    assert any(row["id"] == invoice_id for row in listing.json()["items"])

    # Explicit tenant filtering: tenant 2 cannot see tenant 1's open invoice.
    assert list_open_invoices(tenant_id=2)["items"] == []

    closed_response = client.post(
        f"/accounting/invoices/{invoice_id}/close",
        headers=_auth(token),
    )
    assert closed_response.status_code == 200, closed_response.text
    closed = closed_response.json()
    assert closed["status"] == "closed"
    assert closed["total_amount"] == 85000
    assert closed["closed_by"] == accounting_ready["username"]

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
            """
            SELECT price, notes FROM accounting.visits
            WHERE tenant_id=1 AND invoice_id=%s
            """,
            (invoice_id,),
        ).fetchone()
        assert int(visit[0]) == 85000
        assert visit[1] == "ویزیت مهاجرت حسابداری"

        actions = conn.execute(
            """
            SELECT action_type FROM accounting.activity_logs
            WHERE tenant_id=1 AND invoice_id=%s
            ORDER BY id
            """,
            (invoice_id,),
        ).fetchall()
        assert [row[0] for row in actions] == [
            "invoice_create",
            "invoice_close",
        ]


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_supplementary_tariff_overrides_primary_and_patient_is_upserted(
    accounting_ready,
):
    token = _login(accounting_ready["username"], accounting_ready["password"])
    client = _client()
    national_id = "0001001000"

    first = client.post(
        "/accounting/invoices/visit",
        headers=_auth(token),
        json={
            "patient": {
                "name": "سارا",
                "family_name": "تطبیق",
                "national_id": national_id,
                "phone_number": "09125555555",
                "is_foreign": False,
            },
            "insurance_type": "تامین اجتماعی",
        },
    )
    assert first.status_code == 201, first.text
    assert first.json()["total_amount"] == 85000

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
    assert search.status_code == 200, search.text
    assert len(search.json()) == 1
    assert search.json()[0]["phone_number"] == "09126666666"

    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM accounting.patients "
            "WHERE tenant_id=1 AND national_id=%s",
            (national_id,),
        ).fetchone()[0]
        assert count == 1


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
                "national_id": "2110530979",
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
            """
            SELECT COUNT(*) FROM accounting.patients
            WHERE tenant_id=1 AND national_id='2110530979'
            """
        ).fetchone()[0] == 0
        assert conn.execute(
            """
            SELECT COUNT(*) FROM accounting.invoices i
            JOIN accounting.patients p
              ON p.tenant_id=i.tenant_id AND p.id=i.patient_id
            WHERE i.tenant_id=1 AND p.national_id='2110530979'
            """
        ).fetchone()[0] == 0


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_close_refuses_unported_item_families_without_mutation(accounting_ready):
    token = _login(accounting_ready["username"], accounting_ready["password"])
    client = _client()
    opened_response = client.post(
        "/accounting/invoices/visit",
        headers=_auth(token),
        json={
            "patient": {
                "name": "زهرا",
                "family_name": "محافظت مالی",
                "national_id": "0440253519",
                "phone_number": "09123333333",
                "is_foreign": False,
            },
            "insurance_type": "آزاد",
        },
    )
    assert opened_response.status_code == 201, opened_response.text
    opened = opened_response.json()

    # Simulate an invoice containing a family whose patient-share rules have not
    # yet been ported to the new close command.
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

    close_response = client.post(
        f"/accounting/invoices/{opened['id']}/close",
        headers=_auth(token),
    )
    assert close_response.status_code == 409
    assert close_response.json()["code"] == "unsupported_invoice_items"

    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as conn:
        row = conn.execute(
            """
            SELECT status, closed_at, total_amount
            FROM accounting.invoices WHERE tenant_id=1 AND id=%s
            """,
            (opened["id"],),
        ).fetchone()
        assert row[0] == "open"
        assert row[1] is None
        assert int(row[2]) == 200000


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_close_refuses_legacy_pricing_invoice(accounting_ready):
    token = _login(accounting_ready["username"], accounting_ready["password"])
    client = _client()
    opened_response = client.post(
        "/accounting/invoices/visit",
        headers=_auth(token),
        json={
            "patient": {
                "name": "رضا",
                "family_name": "قدیمی",
                "national_id": "0001000004",
                "phone_number": "09124444444",
                "is_foreign": False,
            },
            "insurance_type": "آزاد",
        },
    )
    assert opened_response.status_code == 201, opened_response.text
    invoice_id = opened_response.json()["id"]

    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as conn:
        conn.execute(
            "UPDATE accounting.invoices SET pricing_version='legacy' "
            "WHERE tenant_id=1 AND id=%s",
            (invoice_id,),
        )

    response = client.post(
        f"/accounting/invoices/{invoice_id}/close",
        headers=_auth(token),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "legacy_invoice_close_blocked"

    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as conn:
        row = conn.execute(
            "SELECT status, closed_at FROM accounting.invoices "
            "WHERE tenant_id=1 AND id=%s",
            (invoice_id,),
        ).fetchone()
        assert row == ("open", None)


def test_accounting_login_is_confined_to_accounting(accounting_ready):
    with psycopg.connect(
        _conninfo(ACCOUNTING_USER, ACCOUNTING_PASSWORD), autocommit=True
    ) as conn:
        conn.execute("SELECT COUNT(*) FROM accounting.patients").fetchone()

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT COUNT(*) FROM clinical.patient_links").fetchone()

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT password_hash FROM platform.users LIMIT 1").fetchone()
