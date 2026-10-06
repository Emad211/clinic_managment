"""Accounting mirror (acc_* tables, docs/04 §7). Written only by the poller."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterable

ItemKey = tuple[str, int]          # (item_type, item_id)


@dataclass(frozen=True)
class MirrorItem:
    item_type: str
    item_id: int
    acc_invoice_id: int
    acc_patient_id: int | None
    raw_name: str | None
    service_id: int | None
    doctor_staff_id: int | None
    nurse_staff_id: int | None
    performer_type: str | None
    price: float | None
    work_date: str | None
    shift: str | None
    item_at: str | None

    @property
    def key(self) -> ItemKey:
        return self.item_type, self.item_id


@dataclass(frozen=True)
class MirrorItemState:
    acc_invoice_id: int
    is_paid: int
    deleted_at: str | None
    raw_name: str | None
    service_id: int | None


def _marks(n: int) -> str:
    return ",".join("?" * n)


def _chunks(ids: Iterable[int], size: int = 500):
    ids = list(ids)
    for i in range(0, len(ids), size):
        yield ids[i:i + size]


# ------------------------------------------------------------------ invoices
def open_invoice_ids(conn: sqlite3.Connection) -> set[int]:
    return {r[0] for r in conn.execute("SELECT acc_id FROM acc_invoice WHERE status = 'open'")}


def invoice_statuses(conn: sqlite3.Connection, ids: Iterable[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    for chunk in _chunks(ids):
        out.update(conn.execute(
            f"SELECT acc_id, status FROM acc_invoice WHERE acc_id IN ({_marks(len(chunk))})", chunk).fetchall())
    return out


def upsert_invoice(conn: sqlite3.Connection, inv, now: str) -> None:
    conn.execute(
        "INSERT INTO acc_invoice(acc_id, acc_patient_id, status, work_date, shift, opened_at, closed_at, "
        "opened_by, total_amount, first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(acc_id) DO UPDATE SET acc_patient_id = excluded.acc_patient_id, status = excluded.status, "
        "work_date = excluded.work_date, shift = excluded.shift, opened_at = excluded.opened_at, "
        "closed_at = excluded.closed_at, opened_by = excluded.opened_by, total_amount = excluded.total_amount, "
        "last_seen_at = excluded.last_seen_at",
        (inv.id, inv.patient_id, inv.status or "open", inv.work_date, inv.shift, inv.opened_at, inv.closed_at,
         inv.opened_by, inv.total_amount, now, now))


def mark_invoice_missing(conn: sqlite3.Connection, acc_id: int, now: str) -> None:
    """The invoice vanished from accounting; take it out of the watched set."""
    conn.execute("UPDATE acc_invoice SET status = 'missing', last_seen_at = ? WHERE acc_id = ?", (now, acc_id))


# ------------------------------------------------------------------ items
def item_states(conn: sqlite3.Connection, invoice_ids: Iterable[int]) -> dict[ItemKey, MirrorItemState]:
    out: dict[ItemKey, MirrorItemState] = {}
    for chunk in _chunks(invoice_ids):
        for r in conn.execute(
                "SELECT item_type, item_id, acc_invoice_id, is_paid, deleted_at, raw_name, service_id FROM acc_item "
                f"WHERE acc_invoice_id IN ({_marks(len(chunk))})", chunk):
            out[(r[0], r[1])] = MirrorItemState(*r[2:])
    return out


def upsert_item(conn: sqlite3.Connection, it: MirrorItem) -> None:
    conn.execute(
        "INSERT INTO acc_item(item_type, item_id, acc_invoice_id, acc_patient_id, raw_name, service_id, "
        "doctor_staff_id, nurse_staff_id, performer_type, price, work_date, shift, item_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(item_type, item_id) DO UPDATE SET acc_invoice_id = excluded.acc_invoice_id, "
        "acc_patient_id = excluded.acc_patient_id, raw_name = excluded.raw_name, service_id = excluded.service_id, "
        "doctor_staff_id = excluded.doctor_staff_id, nurse_staff_id = excluded.nurse_staff_id, "
        "performer_type = excluded.performer_type, price = excluded.price, work_date = excluded.work_date, "
        "shift = excluded.shift, item_at = excluded.item_at, deleted_at = NULL",
        (it.item_type, it.item_id, it.acc_invoice_id, it.acc_patient_id, it.raw_name, it.service_id,
         it.doctor_staff_id, it.nurse_staff_id, it.performer_type, it.price, it.work_date, it.shift, it.item_at))


def mark_item_deleted(conn: sqlite3.Connection, key: ItemKey, now: str) -> None:
    conn.execute("UPDATE acc_item SET deleted_at = ? WHERE item_type = ? AND item_id = ? AND deleted_at IS NULL",
                 (now, *key))


def set_item_payment(conn: sqlite3.Connection, key: ItemKey, is_paid: int, payment_type: str | None,
                     now: str) -> None:
    conn.execute(
        "UPDATE acc_item SET is_paid = ?, payment_type = ?, "
        "paid_seen_at = CASE WHEN ? = 1 THEN coalesce(paid_seen_at, ?) ELSE NULL END "
        "WHERE item_type = ? AND item_id = ?",
        (is_paid, payment_type, is_paid, now, *key))


def replace_item_categories(conn: sqlite3.Connection, key: ItemKey, categories: Iterable[str]) -> None:
    conn.execute("DELETE FROM acc_item_category WHERE item_type = ? AND item_id = ?", key)
    conn.executemany("INSERT INTO acc_item_category(item_type, item_id, category) VALUES (?,?,?)",
                     [(*key, c) for c in sorted(categories)])


def procedure_category_map(conn: sqlite3.Connection) -> dict[str, str | None]:
    return dict(conn.execute("SELECT normalized_name, category FROM procedure_category_map").fetchall())


# ------------------------------------------------------------------ patients, staff, shifts
def upsert_patient(conn: sqlite3.Connection, p, identity_ok: bool, now: str) -> bool:
    """Returns True if the identity-relevant fields changed (or the row is new)."""
    before = conn.execute(
        "SELECT name, family_name, national_id, phone, is_foreign, identity_ok FROM acc_patient WHERE acc_id = ?",
        (p.id,)).fetchone()
    after = (p.name, p.family_name, p.national_id, p.phone_number, p.is_foreign, int(identity_ok))
    conn.execute(
        "INSERT INTO acc_patient(acc_id, name, family_name, national_id, phone, is_foreign, identity_ok, last_seen_at) "
        "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(acc_id) DO UPDATE SET name = excluded.name, "
        "family_name = excluded.family_name, national_id = excluded.national_id, phone = excluded.phone, "
        "is_foreign = excluded.is_foreign, identity_ok = excluded.identity_ok, last_seen_at = excluded.last_seen_at",
        (p.id, *after, now))
    return before is None or tuple(before) != after


def replace_staff(conn: sqlite3.Connection, staff, now: str) -> None:
    """medical_staff is tiny; rows deleted in accounting disappear here too."""
    conn.execute("DELETE FROM acc_staff")
    conn.executemany("INSERT INTO acc_staff(acc_id, full_name, staff_type, is_active, last_seen_at) "
                     "VALUES (?,?,?,?,?)",
                     [(s.id, s.full_name, s.staff_type, s.is_active, now) for s in staff])


def active_doctors(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT acc_id, full_name FROM acc_staff WHERE staff_type = 'doctor' "
                        "AND coalesce(is_active, 1) = 1 ORDER BY full_name").fetchall()


def staff_names(conn: sqlite3.Connection) -> dict[int, str]:
    return dict(conn.execute("SELECT acc_id, full_name FROM acc_staff").fetchall())


def upsert_shift_staff(conn: sqlite3.Connection, rows) -> None:
    conn.executemany(
        "INSERT INTO acc_shift_staff(work_date, shift, doctor_id, nurse_id) VALUES (?,?,?,?) "
        "ON CONFLICT(work_date, shift) DO UPDATE SET doctor_id = excluded.doctor_id, nurse_id = excluded.nurse_id",
        [(r.work_date, r.shift, r.doctor_id, r.nurse_id) for r in rows])


# ------------------------------------------------------------------ doctor queue (docs/06 §4-1)
def doctor_queue(conn: sqlite3.Connection, staff_id: int, work_date: str, shift: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT v.item_id AS visit_id, v.acc_invoice_id, v.acc_patient_id, v.item_at, "
        "       coalesce(local.first_name,p.name) AS name, coalesce(local.last_name,p.family_name) AS family_name, "
        "       coalesce(local.national_id,p.national_id) AS national_id, "
        "       CASE WHEN local.id IS NOT NULL THEN 1 ELSE coalesce(p.identity_ok,0) END AS identity_ok, "
        "       e.decision, "
        "       (SELECT group_concat(c.category) FROM acc_item o JOIN acc_item_category c "
        "          ON c.item_type = o.item_type AND c.item_id = o.item_id "
        "        WHERE o.acc_invoice_id = v.acc_invoice_id AND o.deleted_at IS NULL "
        "          AND o.item_type <> 'visit') AS other_categories "
        "FROM acc_item v "
        "LEFT JOIN acc_patient p ON p.acc_id = v.acc_patient_id "
        "LEFT JOIN person_acc_link l ON l.acc_patient_id = v.acc_patient_id "
        "LEFT JOIN person local ON local.id = l.person_id "
        "LEFT JOIN encounter e ON e.acc_visit_id = v.item_id "
        "WHERE v.item_type = 'visit' AND v.work_date = ? AND v.shift = ? AND v.doctor_staff_id = ? "
        "  AND v.deleted_at IS NULL "
        "ORDER BY (e.decision IS NOT NULL), v.item_at, v.item_id",
        (work_date, shift, staff_id)).fetchall()
