"""Synthetic accounting databases built from the production DDL.

Only invented data. tests/fixtures/accounting_schema.sql is schema only;
real rows never enter the repository.
"""
from __future__ import annotations

import random
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA_FILE = FIXTURES / "accounting_schema.sql"

BS_TEST_ID = 22
BP_CHECK_ID = 31
TODAY = date(2026, 10, 6)


def schema_sql(*, drop_columns: dict[str, str] | None = None, drop_indexes: tuple[str, ...] = ()) -> str:
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    for table, column in (drop_columns or {}).items():
        body = re.search(rf"CREATE TABLE {table} \((.*?)\n\);", sql, re.S)
        assert body, table
        lines = [ln for ln in body.group(1).split("\n") if not re.match(rf"\s*{column}\s", ln)]
        sql = sql.replace(body.group(1), "\n".join(lines))
    for name in drop_indexes:
        sql = re.sub(rf"CREATE INDEX {name} [^;]*;", "", sql)
    return sql


def build_accounting_db(path: Path, *, invoices: int = 300, open_invoices: int = 10, seed: int = 7,
                        drop_columns: dict[str, str] | None = None,
                        drop_indexes: tuple[str, ...] = ()) -> Path:
    """Create a DELETE-journal accounting DB with plausible synthetic rows."""
    rng = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(schema_sql(drop_columns=drop_columns, drop_indexes=drop_indexes))
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    if drop_columns:
        conn.close()
        return path

    conn.executemany("INSERT INTO users(id, username, password_hash, role, full_name) VALUES (?,?,?,?,?)",
                     [(1, "manager1", b"x", "manager", "مدیر"), (2, "recep1", b"x", "reception", "پذیرش یک"),
                      (3, "recep2", b"x", "reception", "پذیرش دو")])
    conn.executemany("INSERT INTO medical_staff(id, full_name, staff_type) VALUES (?,?,?)",
                     [(1, "دکتر الف", "doctor"), (2, "دکتر ب", "doctor"), (5, "پرستار ج", "nurse")])
    services = [(i, f"خدمت {i}", 1) for i in range(1, 35)]
    services[BS_TEST_ID - 1] = (BS_TEST_ID, "تست قند", 1)
    services[BP_CHECK_ID - 1] = (BP_CHECK_ID, "کنترل فشار", 1)
    conn.executemany("INSERT INTO nursing_services(id, service_name, is_active) VALUES (?,?,?)", services)
    conn.executemany("INSERT INTO user_active_shift(user_id, active_shift, work_date, shift_started_at) "
                     "VALUES (?,?,?,?)",
                     [(2, "morning", TODAY.isoformat(), f"{TODAY} 07:58:00"),
                      (3, "evening", (TODAY - timedelta(days=1)).isoformat(), f"{TODAY - timedelta(days=1)} 15:01:00")])

    patients = []
    for pid in range(1, invoices // 2 + 2):
        nid = f"{1_000_000_000 + pid}" if rng.random() < 0.3 else None
        patients.append((pid, f"نام{pid}", f"خانواده{pid}", nid, f"0912{rng.randrange(10**6, 10**7)}", 0))
    conn.executemany("INSERT OR IGNORE INTO patients(id, name, family_name, national_id, phone_number, is_foreign) "
                     "VALUES (?,?,?,?,?,?)", patients)

    days = max(1, invoices // 120)
    for iid in range(1, invoices + 1):
        work = TODAY - timedelta(days=days - (iid * days) // (invoices + 1))
        is_open = iid > invoices - open_invoices
        pid = rng.randrange(1, len(patients) + 1)
        shift = rng.choice(["morning", "evening", "night"])
        conn.execute(
            "INSERT INTO invoices(id, patient_id, status, total_amount, work_date, shift, opened_at, closed_at, opened_by) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (iid, pid, "open" if is_open else "closed", 0, work.isoformat(), shift, f"{work} 09:00:00",
             None if is_open else f"{work} 09:20:00", "recep1"))
        add_items(conn, iid, pid, work.isoformat(), shift, rng, paid=not is_open)
    for d in range(90):
        day = (TODAY - timedelta(days=d)).isoformat()
        for shift in ("morning", "evening", "night"):
            conn.execute("INSERT INTO shift_staff VALUES (?,?,?,?)", (day, shift, rng.choice([1, 2]), 5))
    conn.commit()
    conn.close()
    return path


def add_items(conn: sqlite3.Connection, iid: int, pid: int, work: str, shift: str,
              rng: random.Random, *, paid: bool) -> None:
    def pay(item_type: str, item_id: int) -> None:
        conn.execute("INSERT INTO invoice_item_payments(invoice_id, item_type, item_id, payment_type, is_paid) "
                     "VALUES (?,?,?,?,?)", (iid, item_type, item_id, "cash", 1 if paid else 0))

    cur = conn.execute("INSERT INTO visits(patient_id, invoice_id, doctor_id, work_date, shift, price) "
                       "VALUES (?,?,?,?,?,?)", (pid, iid, rng.choice([1, 2]), work, shift, 500000))
    pay("visit", cur.lastrowid)
    conn.execute("INSERT INTO activity_logs(action_type, action_category, invoice_id, target_type, target_id) "
                 "VALUES ('invoice_create', 'invoice', ?, 'invoice', ?)", (iid, iid))
    if rng.random() < 0.4:
        sid = rng.choice([BS_TEST_ID, BP_CHECK_ID])
        cur = conn.execute(
            "INSERT INTO injections(patient_id, injection_type, service_id, work_date, shift, total_price, "
            "invoice_id, nurse_id) VALUES (?,?,?,?,?,?,?,?)",
            (pid, "تست قند" if sid == BS_TEST_ID else "کنترل فشار", sid, work, shift, 80000, iid, 5))
        pay("injection", cur.lastrowid)
    if rng.random() < 0.2:
        cur = conn.execute(
            "INSERT INTO procedures(patient_id, procedure_type, work_date, shift, price, invoice_id, "
            "performer_type, nurse_id) VALUES (?,?,?,?,?,?,?,?)",
            (pid, rng.choice(["کشیدن بخیه", "پانسمان", "شستشوی گوش"]), work, shift, 150000, iid, "nurse", 5))
        pay("procedure", cur.lastrowid)


class Reception:
    """Plays the accounting app's reception writes on a synthetic DB (same tables, same rows).

    Every write is its own short transaction with python's default timeout=5,
    like the accounting app.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def _run(self, sql: str, params=()) -> int:
        conn = sqlite3.connect(str(self.path), timeout=5)
        try:
            cur = conn.execute(sql, params)
            conn.commit()
            return int(cur.lastrowid or 0)
        finally:
            conn.close()

    def _log(self, action: str, invoice_id: int | None, target_type: str | None = None,
             target_id: int | None = None) -> None:
        self._run("INSERT INTO activity_logs(action_type, action_category, invoice_id, target_type, target_id) "
                  "VALUES (?, 'invoice', ?, ?, ?)", (action, invoice_id, target_type, target_id))

    def add_patient(self, name: str, family: str, national_id: str | None = None,
                    phone: str | None = None, is_foreign: int = 0) -> int:
        return self._run("INSERT INTO patients(name, family_name, national_id, phone_number, is_foreign) "
                         "VALUES (?,?,?,?,?)", (name, family, national_id, phone, is_foreign))

    def update_patient(self, pid: int, **fields) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._run(f"UPDATE patients SET {cols} WHERE id = ?", (*fields.values(), pid))

    def open_invoice(self, patient_id: int, work_date: str, shift: str) -> int:
        iid = self._run("INSERT INTO invoices(patient_id, status, work_date, shift, opened_by) "
                        "VALUES (?, 'open', ?, ?, 'recep1')", (patient_id, work_date, shift))
        self._log("invoice_create", iid, "invoice", iid)
        return iid

    def _patient_of(self, iid: int) -> tuple[int, str, str]:
        conn = sqlite3.connect(str(self.path))
        try:
            return conn.execute("SELECT patient_id, work_date, shift FROM invoices WHERE id = ?", (iid,)).fetchone()
        finally:
            conn.close()

    def add_visit(self, iid: int, doctor_id: int, at: str | None = None, price: float = 500000) -> int:
        pid, work, shift = self._patient_of(iid)
        vid = self._run("INSERT INTO visits(patient_id, invoice_id, doctor_id, work_date, shift, price, visit_date) "
                        "VALUES (?,?,?,?,?,?, coalesce(?, datetime('now')))", (pid, iid, doctor_id, work, shift, price, at))
        self._run("INSERT INTO invoice_item_payments(invoice_id, item_type, item_id, is_paid) VALUES (?, 'visit', ?, 0)",
                  (iid, vid))
        self._log("visit_add", iid, "visit", vid)
        return vid

    def add_injection(self, iid: int, service_id: int, name: str, nurse_id: int = 5) -> int:
        pid, work, shift = self._patient_of(iid)
        jid = self._run("INSERT INTO injections(patient_id, injection_type, service_id, work_date, shift, "
                        "total_price, invoice_id, nurse_id) VALUES (?,?,?,?,?,?,?,?)",
                        (pid, name, service_id, work, shift, 80000, iid, nurse_id))
        self._run("INSERT INTO invoice_item_payments(invoice_id, item_type, item_id, is_paid) "
                  "VALUES (?, 'injection', ?, 0)", (iid, jid))
        self._log("injection_add", iid, "injection", jid)
        return jid

    def add_procedure(self, iid: int, name: str, nurse_id: int = 5) -> int:
        pid, work, shift = self._patient_of(iid)
        rid = self._run("INSERT INTO procedures(patient_id, procedure_type, work_date, shift, price, invoice_id, "
                        "performer_type, nurse_id) VALUES (?,?,?,?,?,?,'nurse',?)",
                        (pid, name, work, shift, 150000, iid, nurse_id))
        self._run("INSERT INTO invoice_item_payments(invoice_id, item_type, item_id, is_paid) "
                  "VALUES (?, 'procedure', ?, 0)", (iid, rid))
        self._log("procedure_add", iid, "procedure", rid)
        return rid

    def set_paid(self, iid: int, item_type: str, item_id: int, paid: bool = True) -> None:
        self._run("INSERT INTO invoice_item_payments(invoice_id, item_type, item_id, payment_type, is_paid) "
                  "VALUES (?,?,?, 'cash', ?) ON CONFLICT(invoice_id, item_type, item_id) "
                  "DO UPDATE SET is_paid = excluded.is_paid, payment_type = excluded.payment_type",
                  (iid, item_type, item_id, int(paid)))
        self._log("payment_update", iid, item_type, item_id)

    def delete_item(self, iid: int, item_type: str, item_id: int) -> None:
        table = {"visit": "visits", "injection": "injections", "procedure": "procedures"}[item_type]
        self._run(f"DELETE FROM {table} WHERE id = ?", (item_id,))
        self._run("DELETE FROM invoice_item_payments WHERE invoice_id = ? AND item_type = ? AND item_id = ?",
                  (iid, item_type, item_id))
        self._log(f"{item_type}_delete", iid, item_type, item_id)

    def close_invoice(self, iid: int, total: float) -> None:
        self._run("UPDATE invoices SET status = 'closed', total_amount = ?, closed_at = datetime('now') "
                  "WHERE id = ?", (total, iid))
        self._log("invoice_close", iid, "invoice", iid)

    def start_shift(self, user_id: int, shift: str, work_date: str, started_at: str) -> None:
        self._run("INSERT INTO user_active_shift(user_id, active_shift, work_date, shift_started_at) "
                  "VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET active_shift = excluded.active_shift, "
                  "work_date = excluded.work_date, shift_started_at = excluded.shift_started_at",
                  (user_id, shift, work_date, started_at))

    def set_staff_active(self, staff_id: int, active: bool) -> None:
        self._run("UPDATE medical_staff SET is_active = ? WHERE id = ?", (int(active), staff_id))

    def add_user(self, username: str, password_hash: bytes | str, role: str, *, active: int = 1,
                 locked_until: str | None = None, full_name: str = "") -> int:
        return self._run("INSERT INTO users(username, password_hash, role, full_name, is_active, locked_until) "
                         "VALUES (?,?,?,?,?,?)", (username, password_hash, role, full_name, active, locked_until))
