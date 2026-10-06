"""Manager tools: reports, audit log, procedure-name mapping, mirror retention (docs/06 §6, docs/04 §7)."""
from __future__ import annotations

import sqlite3
from typing import Iterable


# ------------------------------------------------------------------ reports (journeys created in [start, end])
def journeys_by_template_status(conn: sqlite3.Connection, start: str, end: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT j.template_code, t.title, j.status, count(*) AS n "
        "FROM journey j JOIN journey_template t ON t.code = j.template_code AND t.version = j.template_version "
        "WHERE substr(j.created_at, 1, 10) BETWEEN ? AND ? AND j.origin_kind <> 'continuation' "
        "GROUP BY j.template_code, j.status ORDER BY t.title", (start, end)).fetchall()


def outcomes_by_doctor(conn: sqlite3.Connection, start: str, end: str) -> list[sqlite3.Row]:
    """Closed journeys per origin doctor: succeeded / partial / failed, plus same-doctor returns (M8)."""
    return conn.execute(
        "SELECT j.origin_doctor_staff_id AS staff_id, coalesce(s.full_name, '—') AS doctor, "
        "sum(j.status = 'succeeded') AS succeeded, sum(j.status = 'partial') AS partial, "
        "sum(j.status = 'failed') AS failed, "
        "(SELECT count(*) FROM return_evidence e JOIN journey j2 ON j2.id = e.journey_id "
        "  WHERE e.revoked_at IS NULL AND j2.origin_doctor_staff_id = j.origin_doctor_staff_id "
        "  AND e.performer_staff_id = e.origin_doctor_staff_id AND e.acc_item_type = 'visit' "
        "  AND substr(j2.created_at, 1, 10) BETWEEN ? AND ?) AS same_doctor_visits, "
        "(SELECT count(*) FROM return_evidence e JOIN journey j2 ON j2.id = e.journey_id "
        "  WHERE e.revoked_at IS NULL AND j2.origin_doctor_staff_id = j.origin_doctor_staff_id "
        "  AND e.acc_item_type = 'visit' AND substr(j2.created_at, 1, 10) BETWEEN ? AND ?) AS return_visits "
        "FROM journey j LEFT JOIN acc_staff s ON s.acc_id = j.origin_doctor_staff_id "
        "WHERE substr(j.created_at, 1, 10) BETWEEN ? AND ? AND j.origin_kind = 'encounter' "
        "GROUP BY j.origin_doctor_staff_id ORDER BY doctor",
        (start, end, start, end, start, end)).fetchall()


def calls_by_user(conn: sqlite3.Connection, start: str, end: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT by_user, outcome, count(*) AS n FROM call_attempt "
        "WHERE substr(at, 1, 10) BETWEEN ? AND ? GROUP BY by_user, outcome ORDER BY by_user", (start, end)).fetchall()


# ------------------------------------------------------------------ audit log
def audit_page(conn: sqlite3.Connection, *, start: str, end: str, actor: str | None, action: str | None,
               limit: int, offset: int) -> list[sqlite3.Row]:
    sql = "SELECT * FROM audit_log WHERE substr(at, 1, 10) BETWEEN ? AND ?"
    params: list = [start, end]
    if actor:
        sql += " AND actor LIKE ?"
        params.append(f"%{actor}%")
    if action:
        sql += " AND action LIKE ?"
        params.append(f"{action}%")
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    return conn.execute(sql, (*params, limit, offset)).fetchall()


def audit_actions(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT DISTINCT action FROM audit_log ORDER BY action")]


# ------------------------------------------------------------------ procedure names (docs/03 §9)
def procedure_names(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every distinct raw procedure name in the mirror with its row count."""
    return conn.execute(
        "SELECT raw_name, count(*) AS n FROM acc_item WHERE item_type = 'procedure' AND raw_name IS NOT NULL "
        "AND deleted_at IS NULL GROUP BY raw_name ORDER BY n DESC").fetchall()


def procedure_items(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT item_id, raw_name FROM acc_item WHERE item_type = 'procedure'").fetchall()


def set_procedure_map(conn: sqlite3.Connection, normalized: str, category: str | None, by: str, at: str) -> None:
    conn.execute(
        "INSERT INTO procedure_category_map(normalized_name, category, set_by, set_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(normalized_name) DO UPDATE SET category = excluded.category, set_by = excluded.set_by, "
        "set_at = excluded.set_at", (normalized, category, by, at))


def delete_procedure_map(conn: sqlite3.Connection, normalized: str) -> None:
    conn.execute("DELETE FROM procedure_category_map WHERE normalized_name = ?", (normalized,))


# ------------------------------------------------------------------ mirror retention (docs/04 §7)
_REFERENCED = (
    "SELECT acc_invoice_id FROM encounter UNION SELECT acc_invoice_id FROM walkin_entry "
    "UNION SELECT acc_invoice_id FROM return_evidence UNION SELECT origin_acc_invoice_id FROM journey "
    "WHERE origin_acc_invoice_id IS NOT NULL UNION SELECT acc_invoice_id FROM match_suggestion "
    "UNION SELECT acc_invoice_id FROM identity_dismissal")


def purge_mirror(conn: sqlite3.Connection, before: str) -> dict[str, int]:
    """Delete mirror rows whose work_date is before ``before`` unless panel records point at them."""
    old = f"SELECT acc_id FROM acc_invoice WHERE work_date < ? AND status <> 'open' AND acc_id NOT IN ({_REFERENCED})"
    counts = {}
    counts["categories"] = conn.execute(
        "DELETE FROM acc_item_category WHERE (item_type, item_id) IN (SELECT item_type, item_id FROM acc_item "
        f"WHERE acc_invoice_id IN ({old}))", (before,)).rowcount
    counts["items"] = conn.execute(f"DELETE FROM acc_item WHERE acc_invoice_id IN ({old})", (before,)).rowcount
    counts["invoices"] = conn.execute(f"DELETE FROM acc_invoice WHERE acc_id IN ({old})", (before,)).rowcount
    counts["patients"] = conn.execute(
        "DELETE FROM acc_patient WHERE acc_id NOT IN (SELECT acc_patient_id FROM acc_invoice) "
        "AND acc_id NOT IN (SELECT acc_patient_id FROM person_acc_link)").rowcount
    counts["shift_days"] = conn.execute("DELETE FROM acc_shift_staff WHERE work_date < ?", (before,)).rowcount
    return counts


def table_counts(conn: sqlite3.Connection, tables: Iterable[str]) -> dict[str, int]:
    return {t: int(conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]) for t in tables}
