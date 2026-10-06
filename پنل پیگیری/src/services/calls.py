"""Reception calls and the follow-up worklists (docs/06 §5, docs/05 §3 G2–G5, §5-4, §5-7, §10).

Outcomes:
* booked (with date) — call done; the next expect window becomes
  [booked, max(window_end, booked + 1)]; a ``no_show`` call is placed for the
  day after the appointment and is skipped automatically if the patient
  returns (M6) (G3).
* no_answer — retry tomorrow; the 3rd one fails the journey 'unreachable' (G4).
* refused — fails 'refused' (G5), unless the template retries
  (ear_wax_norx: again in 3 days, fails after 3 refusals, A4).
* lab_not_done — lab_order only: again in 3 days, fails after 3 (§5-4).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from ..adapters.sqlite import account_repo, followup_repo as repo, journey_repo, mirror_repo, state_repo
from ..adapters.sqlite.core import transaction
from ..common.iran_time import TS_FORMAT
from ..common.jalali import gregorian_from_jalali, jalali_date, jalali_long
from ..common.persian_text import fa_digits
from ..domain import journey_rules as rules
from ..domain import schedule
from ..domain.categories import LABELS_FA
from ..domain.identity import mask_national_id
from . import identity, journeys

OUTCOMES = ("booked", "no_answer", "refused", "lab_not_done")
FOLLOWUP_DOCTORS_KEY = "followup_doctor_staff_ids"
PURPOSE_LABELS = {
    "renewal_reminder": "یادآوری تمدید نسخه", "quarterly_lab_reminder": "یادآوری آزمایش دوره‌ای دیابت",
    "lab_check": "پیگیری جواب آزمایش", "ear_wash_reminder": "یادآوری شستشوی گوش",
    "ear_invite_visit": "دعوت به ویزیت (جرم گوش)", "invite_visit": "دعوت به ویزیت",
    "respiratory_check": "پیگیری وضعیت تنفس", "missed": "نوبتِ انجام‌نشده", "no_show": "مراجعه نکرد در روز نوبت",
}
SHIFT_FA = {"morning": "صبح", "evening": "عصر", "night": "شب"}


class CallError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ worklists
def _text(conn: sqlite3.Connection, r: sqlite3.Row) -> str:
    template = state_repo.setting_get(conn, journeys.CALL_TEXT_PREFIX + r["purpose"]) or ""
    params = json.loads(r["params"])
    due = ""
    if params.get("due_day"):
        due = jalali_date((date.fromisoformat(r["start_date"]) + timedelta(days=params["due_day"])).isoformat())
    category = LABELS_FA.get(r["about_category"] or "", "")
    return template.replace("{due_date}", due).replace("{category}", category)


def _call_view(conn: sqlite3.Connection, r: sqlite3.Row, today: date) -> dict[str, Any]:
    due = date.fromisoformat(r["due_date"])
    return {
        "step_id": r["step_id"], "journey_id": r["journey_id"], "template": r["template_code"],
        "journey_title": r["title"], "purpose": r["purpose"],
        "reason": PURPOSE_LABELS.get(r["purpose"], r["purpose"]), "text": _text(conn, r),
        "name": f"{r['first_name']} {r['last_name']}", "mobile": r["mobile"],
        "national_id_masked": mask_national_id(r["national_id"]), "doctor": r["doctor_name"] or "",
        "attempts": r["attempts"], "due_date_fa": jalali_date(r["due_date"]), "days_late": (today - due).days,
        "last_note": r["last_note"] or "",
        "outcomes": ["booked", "no_answer", "refused"] + (["lab_not_done"] if r["template_code"] == "lab_order" else []),
    }


def worklists(conn: sqlite3.Connection, now: datetime) -> dict[str, Any]:
    today = now.date()
    t = today.isoformat()
    return {
        "today": [_call_view(conn, r, today) for r in repo.calls_due(conn, t)],
        "overdue": [_call_view(conn, r, today) for r in repo.calls_overdue(conn, t)],
        "expected": [{"step_id": r["step_id"], "journey_id": r["journey_id"], "title": r["title"],
                      "category": LABELS_FA.get(r["category"], r["category"]), "person_id": r["person_id"],
                      "name": f"{r['first_name']} {r['last_name']}", "mobile": r["mobile"],
                      "national_id_masked": mask_national_id(r["national_id"]),
                      "window_end_fa": jalali_date(r["window_end"]), "booked": r["purpose"] == "booked"}
                     for r in repo.expected_on(conn, t)],
        "unlinked_today": [{"invoice_id": r["invoice_id"], "name": " ".join(x for x in (r["name"], r["family_name"]) if x),
                            "phone": r["phone"] or "",
                            "categories": [LABELS_FA[c] for c in sorted(set((r["categories"] or "").split(",")) - {""})
                                           if c in LABELS_FA]}
                           for r in repo.unlinked_invoices_on(conn, t)],
        "suggestions": [{"id": r["id"], "invoice_id": r["acc_invoice_id"], "work_date_fa": jalali_date(r["work_date"]),
                         "invoice_name": " ".join(x for x in (r["name"], r["family_name"]) if x), "phone": r["phone"],
                         "person_name": f"{r['first_name']} {r['last_name']}", "person_mobile": r["mobile"],
                         "national_id_masked": mask_national_id(r["national_id"])}
                        for r in repo.pending_suggestions(conn)],
    }


# ------------------------------------------------------------------ appointment suggestion (§10)
def appointment_slots(conn: sqlite3.Connection, step_id: int, now: datetime) -> list[dict[str, Any]]:
    r = repo.call_row(conn, step_id)
    if r is None:
        raise CallError("این تماس دیگر باز نیست؛ فهرست را تازه کنید", 409)
    today = now.date()
    rows = repo.shift_staff_rows(conn, (today - timedelta(weeks=schedule.WEEKS)).isoformat())
    doctors = [r["origin_doctor_staff_id"], *(state_repo.setting_get(conn, FOLLOWUP_DOCTORS_KEY) or [])]
    names = mirror_repo.staff_names(conn)
    return [{"date": s.day.isoformat(), "date_fa": jalali_date(s.day), "date_long": jalali_long(s.day, year=False), "shift": s.shift,
             "shift_fa": SHIFT_FA[s.shift], "doctor": names.get(s.doctor_id, ""),
             "origin": s.doctor_id == r["origin_doctor_staff_id"]}
            for s in schedule.suggest(rows, doctors, today)][:8]


# ------------------------------------------------------------------ outcomes
def _fail(conn, j, reason: str, actor: str, at: str) -> None:
    ch = rules.close(journeys._load_steps(conn, j["id"]), rules.Changes(), "failed", reason)
    journeys._apply(conn, j, ch, actor, at)


def record(conn: sqlite3.Connection, step_id: int, form: dict[str, Any], *, actor: str, now: datetime) -> dict[str, Any]:
    outcome = form.get("outcome") if isinstance(form, dict) else None
    if outcome not in OUTCOMES:
        raise CallError("نتیجهٔ تماس را انتخاب کنید")
    note = (form.get("note") or "").strip() or None
    if note and len(note) > 200:
        raise CallError("یادداشت حداکثر ۲۰۰ نویسه است")
    at, today = now.strftime(TS_FORMAT), now.date()
    with transaction(conn):
        r = repo.call_row(conn, step_id)
        if r is None:
            raise CallError("این تماس دیگر باز نیست؛ فهرست را تازه کنید", 409)
        if date.fromisoformat(r["due_date"]) > today:
            raise CallError("موعد این تماس هنوز نرسیده است", 409)
        j = journey_repo.journey(conn, r["journey_id"])
        t, _ = journeys.template(conn, j["template_code"], j["template_version"])
        booked = None
        if outcome == "booked":
            try:
                booked = gregorian_from_jalali(str(form.get("booked_date_fa") or ""))
            except ValueError as exc:
                raise CallError(f"تاریخ نوبت: {exc}") from None
            if booked < today.isoformat():
                raise CallError("تاریخ نوبت نمی‌تواند گذشته باشد")
            if booked > (today + timedelta(days=60)).isoformat():
                raise CallError("تاریخ نوبت حداکثر ۶۰ روز بعد است")
        if outcome == "lab_not_done" and "lab_not_done" not in t.call_rules:
            raise CallError("«هنوز آزمایش نداده» فقط برای پیگیری جواب آزمایش است")

        repo.insert_attempt(conn, step_id, outcome, booked, note, actor, at)
        attempts = r["attempts"] + 1
        repo.update_step(conn, step_id, attempts=attempts)
        message = "ثبت شد"

        if outcome == "booked":
            journey_repo.set_step_status(conn, step_id, "done", at)
            _book(conn, j["id"], r["about_category"], booked, at)
            message = f"نوبت {jalali_long(booked)} ثبت شد"
        elif outcome == "no_answer":
            max_attempts = int(t.call_rules.get("max_attempts", 3))
            if attempts >= max_attempts:
                _fail(conn, j, "unreachable", actor, at)
                message = f"{fa_digits(attempts)} تماس بی‌پاسخ ماند؛ پیگیری بسته شد"
            else:
                repo.update_step(conn, step_id, due_date=(today + timedelta(
                    days=int(t.call_rules.get("no_answer_retry_days", 1)))).isoformat())
                message = "تماس بعدی: فردا"
        elif outcome == "refused":
            rule = t.refused_rule()
            refusals = repo.count_outcomes(conn, j["id"], "refused")
            if rule is None or refusals >= int(rule["max"]):
                _fail(conn, j, "refused", actor, at)
                message = "پیگیری بسته شد؛ بیمار مراجعه نمی‌کند"
            else:
                repo.update_step(conn, step_id, due_date=(today + timedelta(days=int(rule["retry_days"]))).isoformat())
                message = f"تماس بعدی: {fa_digits(rule['retry_days'])} روز دیگر"
        else:  # lab_not_done
            rule = t.call_rules["lab_not_done"]
            if repo.count_outcomes(conn, j["id"], "lab_not_done") >= int(rule["max"]):
                _fail(conn, j, "lab_not_done", actor, at)
                message = "پیگیری بسته شد؛ آزمایش انجام نشد"
            else:
                repo.update_step(conn, step_id, due_date=(today + timedelta(days=int(rule["retry_days"]))).isoformat())
                message = f"تماس بعدی: {fa_digits(rule['retry_days'])} روز دیگر"
        account_repo.audit(conn, at, actor, "call.outcome", "journey_step", step_id,
                           after={"outcome": outcome, "booked_date": booked, "attempt": attempts})
    return {"message": message}


def _book(conn: sqlite3.Connection, journey_id: int, about: str | None, booked: str, at: str) -> None:
    """G3: move the next expect window to the appointment and plan the no-show call."""
    pending = [s for s in journey_repo.steps(conn, journey_id) if s["kind"] == "expect" and s["status"] == "pending"]
    if about:
        pending = [s for s in pending if s["category"] == about] or pending
    end_min = (date.fromisoformat(booked) + timedelta(days=1)).isoformat()
    if pending:
        s = pending[0]
        repo.update_step(conn, s["id"], due_date=booked, window_end=max(s["window_end"], end_min), purpose="booked")
    else:
        category = about or next((s["category"] for s in journey_repo.steps(conn, journey_id)
                                  if s["kind"] == "expect"), "visit")
        journey_repo.insert_step(conn, journey_id, seq=journey_repo.next_seq(conn, journey_id), kind="expect",
                                 due_date=booked, window_end=end_min, category=category, purpose="booked")
    journey_repo.insert_step(conn, journey_id, seq=journey_repo.next_seq(conn, journey_id), kind="call",
                             due_date=end_min, window_end=None, category=None, purpose="no_show",
                             about_category=about)


# ------------------------------------------------------------------ M9: manual link & suggestions
def link_invoice(conn: sqlite3.Connection, invoice_id: int, person_id: int, *, actor: str, now: datetime) -> dict:
    """«اتصال به فاکتور امروز»: the invoice's accounting file is linked to an expected person."""
    at = now.strftime(TS_FORMAT)
    with transaction(conn):
        inv = repo.invoice_row(conn, invoice_id)
        if inv is None or inv["status"] == "missing":
            raise CallError("فاکتور در آینه پیدا نشد", 404)
        if repo.person_of_patient(conn, inv["acc_patient_id"]) is not None:
            raise CallError("پروندهٔ این فاکتور قبلاً به شخصی متصل شده است", 409)
        try:
            identity.link_patient(conn, inv["acc_patient_id"], person_id, "manual", actor, at)
        except identity.IdentityError as exc:
            raise CallError(str(exc), 409) from None
    return {"message": "پرونده متصل شد و مراجعه بررسی شد"}


def decide_suggestion(conn: sqlite3.Connection, suggestion_id: int, accept: bool, *, actor: str,
                      now: datetime) -> dict:
    at = now.strftime(TS_FORMAT)
    with transaction(conn):
        s = repo.suggestion_by_id(conn, suggestion_id)
        if s is None or s["status"] != "pending":
            raise CallError("این پیشنهاد دیگر باز نیست", 409)
        inv = repo.invoice_row(conn, s["acc_invoice_id"])
        if accept:
            if repo.person_of_patient(conn, inv["acc_patient_id"]) is not None:
                raise CallError("پروندهٔ این فاکتور قبلاً متصل شده است", 409)
            identity.link_patient(conn, inv["acc_patient_id"], s["person_id"], "suggestion", actor, at)
        repo.decide_suggestion(conn, suggestion_id, "accepted" if accept else "rejected", actor, at)
        account_repo.audit(conn, at, actor, "suggestion." + ("accept" if accept else "reject"),
                           "match_suggestion", suggestion_id)
    return {"message": "اتصال تأیید شد" if accept else "پیشنهاد رد شد"}


def followup_doctors(conn: sqlite3.Connection) -> tuple[list[sqlite3.Row], set[int]]:
    return mirror_repo.active_doctors(conn), set(state_repo.setting_get(conn, FOLLOWUP_DOCTORS_KEY) or [])


def set_followup_doctors(conn: sqlite3.Connection, staff_ids: list[int], *, actor: str, now: datetime) -> None:
    valid = {r["acc_id"] for r in mirror_repo.active_doctors(conn)}
    if any(i not in valid for i in staff_ids):
        raise CallError("فقط پزشکانِ فعال حسابداری قابل انتخاب‌اند")
    at = now.strftime(TS_FORMAT)
    with transaction(conn):
        state_repo.setting_set(conn, FOLLOWUP_DOCTORS_KEY, sorted(set(staff_ids)), actor, at)
        account_repo.audit(conn, at, actor, "setting.followup_doctors", "setting", FOLLOWUP_DOCTORS_KEY,
                           after=sorted(set(staff_ids)))
