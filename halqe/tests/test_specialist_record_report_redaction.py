"""PHI-redaction tests for operator-facing specialist import reports."""
from __future__ import annotations

import json
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
    accounting_patient_id: int | None,
    national_id: str,
    full_name: str,
    wallet_balance: int = 0,
) -> Path:
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE patient_links (
            id INTEGER PRIMARY KEY,
            national_id TEXT,
            accounting_patient_id INTEGER,
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
            (id, national_id, accounting_patient_id, full_name,
             wallet_balance, sms_opt_out, is_active)
        VALUES (77, ?, ?, ?, ?, 0, 1)
        """,
        [national_id, accounting_patient_id, full_name, wallet_balance],
    )
    db.commit()
    db.close()
    return path


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_unresolved_error_and_report_redact_raw_identity(seed_data, tmp_path):
    national_id = "0099988877"
    full_name = "نام محرمانه تست"
    source = _source(
        tmp_path / "unresolved-redaction.db",
        accounting_patient_id=99999999,
        national_id=national_id,
        full_name=full_name,
    )
    importer = SpecialistRecordImporter(
        sqlite_path=source,
        source_id="record-redaction-unresolved",
        tenant_id=1,
        apply=False,
    )

    with pytest.raises(UnresolvedPatientError) as captured:
        importer.run()

    rendered_error = str(captured.value)
    rendered_report = json.dumps(
        importer.report.to_dict(), ensure_ascii=False, sort_keys=True
    )
    for secret in (national_id, full_name, "99999999"):
        assert secret not in rendered_error
        assert secret not in rendered_report

    # A full traceback must not reveal the original unredacted exception either.
    assert captured.value.__cause__ is None
    assert "77" in rendered_error
    assert importer.report.unresolved_patients == [
        {
            "source_patient_link_id": 77,
            "has_national_id": True,
            "has_accounting_patient_id": True,
        }
    ]


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_financial_out_of_scope_report_keeps_amount_but_redacts_national_id(
    seed_data,
    tmp_path,
):
    national_id = "0088877766"
    source = _source(
        tmp_path / "wallet-redaction.db",
        accounting_patient_id=seed_data["patient_id"],
        national_id=national_id,
        full_name="بیمار کیف پول تست",
        wallet_balance=125000,
    )
    report = SpecialistRecordImporter(
        sqlite_path=source,
        source_id="record-redaction-wallet",
        tenant_id=1,
        apply=False,
    ).run()

    rendered = json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True)
    assert national_id not in rendered
    assert "بیمار کیف پول تست" not in rendered
    assert report.financial_data_out_of_scope["nonzero_patient_wallets"] == [
        {
            "source_patient_link_id": 77,
            "wallet_balance": 125000,
        }
    ]
