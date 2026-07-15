from __future__ import annotations

from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
import stat

from django.core.management import call_command
from django.core.management.base import CommandError
import psycopg
import pytest

from accounting_ops.import_engine import AccountingHistoryImporter
from accounting_ops.import_verifier import AccountingImportVerifier
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
def accounting_verifier_ready(django_db_setup):
    call_command(
        "ensure_accounting_role",
        login_role=ACCOUNTING_USER,
        login_password=ACCOUNTING_PASSWORD,
        verbosity=0,
    )
    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        for tenant_id in range(71, 76):
            conn.execute(
                """
                INSERT INTO platform.tenants(id,name,is_active)
                VALUES(%s,%s,TRUE) ON CONFLICT(id) DO NOTHING
                """,
                (tenant_id, f"Accounting verifier test {tenant_id}"),
            )
    return True


def _apply(source: Path, *, source_id: str, tenant_id: int) -> None:
    result = AccountingHistoryImporter(
        sqlite_path=source,
        source_id=source_id,
        tenant_id=tenant_id,
        imported_by="verification-test-suite",
        apply=True,
    ).run()
    assert result.transaction_status == "committed"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_clean_import_is_independently_verified(tmp_path, accounting_verifier_ready):
    source = build_source(tmp_path / "verified.db")
    _apply(source, source_id="verify-clean", tenant_id=71)

    report = AccountingImportVerifier(
        sqlite_path=source,
        source_id="verify-clean",
        tenant_id=71,
    ).run()
    assert report.decision == "VERIFIED", report.errors
    assert report.source_rows == report.ledger_rows == report.target_rows == 10
    assert report.source_money == report.target_money
    assert {check.status for check in report.checks} == {"PASS"}


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_extra_invoice_child_fails_completeness(tmp_path, accounting_verifier_ready):
    source = build_source(tmp_path / "extra-child.db")
    _apply(source, source_id="verify-extra-child", tenant_id=72)

    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        patient_id, invoice_id = conn.execute(
            """
            SELECT p.id,i.id
            FROM accounting.patients p
            JOIN accounting.invoices i
              ON i.tenant_id=p.tenant_id AND i.patient_id=p.id
            WHERE p.tenant_id=72
            """
        ).fetchone()
        conn.execute(
            """
            INSERT INTO accounting.consumables_ledger(
                tenant_id,patient_id,item_name,category,quantity,unit_price,total_cost,
                patient_provided,is_exception,usage_date,invoice_id
            ) VALUES(72,%s,'extra unledgered item','supply',1,1,1,FALSE,FALSE,now(),%s)
            """,
            (patient_id, invoice_id),
        )

    report = AccountingImportVerifier(
        sqlite_path=source,
        source_id="verify-extra-child",
        tenant_id=72,
    ).run()
    assert report.decision == "FAILED"
    check = next(
        check for check in report.checks
        if check.code == "invoice_child_completeness"
    )
    assert check.status == "FAIL"
    assert check.evidence["mismatches"]["consumables_ledger"]["extra"] == 1


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_source_change_fails_digest_continuity(tmp_path, accounting_verifier_ready):
    source = build_source(tmp_path / "source-change.db")
    _apply(source, source_id="verify-source-change", tenant_id=73)
    with sqlite3.connect(source) as db:
        db.execute("UPDATE patients SET family_name='source changed' WHERE id=10")
        db.commit()

    report = AccountingImportVerifier(
        sqlite_path=source,
        source_id="verify-source-change",
        tenant_id=73,
    ).run()
    assert report.decision == "FAILED"
    check = next(
        check for check in report.checks
        if check.code == "source_digest_continuity"
    )
    assert check.status == "FAIL"
    assert check.evidence["mismatches"] == 1


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_target_change_fails_fingerprint_continuity(tmp_path, accounting_verifier_ready):
    source = build_source(tmp_path / "target-change.db")
    _apply(source, source_id="verify-target-change", tenant_id=74)
    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        conn.execute(
            "UPDATE accounting.patients SET family_name='target changed' WHERE tenant_id=74"
        )

    report = AccountingImportVerifier(
        sqlite_path=source,
        source_id="verify-target-change",
        tenant_id=74,
    ).run()
    assert report.decision == "FAILED"
    check = next(
        check for check in report.checks
        if check.code == "target_fingerprint_continuity"
    )
    assert check.status == "FAIL"
    assert check.evidence["mismatches"] == 1


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_verify_command_always_writes_private_artifact(tmp_path, accounting_verifier_ready):
    source = build_source(tmp_path / "command.db")
    _apply(source, source_id="verify-command", tenant_id=75)
    report_path = tmp_path / "private" / "verification.json"
    stdout = StringIO()

    call_command(
        "verify_legacy_accounting_import",
        sqlite=str(source),
        source_id="verify-command",
        tenant_id=75,
        report=str(report_path),
        stdout=stdout,
    )
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o600
    assert json.loads(report_path.read_text(encoding="utf-8"))["decision"] == "VERIFIED"
    assert "Accounting import VERIFIED" in stdout.getvalue()

    with sqlite3.connect(source) as db:
        db.execute("UPDATE patients SET family_name='command source drift' WHERE id=10")
        db.commit()
    with pytest.raises(CommandError, match="verification FAILED"):
        call_command(
            "verify_legacy_accounting_import",
            sqlite=str(source),
            source_id="verify-command",
            tenant_id=75,
            report=str(report_path),
        )
    failed = json.loads(report_path.read_text(encoding="utf-8"))
    assert failed["decision"] == "FAILED"
    assert "source_digest_continuity" in failed["errors"]
