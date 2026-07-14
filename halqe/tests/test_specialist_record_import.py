"""Historical specialist SQLite -> Halqe record ETL characterization tests."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
import pytest

from clinical.specialist_record_import import (
    FinancialDataOutOfScopeError,
    SourceRowChangedError,
    SpecialistRecordImporter,
    UnresolvedPatientError,
)
from platform_core.tenant_context import set_tenant_guc


SOURCE_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "specialist_clinic"
    / "src"
    / "adapters"
    / "sqlite"
    / "schema.sql"
)


def _ensure_column(db: sqlite3.Connection, table: str, column: str, declaration: str):
    columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def _build_source(
    path: Path,
    *,
    accounting_patient_id: int,
    national_id: str = "1234567890",
    wallet_balance: int = 0,
    suffix: str = "base",
) -> Path:
    db = sqlite3.connect(path)
    db.executescript(SOURCE_SCHEMA.read_text(encoding="utf-8"))
    for table, column, declaration in (
        ("patient_links", "wallet_balance", "INTEGER NOT NULL DEFAULT 0"),
        ("patient_links", "sms_opt_out", "INTEGER NOT NULL DEFAULT 0"),
        ("patient_medications", "end_date", "TEXT"),
        ("patient_medications", "drug_class", "TEXT"),
        ("flag_catalog", "record_section", "TEXT"),
        ("followup_tasks", "source_rule", "TEXT"),
        ("followup_tasks", "source_event", "TEXT"),
        ("followup_tasks", "appointment_id", "INTEGER"),
        ("followup_tasks", "fulfillment", "TEXT DEFAULT 'in_person'"),
        ("lab_results", "test_key", "TEXT"),
    ):
        _ensure_column(db, table, column, declaration)

    db.execute(
        """
        INSERT OR REPLACE INTO users
            (id, username, password_hash, role, full_name, is_active)
        VALUES (77, 'testuser', ?, 'provider', 'پزشک تست', 1)
        """,
        (b"not-used-by-etl",),
    )
    db.execute(
        """
        INSERT INTO patient_links
            (id, accounting_patient_id, national_id, full_name, phone_number,
             gender, birthdate, address, notes, wallet_balance, sms_opt_out,
             is_active, enrolled_by, enrolled_at)
        VALUES (1001, ?, ?, 'علی رضایی', '09120000001', 'male',
                '1990-05-15', 'آدرس تست', 'یادداشت لینک', ?, 1, 1,
                'testuser', '2025-01-01 08:00:00')
        """,
        (accounting_patient_id, national_id, wallet_balance),
    )

    condition_code = f"etl_condition_{suffix}"
    flag_key = f"etl_flag_{suffix}"
    class_key = f"etl_class_{suffix}"
    test_key = f"etl_lab_{suffix}"
    db.execute(
        """
        INSERT INTO conditions
            (id, name, code, is_active, is_chronic, display_order,
             description, icon, color)
        VALUES (9101, ?, ?, 1, 1, 910, 'شرح ETL', 'i-test', 'info')
        """,
        (f"بیماری ETL {suffix}", condition_code),
    )
    db.execute(
        """
        INSERT INTO patient_conditions
            (id, patient_link_id, condition_id, stage, onset_date, notes,
             is_active, diagnosed_at)
        VALUES (9102, 1001, 9101, 'mild', '2024-01-01',
                'تشخیص واردشده', 1, '2025-01-01 09:00:00')
        """
    )
    db.execute(
        """
        INSERT INTO flag_catalog
            (id, flag_key, label, flag_type, options, category,
             display_order, is_active, notes, record_section)
        VALUES (9201, ?, 'فلگ ETL', 'enum', 'low|کم,high|زیاد',
                'risk', 920, 1, 'توضیح', 'disease')
        """,
        (flag_key,),
    )
    db.execute(
        """
        INSERT INTO patient_flags
            (id, patient_link_id, flag_key, value, recorded_by, updated_at)
        VALUES (9202, 1001, ?, 'high', 'testuser', '2025-01-02 10:00:00')
        """,
        (flag_key,),
    )
    db.execute(
        """
        INSERT INTO drug_classes
            (id, class_key, label, glucose_lowering, display_order, is_active)
        VALUES (9301, ?, 'کلاس ETL', 0, 930, 1)
        """,
        (class_key,),
    )
    db.execute(
        """
        INSERT INTO drug_catalog
            (id, generic_fa, drug_class_key, standard_doses, is_active)
        VALUES (9302, ?, ?, '5 mg,10 mg', 1)
        """,
        (f"داروی کاتالوگ {suffix}", class_key),
    )
    db.execute(
        """
        INSERT INTO patient_medications
            (id, patient_link_id, drug_name, dose, schedule, start_date,
             refill_due_date, end_date, drug_class, is_active, notes, created_at)
        VALUES (9303, 1001, ?, '5 mg', 'روزی یک بار', '2025-01-01',
                '2025-01-31', NULL, ?, 1, 'شروع ETL',
                '2025-01-01 10:00:00')
        """,
        (f"داروی بیمار {suffix}", class_key),
    )
    db.execute(
        """
        INSERT INTO medication_events
            (id, patient_link_id, medication_id, drug_name, event_type,
             dose, event_date, note, created_by, created_at)
        VALUES (9304, 1001, 9303, ?, 'start', '5 mg', '2025-01-01',
                'رویداد شروع', 'testuser', '2025-01-01 10:00:00')
        """,
        (f"داروی بیمار {suffix}",),
    )
    db.execute(
        """
        INSERT INTO lab_test_catalog
            (test_key, name_fa, unit, ref_low, ref_high, category,
             display_order, is_active)
        VALUES (?, 'آزمایش ETL', 'mg/dL', 10, 20, 'other', 940, 1)
        """,
        (test_key,),
    )
    db.execute(
        """
        INSERT INTO condition_lab_tests
            (condition_code, lab_test_key, display_order)
        VALUES (?, ?, 10)
        """,
        (condition_code, test_key),
    )
    db.execute(
        """
        INSERT INTO allergies
            (id, patient_link_id, substance, reaction, severity, created_at)
        VALUES (9401, 1001, 'پنی‌سیلین ETL', 'راش', 'moderate',
                '2025-01-03 10:00:00')
        """
    )
    db.execute(
        """
        INSERT INTO vital_readings
            (id, patient_link_id, type, value, unit, measured_at,
             source, notes, recorded_by)
        VALUES (9402, 1001, 'weight', 81.5, 'kg',
                '2025-01-04 10:00:00', 'self', 'خوداظهاری', 'patient')
        """
    )
    db.execute(
        """
        INSERT INTO lab_results
            (id, patient_link_id, test_name, test_key, value, unit,
             ref_low, ref_high, taken_at, notes, recorded_by)
        VALUES (9403, 1001, 'آزمایش ETL', ?, 14.5, 'mg/dL',
                10, 20, '2025-01-05 10:00:00', 'نمونه', 'testuser')
        """,
        (test_key,),
    )
    db.execute(
        """
        INSERT INTO appointments
            (id, patient_link_id, scheduled_at, appt_type, status,
             recurrence_months, parent_appointment_id, reminder_sent,
             notes, created_by, created_at)
        VALUES (9501, 1001, '2025-02-01 09:00:00', 'checkup',
                'scheduled', 3, NULL, 0, 'نوبت ETL', 'testuser',
                '2025-01-01 11:00:00')
        """
    )
    db.execute(
        """
        INSERT INTO followup_tasks
            (id, patient_link_id, due_date, reason, detail, status,
             assigned_to, call_log, created_at, resolved_at, source_rule,
             source_event, appointment_id, fulfillment)
        VALUES (9502, 1001, '2025-02-02', 'etl_followup', 'پیگیری ETL',
                'open', 'testuser', NULL, '2025-01-01 12:00:00', NULL,
                'rule-etl', 'event-etl', 9501, 'in_person')
        """
    )
    db.execute(
        """
        INSERT INTO suggestion_log
            (id, patient_link_id, rule_code, suggestion_text,
             evidence_level, status, acted_by, acted_at, note, created_at)
        VALUES (9503, 1001, ?, 'پیشنهاد تاریخی ETL', 'B',
                'accepted', 'testuser', '2025-01-02 12:00:00',
                'پذیرفته شد', '2025-01-01 12:00:00')
        """,
        (f"etl_rule_{suffix}",),
    )
    db.execute(
        """
        INSERT INTO surgery_history
            (id, patient_link_id, title, performed_on, note, created_at)
        VALUES (9601, 1001, 'جراحی ETL', '2020-01-01',
                'بدون عارضه', '2025-01-01 13:00:00')
        """
    )
    db.execute(
        """
        INSERT INTO medical_history
            (id, patient_link_id, title, note, since, created_at)
        VALUES (9602, 1001, 'سابقه ETL', 'شرح سابقه', '2019-01-01',
                '2025-01-01 13:00:00')
        """
    )
    db.execute(
        """
        INSERT INTO clinical_notes
            (id, patient_link_id, kind, body, recorded_at, recorded_by)
        VALUES (9603, 1001, 'general', 'یادداشت ETL',
                '2025-01-06 10:00:00', 'testuser')
        """
    )
    db.execute(
        """
        INSERT INTO prescriptions
            (id, patient_link_id, kind, items, mode, insurer,
             portal_rx_id, prescriber_user_id, followup_task_id, issued_at)
        VALUES (9604, 1001, 'etl_prescription', ?, 'free', NULL,
                NULL, 77, 9502, '2025-01-07 10:00:00')
        """,
        (json.dumps([{"drug_name": "داروی نسخه ETL", "dose": "5 mg"}], ensure_ascii=False),),
    )
    db.commit()
    db.close()
    return path


def _scalar(query: str, params=()):
    with connection.cursor() as cursor:
        set_tenant_guc(1)
        cursor.execute(query, params)
        return cursor.fetchone()[0]


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_dry_run_is_no_write_and_reports_planned_rows(seed_data, tmp_path):
    source = _build_source(
        tmp_path / "dry-run.db",
        accounting_patient_id=seed_data["patient_id"],
        suffix="dry",
    )
    report = SpecialistRecordImporter(
        sqlite_path=source,
        source_id="record-etl-dry",
        tenant_id=1,
        apply=False,
    ).run()

    assert report.mode == "dry-run"
    assert report.tables["patient_links"].planned_reuse == 1
    assert report.tables["medical_history"].planned_insert == 1
    assert report.source_manifest_sha256
    assert _scalar(
        "SELECT COUNT(*) FROM clinical.record_import_ledger WHERE tenant_id=1 AND source_id=%s",
        ["record-etl-dry"],
    ) == 0
    assert _scalar(
        "SELECT COUNT(*) FROM clinical.conditions WHERE tenant_id=1 AND code='etl_condition_dry'"
    ) == 0


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_apply_is_complete_idempotent_and_preserves_safety(seed_data, tmp_path):
    source = _build_source(
        tmp_path / "apply.db",
        accounting_patient_id=seed_data["patient_id"],
        suffix="apply",
    )
    importer = SpecialistRecordImporter(
        sqlite_path=source,
        source_id="record-etl-apply",
        tenant_id=1,
        apply=True,
    )
    first = importer.run()
    assert first.ledger_rows_after and first.ledger_rows_after > 10
    assert first.tables["medical_history"].inserted == 1

    with connection.cursor() as cursor:
        set_tenant_guc(1)
        cursor.execute(
            """
            SELECT sms_consent, sms_opt_out
            FROM clinical.patient_links
            WHERE tenant_id=1 AND id=%s
            """,
            [seed_data["link_id"]],
        )
        assert cursor.fetchone() == (True, True)
        cursor.execute(
            """
            SELECT m.id, e.medication_id, e.event_type
            FROM clinical.patient_medications m
            JOIN clinical.medication_events e
              ON e.tenant_id=m.tenant_id AND e.medication_id=m.id
            WHERE m.tenant_id=1 AND m.patient_link_id=%s
              AND m.drug_name='داروی بیمار apply'
            """,
            [seed_data["link_id"]],
        )
        med_id, event_med_id, event_type = cursor.fetchone()
        assert med_id == event_med_id
        assert event_type == "start"
        cursor.execute(
            """
            SELECT source, verified
            FROM clinical.vital_readings
            WHERE tenant_id=1 AND patient_link_id=%s
              AND notes='خوداظهاری'
            """,
            [seed_data["link_id"]],
        )
        assert cursor.fetchone() == ("patient_self", False)
        cursor.execute(
            """
            SELECT verified, obs_key, value
            FROM clinical.observations
            WHERE tenant_id=1 AND patient_link_id=%s
              AND source_table='lab' AND obs_key='lab:etl_lab_apply'
            """,
            [seed_data["link_id"]],
        )
        assert cursor.fetchone() == (True, "lab:etl_lab_apply", 14.5)
        cursor.execute(
            """
            SELECT f.appointment_id, p.followup_task_id, p.prescriber_user_id
            FROM clinical.followup_tasks f
            JOIN clinical.prescriptions p
              ON p.tenant_id=f.tenant_id AND p.followup_task_id=f.id
            WHERE f.tenant_id=1 AND f.patient_link_id=%s
              AND f.reason='etl_followup'
            """,
            [seed_data["link_id"]],
        )
        appointment_id, followup_id, prescriber_id = cursor.fetchone()
        assert appointment_id is not None
        assert followup_id is not None
        assert prescriber_id == seed_data["user_id"]

    before = _scalar(
        "SELECT COUNT(*) FROM clinical.medical_history WHERE tenant_id=1 AND title='سابقه ETL'"
    )
    second = SpecialistRecordImporter(
        sqlite_path=source,
        source_id="record-etl-apply",
        tenant_id=1,
        apply=True,
    ).run()
    assert second.tables["medical_history"].replayed == 1
    assert _scalar(
        "SELECT COUNT(*) FROM clinical.medical_history WHERE tenant_id=1 AND title='سابقه ETL'"
    ) == before


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_changed_source_row_conflicts_and_rolls_back_new_rows(seed_data, tmp_path):
    source = _build_source(
        tmp_path / "changed.db",
        accounting_patient_id=seed_data["patient_id"],
        suffix="changed",
    )
    kwargs = dict(
        sqlite_path=source,
        source_id="record-etl-changed",
        tenant_id=1,
        apply=True,
    )
    SpecialistRecordImporter(**kwargs).run()

    db = sqlite3.connect(source)
    db.execute(
        """
        INSERT INTO medical_history
            (id, patient_link_id, title, note, since, created_at)
        VALUES (9999, 1001, 'باید rollback شود', NULL, '2021-01-01',
                '2025-01-10 10:00:00')
        """
    )
    db.execute("UPDATE clinical_notes SET body='متن تغییرکرده' WHERE id=9603")
    db.commit()
    db.close()

    with pytest.raises(SourceRowChangedError):
        SpecialistRecordImporter(**kwargs).run()
    assert _scalar(
        "SELECT COUNT(*) FROM clinical.medical_history WHERE tenant_id=1 AND title='باید rollback شود'"
    ) == 0
    assert _scalar(
        """
        SELECT COUNT(*) FROM clinical.record_import_ledger
        WHERE tenant_id=1 AND source_id='record-etl-changed'
          AND source_table='medical_history' AND source_row_id=9999
        """
    ) == 0


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_unresolved_patient_is_fail_closed(seed_data, tmp_path):
    source = _build_source(
        tmp_path / "unresolved.db",
        accounting_patient_id=99999999,
        national_id="0000000000",
        suffix="unresolved",
    )
    with pytest.raises(UnresolvedPatientError):
        SpecialistRecordImporter(
            sqlite_path=source,
            source_id="record-etl-unresolved",
            tenant_id=1,
            apply=True,
        ).run()
    assert _scalar(
        "SELECT COUNT(*) FROM clinical.conditions WHERE tenant_id=1 AND code='etl_condition_unresolved'"
    ) == 0


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_financial_data_requires_explicit_acknowledgement(seed_data, tmp_path):
    source = _build_source(
        tmp_path / "wallet.db",
        accounting_patient_id=seed_data["patient_id"],
        wallet_balance=50000,
        suffix="wallet",
    )
    dry = SpecialistRecordImporter(
        sqlite_path=source,
        source_id="record-etl-wallet-dry",
        tenant_id=1,
        apply=False,
    ).run()
    assert dry.financial_data_out_of_scope["nonzero_patient_wallets"][0]["wallet_balance"] == 50000

    with pytest.raises(FinancialDataOutOfScopeError):
        SpecialistRecordImporter(
            sqlite_path=source,
            source_id="record-etl-wallet-apply",
            tenant_id=1,
            apply=True,
        ).run()


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_management_command_writes_reconciliation_report(seed_data, tmp_path):
    source = _build_source(
        tmp_path / "command.db",
        accounting_patient_id=seed_data["patient_id"],
        suffix="command",
    )
    report_path = tmp_path / "reports" / "record-import.json"
    call_command(
        "import_specialist_record",
        sqlite=str(source),
        source_id="record-etl-command",
        tenant_id=1,
        report=str(report_path),
        verbosity=0,
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "dry-run"
    assert payload["source_manifest_sha256"]
    assert payload["tables"]["clinical_notes"]["planned_insert"] == 1


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_import_ledger_is_rls_scoped_and_append_only(seed_data, tmp_path):
    source = _build_source(
        tmp_path / "ledger.db",
        accounting_patient_id=seed_data["patient_id"],
        suffix="ledger",
    )
    SpecialistRecordImporter(
        sqlite_path=source,
        source_id="record-etl-ledger",
        tenant_id=1,
        apply=True,
    ).run()

    with transaction.atomic():
        set_tenant_guc(1)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) FROM clinical.record_import_ledger
                WHERE tenant_id=1 AND source_id='record-etl-ledger'
                """
            )
            assert cursor.fetchone()[0] > 0

    with pytest.raises(DatabaseError):
        with transaction.atomic():
            set_tenant_guc(1)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE clinical.record_import_ledger
                    SET imported_by='tampered'
                    WHERE tenant_id=1 AND source_id='record-etl-ledger'
                    """
                )
