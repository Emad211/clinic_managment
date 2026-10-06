"""Templates, journeys, steps, encounters, walk-ins, measurements, chronic tags and cut-offs (docs/04 §4–§6)."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable

OPEN_STATUSES = ("awaiting_identity", "active", "needs_review")


# ------------------------------------------------------------------ templates
def template_codes(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT DISTINCT code FROM journey_template")}


def insert_template(conn: sqlite3.Connection, code: str, version: int, title: str, definition: dict,
                    enabled: bool, by: str, at: str) -> None:
    conn.execute("UPDATE journey_template SET is_current = 0 WHERE code = ?", (code,))
    conn.execute(
        "INSERT INTO journey_template(code, version, title, definition, is_enabled, is_current, changed_by, changed_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
        (code, version, title, json.dumps(definition, ensure_ascii=False), int(enabled), by, at))


def current_templates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT code, version, title, definition, is_enabled FROM journey_template "
                        "WHERE is_current = 1 ORDER BY code").fetchall()


def template_version(conn: sqlite3.Connection, code: str, version: int) -> sqlite3.Row | None:
    return conn.execute("SELECT code, version, title, definition, is_enabled FROM journey_template "
                        "WHERE code = ? AND version = ?", (code, version)).fetchone()


# ------------------------------------------------------------------ journeys & steps
def insert_journey(conn: sqlite3.Connection, *, person_id: int | None, code: str, version: int, params: dict,
                   origin_kind: str, origin_id: int | None, origin_invoice_id: int | None,
                   origin_doctor_staff_id: int | None, start_date: str, status: str, by: str, at: str) -> int:
    cur = conn.execute(
        "INSERT INTO journey(person_id, template_code, template_version, params, origin_kind, origin_id, "
        "origin_acc_invoice_id, origin_doctor_staff_id, start_date, status, created_at, created_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (person_id, code, version, json.dumps(params, ensure_ascii=False, sort_keys=True), origin_kind, origin_id,
         origin_invoice_id, origin_doctor_staff_id, start_date, status, at, by))
    return int(cur.lastrowid)


def insert_step(conn: sqlite3.Connection, journey_id: int, *, seq: int, kind: str, due_date: str,
                window_end: str | None, category: str | None, purpose: str, accept_early: bool = False,
                recall_on_miss: bool = False, completes: bool = False, about_category: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO journey_step(journey_id, seq, kind, due_date, window_end, category, purpose, status, "
        "accept_early, recall_on_miss, completes, about_category) VALUES (?,?,?,?,?,?,?, 'pending', ?,?,?,?)",
        (journey_id, seq, kind, due_date, window_end, category, purpose, int(accept_early), int(recall_on_miss),
         int(completes), about_category))
    return int(cur.lastrowid)


def next_seq(conn: sqlite3.Connection, journey_id: int) -> int:
    return int(conn.execute("SELECT coalesce(max(seq), 0) + 1 FROM journey_step WHERE journey_id = ?",
                            (journey_id,)).fetchone()[0])


def journey(conn: sqlite3.Connection, journey_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM journey WHERE id = ?", (journey_id,)).fetchone()


def steps(conn: sqlite3.Connection, journey_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM journey_step WHERE journey_id = ? ORDER BY seq", (journey_id,)).fetchall()


def open_journey(conn: sqlite3.Connection, person_id: int, code: str) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT * FROM journey WHERE person_id = ? AND template_code = ? AND status IN {OPEN_STATUSES}",
        (person_id, code)).fetchone()


def journeys_to_tick(conn: sqlite3.Connection) -> list[int]:
    return [r[0] for r in conn.execute(
        "SELECT id FROM journey WHERE status IN ('awaiting_identity', 'active') ORDER BY id")]


def journeys_from_origin(conn: sqlite3.Connection, origin_kind: str, origin_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM journey WHERE origin_kind = ? AND origin_id = ? ORDER BY id",
                        (origin_kind, origin_id)).fetchall()


def open_journeys_of_person(conn: sqlite3.Connection, person_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT j.*, t.title, (SELECT min(s.due_date) FROM journey_step s WHERE s.journey_id = j.id "
        "  AND s.status = 'pending') AS next_due "
        f"FROM journey j JOIN journey_template t ON t.code = j.template_code AND t.version = j.template_version "
        f"WHERE j.person_id = ? AND j.status IN {OPEN_STATUSES} ORDER BY j.id", (person_id,)).fetchall()


def set_step_status(conn: sqlite3.Connection, step_id: int, status: str, at: str) -> None:
    conn.execute("UPDATE journey_step SET status = ?, resolved_at = CASE WHEN ? = 'pending' THEN NULL ELSE ? END "
                 "WHERE id = ?", (status, status, at, step_id))


def set_journey_status(conn: sqlite3.Connection, journey_id: int, status: str, reason: str | None,
                       at: str) -> None:
    closed = status not in OPEN_STATUSES
    conn.execute("UPDATE journey SET status = ?, close_reason = ?, closed_at = ? WHERE id = ?",
                 (status, reason if closed else None, at if closed else None, journey_id))


def set_journey_person(conn: sqlite3.Connection, journey_id: int, person_id: int) -> None:
    conn.execute("UPDATE journey SET person_id = ? WHERE id = ?", (person_id, journey_id))


# ------------------------------------------------------------------ encounters & measurements
def encounter_by_visit(conn: sqlite3.Connection, visit_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM encounter WHERE acc_visit_id = ?", (visit_id,)).fetchone()


def insert_encounter(conn: sqlite3.Connection, **f: Any) -> int:
    cur = conn.execute(
        "INSERT INTO encounter(acc_visit_id, acc_invoice_id, acc_patient_id, person_id, doctor_staff_id, decision, "
        "note, chronic_tags, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (f["visit_id"], f["invoice_id"], f["patient_id"], f["person_id"], f["doctor_staff_id"], f["decision"],
         f["note"], f["chronic_tags"], f["at"], f["at"]))
    return int(cur.lastrowid)


def update_encounter(conn: sqlite3.Connection, encounter_id: int, **f: Any) -> None:
    conn.execute("UPDATE encounter SET person_id = ?, decision = ?, note = ?, chronic_tags = ?, updated_at = ? "
                 "WHERE id = ?", (f["person_id"], f["decision"], f["note"], f["chronic_tags"], f["at"], encounter_id))


def encounters_pending_tags(conn: sqlite3.Connection, person_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM encounter WHERE person_id = ? AND chronic_tags IS NOT NULL ORDER BY id",
                        (person_id,)).fetchall()


def insert_measurement(conn: sqlite3.Connection, **f: Any) -> int:
    cur = conn.execute(
        "INSERT INTO measurement(person_id, source, encounter_id, walkin_entry_id, kind, systolic, diastolic, glucose, "
        "glucose_type, on_medication, approx_renewal_date, measured_at, recorded_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f.get("person_id"), f["source"], f.get("encounter_id"), f.get("walkin_entry_id"), f["kind"],
         f.get("systolic"), f.get("diastolic"), f.get("glucose"), f.get("glucose_type"), f.get("on_medication"),
         f.get("approx_renewal_date"), f["at"], f["by"]))
    return int(cur.lastrowid)


def delete_measurements_of_encounter(conn: sqlite3.Connection, encounter_id: int) -> None:
    conn.execute("DELETE FROM measurement WHERE encounter_id = ?", (encounter_id,))


def measurements_of_encounter(conn: sqlite3.Connection, encounter_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM measurement WHERE encounter_id = ? ORDER BY id", (encounter_id,)).fetchall()


# ------------------------------------------------------------------ chronic tags
def chronic_tags(conn: sqlite3.Connection, person_id: int) -> dict[str, str]:
    return dict(conn.execute("SELECT tag, status FROM chronic_tag WHERE person_id = ?", (person_id,)).fetchall())


def set_chronic_tag(conn: sqlite3.Connection, person_id: int, tag: str, active: bool, staff_id: int,
                    at: str) -> None:
    conn.execute(
        "INSERT INTO chronic_tag(person_id, tag, status, set_by_staff_id, set_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(person_id, tag) DO UPDATE SET status = excluded.status, set_by_staff_id = excluded.set_by_staff_id, "
        "set_at = excluded.set_at", (person_id, tag, "active" if active else "removed", staff_id, at))


# ------------------------------------------------------------------ visit context (mirror)
def visit_context(conn: sqlite3.Connection, visit_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT v.item_id AS visit_id, v.acc_invoice_id AS invoice_id, v.acc_patient_id AS patient_id, "
        "v.doctor_staff_id, v.work_date, v.shift, v.deleted_at, i.status AS invoice_status, "
        "a.name, a.family_name, a.national_id, a.phone, a.identity_ok, "
        "l.person_id, p.first_name, p.last_name, p.national_id AS person_nid, p.mobile AS person_mobile, "
        "(SELECT group_concat(DISTINCT c.category) FROM acc_item o JOIN acc_item_category c "
        "   ON c.item_type = o.item_type AND c.item_id = o.item_id "
        " WHERE o.acc_invoice_id = v.acc_invoice_id AND o.deleted_at IS NULL AND o.item_type <> 'visit') AS categories "
        "FROM acc_item v JOIN acc_invoice i ON i.acc_id = v.acc_invoice_id "
        "LEFT JOIN acc_patient a ON a.acc_id = v.acc_patient_id "
        "LEFT JOIN person_acc_link l ON l.acc_patient_id = v.acc_patient_id "
        "LEFT JOIN person p ON p.id = l.person_id "
        "WHERE v.item_type = 'visit' AND v.item_id = ?", (visit_id,)).fetchone()


# ------------------------------------------------------------------ walk-ins (nurse paper)
def walkin_candidates(conn: sqlite3.Connection, since: str) -> list[sqlite3.Row]:
    """Invoices with a BS/BP service, no visit and no walk-in entry yet (docs/06 §5)."""
    return conn.execute(
        "SELECT i.acc_id AS invoice_id, i.acc_patient_id AS patient_id, i.work_date, i.shift, "
        "a.name, a.family_name, a.national_id, a.identity_ok, l.person_id, p.first_name, p.last_name, "
        "(SELECT group_concat(DISTINCT c.category) FROM acc_item o JOIN acc_item_category c "
        "   ON c.item_type = o.item_type AND c.item_id = o.item_id "
        " WHERE o.acc_invoice_id = i.acc_id AND o.deleted_at IS NULL AND c.category IN ('bs_test', 'bp_check')) "
        "  AS categories, "
        "(SELECT min(o.nurse_staff_id) FROM acc_item o JOIN acc_item_category c "
        "   ON c.item_type = o.item_type AND c.item_id = o.item_id "
        " WHERE o.acc_invoice_id = i.acc_id AND o.deleted_at IS NULL AND c.category IN ('bs_test', 'bp_check')) "
        "  AS nurse_staff_id "
        "FROM acc_invoice i LEFT JOIN acc_patient a ON a.acc_id = i.acc_patient_id "
        "LEFT JOIN person_acc_link l ON l.acc_patient_id = i.acc_patient_id "
        "LEFT JOIN person p ON p.id = l.person_id "
        "WHERE i.work_date >= ? AND i.status <> 'missing' "
        "  AND NOT EXISTS (SELECT 1 FROM walkin_entry w WHERE w.acc_invoice_id = i.acc_id) "
        "  AND NOT EXISTS (SELECT 1 FROM acc_item o WHERE o.acc_invoice_id = i.acc_id AND o.item_type = 'visit' "
        "                  AND o.deleted_at IS NULL) "
        "  AND EXISTS (SELECT 1 FROM acc_item o JOIN acc_item_category c ON c.item_type = o.item_type "
        "              AND c.item_id = o.item_id WHERE o.acc_invoice_id = i.acc_id AND o.deleted_at IS NULL "
        "              AND c.category IN ('bs_test', 'bp_check')) "
        "ORDER BY i.work_date DESC, i.opened_at DESC, i.acc_id DESC", (since,)).fetchall()


def walkin_candidate(conn: sqlite3.Connection, invoice_id: int, since: str) -> sqlite3.Row | None:
    return next((r for r in walkin_candidates(conn, since) if r["invoice_id"] == invoice_id), None)


def insert_walkin(conn: sqlite3.Connection, **f: Any) -> int:
    cur = conn.execute(
        "INSERT INTO walkin_entry(acc_invoice_id, acc_patient_id, person_id, nurse_staff_id, status, "
        "cutoff_ruleset_id, entered_by, entered_at) VALUES (?,?,?,?,?,?,?,?)",
        (f["invoice_id"], f["patient_id"], f["person_id"], f["nurse_staff_id"], f["status"], f["ruleset_id"],
         f["by"], f["at"]))
    return int(cur.lastrowid)


def set_person_device(conn: sqlite3.Connection, person_id: int, has_device: bool, by: str, at: str) -> None:
    conn.execute("UPDATE person SET has_personal_device = ?, updated_by = ?, updated_at = ? WHERE id = ?",
                 (int(has_device), by, at, person_id))


# ------------------------------------------------------------------ cut-offs
def cutoff_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM cutoff_ruleset ORDER BY version DESC").fetchall()


def approved_cutoff(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM cutoff_ruleset WHERE status = 'approved'").fetchone()


def draft_cutoff(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM cutoff_ruleset WHERE status = 'draft' ORDER BY version DESC LIMIT 1").fetchone()


def save_cutoff_draft(conn: sqlite3.Connection, rules: dict, by: str, at: str) -> int:
    draft = draft_cutoff(conn)
    text = json.dumps(rules, ensure_ascii=False, sort_keys=True)
    if draft is not None:
        conn.execute("UPDATE cutoff_ruleset SET rules = ?, drafted_by = ?, drafted_at = ? WHERE id = ?",
                     (text, by, at, draft["id"]))
        return int(draft["id"])
    version = int(conn.execute("SELECT coalesce(max(version), 0) + 1 FROM cutoff_ruleset").fetchone()[0])
    cur = conn.execute("INSERT INTO cutoff_ruleset(version, rules, status, drafted_by, drafted_at) "
                       "VALUES (?, ?, 'draft', ?, ?)", (version, text, by, at))
    return int(cur.lastrowid)


def approve_cutoff(conn: sqlite3.Connection, ruleset_id: int, staff_id: int, at: str) -> None:
    conn.execute("UPDATE cutoff_ruleset SET status = 'retired' WHERE status = 'approved'")
    conn.execute("UPDATE cutoff_ruleset SET status = 'approved', approved_by_staff_id = ?, approved_at = ? "
                 "WHERE id = ?", (staff_id, at, ruleset_id))


def ids(rows: Iterable[sqlite3.Row], key: str = "id") -> list[int]:
    return [r[key] for r in rows]
