from __future__ import annotations

from io import StringIO
import json
import os
import stat

from django.core.management import call_command
from django.core.management.base import CommandError
import psycopg
import pytest

from accounting_ops.dual_run_service import compare_accounting_dual_run
from accounting_ops.import_engine import AccountingHistoryImporter
from tests.accounting_dual_run_source import build_dual_run_source


PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = os.environ.get("PG_PORT", "55432")
TEST_DB = os.environ.get("PG_TEST_DB", "halqe_app_test")
PG_USER = os.environ.get("PG_USER", "postgres")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "validate_only")
ACCOUNTING_USER = os.environ.get("PG_ACCOUNTING_USER", "accounting_login_test")
ACCOUNTING_PASSWORD = os.environ.get("PG_ACCOUNTING_PASSWORD", "accounting_test_pw")
os.environ.setdefault("PG_ACCOUNTING_USER", ACCOUNTING_USER)
os.environ.setdefault("PG_ACCOUNTING_PASSWORD", ACCOUNTING_PASSWORD)


def _conninfo() -> str:
    return (
        f"host='{PG_HOST}' port='{PG_PORT}' user='{PG_USER}' "
        f"password='{PG_PASSWORD}' dbname='{TEST_DB}'"
    )


@pytest.fixture(scope="session")
def dual_run_database(django_db_setup):
    call_command(
        "ensure_accounting_role",
        login_role=ACCOUNTING_USER,
        login_password=ACCOUNTING_PASSWORD,
        verbosity=0,
    )
    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        for tenant_id in (67, 68, 69):
            conn.execute(
                "INSERT INTO platform.tenants(id,name,is_active) "
                "VALUES(%s,%s,TRUE) ON CONFLICT(id) DO NOTHING",
                (tenant_id, f"Dual run tenant {tenant_id}"),
            )
    return True


def _apply(source, *, tenant_id: int, source_id: str) -> None:
    AccountingHistoryImporter(
        sqlite_path=source,
        source_id=source_id,
        tenant_id=tenant_id,
        imported_by="dual-run-test",
        apply=True,
    ).run()


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_dual_run_matches_financial_and_payroll_exactly(tmp_path, dual_run_database):
    source = build_dual_run_source(tmp_path / "dual-go.db")
    source_id = "dual-run-go-source"
    _apply(source, tenant_id=67, source_id=source_id)

    report = compare_accounting_dual_run(
        sqlite_path=source,
        source_id=source_id,
        tenant_id=67,
        date_from="2099-01-01",
        date_to="2099-01-01",
    )
    assert report.decision == "GO", [item.path for item in report.differences]
    assert report.financial_source == report.financial_target
    assert report.payroll_source == report.payroll_target
    assert report.financial_source["totals"]["operating_revenue"] == 230000
    assert report.financial_source["totals"]["consumable_center_amount"] == 12000
    assert report.financial_source["by_shift"]["morning"]["invoice_count"] == 1
    assert report.payroll_source["summary"]["staff_count"] == 2


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_dual_run_detects_money_and_mapping_drift(tmp_path, dual_run_database):
    source = build_dual_run_source(tmp_path / "dual-drift.db")
    source_id = "dual-run-drift-source"
    _apply(source, tenant_id=68, source_id=source_id)
    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        conn.execute(
            "UPDATE accounting.invoices SET total_amount=230001 WHERE tenant_id=68"
        )

    drift = compare_accounting_dual_run(
        sqlite_path=source,
        source_id=source_id,
        tenant_id=68,
        date_from="2099-01-01",
        date_to="2099-01-01",
    )
    assert drift.decision == "NO_GO"
    assert any(
        item.path == "financial.totals.invoice_amount" and item.delta == 1
        for item in drift.differences
    )

    missing_map = compare_accounting_dual_run(
        sqlite_path=source,
        source_id="different-valid-source-id",
        tenant_id=68,
        date_from="2099-01-01",
        date_to="2099-01-01",
    )
    assert missing_map.decision == "NO_GO"
    assert any(item.path.startswith("payroll.rows") for item in missing_map.differences)


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_dual_run_command_writes_private_go_and_no_go_reports(
    tmp_path,
    dual_run_database,
):
    source = build_dual_run_source(tmp_path / "dual-command.db")
    source_id = "dual-run-command-source"
    _apply(source, tenant_id=69, source_id=source_id)
    report_path = tmp_path / "private" / "dual-run.json"
    stdout = StringIO()

    call_command(
        "compare_accounting_dual_run",
        sqlite=str(source),
        source_id=source_id,
        tenant_id=69,
        date_from="2099-01-01",
        date_to="2099-01-01",
        report=str(report_path),
        stdout=stdout,
    )
    assert stat.S_IMODE(report_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o600
    assert json.loads(report_path.read_text(encoding="utf-8"))["decision"] == "GO"
    assert "Accounting dual-run GO" in stdout.getvalue()

    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        conn.execute(
            "UPDATE accounting.invoice_item_payments SET is_paid=FALSE "
            "WHERE tenant_id=69 AND item_type='visit'"
        )
    with pytest.raises(CommandError, match="NO_GO"):
        call_command(
            "compare_accounting_dual_run",
            sqlite=str(source),
            source_id=source_id,
            tenant_id=69,
            date_from="2099-01-01",
            date_to="2099-01-01",
            report=str(report_path),
        )
    failed = json.loads(report_path.read_text(encoding="utf-8"))
    assert failed["decision"] == "NO_GO"
    assert any(
        item["path"] == "financial.totals.payment_paid_count"
        for item in failed["differences"]
    )
