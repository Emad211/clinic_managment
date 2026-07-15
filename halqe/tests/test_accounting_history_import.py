from __future__ import annotations

import os
import sqlite3

from django.core.management import call_command
import psycopg
import pytest

from accounting_ops.import_common import (
    ReplayConflictError,
    UnsupportedServiceTypeError,
    mapped_service_type,
)
from accounting_ops.import_engine import AccountingHistoryImporter
from tests.accounting_import_source import build_source


PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = os.environ.get("PG_PORT", "55432")
TEST_DB = os.environ.get("PG_TEST_DB", "halqe_app_test")
PG_SU_USER = os.environ.get("PG_USER", "postgres")
PG_SU_PASSWORD = os.environ.get("PG_PASSWORD", "validate_only")
ACCOUNTING_USER = os.environ.get("PG_ACCOUNTING_USER", "accounting_login_test")
ACCOUNTING_PASSWORD = os.environ.get("PG_ACCOUNTING_PASSWORD", "accounting_test_pw")
os.environ.setdefault("PG_ACCOUNTING_USER", ACCOUNTING_USER)
os.environ.setdefault("PG_ACCOUNTING_PASSWORD", ACCOUNTING_PASSWORD)


def _conninfo() -> str:
    return (
        f"host='{PG_HOST}' port='{PG_PORT}' user='{PG_SU_USER}' "
        f"password='{PG_SU_PASSWORD}' dbname='{TEST_DB}'"
    )


@pytest.fixture(scope="session")
def accounting_import_ready(django_db_setup):
    call_command(
        "ensure_accounting_role",
        login_role=ACCOUNTING_USER,
        login_password=ACCOUNTING_PASSWORD,
        verbosity=0,
    )
    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        for tenant_id in range(61, 66):
            conn.execute(
                """
                INSERT INTO platform.tenants(id,name,is_active)
                VALUES(%s,%s,TRUE) ON CONFLICT(id) DO NOTHING
                """,
                (tenant_id, f"Accounting import test {tenant_id}"),
            )
    return True


def _count(tenant_id: int, table: str) -> int:
    with psycopg.connect(_conninfo()) as conn:
        return int(
            conn.execute(
                f"SELECT COUNT(*) FROM accounting.{table} WHERE tenant_id=%s",
                (tenant_id,),
            ).fetchone()[0]
        )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_dry_run_reconciles_and_leaves_no_rows(tmp_path, accounting_import_ready):
    source = build_source(tmp_path / "dry-run.db")
    report = AccountingHistoryImporter(
        sqlite_path=source,
        source_id="accounting-dry-run",
        tenant_id=61,
        imported_by="test-suite",
        apply=False,
    ).run()
    assert report.transaction_status == "rolled_back"
    assert report.source_money == report.target_money
    assert report.ledger_rows_before == report.ledger_rows_after == 0
    assert report.table("patients").planned_insert == 1
    assert report.table("invoice_item_payments").planned_insert == 4
    assert _count(61, "patients") == 0
    assert _count(61, "invoices") == 0
    assert _count(61, "accounting_import_ledger") == 0


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_apply_then_replay_is_idempotent(tmp_path, accounting_import_ready):
    source = build_source(tmp_path / "apply.db")
    importer = AccountingHistoryImporter(
        sqlite_path=source,
        source_id="accounting-apply-replay",
        tenant_id=62,
        imported_by="test-suite",
        apply=True,
    )
    first = importer.run()
    assert first.transaction_status == "committed"
    assert first.source_money == first.target_money
    assert first.ledger_rows_before == 0
    assert first.ledger_rows_after == 10
    assert _count(62, "patients") == 1
    assert _count(62, "invoices") == 1
    assert _count(62, "invoice_item_payments") == 4

    with psycopg.connect(_conninfo()) as conn:
        invoice = conn.execute(
            """
            SELECT status,total_amount,pricing_version
            FROM accounting.invoices WHERE tenant_id=62
            """
        ).fetchone()
    assert invoice == ("closed", 230000, "legacy")

    second = importer.run()
    assert second.transaction_status == "committed"
    assert second.ledger_rows_before == second.ledger_rows_after == 10
    assert sum(stats.replayed for stats in second.tables.values()) == 10
    assert sum(stats.inserted for stats in second.tables.values()) == 0
    assert _count(62, "invoices") == 1


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_source_row_change_is_rejected_without_new_ledger(tmp_path, accounting_import_ready):
    source = build_source(tmp_path / "source-drift.db")
    importer = AccountingHistoryImporter(
        sqlite_path=source,
        source_id="accounting-source-drift",
        tenant_id=63,
        imported_by="test-suite",
        apply=True,
    )
    importer.run()
    with sqlite3.connect(source) as db:
        db.execute("UPDATE patients SET family_name='تغییر یافته' WHERE id=10")
        db.commit()
    with pytest.raises(ReplayConflictError, match="Source row changed"):
        importer.run()
    assert _count(63, "accounting_import_ledger") == 10
    assert _count(63, "patients") == 1


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_target_change_is_rejected_on_replay(tmp_path, accounting_import_ready):
    source = build_source(tmp_path / "target-drift.db")
    importer = AccountingHistoryImporter(
        sqlite_path=source,
        source_id="accounting-target-drift",
        tenant_id=64,
        imported_by="test-suite",
        apply=True,
    )
    importer.run()
    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        conn.execute(
            "UPDATE accounting.patients SET family_name='target drift' WHERE tenant_id=64"
        )
    with pytest.raises(ReplayConflictError, match="Target fingerprint changed"):
        importer.run()
    assert _count(64, "accounting_import_ledger") == 10


def test_legacy_service_types_require_explicit_mapping():
    with pytest.raises(UnsupportedServiceTypeError):
        mapped_service_type("custom", {})
    assert mapped_service_type("custom", {"custom": "procedure"}) == (
        "procedure",
        "custom",
    )
