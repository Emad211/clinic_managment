from __future__ import annotations

from pathlib import Path
import sqlite3

from tests.accounting_import_source import build_source


def build_dual_run_source(path: Path) -> Path:
    source = build_source(path)
    with sqlite3.connect(source) as db:
        db.executescript(
            """
            INSERT INTO medical_staff(id,full_name,staff_type,is_active)
            VALUES(1,'Dual doctor','doctor',1),(2,'Dual nurse','nurse',1);
            INSERT INTO payroll_settings(
                id,staff_id,base_morning,base_evening,base_night,visit_fee,
                injection_percent,procedure_percent,tax_percent,nursing_percent,
                nurse_procedure_percent
            ) VALUES
                (1,1,100000,0,0,20000,30,40,10,6,35),
                (2,2,80000,0,0,0,0,0,0,6,35);
            UPDATE invoices SET doctor_id=1,nurse_id=2,shift='morning' WHERE id=100;
            UPDATE visits SET doctor_id=1,shift='morning' WHERE id=110;
            UPDATE injections SET doctor_id=1,nurse_id=2,shift='morning' WHERE id=120;
            UPDATE procedures
            SET doctor_id=1,nurse_id=2,performer_type='nurse',performer_id=2,
                shift='morning'
            WHERE id=130;
            UPDATE consumables_ledger SET doctor_id=1,nurse_id=2,shift='morning'
            WHERE id=140;
            """
        )
        db.commit()
    return source
