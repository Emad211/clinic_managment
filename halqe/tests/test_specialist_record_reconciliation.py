"""End-to-end go/no-go tests for specialist-record reconciliation."""
from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
import sqlite3
import stat
import uuid

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
import pytest

from clinical.secure_report_io import write_private_text
from clinical.specialist_record_import import SpecialistRecordImporter
from clinical.specialist_record_reconciliation import SpecialistRecordReconciler
from platform_core.tenant_context import set_tenant_guc


SOURCE_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "specialist_clinic"
    / "src"
    / "adapters"
    / "sqlite"
    / "schema.sql"
)


def _ensure_column(
    db: sqlite3.Connection,
    table: str,
    column: str,
    declaration: str,
) -> None:
    columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def _build_source(
    path: Path,
    *,
    accounting_patient_id: int,
    suffix: str,
) -> Path:
    db = sqlite3.connect(path)
    db.executescript(SOURCE_SCHEMA.read_text(encoding="utf-8"))
    for table, column, declaration in (
        ("patient_links", "wallet_balance", "INTEGER NOT NULL DEFAULT 0"),
        ("patient_links", "sms_opt_out", "INTEGER NOT NULL DEFAULT 0"),
        ("lab_results", "test_key", "TEXT"),
    ):
        _ensure_column(db, table, column, declaration)

    test_key = f"reconcile_lab_{suffix}"
    db.execute(
        """
        INSERT INTO patient_links
            (id, accounting_patient_id, national_id, full_name, phone_number,
             wallet_balance, sms_opt_out, is_active, enrolled_at)
        VALUES (7001, ?, NULL, 'بیمار تطبیق تست', '09120007001',
                0, 0, 1, '2025-01-01 08:00:00')
        """,
        [accounting_patient_id],
    )
    db.execute(
        """
        INSERT INTO lab_test_catalog
            (test_key, name_fa, unit, ref_low, ref_high, category,
             display_order, is_active)
        VALUES (?, 'آزمایش تطبیق تست', 'mg/dL', 10, 20,
                'other', 990, 1)
        """,
        [test_key],
    )
    db.execute(
        """
        INSERT INTO vital_readings
            (id, patient_link_id, type, value, unit, measured_at,
             source, notes, recorded_by)
        VALUES (7002, 7001, 'weight', 82.5, 'kg',
                '2025-01-02 09:00:00', 'self',
                'خوداظهاری تطبیق', 'patient')
        """
    )
    db.execute(
        """
        INSERT INTO lab_results
            (id, patient_link_id, test_name, test_key, value, unit,
             ref_low, ref_high, taken_at, notes, recorded_by)
        VALUES (7003, 7001, 'آزمایش تطبیق تست', ?, 14.5,
                'mg/dL', 10, 20, '2025-01-03 10:00:00',
                'نمونه تطبیق', 'testuser')
        """,
        [test_key],
    )
    db.execute(
        """
        INSERT INTO medical_history
            (id, patient_link_id, title, note, since, created_at)
        VALUES (7004, 7001, 'سابقه تطبیق تست', 'شرح اولیه',
                '2020-01-01', '2025-01-04 11:00:00')
        """
    )
    db.commit()
    db.close()
    return path


def _reports(
    *,
    source: Path,
    source_id: str,
    tmp_path: Path,
) -> tuple[Path, Path]:
    apply = SpecialistRecordImporter(
        sqlite_path=source,
        source_id=source_id,
        tenant_id=1,
        apply=True,
    ).run()
    replay = SpecialistRecordImporter(
        sqlite_path=source,
        source_id=source_id,
        tenant_id=1,
        apply=True,
    ).run()
    apply_path = write_private_text(
        tmp_path / "apply-report.json",
        json.dumps(apply.to_dict(), ensure_ascii=False, sort_keys=True) + "\n",
    )
    replay_path = write_private_text(
        tmp_path / "replay-report.json",
        json.dumps(replay.to_dict(), ensure_ascii=False, sort_keys=True) + "\n",
    )
    return apply_path, replay_path


def _reconciler(
    *,
    source: Path,
    source_id: str,
    apply_report: Path,
    replay_report: Path | None,
    require_replay: bool = True,
) -> SpecialistRecordReconciler:
    return SpecialistRecordReconciler(
        sqlite_path=source,
        apply_report_path=apply_report,
        replay_report_path=replay_report,
        source_id=source_id,
        tenant_id=1,
        require_replay=require_replay,
    )


def _check(report, name: str):
    return next(item for item in report.checks if item.name == name)


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_reconciliation_is_go_after_apply_and_pure_replay(seed_data, tmp_path):
    suffix = uuid.uuid4().hex
    source_id = f"reconciliation-go-{suffix}"
    source = _build_source(
        tmp_path / "reconciliation-go.db",
        accounting_patient_id=seed_data["patient_id"],
        suffix=suffix,
    )
    apply_report, replay_report = _reports(
        source=source,
        source_id=source_id,
        tmp_path=tmp_path,
    )

    result = _reconciler(
        source=source,
        source_id=source_id,
        apply_report=apply_report,
        replay_report=replay_report,
    ).run()

    assert result.decision == "GO"
    assert _check(result, "apply_report_contract").status == "pass"
    assert _check(result, "idempotent_replay_report").status == "pass"
    assert _check(result, "relational_dry_run_reproduction").status == "pass"
    assert _check(result, "ledger_manifest").status == "pass"
    assert _check(result, "ledger_target_existence").status == "pass"
    assert _check(result, "verified_patient_self_reports").status == "pass"
    assert _check(result, "lab_observation_visibility").status == "pass"


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_missing_target_pointer_is_no_go(seed_data, tmp_path):
    suffix = uuid.uuid4().hex
    source_id = f"reconciliation-missing-target-{suffix}"
    source = _build_source(
        tmp_path / "reconciliation-missing-target.db",
        accounting_patient_id=seed_data["patient_id"],
        suffix=suffix,
    )
    apply_report, replay_report = _reports(
        source=source,
        source_id=source_id,
        tmp_path=tmp_path,
    )

    set_tenant_guc(1)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT target_row_id
            FROM clinical.record_import_ledger
            WHERE tenant_id=1 AND source_id=%s
              AND source_table='medical_history'
            """,
            [source_id],
        )
        target_id = int(cursor.fetchone()[0])
        cursor.execute(
            "DELETE FROM clinical.medical_history WHERE tenant_id=1 AND id=%s",
            [target_id],
        )

    result = _reconciler(
        source=source,
        source_id=source_id,
        apply_report=apply_report,
        replay_report=replay_report,
    ).run()
    assert result.decision == "NO_GO"
    assert _check(result, "ledger_target_existence").status == "fail"
    assert _check(result, "relational_dry_run_reproduction").status == "fail"


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_verified_imported_self_report_is_no_go(seed_data, tmp_path):
    suffix = uuid.uuid4().hex
    source_id = f"reconciliation-self-report-{suffix}"
    source = _build_source(
        tmp_path / "reconciliation-self-report.db",
        accounting_patient_id=seed_data["patient_id"],
        suffix=suffix,
    )
    apply_report, replay_report = _reports(
        source=source,
        source_id=source_id,
        tmp_path=tmp_path,
    )

    set_tenant_guc(1)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE clinical.vital_readings v
            SET verified=TRUE, verified_by='tampered-rehearsal'
            FROM clinical.record_import_ledger l
            WHERE l.tenant_id=1 AND l.source_id=%s
              AND l.source_table='vital_readings'
              AND v.tenant_id=l.tenant_id AND v.id=l.target_row_id
            """,
            [source_id],
        )

    result = _reconciler(
        source=source,
        source_id=source_id,
        apply_report=apply_report,
        replay_report=replay_report,
    ).run()
    assert result.decision == "NO_GO"
    check = _check(result, "verified_patient_self_reports")
    assert check.status == "fail"
    assert check.metrics["violations"] == 1


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_changed_source_after_apply_is_no_go(seed_data, tmp_path):
    suffix = uuid.uuid4().hex
    source_id = f"reconciliation-source-drift-{suffix}"
    source = _build_source(
        tmp_path / "reconciliation-source-drift.db",
        accounting_patient_id=seed_data["patient_id"],
        suffix=suffix,
    )
    apply_report, replay_report = _reports(
        source=source,
        source_id=source_id,
        tmp_path=tmp_path,
    )

    db = sqlite3.connect(source)
    db.execute(
        "UPDATE medical_history SET note='شرح تغییرکرده' WHERE id=7004"
    )
    db.commit()
    db.close()

    result = _reconciler(
        source=source,
        source_id=source_id,
        apply_report=apply_report,
        replay_report=replay_report,
    ).run()
    assert result.decision == "NO_GO"
    assert _check(result, "relational_dry_run_reproduction").status == "fail"


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_replay_report_is_required_by_default(seed_data, tmp_path):
    suffix = uuid.uuid4().hex
    source_id = f"reconciliation-replay-required-{suffix}"
    source = _build_source(
        tmp_path / "reconciliation-replay-required.db",
        accounting_patient_id=seed_data["patient_id"],
        suffix=suffix,
    )
    apply_report, _replay_report = _reports(
        source=source,
        source_id=source_id,
        tmp_path=tmp_path,
    )

    result = _reconciler(
        source=source,
        source_id=source_id,
        apply_report=apply_report,
        replay_report=None,
    ).run()
    assert result.decision == "NO_GO"
    assert _check(result, "replay_report_present").status == "fail"


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_verifier_command_writes_private_go_report(seed_data, tmp_path):
    suffix = uuid.uuid4().hex
    source_id = f"reconciliation-command-{suffix}"
    source = _build_source(
        tmp_path / "reconciliation-command.db",
        accounting_patient_id=seed_data["patient_id"],
        suffix=suffix,
    )
    apply_report, replay_report = _reports(
        source=source,
        source_id=source_id,
        tmp_path=tmp_path,
    )
    output = tmp_path / "private" / "verification.json"
    stdout = StringIO()

    call_command(
        "verify_specialist_record_import",
        sqlite=str(source),
        apply_report=str(apply_report),
        replay_report=str(replay_report),
        source_id=source_id,
        tenant_id=1,
        report=str(output),
        stdout=stdout,
        verbosity=0,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["decision"] == "GO"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert "Specialist record reconciliation GO" in stdout.getvalue()


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_verifier_command_exits_nonzero_on_no_go(seed_data, tmp_path):
    suffix = uuid.uuid4().hex
    source_id = f"reconciliation-command-fail-{suffix}"
    source = _build_source(
        tmp_path / "reconciliation-command-fail.db",
        accounting_patient_id=seed_data["patient_id"],
        suffix=suffix,
    )
    apply_report, _replay_report = _reports(
        source=source,
        source_id=source_id,
        tmp_path=tmp_path,
    )

    with pytest.raises(CommandError, match="NO_GO"):
        call_command(
            "verify_specialist_record_import",
            sqlite=str(source),
            apply_report=str(apply_report),
            source_id=source_id,
            tenant_id=1,
            verbosity=0,
        )
