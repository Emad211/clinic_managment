"""PostgreSQL integration tests for the accounting invoice workbench."""
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
def workbench_ready(django_db_setup):
    password = "invoice-workbench-secret"
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
            VALUES (1, 'بیمه کاربرگ فاکتور', 100000, 0, TRUE, TRUE, FALSE, FALSE)
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
            VALUES (1, 'workbench_reception', %s, 'reception', 'accounting',
                    'پذیرش کاربرگ', TRUE, 0)
            ON CONFLICT (tenant_id, username) DO UPDATE SET
                password_hash=EXCLUDED.password_hash,
                role='reception', app='accounting', full_name='پذیرش کاربرگ',
                is_active=TRUE, failed_attempts=0, locked_until=NULL
            """,
            (password_hash,),
        )
        user_id = conn.execute(
            "SELECT id FROM platform.users "
            "WHERE tenant_id=1 AND username='workbench_reception'"
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO accounting.user_active_shift
                (tenant_id, user_id, active_shift, work_date, shift_started_at)
            VALUES (1, %s, 'morning', '2026-07-15', now())
            ON CONFLICT (tenant_id, user_id) DO UPDATE SET
                active_shift='morning', work_date='2026-07-15',
                shift_started_at=now()
            """,
            (user_id,),
        )
        conn.execute(
            """
            INSERT INTO accounting.medical_staff
                (id, tenant_id, full_name, staff_type, is_active)
            VALUES
                (9401, 1, 'دکتر کاربرگ تست', 'doctor', TRUE),
                (9402, 1, 'پرستار کاربرگ تست', 'nurse', TRUE)
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
                (tenant_id, service_name, unit_price, is_active)
            VALUES (1, 'تزریق کاربرگ تست', 30000, TRUE)
            ON CONFLICT (tenant_id, service_name) DO UPDATE SET
                unit_price=EXCLUDED.unit_price, is_active=TRUE
            """
        )
        nursing_id = conn.execute(
            "SELECT id FROM accounting.nursing_services "
            "WHERE tenant_id=1 AND service_name='تزریق کاربرگ تست'"
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO accounting.procedure_tariffs
                (tenant_id, name, unit_price, is_active)
            VALUES (1, 'پروسیجر کاربرگ تست', 50000, TRUE)
            ON CONFLICT (tenant_id, name) DO UPDATE SET
                unit_price=EXCLUDED.unit_price, is_active=TRUE
            """
        )
        procedure_id = conn.execute(
            "SELECT id FROM accounting.procedure_tariffs "
            "WHERE tenant_id=1 AND name='پروسیجر کاربرگ تست'"
        ).fetchone()[0]

    return {
        "username": "workbench_reception",
        "password": password,
        "doctor_id": 9401,
        "nurse_id": 9402,
        "nursing_service_id": int(nursing_id),
        "procedure_tariff_id": int(procedure_id),
    }


def _open_invoice(token: str, national_id: str) -> dict:
    response = _client().post(
        "/accounting/invoices/visit",
        headers=_auth(token),
        json={
            "patient": {
                "name": "بیمار",
                "family_name": "کاربرگ",
                "national_id": national_id,
                "phone_number": "09128888888",
                "is_foreign": False,
            },
            "insurance_type": "بیمه کاربرگ فاکتور",
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


def _add_all_item_families(token: str, invoice_id: int, fixture: dict) -> None:
    nursing = _client().post(
        f"/accounting/invoices/{invoice_id}/nursing-items",
        headers=_auth(token),
        json={
            "services": [
                {"service_id": fixture["nursing_service_id"], "quantity": 1}
            ],
            "consumables": [
                {
                    "name": "گاز کاربرگ تست",
                    "category": "supply",
                    "quantity": 2,
                    "unit_price": 10000,
                    "patient_provided": False,
                    "is_exception": False,
                }
            ],
            "notes": "ثبت کاربرگ",
        },
    )
    assert nursing.status_code == 201, nursing.text
    procedure = _client().post(
        f"/accounting/invoices/{invoice_id}/procedure-items",
        headers=_auth(token),
        json={
            "procedures": [
                {
                    "tariff_id": fixture["procedure_tariff_id"],
                    "quantity": 1,
                    "performer_type": "doctor",
                }
            ]
        },
    )
    assert procedure.status_code == 201, procedure.text


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_detail_projects_every_item_family_and_frozen_liability(workbench_ready):
    token = _login(workbench_ready["username"], workbench_ready["password"])
    opened = _open_invoice(token, "0000004006")
    _set_staff(token, opened["id"], workbench_ready)
    _add_all_item_families(token, opened["id"], workbench_ready)

    response = _client().get(
        f"/accounting/invoices/{opened['id']}/detail",
        headers=_auth(token),
    )
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["invoice"]["pricing_version"] == "halqe_visit_procedure_v1"
    assert {row["item_type"] for row in detail["items"]} == {
        "visit",
        "injection",
        "procedure",
        "consumable",
    }
    by_type = {row["item_type"]: row for row in detail["items"]}
    assert by_type["visit"]["patient_amount"] == 100000
    assert by_type["injection"]["recorded_amount"] == 30000
    assert by_type["injection"]["patient_amount"] == 0
    assert by_type["injection"]["insurance_amount"] == 30000
    assert by_type["injection"]["covered_by_insurance"] is True
    assert by_type["procedure"]["patient_amount"] == 50000
    assert by_type["consumable"]["quantity"] == 2.0
    assert by_type["consumable"]["patient_amount"] == 20000
    assert all(row["is_paid"] is False for row in detail["items"])
    assert detail["financials"]["total_amount"] == 170000


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_add_visit_preserves_highest_pricing_version_and_adds_unpaid_item(
    workbench_ready,
):
    token = _login(workbench_ready["username"], workbench_ready["password"])
    opened = _open_invoice(token, "0000004014")
    _set_staff(token, opened["id"], workbench_ready)
    _add_all_item_families(token, opened["id"], workbench_ready)

    response = _client().post(
        f"/accounting/invoices/{opened['id']}/visits",
        headers=_auth(token),
        json={"notes": "ویزیت دوم"},
    )
    assert response.status_code == 201, response.text
    detail = response.json()
    assert detail["invoice"]["pricing_version"] == "halqe_visit_procedure_v1"
    visits = [row for row in detail["items"] if row["item_type"] == "visit"]
    assert len(visits) == 2
    assert any(row["notes"] == "ویزیت دوم" for row in visits)
    assert detail["financials"]["total_amount"] == 270000
    assert detail["financials"]["all_items_paid"] is False


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_delete_paid_item_removes_payment_and_recalculates_total(workbench_ready):
    token = _login(workbench_ready["username"], workbench_ready["password"])
    opened = _open_invoice(token, "0000004022")
    _set_staff(token, opened["id"], workbench_ready)
    _add_all_item_families(token, opened["id"], workbench_ready)

    settled = _client().post(
        f"/accounting/invoices/{opened['id']}/procedure/settle-all",
        headers=_auth(token),
        json={"payment_type": "card"},
    )
    assert settled.status_code == 200, settled.text
    detail = _client().get(
        f"/accounting/invoices/{opened['id']}/detail",
        headers=_auth(token),
    ).json()
    consumable = next(
        row for row in detail["items"] if row["item_type"] == "consumable"
    )

    deleted = _client().delete(
        f"/accounting/invoices/{opened['id']}/items/consumable/"
        f"{consumable['item_id']}",
        headers=_auth(token),
    )
    assert deleted.status_code == 200, deleted.text
    body = deleted.json()
    assert body["deleted"] is True
    assert body["detail"]["financials"]["total_amount"] == 150000
    assert body["detail"]["financials"]["paid_amount"] == 150000
    assert body["detail"]["financials"]["all_items_paid"] is True
    assert not any(
        row["item_type"] == "consumable" for row in body["detail"]["items"]
    )

    closed = _client().post(
        f"/accounting/invoices/{opened['id']}/procedure/close",
        headers=_auth(token),
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["total_amount"] == 150000

    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as conn:
        assert conn.execute(
            """
            SELECT COUNT(*) FROM accounting.invoice_item_payments
            WHERE tenant_id=1 AND invoice_id=%s
              AND item_type='consumable' AND item_id=%s
            """,
            (opened["id"], consumable["item_id"]),
        ).fetchone()[0] == 0
        actions = [
            row[0]
            for row in conn.execute(
                """
                SELECT action_type FROM accounting.activity_logs
                WHERE tenant_id=1 AND invoice_id=%s
                ORDER BY id
                """,
                (opened["id"],),
            ).fetchall()
        ]
        assert "consumable_delete" in actions


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_closed_invoice_and_wrong_item_are_fail_closed(workbench_ready):
    token = _login(workbench_ready["username"], workbench_ready["password"])
    opened = _open_invoice(token, "0000004030")
    visit_id = opened["visit_id"]

    missing = _client().delete(
        f"/accounting/invoices/{opened['id']}/items/visit/99999999",
        headers=_auth(token),
    )
    assert missing.status_code == 404

    settled = _client().post(
        f"/accounting/invoices/{opened['id']}/settle-all",
        headers=_auth(token),
        json={"payment_type": "cash"},
    )
    assert settled.status_code == 200, settled.text
    closed = _client().post(
        f"/accounting/invoices/{opened['id']}/close",
        headers=_auth(token),
    )
    assert closed.status_code == 200, closed.text

    blocked = _client().delete(
        f"/accounting/invoices/{opened['id']}/items/visit/{visit_id}",
        headers=_auth(token),
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "invoice_already_closed"

    readable = _client().get(
        f"/accounting/invoices/{opened['id']}/detail",
        headers=_auth(token),
    )
    assert readable.status_code == 200, readable.text
    assert readable.json()["invoice"]["status"] == "closed"
