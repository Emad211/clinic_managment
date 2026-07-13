"""Durability-state tests for specialist record reconciliation reports."""
from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from clinical.specialist_record_import import (
    SpecialistRecordImporter,
    UnresolvedPatientError,
)


def _source(
    path: Path,
    *,
    accounting_patient_id: int,
    national_id: str | None = None,
) -> Path:
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE patient_links (
            id INTEGER PRIMARY KEY,
            accounting_patient_id INTEGER,
            national_id TEXT,
            full_name TEXT,
            wallet_balance INTEGER DEFAULT 0,
            sms_opt_out INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        );
        """
    )
    db.execute(
        """
        INSERT INTO patient_links
            (id, accounting_patient_id, national_id, full_name,
             wallet_balance, sms_opt_out, is_active)
        VALUES (1, ?, ?, 'بیمار وضعیت تراکنش', 0, 0, 1)
        """,
        [accounting_patient_id, national_id],
    )
    db.commit()
    db.close()
    return path


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_dry_run_report_explicitly_states_no_commit(seed_data, tmp_path):
    source = _source(
        tmp_path / "status-dry.db",
        accounting_patient_id=seed_data["patient_id"],
    )
    report = SpecialistRecordImporter(
        sqlite_path=source,
        source_id="transaction-status-dry",
        tenant_id=1,
        apply=False,
    ).run()

    payload = report.to_dict()
    assert payload["transaction_status"] == "validated_no_commit"
    assert payload["ledger_rows_after"] == 0
    assert payload["tables"]["patient_links"]["planned_reuse"] == 1


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_apply_report_explicitly_states_commit_and_durable_ledger_count(
    seed_data,
    tmp_path,
):
    source = _source(
        tmp_path / "status-apply.db",
        accounting_patient_id=seed_data["patient_id"],
    )
    report = SpecialistRecordImporter(
        sqlite_path=source,
        source_id="transaction-status-apply",
        tenant_id=1,
        apply=True,
    ).run()

    payload = report.to_dict()
    assert payload["transaction_status"] == "committed"
    assert payload["ledger_rows_after"] == 1
    assert payload["tables"]["patient_links"]["reused"] == 1


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_failed_report_states_no_commit_and_uses_durable_ledger_count(
    seed_data,
    tmp_path,
):
    source = _source(
        tmp_path / "status-failed.db",
        accounting_patient_id=99999999,
        national_id="0099900011",
    )
    importer = SpecialistRecordImporter(
        sqlite_path=source,
        source_id="transaction-status-failed",
        tenant_id=1,
        apply=True,
    )

    with pytest.raises(UnresolvedPatientError):
        importer.run()

    payload = importer.report.to_dict()
    assert payload["transaction_status"] == "failed_no_commit"
    assert payload["ledger_rows_after"] == 0
    assert any(
        "No import changes were committed" in warning
        for warning in payload["warnings"]
    )
