"""Tests for the no-write accounting SQLite import preflight."""
from __future__ import annotations

from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
import stat

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
import pytest

from accounting_ops.import_preflight import AccountingImportPreflight


def _source(path: Path, *, orphan_payment: bool = False) -> Path:
    schema = (
        Path(settings.BASE_DIR).parent
        / "webapp"
        / "src"
        / "adapters"
        / "sqlite"
        / "schema.sql"
    ).read_text(encoding="utf-8")
    db = sqlite3.connect(path)
    db.executescript(schema)
    db.execute("ALTER TABLE invoices ADD COLUMN work_date TEXT")
    db.execute("ALTER TABLE invoices ADD COLUMN shift TEXT")
    for table in ("visits", "injections", "procedures", "consumables_ledger"):
        db.execute(f"ALTER TABLE {table} ADD COLUMN work_date TEXT")

    db.execute(
        "INSERT INTO medical_staff(id,full_name,staff_type,is_active) VALUES(1,'دکتر ETL','doctor',1)"
    )
    db.execute(
        "INSERT INTO medical_staff(id,full_name,staff_type,is_active) VALUES(2,'پرستار ETL','nurse',1)"
    )
    db.execute(
        """
        INSERT INTO patients(id,name,family_name,national_id,phone_number)
        VALUES(10,'بیمار','ETL','0013546821','09121112233')
        """
    )
    db.execute(
        "INSERT INTO visit_tariffs(id,insurance_type,tariff_price,nursing_tariff,nursing_covers) VALUES(20,'بیمه ETL',100000,20000,1)"
    )
    db.execute(
        "INSERT INTO services(id,name,base_price,service_type,is_active) VALUES(30,'خدمت ETL',25000,'custom',1)"
    )
    db.execute(
        "INSERT INTO nursing_services(id,service_name,unit_price,is_active) VALUES(40,'تزریق ETL',50000,1)"
    )
    db.execute(
        "INSERT INTO injection_types(id,type_name,base_price,is_active) VALUES(41,'تزریق ETL',50000,1)"
    )
    db.execute(
        "INSERT INTO procedure_tariffs(id,name,unit_price,is_active) VALUES(50,'پروسیجر ETL',80000,1)"
    )
    db.execute(
        "INSERT INTO consumable_tariffs(id,name,default_price,category,is_active) VALUES(60,'گاز ETL',12000,'supply',1)"
    )
    db.execute(
        "INSERT INTO insurance_nursing_exclusions(id,insurance_type,nursing_service_id,note) VALUES(70,'بیمه ETL',40,'استثنا')"
    )
    db.execute(
        """
        INSERT INTO payroll_settings(id,staff_id,base_morning,visit_fee,injection_percent,
                                     procedure_percent,tax_percent,nursing_percent,
                                     nurse_procedure_percent)
        VALUES(80,1,100000,20000,30,40,10,6,35)
        """
    )
    db.execute(
        """
        INSERT INTO invoices(id,patient_id,doctor_id,nurse_id,status,insurance_type,
                             total_amount,opened_by,work_date,shift)
        VALUES(100,10,1,2,'closed','بیمه ETL',230000,'admin','2099-01-01','morning')
        """
    )
    db.execute(
        """
        INSERT INTO visits(id,patient_id,doctor_name,visit_date,shift,insurance_type,
                           status,price,payment_status,reception_user,invoice_id,
                           doctor_id,work_date)
        VALUES(110,10,'دکتر ETL','2099-01-01 08:00:00','morning','بیمه ETL',
               'done',100000,'paid','admin',100,1,'2099-01-01')
        """
    )
    db.execute(
        "INSERT INTO visit_items(id,visit_id,service_id,quantity,price_at_time) VALUES(111,110,30,1,25000)"
    )
    db.execute(
        """
        INSERT INTO injections(id,patient_id,injection_type,injection_date,shift,count,
                               unit_price,total_price,reception_user,invoice_id,
                               doctor_id,nurse_id,work_date)
        VALUES(120,10,'تزریق ETL','2099-01-01 08:10:00','morning',1,
               50000,50000,'admin',100,1,2,'2099-01-01')
        """
    )
    db.execute(
        """
        INSERT INTO procedures(id,patient_id,procedure_type,procedure_date,shift,price,
                               reception_user,invoice_id,performer_type,performer_id,
                               doctor_id,nurse_id,work_date)
        VALUES(130,10,'پروسیجر ETL','2099-01-01 08:20:00','morning',80000,
               'admin',100,'nurse',2,1,2,'2099-01-01')
        """
    )
    db.execute(
        """
        INSERT INTO consumables_ledger(id,patient_id,item_name,category,quantity,
                                       unit_price,total_cost,patient_provided,is_exception,
                                       usage_date,shift,reception_user,invoice_id,
                                       doctor_id,nurse_id,work_date)
        VALUES(140,10,'گاز ETL','supply',1,12000,12000,0,0,
               '2099-01-01 08:30:00','morning','admin',100,1,2,'2099-01-01')
        """
    )
    payment_item = 999 if orphan_payment else 110
    db.execute(
        "INSERT INTO invoice_item_payments(invoice_id,item_type,item_id,payment_type,is_paid) VALUES(100,'visit',?,'card',1)",
        [payment_item],
    )
    db.commit()
    db.close()
    return path


def test_valid_snapshot_produces_go_and_pinned_money_totals(tmp_path):
    source = _source(tmp_path / "legacy-accounting.db")
    report = AccountingImportPreflight(
        sqlite_path=source,
        source_id="clinic-main-accounting",
    ).run()
    assert report.decision == "GO", report.errors
    assert report.quick_check == "ok"
    assert report.money["invoice_total_all"] == 230000
    assert report.money["visit_raw"] == 100000
    assert report.money["nursing_raw"] == 50000
    assert report.money["procedure_raw"] == 80000
    assert report.money["operating_revenue_raw"] == 230000
    assert report.money["consumables_center"] == 12000
    assert report.money["payments_paid"] == 1
    assert len(report.source_manifest_sha256) == 64


def test_orphan_payment_fails_closed(tmp_path):
    source = _source(tmp_path / "orphan-payment.db", orphan_payment=True)
    report = AccountingImportPreflight(
        sqlite_path=source,
        source_id="clinic-orphan-accounting",
    ).run()
    assert report.decision == "NO_GO"
    check = next(item for item in report.checks if item["code"] == "payment_item_references")
    assert check["status"] == "FAIL"
    assert check["evidence"]["orphan_rows"] == 1


def test_command_writes_private_report_and_refuses_source_collision(tmp_path):
    source = _source(tmp_path / "command-source.db")
    report_path = tmp_path / "private" / "preflight.json"
    stdout = StringIO()
    call_command(
        "inspect_legacy_accounting",
        sqlite=str(source),
        source_id="clinic-command-accounting",
        report=str(report_path),
        stdout=stdout,
    )
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o600
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["decision"] == "GO"
    assert "Accounting import preflight GO" in stdout.getvalue()

    with pytest.raises(CommandError, match="overwrite"):
        call_command(
            "inspect_legacy_accounting",
            sqlite=str(source),
            source_id="clinic-command-accounting",
            report=str(source),
        )


def test_nonempty_wal_is_no_go(tmp_path):
    source = _source(tmp_path / "live-source.db")
    source.with_name(source.name + "-wal").write_bytes(b"live")
    report = AccountingImportPreflight(
        sqlite_path=source,
        source_id="clinic-live-accounting",
    ).run()
    assert report.decision == "NO_GO"
    assert any(
        item["code"] == "quiesced_snapshot" and item["status"] == "FAIL"
        for item in report.checks
    )
