"""PostgreSQL integration tests for the nursing/consumable migration slice.

These tests pin the production Flask accounting semantics before the old app is
retired: shift-level staff, explicit nursing coverage, per-service exclusions,
consumables as patient liability, atomic rollback and paid-only close.
"""
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
def nursing_ready(django_db_setup):
    """Create the writer role and deterministic nursing catalogue fixtures."""
    password = "nursing-reception-secret"
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
                (1, 'آزاد', 200000, 0, FALSE, TRUE, FALSE, TRUE),
                (1, 'بیمه پرستاری', 85000, 0, TRUE, TRUE, FALSE, FALSE),
                (1, 'بیمه لگسی پرستاری', 90000, 0, FALSE, TRUE, FALSE, FALSE)
            ON CONFLICT (tenant_id, insurance_type) DO UPDATE SET
                tariff_price=EXCLUDED.tariff_price,
                nursing_tariff=EXCLUDED.nursing_tariff,
                nursing_covers=EXCLUDED.nursing_covers,
                is_active=TRUE,
                is_supplementary=FALSE,
                is_base_tariff=EXCLUDED.is_base_tariff
            """
        )
        conn.execute(
            """
            INSERT INTO platform.users
                (tenant_id, username, password_hash, role, app, full_name,
                 is_active, failed_attempts)
            VALUES (1, 'nursing_reception', %s, 'reception', 'accounting',
                    'پذیرش پرستاری', TRUE, 0)
            ON CONFLICT (tenant_id, username) DO UPDATE SET
                password_hash=EXCLUDED.password_hash,
                role='reception', app='accounting', full_name='پذیرش پرستاری',
                is_active=TRUE, failed_attempts=0, locked_until=NULL
            """,
            (password_hash,),
        )
        user_id = conn.execute(
            "SELECT id FROM platform.users "
            "WHERE tenant_id=1 AND username='nursing_reception'"
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO accounting.user_active_shift
                (tenant_id, user_id, active_shift, work_date, shift_started_at)
            VALUES (1, %s, 'evening', '2026-07-13', now())
            ON CONFLICT (tenant_id, user_id) DO UPDATE SET
                active_shift='evening', work_date='2026-07-13',
                shift_started_at=now()
            """,
            (user_id,),
        )

        conn.execute(
            """
            INSERT INTO accounting.medical_staff
                (id, tenant_id, full_name, staff_type, is_active)
            VALUES
                (9101, 1, 'دکتر شیفت تست', 'doctor', TRUE),
                (9102, 1, 'پرستار شیفت تست', 'nurse', TRUE)
            ON CONFLICT (id) DO UPDATE SET
                tenant_id=EXCLUDED.tenant_id,
                full_name=EXCLUDED.full_name,
                staff_type=EXCLUDED.staff_type,
                is_active=TRUE
            """
        )
        conn.execute(
            """
            INSERT INTO accounting.nursing_services
                (id, tenant_id, service_name, unit_price, is_active)
            VALUES
                (9201, 1, 'تزریق معمولی تست', 30000, TRUE),
                (9202, 1, 'واکسن مستثنا تست', 120000, TRUE)
            ON CONFLICT (tenant_id, service_name) DO UPDATE SET
                unit_price=EXCLUDED.unit_price,
                is_active=TRUE
            """
        )
        service_rows = conn.execute(
            """
            SELECT service_name, id FROM accounting.nursing_services
            WHERE tenant_id=1 AND service_name IN
                ('تزریق معمولی تست', 'واکسن مستثنا تست')
            """
        ).fetchall()
        service_ids = {name: int(service_id) for name, service_id in service_rows}

        conn.execute(
            """
            DELETE FROM accounting.insurance_nursing_exclusions
            WHERE tenant_id=1 AND insurance_type='بیمه پرستاری'
              AND nursing_service_id=%s
            """,
            (service_ids["واکسن مستثنا تست"],),
        )
        conn.execute(
            """
            INSERT INTO accounting.insurance_nursing_exclusions
                (tenant_id, insurance_type, nursing_service_id, note)
            VALUES (1, 'بیمه پرستاری', %s, 'characterization exclusion')
            """,
            (service_ids["واکسن مستثنا تست"],),
        )
        conn.execute(
            """
            INSERT INTO accounting.consumable_tariffs
                (tenant_id, name, default_price, category, is_active)
            VALUES (1, 'گاز استریل تست', 25000, 'supply', TRUE)
            ON CONFLICT (tenant_id, name) DO UPDATE SET
                default_price=EXCLUDED.default_price,
                category='supply', is_active=TRUE
            """
        )

    return {
        "username": "nursing_reception",
        "password": password,
        "doctor_id": 9101,
        "nurse_id": 9102,
        "covered_service_id": service_ids["تزریق معمولی تست"],
        "excluded_service_id": service_ids["واکسن مستثنا تست"],
    }


def _open_invoice(
    token: str,
    *,
    national_id: str,
    insurance_type: str = "بیمه پرستاری",
) -> dict:
    response = _client().post(
        "/accounting/invoices/visit",
        headers=_auth(token),
        json={
            "patient": {
                "name": "بیمار",
                "family_name": "پرستاری",
                "national_id": national_id,
                "phone_number": "09128888888",
                "is_foreign": False,
            },
            "insurance_type": insurance_type,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _set_staff(token: str, invoice_id: int, fixture: dict) -> dict:
    response = _client().put(
        f"/accounting/invoices/{invoice_id}/shift-staff",
        headers=_auth(token),
        json={
            "doctor_id": fixture["doctor_id"],
            "nurse_id": fixture["nurse_id"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_nursing_catalogues_and_staff_are_accounting_scoped(nursing_ready):
    token = _login(nursing_ready["username"], nursing_ready["password"])
    client = _client()

    services = client.get("/accounting/nursing/services", headers=_auth(token))
    assert services.status_code == 200, services.text
    by_name = {row["service_name"]: row for row in services.json()}
    assert by_name["تزریق معمولی تست"]["unit_price"] == 30000

    consumables = client.get(
        "/accounting/consumables/tariffs?category=supply",
        headers=_auth(token),
    )
    assert consumables.status_code == 200, consumables.text
    assert any(row["name"] == "گاز استریل تست" for row in consumables.json())

    staff = client.get("/accounting/staff", headers=_auth(token))
    assert staff.status_code == 200, staff.text
    ids = {row["id"] for row in staff.json()}
    assert nursing_ready["doctor_id"] in ids
    assert nursing_ready["nurse_id"] in ids


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_shift_staff_is_required_before_nursing_write(nursing_ready):
    token = _login(nursing_ready["username"], nursing_ready["password"])
    opened = _open_invoice(token, national_id="0001000012")

    response = _client().post(
        f"/accounting/invoices/{opened['id']}/nursing-items",
        headers=_auth(token),
        json={
            "services": [
                {
                    "service_id": nursing_ready["covered_service_id"],
                    "quantity": 1,
                }
            ],
            "consumables": [],
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "shift_staff_required"

    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM accounting.injections "
            "WHERE tenant_id=1 AND invoice_id=%s",
            (opened["id"],),
        ).fetchone()[0] == 0


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_covered_excluded_and_consumable_liability_matches_oracle(nursing_ready):
    token = _login(nursing_ready["username"], nursing_ready["password"])
    client = _client()
    opened = _open_invoice(token, national_id="0001000020")
    staff = _set_staff(token, opened["id"], nursing_ready)
    assert staff["shift"] == "evening"
    assert staff["work_date"] == "2026-07-13"
    assert staff["doctor_name"] == "دکتر شیفت تست"
    assert staff["nurse_name"] == "پرستار شیفت تست"

    response = client.post(
        f"/accounting/invoices/{opened['id']}/nursing-items",
        headers=_auth(token),
        json={
            "services": [
                {
                    "service_id": nursing_ready["covered_service_id"],
                    "quantity": 1,
                },
                {
                    "service_id": nursing_ready["excluded_service_id"],
                    "quantity": 1,
                },
            ],
            "consumables": [
                {
                    "name": "گاز استریل تست",
                    "category": "supply",
                    "quantity": 2,
                    "unit_price": 25000,
                    "patient_provided": False,
                    "is_exception": False,
                }
            ],
            "notes": "ثبت پرستاری تست",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["pricing_version"] == "halqe_visit_nursing_v1"
    assert len(body["injection_ids"]) == 2
    assert len(body["consumable_ids"]) == 1
    # visit 85k + covered service 0 + excluded service 120k + consumable 50k
    assert body["financials"]["total_amount"] == 255000
    assert body["financials"]["paid_amount"] == 0
    assert body["financials"]["remaining_amount"] == 255000

    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as conn:
        injections = conn.execute(
            """
            SELECT service_id, total_price, patient_amount, insurance_amount,
                   covered_by_insurance, doctor_id, nurse_id
            FROM accounting.injections
            WHERE tenant_id=1 AND invoice_id=%s
            ORDER BY service_id
            """,
            (opened["id"],),
        ).fetchall()
        by_service = {int(row[0]): row for row in injections}
        covered = by_service[nursing_ready["covered_service_id"]]
        assert tuple(map(int, covered[1:4])) == (30000, 0, 30000)
        assert covered[4] is True
        assert (covered[5], covered[6]) == (
            nursing_ready["doctor_id"], nursing_ready["nurse_id"]
        )
        excluded = by_service[nursing_ready["excluded_service_id"]]
        assert tuple(map(int, excluded[1:4])) == (120000, 120000, 0)
        assert excluded[4] is False

        consumable = conn.execute(
            """
            SELECT quantity, unit_price, total_cost, patient_provided
            FROM accounting.consumables_ledger
            WHERE tenant_id=1 AND invoice_id=%s
            """,
            (opened["id"],),
        ).fetchone()
        assert float(consumable[0]) == 2.0
        assert (int(consumable[1]), int(consumable[2])) == (25000, 50000)
        assert consumable[3] is False

        invoice = conn.execute(
            "SELECT total_amount, pricing_version FROM accounting.invoices "
            "WHERE tenant_id=1 AND id=%s",
            (opened["id"],),
        ).fetchone()
        assert (int(invoice[0]), invoice[1]) == (255000, "halqe_visit_nursing_v1")

    blocked = client.post(
        f"/accounting/invoices/{opened['id']}/nursing/close",
        headers=_auth(token),
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "invoice_unpaid_items"

    settled = client.post(
        f"/accounting/invoices/{opened['id']}/nursing/settle-all",
        headers=_auth(token),
        json={"payment_type": "card"},
    )
    assert settled.status_code == 200, settled.text
    assert settled.json()["paid_amount"] == 255000
    assert settled.json()["all_items_paid"] is True

    closed = client.post(
        f"/accounting/invoices/{opened['id']}/nursing/close",
        headers=_auth(token),
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"
    assert closed.json()["total_amount"] == 255000


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_false_nursing_covers_with_zero_tariff_preserves_pinned_legacy_behavior(
    nursing_ready,
):
    token = _login(nursing_ready["username"], nursing_ready["password"])
    opened = _open_invoice(
        token,
        national_id="0001000039",
        insurance_type="بیمه لگسی پرستاری",
    )
    _set_staff(token, opened["id"], nursing_ready)

    response = _client().post(
        f"/accounting/invoices/{opened['id']}/nursing-items",
        headers=_auth(token),
        json={
            "services": [
                {
                    "service_id": nursing_ready["covered_service_id"],
                    "quantity": 1,
                }
            ],
            "consumables": [],
        },
    )
    assert response.status_code == 201, response.text

    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as conn:
        row = conn.execute(
            """
            SELECT total_price, patient_amount, insurance_amount,
                   covered_by_insurance
            FROM accounting.injections
            WHERE tenant_id=1 AND invoice_id=%s
            """,
            (opened["id"],),
        ).fetchone()
        assert tuple(map(int, row[:3])) == (30000, 30000, 0)
        assert row[3] is False


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_invalid_late_item_rolls_back_entire_nursing_batch(nursing_ready):
    token = _login(nursing_ready["username"], nursing_ready["password"])
    opened = _open_invoice(token, national_id="0001000047")
    _set_staff(token, opened["id"], nursing_ready)

    response = _client().post(
        f"/accounting/invoices/{opened['id']}/nursing-items",
        headers=_auth(token),
        json={
            "services": [
                {
                    "service_id": nursing_ready["covered_service_id"],
                    "quantity": 1,
                },
                {
                    "service_id": nursing_ready["excluded_service_id"],
                    "quantity": 101,
                },
            ],
            "consumables": [],
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_nursing_quantity"

    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM accounting.injections "
            "WHERE tenant_id=1 AND invoice_id=%s",
            (opened["id"],),
        ).fetchone()[0] == 0
        invoice = conn.execute(
            "SELECT total_amount, pricing_version FROM accounting.invoices "
            "WHERE tenant_id=1 AND id=%s",
            (opened["id"],),
        ).fetchone()
        assert (int(invoice[0]), invoice[1]) == (85000, "halqe_visit_v1")
