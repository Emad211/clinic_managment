"""Security contracts for the specialist-record management command output."""
from __future__ import annotations

from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
import stat

from django.core.management import call_command
from django.core.management.base import CommandError
import pytest


def _minimal_source(path: Path, *, accounting_patient_id: int) -> Path:
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
        VALUES (1, NULL, ?, 'نام نباید در stdout چاپ شود', 0, 0, 1)
        """,
        [accounting_patient_id],
    )
    db.commit()
    db.close()
    return path


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_command_writes_atomic_owner_only_report_and_compact_stdout(
    seed_data,
    tmp_path,
):
    source = _minimal_source(
        tmp_path / "private-report-source.db",
        accounting_patient_id=seed_data["patient_id"],
    )
    report = tmp_path / "nested" / "record-report.json"
    stdout = StringIO()

    call_command(
        "import_specialist_record",
        sqlite=str(source),
        source_id="private-report-test",
        tenant_id=1,
        report=str(report),
        stdout=stdout,
        verbosity=0,
    )

    assert report.exists()
    assert stat.S_IMODE(report.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(report.stat().st_mode) == 0o600
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["mode"] == "dry-run"
    assert payload["source_id"] == "private-report-test"

    output = stdout.getvalue()
    assert "Specialist record import validated" in output
    assert "Wrote private reconciliation report (0600)" in output
    assert '"source_path"' not in output
    assert "نام نباید در stdout چاپ شود" not in output
    assert not list(report.parent.glob(f".{report.name}.*.tmp"))


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_print_report_is_explicit_and_still_redacted(seed_data, tmp_path):
    source = _minimal_source(
        tmp_path / "print-report-source.db",
        accounting_patient_id=seed_data["patient_id"],
    )
    stdout = StringIO()

    call_command(
        "import_specialist_record",
        sqlite=str(source),
        source_id="print-report-test",
        tenant_id=1,
        print_report=True,
        stdout=stdout,
        verbosity=0,
    )

    output = stdout.getvalue()
    assert '"source_id": "print-report-test"' in output
    assert "نام نباید در stdout چاپ شود" not in output


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_command_refuses_report_symlink_without_touching_target(seed_data, tmp_path):
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks are not supported on this platform")

    source = _minimal_source(
        tmp_path / "symlink-source.db",
        accounting_patient_id=seed_data["patient_id"],
    )
    protected = tmp_path / "protected.txt"
    protected.write_text("do-not-overwrite", encoding="utf-8")
    report_link = tmp_path / "report-link.json"
    try:
        os.symlink(protected, report_link)
    except OSError as exc:
        pytest.skip(f"cannot create symlink on this platform: {exc}")

    with pytest.raises(CommandError, match="symlink"):
        call_command(
            "import_specialist_record",
            sqlite=str(source),
            source_id="symlink-report-test",
            tenant_id=1,
            report=str(report_link),
            verbosity=0,
        )

    assert protected.read_text(encoding="utf-8") == "do-not-overwrite"
    assert report_link.is_symlink()
