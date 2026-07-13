"""PostgreSQL integration tests for the procedure migration slice."""
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


@pytest.fixture(scope="session")
def procedure_ready(django_db_setup):
    password = "procedure-reception-secret"
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
            INSERT INTO accounting.visit_tariffs
                (tenant_id, insurance_type, tariff_price, nursing_tariff,
                 nursing_covers, is_active, is_supplementary, is_base_tariff)
            VALUES
                (1, 'بیمه پروسیجر پوشش‌دار', 85000, 0, TRUE, TRUE, FALSE, FALSE),
                (1, 'بیمه پروسیجر بدون پوشش', 90000, 1000, FALSE, TRUE, FALSE, FALSE)
            ON CONFLICT (tenant_id, insurance_type) DO UPDATE SET
                tariff_price=EXCLUDED.tariff_price,
                nursing_tariff=EXCLUDED.nursing_tariff,
                nursing_covers=EXCLUDED.nursing_covers,
                is_active=TRUE,
                is_supplementary=FALSE
            """
        )
        conn.execute(
            """
            INSERT INTO platform.users
                (tenant_id, username, password_hash, role, app, full_name,
                 is_active, failed_attempts)
            VALUES (1, 'procedure_reception', %s, 'reception', 'accounting',
                    'پذیرش پروسیجر', TRUE, 0)
            ON CONFLICT (tenant_id, username) DO UPDATE SET
                password_hash=EXCLUDED.password_hash,
                role='reception', app='accounting', full_name='پذیرش پروسیجر',
                is_active=TRUE, failed_attempts=0, locked_until=NULL
            """,
            (password_hash,),
        )
        user_id = conn.execute(
            "SELECT id FROM platform.users "
            "WHERE tenant_id=1 AND username='procedure_reception'"
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO accounting.user_active_shift
                (tenant_id, user_id, active_shift, work_date, shift_started_at)
            VALUES (1, %s, 'morning', '2026-07-14', now())
            ON CONFLICT (tenant_id, user_id) DO UPDATE SET
                active_shift='morning', work_date='2026-07-14',
                shift_started_at=now()
            """,
            (user_id,),
        )
        conn.execute(
            """
            INSERT INTO accounting.medical_staff
                (id, tenant_id, full_name, staff_type, is_active)
            VALUES
                (9301, 1, 'دکتر پروسیجر تست', 'doctor', TRUE),
                (9302, 1, 'پرستار پروسیجر تست', 'nurse', TRUE)
            ON CONFLICT (id) DO UPDATE SET
                tenant_id=EXCLUDED.tenant_id,
                full_name=EXCLUDED.full_name,
                staff_type=EXCLUDED.staff_type,
                is_active=TRUE
            """
        )
        conn.execute(
            """
            INSERT INTO accounting.procedure_tariffs
                (tenant_id, name, unit_price, is_active)
            VALUES
                (1, 'پانسمان پروسیجر تست', 45000, TRUE),
                (1, 'بخیه پروسیجر تست', 150000, TRUE)
            ON CONFLICT (tenant_id, name) DO UPDATE SET
                unit_price=EXCLUDED.unit_price, is_active=TRUE
            """
        )
        tariff_rows = conn.execute(
            """
            SELECT name, id FROM accounting.procedure_tariffs
            WHERE tenant_id=1 AND name IN
                ('پانسمان پروسیجر تست', 'بخیه پروسیجر تست')
            """
        ).fetchall()
        tariff_ids = {name: int(tid) for name, tid in tariff_rows}

    return {
        "username": "procedure_reception",
        "password": password,
        "doctor_id": 9301,
        "nurse_id": 9302,
        "dressing_tariff_id": tariff_ids["پانسمان پروسیجر تست"],
        "suture_tariff_id": tariff_ids["بخیه پروسیجر تست"],
    }


def _open_invoice(token: str, *, national_id: str, insurance_type: str) -> dict:
    response = _client().post(
        "/accounting/invoices/visit",
        headers=_auth(token),
        json={
            "patient": {
                "name": "بیمار",
                "family_name": "پروسیجر",
                "national_id": national_id,
                "phone_number": "09127777777",
                "is_foreign": False,
            },
            "insurance_type": insurance_type,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _set_staff(token: str, invoice_id: int, fixture: dict) -> None:
    response = _client().put(
        f"/accounting/invoices/{invoice_id}/shift-staff",
        headers=_auth(token),
        json={
            "doctor_id": fixture["doctor_id"],
            "nurse_id": fixture["nurse_id"],
        },
    )
    assert response.status_code == 200, response.text


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_procedure_catalogue_is_available(procedure_ready):
    token = _login(procedure_ready["username"], procedure_ready["password"])
    response = _client().get(
        "/accounting/procedures/tariffs",
        headers=_auth(token),
    )
    assert response.status_code == 200, response.text
    by_name = {row["name"]: row for row in response.json()}
    assert by_name["پانسمان پروسیجر تست"]["unit_price"] == 45000
    assert by_name["بخیه پروسیجر تست"]["unit_price"] == 150000


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_nurse_covered_and_doctor_full_liability_are_snapshotted(procedure_ready):
    token = _login(procedure_ready["username"], procedure_ready["password"])
    client = _client()
    opened = _open_invoice(
        token,
        national_id="0000100005",
        insurance_type="بیمه پروسیجر پوشش‌دار",
    )
    _set_staff(token, opened["id"], procedure_ready)

    response = client.post(
        f"/accounting/invoices/{opened['id']}/procedure-items",
        headers=_auth(token),
        json={
            "procedures": [
                {
                    "tariff_id": procedure_ready["dressing_tariff_id"],
                    "quantity": 1,
                    "performer_type": "nurse",
                },
                {
                    "tariff_id": procedure_ready["suture_tariff_id"],
                    "quantity": 1,
                    "performer_type": "doctor",
                },
            ],
            "notes": "پروسیجر تست",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["pricing_version"] == "halqe_visit_procedure_v1"
    assert len(body["procedure_ids"]) == 2
    # visit 85k + nurse procedure 0 + doctor procedure 150k
    assert body["financials"]["total_amount"] == 235000
    assert body["financials"]["remaining_amount"] == 235000

    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as conn:
        rows = conn.execute(
            """
            SELECT procedure_type, price, patient_amount, insurance_amount,
                   covered_by_insurance, performer_type, performer_id,
                   doctor_id, nurse_id
            FROM accounting.procedures
            WHERE tenant_id=1 AND invoice_id=%s
            ORDER BY procedure_type
            """,
            (opened["id"],),
        ).fetchall()
        by_name = {row[0]: row for row in rows}
        dressing = by_name["پانسمان پروسیجر تست"]
        assert tuple(map(int, dressing[1:4])) == (45000, 0, 45000)
        assert dressing[4] is True
        assert dressing[5] == "nurse"
        assert (dressing[6], dressing[7], dressing[8]) == (
            procedure_ready["nurse_id"],
            None,
            procedure_ready["nurse_id"],
        )
        suture = by_name["بخیه پروسیجر تست"]
        assert tuple(map(int, suture[1:4])) == (150000, 150000, 0)
        assert suture[4] is False
        assert suture[5] == "doctor"
        assert (suture[6], suture[7], suture[8]) == (
            procedure_ready["doctor_id"],
            procedure_ready["doctor_id"],
            None,
        )
        invoice = conn.execute(
            "SELECT total_amount, pricing_version FROM accounting.invoices "
            "WHERE tenant_id=1 AND id=%s",
            (opened["id"],),
        ).fetchone()
        assert (int(invoice[0]), invoice[1]) == (
            235000,
            "halqe_visit_procedure_v1",
        )

    blocked = client.post(
        f"/accounting/invoices/{opened['id']}/procedure/close",
        headers=_auth(token),
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "invoice_unpaid_items"

    settled = client.post(
        f"/accounting/invoices/{opened['id']}/procedure/settle-all",
        headers=_auth(token),
        json={"payment_type": "card"},
    )
    assert settled.status_code == 200, settled.text
    assert settled.json()["paid_amount"] == 235000
    assert settled.json()["all_items_paid"] is True

    closed = client.post(
        f"/accounting/invoices/{opened['id']}/procedure/close",
        headers=_auth(token),
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"
    assert closed.json()["total_amount"] == 235000


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_nurse_without_coverage_pays_full_price(procedure_ready):
    token = _login(procedure_ready["username"], procedure_ready["password"])
    opened = _open_invoice(
        token,
        national_id="0000100013",
        insurance_type="بیمه پروسیجر بدون پوشش",
    )
    _set_staff(token, opened["id"], procedure_ready)
    response = _client().post(
        f"/accounting/invoices/{opened['id']}/procedure-items",
        headers=_auth(token),
        json={
            "procedures": [
                {
                    "tariff_id": procedure_ready["dressing_tariff_id"],
                    "quantity": 1,
                    "performer_type": "nurse",
                }
            ]
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["financials"]["total_amount"] == 135000

    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as conn:
        row = conn.execute(
            """
            SELECT price, patient_amount, insurance_amount, covered_by_insurance
            FROM accounting.procedures
            WHERE tenant_id=1 AND invoice_id=%s
            """,
            (opened["id"],),
        ).fetchone()
        assert tuple(map(int, row[:3])) == (45000, 45000, 0)
        assert row[3] is False


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_manual_procedure_price_and_atomic_rollback(procedure_ready):
    token = _login(procedure_ready["username"], procedure_ready["password"])
    opened = _open_invoice(
        token,
        national_id="0000100021",
        insurance_type="بیمه پروسیجر پوشش‌دار",
    )
    _set_staff(token, opened["id"], procedure_ready)

    response = _client().post(
        f"/accounting/invoices/{opened['id']}/procedure-items",
        headers=_auth(token),
        json={
            "procedures": [
                {
                    "name": "پروسیجر دستی معتبر",
                    "unit_price": 70000,
                    "quantity": 1,
                    "performer_type": "doctor",
                },
                {
                    "name": "پروسیجر نامعتبر",
                    "unit_price": 10000,
                    "quantity": 101,
                    "performer_type": "nurse",
                },
            ]
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_procedure_quantity"

    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM accounting.procedures "
            "WHERE tenant_id=1 AND invoice_id=%s",
            (opened["id"],),
        ).fetchone()[0] == 0
        invoice = conn.execute(
            "SELECT total_amount, pricing_version FROM accounting.invoices "
            "WHERE tenant_id=1 AND id=%s",
            (opened["id"],),
        ).fetchone()
        assert (int(invoice[0]), invoice[1]) == (85000, "halqe_visit_v1")


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_missing_selected_performer_is_rejected(procedure_ready):
    token = _login(procedure_ready["username"], procedure_ready["password"])
    opened = _open_invoice(
        token,
        national_id="0000100031",
        insurance_type="بیمه پروسیجر پوشش‌دار",
    )
    response = _client().put(
        f"/accounting/invoices/{opened['id']}/shift-staff",
        headers=_auth(token),
        json={"doctor_id": procedure_ready["doctor_id"], "nurse_id": None},
    )
    assert response.status_code == 200, response.text

    response = _client().post(
        f"/accounting/invoices/{opened['id']}/procedure-items",
        headers=_auth(token),
        json={
            "procedures": [
                {
                    "tariff_id": procedure_ready["dressing_tariff_id"],
                    "quantity": 1,
                    "performer_type": "nurse",
                }
            ]
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "nurse_shift_staff_required"
