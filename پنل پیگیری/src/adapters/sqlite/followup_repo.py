"""Return evidence, call attempts and reception worklists (docs/04 §5, docs/06 §5)."""
from __future__ import annotations

import sqlite3
from typing import Iterable


# ------------------------------------------------------------------ items of an invoice (mirror)
def invoice_items(conn: sqlite3.Connection, invoice_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT a.item_type, a.item_id, a.acc_invoice_id, a.acc_patient_id, a.work_date, a.is_paid, a.deleted_at, "
        "a.price, a.doctor_staff_id, a.nurse_staff_id, a.performer_type, "
        "i.status AS invoice_status, i.total_amount, i.acc_patient_id AS invoice_patient_id, "
        "(SELECT group_concat(c.category) FROM acc_item_category c "
        "  WHERE c.item_type = a.item_type AND c.item_id = a.item_id) AS categories "
        "FROM acc_item a JOIN acc_invoice i ON i.acc_id = a.acc_invoice_id "
        "WHERE a.acc_invoice_id = ? ORDER BY a.item_type, a.item_id", (invoice_id,)).fetchall()


def invoice_row(conn: sqlite3.Connection, invoice_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM acc_invoice WHERE acc_id = ?", (invoice_id,)).fetchone()


def invoices_of_patient(conn: sqlite3.Connection, patient_id: int, since: str) -> list[int]:
    return [r[0] for r in conn.execute(
        "SELECT acc_id FROM acc_invoice WHERE acc_patient_id = ? AND work_date >= ? ORDER BY acc_id",
        (patient_id, since))]


def patient_phone(conn: sqlite3.Connection, patient_id: int) -> str | None:
    row = conn.execute("SELECT phone FROM acc_patient WHERE acc_id = ?", (patient_id,)).fetchone()
    return row[0] if row else None


def person_of_patient(conn: sqlite3.Connection, patient_id: int) -> int | None:
    row = conn.execute("SELECT person_id FROM person_acc_link WHERE acc_patient_id = ?", (patient_id,)).fetchone()
    return row[0] if row else None


# ------------------------------------------------------------------ evidence
def active_evidence_of_invoice(conn: sqlite3.Connection, invoice_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM return_evidence WHERE acc_invoice_id = ? AND revoked_at IS NULL",
                        (invoice_id,)).fetchall()


def active_evidence_of_journey(conn: sqlite3.Connection, journey_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM return_evidence WHERE journey_id = ? AND revoked_at IS NULL ORDER BY id",
                        (journey_id,)).fetchall()


def insert_evidence(conn: sqlite3.Connection, **f) -> int:
    cur = conn.execute(
        "INSERT INTO return_evidence(journey_id, step_id, acc_invoice_id, acc_item_type, acc_item_id, category, "
        "performer_staff_id, origin_doctor_staff_id, amount_snapshot, basis, matched_by, matched_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (f["journey_id"], f["step_id"], f["invoice_id"], f["item_type"], f["item_id"], f["category"],
         f["performer"], f["origin_doctor"], f["amount"], f["basis"], f["matched_by"], f["at"]))
    return int(cur.lastrowid)


def revoke_evidence(conn: sqlite3.Connection, evidence_id: int, reason: str, at: str) -> None:
    conn.execute("UPDATE return_evidence SET revoked_at = ?, revoke_reason = ? WHERE id = ? AND revoked_at IS NULL",
                 (at, reason, evidence_id))


def recent_evidence_invoices(conn: sqlite3.Connection, since: str) -> set[int]:
    """Invoices whose evidence was recorded recently: re-read by the poller (docs/03 §8 daily review)."""
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT acc_invoice_id FROM return_evidence WHERE revoked_at IS NULL AND matched_at >= ?", (since,))}


# ------------------------------------------------------------------ expect steps of a person
def open_expect_steps(conn: sqlite3.Connection, person_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT s.id AS step_id, s.journey_id, s.category, s.due_date, s.window_end, s.accept_early, "
        "j.start_date, j.origin_acc_invoice_id, j.origin_doctor_staff_id "
        "FROM journey_step s JOIN journey j ON j.id = s.journey_id "
        "WHERE j.person_id = ? AND j.status = 'active' AND s.kind = 'expect' AND s.status = 'pending' "
        "ORDER BY s.due_date, j.id, s.id", (person_id,)).fetchall()


def step(conn: sqlite3.Connection, step_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM journey_step WHERE id = ?", (step_id,)).fetchone()


def update_step(conn: sqlite3.Connection, step_id: int, **fields) -> None:
    allowed = {"due_date", "window_end", "attempts", "purpose", "recall_on_miss"}
    assert fields and set(fields) <= allowed, fields
    conn.execute(f"UPDATE journey_step SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                 (*fields.values(), step_id))


def continuations_of(conn: sqlite3.Connection, journey_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM journey WHERE origin_kind = 'continuation' AND origin_id = ?",
                        (journey_id,)).fetchall()


def journey_has_activity(conn: sqlite3.Connection, journey_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM call_attempt a JOIN journey_step s ON s.id = a.step_id WHERE s.journey_id = ? "
        "UNION SELECT 1 FROM return_evidence WHERE journey_id = ? LIMIT 1", (journey_id, journey_id)).fetchone() is not None


# ------------------------------------------------------------------ calls
def insert_attempt(conn: sqlite3.Connection, step_id: int, outcome: str, booked_date: str | None,
                   note: str | None, by: str, at: str) -> int:
    cur = conn.execute("INSERT INTO call_attempt(step_id, outcome, booked_date, note, by_user, at) "
                       "VALUES (?,?,?,?,?,?)", (step_id, outcome, booked_date, note, by, at))
    return int(cur.lastrowid)


def count_outcomes(conn: sqlite3.Connection, journey_id: int, outcome: str) -> int:
    return int(conn.execute(
        "SELECT count(*) FROM call_attempt a JOIN journey_step s ON s.id = a.step_id "
        "WHERE s.journey_id = ? AND a.outcome = ?", (journey_id, outcome)).fetchone()[0])


_CALL_ROWS = (
    "SELECT s.id AS step_id, s.journey_id, s.purpose, s.due_date, s.attempts, s.about_category, "
    "j.template_code, j.params, j.start_date, j.origin_doctor_staff_id, t.title, "
    "p.id AS person_id, p.first_name, p.last_name, p.mobile, p.national_id, st.full_name AS doctor_name, "
    "(SELECT a.note FROM call_attempt a WHERE a.step_id = s.id ORDER BY a.id DESC LIMIT 1) AS last_note "
    "FROM journey_step s JOIN journey j ON j.id = s.journey_id "
    "JOIN journey_template t ON t.code = j.template_code AND t.version = j.template_version "
    "JOIN person p ON p.id = j.person_id "
    "LEFT JOIN acc_staff st ON st.acc_id = j.origin_doctor_staff_id "
    "WHERE s.kind = 'call' AND s.status = 'pending' AND j.status = 'active' ")


def calls_due(conn: sqlite3.Connection, today: str) -> list[sqlite3.Row]:
    return conn.execute(_CALL_ROWS + "AND s.due_date = ? ORDER BY s.due_date, s.id", (today,)).fetchall()


def calls_overdue(conn: sqlite3.Connection, today: str) -> list[sqlite3.Row]:
    return conn.execute(_CALL_ROWS + "AND s.due_date < ? ORDER BY s.due_date, s.id", (today,)).fetchall()


def call_row(conn: sqlite3.Connection, step_id: int) -> sqlite3.Row | None:
    return conn.execute(_CALL_ROWS + "AND s.id = ?", (step_id,)).fetchone()


# ------------------------------------------------------------------ expected today & manual link (M9)
def expected_on(conn: sqlite3.Connection, today: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT s.id AS step_id, s.journey_id, s.category, s.due_date, s.window_end, s.purpose, t.title, "
        "p.id AS person_id, p.first_name, p.last_name, p.mobile, p.national_id "
        "FROM journey_step s JOIN journey j ON j.id = s.journey_id "
        "JOIN journey_template t ON t.code = j.template_code AND t.version = j.template_version "
        "JOIN person p ON p.id = j.person_id "
        "WHERE s.kind = 'expect' AND s.status = 'pending' AND j.status = 'active' "
        "AND s.due_date = ? ORDER BY p.last_name, p.first_name, s.id", (today,)).fetchall()


def unlinked_invoices_on(conn: sqlite3.Connection, day: str) -> list[sqlite3.Row]:
    """Invoices of the day whose accounting file has no person link (M9 path 2)."""
    return conn.execute(
        "SELECT i.acc_id AS invoice_id, i.acc_patient_id AS patient_id, a.name, a.family_name, a.phone, "
        "(SELECT group_concat(DISTINCT c.category) FROM acc_item o JOIN acc_item_category c "
        "  ON c.item_type = o.item_type AND c.item_id = o.item_id "
        " WHERE o.acc_invoice_id = i.acc_id AND o.deleted_at IS NULL) AS categories "
        "FROM acc_invoice i LEFT JOIN acc_patient a ON a.acc_id = i.acc_patient_id "
        "WHERE i.work_date = ? AND i.status <> 'missing' "
        "AND NOT EXISTS (SELECT 1 FROM person_acc_link l WHERE l.acc_patient_id = i.acc_patient_id) "
        "ORDER BY i.acc_id DESC", (day,)).fetchall()


def persons_expected_with_mobile(conn: sqlite3.Connection, mobile: str, lo: str, hi: str) -> list[sqlite3.Row]:
    """M9 suggestions: persons with this mobile who are expected within [lo, hi]."""
    return conn.execute(
        "SELECT DISTINCT p.* FROM person p JOIN journey j ON j.person_id = p.id "
        "JOIN journey_step s ON s.journey_id = j.id "
        "WHERE p.mobile = ? AND j.status = 'active' AND s.kind = 'expect' AND s.status = 'pending' "
        "AND s.due_date <= ? AND s.window_end >= ?", (mobile, hi, lo)).fetchall()


def pending_suggestions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT m.id, m.acc_invoice_id, m.person_id, m.reason, m.created_at, i.work_date, "
        "a.name, a.family_name, a.phone, p.first_name, p.last_name, p.mobile, p.national_id "
        "FROM match_suggestion m JOIN acc_invoice i ON i.acc_id = m.acc_invoice_id "
        "LEFT JOIN acc_patient a ON a.acc_id = i.acc_patient_id JOIN person p ON p.id = m.person_id "
        "WHERE m.status = 'pending' AND NOT EXISTS (SELECT 1 FROM person_acc_link l "
        "  WHERE l.acc_patient_id = i.acc_patient_id) ORDER BY m.id").fetchall()


def suggestion_by_id(conn: sqlite3.Connection, suggestion_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM match_suggestion WHERE id = ?", (suggestion_id,)).fetchone()


def add_suggestion(conn: sqlite3.Connection, invoice_id: int, person_id: int, reason: str, at: str) -> None:
    conn.execute("INSERT OR IGNORE INTO match_suggestion(acc_invoice_id, person_id, reason, status, created_at) "
                 "VALUES (?, ?, ?, 'pending', ?)", (invoice_id, person_id, reason, at))


def decide_suggestion(conn: sqlite3.Connection, suggestion_id: int, status: str, by: str, at: str) -> None:
    conn.execute("UPDATE match_suggestion SET status = ?, decided_by = ?, decided_at = ? WHERE id = ?",
                 (status, by, at, suggestion_id))


def shift_staff_rows(conn: sqlite3.Connection, since: str) -> list[tuple[str, str, int | None]]:
    return [tuple(r) for r in conn.execute(
        "SELECT work_date, shift, doctor_id FROM acc_shift_staff WHERE work_date >= ?", (since,))]


def ids_of(rows: Iterable[sqlite3.Row], key: str) -> list[int]:
    return [r[key] for r in rows]
