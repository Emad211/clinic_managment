from __future__ import annotations

from pathlib import Path
import sqlite3

from django.conf import settings


def _ensure(db: sqlite3.Connection, table: str, column: str, kind: str) -> None:
    if column not in {row[1] for row in db.execute(f"PRAGMA table_info({table})")}:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")


def build_source(path: Path) -> Path:
    schema = (
        Path(settings.BASE_DIR).parent
        / "webapp" / "src" / "adapters" / "sqlite" / "schema.sql"
    ).read_text(encoding="utf-8")
    db = sqlite3.connect(path)
    db.executescript(schema)
    _ensure(db, "invoices", "work_date", "TEXT")
    _ensure(db, "invoices", "shift", "TEXT")
    for table in ("visits", "injections", "procedures", "consumables_ledger"):
        _ensure(db, table, "work_date", "TEXT")
    db.executescript(
        """
        INSERT INTO patients(id,name,family_name) VALUES(10,'بیمار','آزمایشی');
        INSERT INTO invoices(id,patient_id,status,total_amount,work_date,shift)
        VALUES(100,10,'closed',230000,'2099-01-01','morning');
        INSERT INTO visits(id,patient_id,visit_date,price,invoice_id,work_date)
        VALUES(110,10,'2099-01-01 08:00:00',100000,100,'2099-01-01');
        INSERT INTO injections(
            id,patient_id,injection_type,injection_date,total_price,invoice_id,work_date
        ) VALUES(120,10,'تزریق آزمایشی','2099-01-01 08:10:00',50000,100,'2099-01-01');
        INSERT INTO procedures(
            id,patient_id,procedure_type,procedure_date,price,invoice_id,work_date
        ) VALUES(130,10,'پروسیجر آزمایشی','2099-01-01 08:20:00',80000,100,'2099-01-01');
        INSERT INTO consumables_ledger(
            id,patient_id,item_name,total_cost,patient_provided,is_exception,
            invoice_id,work_date
        ) VALUES(140,10,'مصرفی آزمایشی',12000,0,0,100,'2099-01-01');
        INSERT INTO invoice_item_payments(invoice_id,item_type,item_id,payment_type,is_paid)
        VALUES
            (100,'visit',110,'card',1),
            (100,'injection',120,'insurance',1),
            (100,'procedure',130,'cash',1),
            (100,'consumable',140,'cash',1);
        """
    )
    db.commit()
    db.close()
    return path
