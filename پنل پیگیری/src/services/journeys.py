"""Journey engine (docs/05, ADR-0005): templates, creation (G9), ticks (G6/G7/G8/G10), cancel (G13), A1.

Every public function runs inside the caller's transaction unless it says
otherwise, so a doctor's panel save, its journeys and its audit rows commit or
fail together.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from ..adapters.sqlite import account_repo, journey_repo as repo, state_repo
from ..adapters.sqlite.core import transaction
from ..common.iran_time import TS_FORMAT
from ..common.jalali import jalali_date
from ..config.settings import resource_dir
from ..domain import journey_rules as rules
from ..domain.templates import Template, TemplateError, parse_template, plan

log = logging.getLogger(__name__)

ENGINE = "system:engine"
CALL_TEXT_PREFIX = "call_text."
FORBIDDEN_IN_EAR_INVITE = ("قطره", "گلیسیرین", "فنیکه", "دارو")     # D18: no drug talk on that call


class JourneyError(ValueError):
    pass


def journeys_dir() -> Path:
    return resource_dir() / "journeys"


# ------------------------------------------------------------------ templates
def ensure_templates(conn: sqlite3.Connection, at: str, directory: Path | None = None) -> int:
    """First run: load journeys/*.json as version 1 of every missing template, plus default call texts."""
    directory = directory or journeys_dir()
    existing = repo.template_codes(conn)
    added = 0
    with transaction(conn):
        for path in sorted(directory.glob("*.json")):
            if path.stem == "call_texts":
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            t = parse_template(data)                       # refuse to seed a broken template
            if t.code not in existing:
                repo.insert_template(conn, t.code, 1, t.title, data, t.enabled, "system:seed", at)
                added += 1
        texts_path = directory / "call_texts.json"
        if texts_path.exists():
            for purpose, text in json.loads(texts_path.read_text(encoding="utf-8")).items():
                if state_repo.setting_get(conn, CALL_TEXT_PREFIX + purpose) is None:
                    state_repo.setting_set(conn, CALL_TEXT_PREFIX + purpose, text, "system:seed", at)
    if added:
        log.info("seeded %d journey templates", added)
    return added


def validate_call_text(purpose: str, text: str) -> None:
    if purpose == "ear_invite_visit" and any(w in text for w in FORBIDDEN_IN_EAR_INVITE):
        raise JourneyError("متن دعوت جرم گوش نباید نام دارو داشته باشد (D18)")


def template(conn: sqlite3.Connection, code: str, version: int | None = None) -> tuple[Template, int]:
    if version is None:
        row = next((r for r in repo.current_templates(conn) if r["code"] == code), None)
    else:
        row = repo.template_version(conn, code, version)
    if row is None:
        raise JourneyError(f"الگوی {code} تعریف نشده است")
    return parse_template(json.loads(row["definition"])), int(row["version"])


# ------------------------------------------------------------------ creation
def _audit(conn, at, actor, action, journey_id, before=None, after=None):
    account_repo.audit(conn, at, actor, action, "journey", journey_id, before, after)


def cancel(conn: sqlite3.Connection, journey_id: int, reason: str, actor: str, at: str) -> None:
    j = repo.journey(conn, journey_id)
    if j is None or j["status"] not in repo.OPEN_STATUSES:
        return
    ch = rules.close(_load_steps(conn, journey_id), rules.Changes(), "cancelled", reason)
    _apply(conn, j, ch, actor, at)


def create(conn: sqlite3.Connection, *, code: str, person_id: int | None, params: dict[str, Any],
           origin_kind: str, origin_id: int | None, origin_invoice_id: int | None,
           origin_doctor_staff_id: int | None, start_date: str, actor: str, at: str) -> int:
    """Plan and store a journey. G9: an open journey of the same template for the person is replaced."""
    t, version = template(conn, code)
    if not t.enabled:
        raise JourneyError(f"الگوی «{t.title}» غیرفعال است")
    try:
        planned = plan(t, params, date.fromisoformat(start_date))
    except TemplateError as exc:
        raise JourneyError(f"پارامترهای «{t.title}» کامل نیست: {exc}") from exc
    if person_id is not None:
        old = repo.open_journey(conn, person_id, code)
        if old is not None:
            cancel(conn, old["id"], "duplicate", actor, at)
    status = "active" if person_id is not None else "awaiting_identity"
    jid = repo.insert_journey(conn, person_id=person_id, code=code, version=version, params=params,
                              origin_kind=origin_kind, origin_id=origin_id, origin_invoice_id=origin_invoice_id,
                              origin_doctor_staff_id=origin_doctor_staff_id, start_date=start_date,
                              status=status, by=actor, at=at)
    for p in planned:
        repo.insert_step(conn, jid, seq=p.seq, kind=p.kind, due_date=p.due_date.isoformat(),
                         window_end=p.window_end.isoformat() if p.window_end else None, category=p.category,
                         purpose=p.purpose, accept_early=p.accept_early, recall_on_miss=p.recall_on_miss,
                         completes=p.completes)
    _audit(conn, at, actor, "journey.create", jid,
           after={"template": code, "version": version, "params": params, "status": status,
                  "person_id": person_id, "start_date": start_date})
    return jid


def activate_with_identity(conn: sqlite3.Connection, journey_id: int, person_id: int, actor: str, at: str) -> str:
    """An awaiting_identity journey gets its person (G10). Due dates stay; G9 keeps the newer journey."""
    j = repo.journey(conn, journey_id)
    if j is None or j["status"] != "awaiting_identity":
        return "skipped"
    other = repo.open_journey(conn, person_id, j["template_code"])
    if other is not None and other["id"] != journey_id:
        newer_is_other = (other["created_at"], other["id"]) > (j["created_at"], j["id"])
        if newer_is_other:
            repo.set_journey_person(conn, journey_id, person_id)
            cancel(conn, journey_id, "duplicate", actor, at)
            return "cancelled"
        cancel(conn, other["id"], "duplicate", actor, at)
    repo.set_journey_person(conn, journey_id, person_id)
    repo.set_journey_status(conn, journey_id, "active", None, at)
    _audit(conn, at, actor, "journey.identity_ready", journey_id, {"status": "awaiting_identity"},
           {"status": "active", "person_id": person_id})
    return "active"


# ------------------------------------------------------------------ ticks
def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _load_steps(conn: sqlite3.Connection, journey_id: int) -> list[rules.Step]:
    return [rules.Step(r["id"], r["seq"], r["kind"], _d(r["due_date"]), _d(r["window_end"]), r["category"],
                       r["purpose"], r["status"], r["attempts"], bool(r["accept_early"]),
                       bool(r["recall_on_miss"]), bool(r["completes"]))
            for r in repo.steps(conn, journey_id)]


def _apply(conn: sqlite3.Connection, j: sqlite3.Row, ch: rules.Changes, actor: str, at: str) -> None:
    for step_id, status in ch.step_status.items():
        repo.set_step_status(conn, step_id, status, at)
    for call in ch.new_calls:
        repo.insert_step(conn, j["id"], seq=repo.next_seq(conn, j["id"]), kind="call",
                         due_date=call.due_date.isoformat(), window_end=None, category=None,
                         purpose=call.purpose, about_category=call.category)
    if ch.journey_status and ch.journey_status != j["status"]:
        repo.set_journey_status(conn, j["id"], ch.journey_status, ch.close_reason, at)
        _audit(conn, at, actor, f"journey.{ch.journey_status}", j["id"], {"status": j["status"]},
               {"status": ch.journey_status, "reason": ch.close_reason})


def tick_journey(conn: sqlite3.Connection, journey_id: int, today: date, at: str) -> bool:
    j = repo.journey(conn, journey_id)
    if j is None:
        return False
    snapshot = rules.Journey(j["id"], j["status"], date.fromisoformat(j["start_date"]),
                             date.fromisoformat(j["created_at"][:10]))
    ch = rules.tick(snapshot, _load_steps(conn, journey_id), today)
    if ch.empty:
        return False
    _apply(conn, j, ch, ENGINE, at)
    return True


def tick_all(conn: sqlite3.Connection, now: datetime) -> int:
    """One engine tick over every open journey, one short transaction per journey."""
    today, at = now.date(), now.strftime(TS_FORMAT)
    changed = 0
    for jid in repo.journeys_to_tick(conn):
        try:
            with transaction(conn):
                changed += tick_journey(conn, jid, today, at)
        except Exception:                        # one bad journey must not stop the others
            log.exception("tick failed for journey %s", jid)
    return changed


# ------------------------------------------------------------------ continuation (A1)
def continue_after_success(conn: sqlite3.Connection, journey_id: int, return_date: str,
                           performer_staff_id: int | None, at: str) -> int | None:
    """renewal / quarterly_lab: start the next round from the return date, same parameters."""
    j = repo.journey(conn, journey_id)
    if j is None or j["status"] != "succeeded" or j["person_id"] is None:
        return None
    t, _ = template(conn, j["template_code"], j["template_version"])
    if not t.continue_on_success:
        return None
    if repo.open_journey(conn, j["person_id"], j["template_code"]) is not None:
        return None                              # the doctor already chose again in that visit (G9)
    if j["template_code"] == "quarterly_lab":
        tags = repo.chronic_tags(conn, j["person_id"])
        if tags.get("diabetes") != "active":
            return None                          # tag removed → continuation stops
    return create(conn, code=j["template_code"], person_id=j["person_id"], params=json.loads(j["params"]),
                  origin_kind="continuation", origin_id=journey_id, origin_invoice_id=None,
                  origin_doctor_staff_id=performer_staff_id, start_date=return_date, actor=ENGINE, at=at)


def days_between(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def add_days(day: str, n: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def cancel_by_user(conn: sqlite3.Connection, journey_id: int, *, role: str, staff_id: int | None, actor: str,
                   now: datetime) -> None:
    """G13: a doctor cancels only journeys they originated; the manager cancels any."""
    at = now.strftime(TS_FORMAT)
    with transaction(conn):
        j = repo.journey(conn, journey_id)
        if j is None or j["status"] not in repo.OPEN_STATUSES:
            raise JourneyError("این پیگیری دیگر باز نیست؛ صفحه را دوباره باز کنید")
        if role != "manager" and not (role == "doctor" and j["origin_doctor_staff_id"] == staff_id):
            raise JourneyError("فقط پزشکی که این پیگیری را ثبت کرده یا مدیر می‌تواند آن را لغو کند")
        cancel(conn, journey_id, "manual", actor, at)


# ------------------------------------------------------------------ G12: origin visit deleted
REVIEWABLE = ("active", "awaiting_identity")


def flag_deleted_origin(conn: sqlite3.Connection, invoice_id: int, actor: str, at: str) -> int:
    """Accounting deleted the visit a panel was saved for: its open journeys wait for a doctor's decision.

    Runs once per panel (encounter.status ok → source_deleted), so a later «ادامه» is never undone.
    """
    flagged = 0
    for enc in repo.encounters_with_deleted_visit(conn, invoice_id):
        repo.set_encounter_status(conn, enc["id"], "source_deleted")
        account_repo.audit(conn, at, actor, "encounter.source_deleted", "encounter", enc["id"],
                           after={"visit_id": enc["acc_visit_id"], "invoice_id": invoice_id})
        for j in repo.journeys_from_origin(conn, "encounter", enc["id"]):
            if j["status"] in REVIEWABLE:
                repo.set_journey_status(conn, j["id"], "needs_review", None, at)
                _audit(conn, at, actor, "journey.needs_review", j["id"], {"status": j["status"]},
                       {"status": "needs_review", "reason": "origin_visit_deleted"})
                flagged += 1
    return flagged


def can_review(j: sqlite3.Row, *, role: str, staff_id: int | None, is_director: bool) -> bool:
    """docs/06 §1: the originating doctor, the director doctor, or the manager."""
    return role == "manager" or (role == "doctor" and (is_director or j["origin_doctor_staff_id"] == staff_id))


def review(conn: sqlite3.Connection, journey_id: int, keep: bool, *, role: str, staff_id: int | None,
           is_director: bool, actor: str, now: datetime) -> str:
    """«ادامه»: back to active (or awaiting_identity); «لغو»: cancelled 'manual' (docs/05 §2)."""
    at = now.strftime(TS_FORMAT)
    with transaction(conn):
        j = repo.journey(conn, journey_id)
        if j is None or j["status"] != "needs_review":
            raise JourneyError("این پیگیری دیگر نیازمند بررسی نیست؛ صفحه را دوباره باز کنید")
        if not can_review(j, role=role, staff_id=staff_id, is_director=is_director):
            raise JourneyError("فقط پزشکی که این پیگیری را ثبت کرده، پزشک مدیر یا مدیر می‌تواند درباره‌اش تصمیم بگیرد")
        if not keep:
            cancel(conn, journey_id, "manual", actor, at)
            return "پیگیری لغو شد"
        status = "active" if j["person_id"] is not None else "awaiting_identity"
        repo.set_journey_status(conn, journey_id, status, None, at)
        _audit(conn, at, actor, "journey.review_keep", journey_id, {"status": "needs_review"}, {"status": status})
        if status == "active":
            tick_journey(conn, journey_id, now.date(), at)        # catch up on whatever came due meanwhile
    return "پیگیری ادامه پیدا می‌کند"


def review_rows(conn: sqlite3.Connection, origin_doctor_staff_id: int | None, *,
                viewer_staff_id: int | None) -> list[dict[str, Any]]:
    return [{"id": r["id"], "title": r["title"], "start_date_fa": jalali_date(r["start_date"]),
             "name": " ".join(x for x in (r["first_name"], r["last_name"]) if x) or r["file_name"] or "بدون نام",
             "doctor": r["doctor_name"] or "", "invoice_id": r["origin_acc_invoice_id"],
             "own": r["origin_doctor_staff_id"] == viewer_staff_id}
            for r in repo.journeys_needing_review(conn, origin_doctor_staff_id)]
