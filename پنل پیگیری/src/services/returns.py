"""Return detection and evidence revocation (docs/05 §4 M1–M9, ADR-0006).

Design: idempotent reconciliation. Poll events only tell *which* invoices
changed; for each one the current mirror state is compared with the active
evidence and brought in line:

* evidence whose item is no longer valid (deleted, payment removed) is revoked (M7);
* valid, still unused items are matched to the best pending expect step (M2–M5),
  which completes the step, skips earlier pending calls (M6), may finish the
  journey (G8) and start its continuation (A1).

Replaying the same events any number of times yields the same result.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta

from ..adapters.sqlite import account_repo, followup_repo as repo, journey_repo, state_repo
from ..adapters.sqlite.core import savepoint
from ..common.iran_time import TS_FORMAT
from ..domain import journey_rules as rules
from ..domain import returns as domain
from ..domain.events import DomainEvent, PatientChanged
from ..domain.identity import clean_mobile, is_valid_mobile
from . import journeys

log = logging.getLogger(__name__)

PATIENT_LOOKBACK_DAYS = 120          # mirror retention (docs/04 §7)
SUGGESTION_DAYS = 7                  # M9: ±7 days around the expected date


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _item(row: sqlite3.Row) -> domain.Item:
    return domain.Item(row["item_type"], row["item_id"], row["acc_invoice_id"], _d(row["work_date"]),
                       frozenset(c for c in (row["categories"] or "").split(",") if c),
                       bool(row["is_paid"]), row["deleted_at"] is not None,
                       row["invoice_status"] == "closed", row["total_amount"])


def _performer(row: sqlite3.Row) -> int | None:
    if row["item_type"] == "visit":
        return row["doctor_staff_id"]
    if row["item_type"] == "procedure" and row["performer_type"] == "doctor":
        return row["doctor_staff_id"]
    return row["nurse_staff_id"] or row["doctor_staff_id"]


# ------------------------------------------------------------------ revocation (M7)
def revoke(conn: sqlite3.Connection, evidence: sqlite3.Row, reason: str, actor: str, at: str, today: date) -> None:
    repo.revoke_evidence(conn, evidence["id"], reason, at)
    step = repo.step(conn, evidence["step_id"])
    j = journey_repo.journey(conn, evidence["journey_id"])
    window_open = step["window_end"] is not None and date.fromisoformat(step["window_end"]) >= today
    journey_repo.set_step_status(conn, step["id"], "pending" if window_open else "missed", at)
    account_repo.audit(conn, at, actor, "evidence.revoke", "return_evidence", evidence["id"],
                       after={"reason": reason, "step_id": step["id"], "journey_id": j["id"]})
    if j["status"] in ("succeeded", "partial"):
        # The continuation started by this success goes first (one open journey per template).
        for cont in repo.continuations_of(conn, j["id"]):
            if cont["status"] in journey_repo.OPEN_STATUSES and not repo.journey_has_activity(conn, cont["id"]):
                journeys.cancel(conn, cont["id"], "manual", actor, at)
        # Undo the closure: sessions skipped by it come back if their window is still open.
        for s in journey_repo.steps(conn, j["id"]):
            if s["kind"] == "expect" and s["status"] == "skipped" and s["window_end"] >= today.isoformat():
                journey_repo.set_step_status(conn, s["id"], "pending", at)
        journey_repo.set_journey_status(conn, j["id"], "active", None, at)
        account_repo.audit(conn, at, actor, "journey.reopened", "journey", j["id"], {"status": j["status"]},
                           {"status": "active", "reason": "evidence_revoked"})
    journeys.tick_journey(conn, j["id"], today, at)


# ------------------------------------------------------------------ matching (M1–M6)
def _record(conn: sqlite3.Connection, row: sqlite3.Row, step: domain.OpenStep, category: str, basis: str,
            matched_by: str, actor: str, at: str) -> int:
    origin_doctor = journey_repo.journey(conn, step.journey_id)["origin_doctor_staff_id"]
    eid = repo.insert_evidence(conn, journey_id=step.journey_id, step_id=step.step_id, invoice_id=row["acc_invoice_id"],
                               item_type=row["item_type"], item_id=row["item_id"], category=category,
                               performer=_performer(row), origin_doctor=origin_doctor, amount=row["price"],
                               basis=basis, matched_by=matched_by, at=at)
    journey_repo.set_step_status(conn, step.step_id, "done", at)
    account_repo.audit(conn, at, actor, "evidence.match", "return_evidence", eid,
                       after={"journey_id": step.journey_id, "step_id": step.step_id, "item": [row["item_type"],
                              row["item_id"]], "basis": basis})
    steps = journeys._load_steps(conn, step.journey_id)
    ch = rules.Changes()
    for sid in rules.calls_to_skip_after_return(steps):          # M6
        ch.step_status[sid] = "skipped"
    rules.evaluate_completion(steps, ch)
    j = journey_repo.journey(conn, step.journey_id)
    journeys._apply(conn, j, ch, actor, at)
    if ch.journey_status == "succeeded":
        journeys.continue_after_success(conn, step.journey_id, row["work_date"], _performer(row), at)
    return eid


def reconcile_invoice(conn: sqlite3.Connection, invoice_id: int, now: datetime, actor: str = journeys.ENGINE,
                      matched_by: str = "auto") -> int:
    """Bring evidence of one invoice in line with the mirror. Returns the number of changes."""
    at, today = now.strftime(TS_FORMAT), now.date()
    inv = repo.invoice_row(conn, invoice_id)
    if inv is None:
        return 0
    changes = journeys.flag_deleted_origin(conn, invoice_id, actor, at)         # G12
    rows = repo.invoice_items(conn, invoice_id)
    by_key = {(r["item_type"], r["item_id"]): r for r in rows}
    evidenced = set()
    for ev in repo.active_evidence_of_invoice(conn, invoice_id):
        row = by_key.get((ev["acc_item_type"], ev["acc_item_id"]))
        if row is None or domain.basis(_item(row)) is None:
            reason = "item_deleted" if row is None or row["deleted_at"] else "payment_removed"
            revoke(conn, ev, reason, actor, at, today)
            changes += 1
        else:
            evidenced.add((ev["acc_item_type"], ev["acc_item_id"]))

    person_id = repo.person_of_patient(conn, inv["acc_patient_id"])
    if person_id is None:
        _suggest(conn, inv, rows, at)
        return changes
    steps = [domain.OpenStep(r["step_id"], r["journey_id"], r["category"], _d(r["due_date"]), _d(r["window_end"]),
                             bool(r["accept_early"]), _d(r["start_date"]), r["origin_acc_invoice_id"])
             for r in repo.open_expect_steps(conn, person_id)]
    taken: set[int] = set()
    for row in rows:
        if (row["item_type"], row["item_id"]) in evidenced:
            continue
        item = _item(row)
        b = domain.basis(item)
        if b is None:
            continue
        choice = domain.choose(item, steps, taken)
        if choice is None:
            continue
        step, category = choice
        taken.add(step.step_id)
        _record(conn, row, step, category, b, matched_by, actor, at)
        changes += 1
        # the journey may have closed or gained steps; refresh candidates
        steps = [s for s in (domain.OpenStep(r["step_id"], r["journey_id"], r["category"], _d(r["due_date"]),
                                             _d(r["window_end"]), bool(r["accept_early"]), _d(r["start_date"]),
                                             r["origin_acc_invoice_id"])
                             for r in repo.open_expect_steps(conn, person_id))]
    return changes


def reconcile_patient(conn: sqlite3.Connection, patient_id: int, now: datetime,
                      actor: str = journeys.ENGINE, matched_by: str = "auto") -> int:
    since = (now.date() - timedelta(days=PATIENT_LOOKBACK_DAYS)).isoformat()
    return sum(reconcile_invoice(conn, iid, now, actor, matched_by)
               for iid in repo.invoices_of_patient(conn, patient_id, since))


# ------------------------------------------------------------------ M9 suggestions
def _suggest(conn: sqlite3.Connection, inv: sqlite3.Row, rows: list[sqlite3.Row], at: str) -> None:
    """Anonymous invoice: suggest a person only on an exact mobile match with someone expected ±7 days."""
    if not any(r["categories"] and r["deleted_at"] is None for r in rows) or not inv["work_date"]:
        return
    mobile = clean_mobile(repo.patient_phone(conn, inv["acc_patient_id"]))
    if not is_valid_mobile(mobile):
        return
    day = date.fromisoformat(inv["work_date"])
    lo, hi = (day - timedelta(days=SUGGESTION_DAYS)).isoformat(), (day + timedelta(days=SUGGESTION_DAYS)).isoformat()
    for person in repo.persons_expected_with_mobile(conn, mobile, lo, hi):
        repo.add_suggestion(conn, inv["acc_id"], person["id"], "mobile+expected", at)


# ------------------------------------------------------------------ poller hook
def on_poll_events(conn: sqlite3.Connection, events: list[DomainEvent], now: datetime) -> None:
    """Runs inside the poll transaction. A failure here never stops the mirror (savepoint + log)."""
    invoices: set[int] = set()
    patients: set[int] = set()
    for ev in events:
        if isinstance(ev, PatientChanged):
            patients.add(ev.acc_patient_id)
        else:
            invoices.add(ev.invoice_id)
    try:
        with savepoint(conn, "returns_sync"):
            for iid in sorted(invoices):
                reconcile_invoice(conn, iid, now)
            for pid in sorted(patients):
                reconcile_patient(conn, pid, now)
    except Exception as exc:
        log.exception("return reconciliation failed; mirror update kept")
        state_repo.sync_set(conn, {"last_engine_error": f"{now:%Y-%m-%d %H:%M:%S} returns: {exc}"[:300]})
