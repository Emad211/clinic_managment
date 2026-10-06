"""Doctor panel (docs/06 §4-2, docs/05 §8, P-*): one save → encounter, tags, measurements, journeys.

Everything commits in one transaction. Re-saving the same visit on the same day
replaces what the first save created (its open journeys are cancelled with
reason 'manual' and recreated), so an edit never leaves stale follow-ups.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from ..adapters.sqlite import account_repo, journey_repo as repo
from ..adapters.sqlite.core import transaction
from ..common.iran_time import TS_FORMAT
from ..common.jalali import jalali_date, jalali_long
from ..common.persian_text import fa_digits
from ..domain.categories import LABELS_FA
from ..domain.identity import mask_national_id
from . import journeys

TAGS = ("diabetes", "hypertension")
RENEWAL_MONTHS = (1, 2, 3)
SUTURE_DAYS = (5, 7, 10, 14)
DRESSING_EVERY = (0, 1, 2, 3)            # 0 = «ندارد»
SERIES_COUNT, SERIES_EVERY = (1, 10), (1, 7)


class EncounterError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _context(conn: sqlite3.Connection, visit_id: int, staff_id: int) -> sqlite3.Row:
    ctx = repo.visit_context(conn, visit_id)
    if ctx is None or ctx["deleted_at"]:
        raise EncounterError("این ویزیت در حسابداری وجود ندارد یا حذف شده است", 404)
    if ctx["doctor_staff_id"] != staff_id:
        raise EncounterError("این ویزیت به نام پزشک دیگری ثبت شده است", 403)
    return ctx


def panel(conn: sqlite3.Connection, visit_id: int, staff_id: int, today: str) -> dict[str, Any]:
    """Everything the doctor panel shows for one visit."""
    ctx = _context(conn, visit_id, staff_id)
    enc = repo.encounter_by_visit(conn, visit_id)
    person_id = ctx["person_id"]
    tags = repo.chronic_tags(conn, person_id) if person_id else {}
    pending_tags = json.loads(enc["chronic_tags"]) if enc and enc["chronic_tags"] else {}
    open_journeys = []
    if person_id:
        for j in repo.open_journeys_of_person(conn, person_id):
            if enc is not None and j["origin_kind"] == "encounter" and j["origin_id"] == enc["id"]:
                continue                           # this visit's own choices are shown in the form
            open_journeys.append({"id": j["id"], "title": j["title"], "next_due": j["next_due"],
                                  "next_due_fa": jalali_date(j["next_due"]),
                                  "own": j["origin_doctor_staff_id"] == staff_id})
    categories = sorted(set((ctx["categories"] or "").split(",")) - {""})
    name = " ".join(x for x in ((ctx["first_name"] or ctx["name"]), (ctx["last_name"] or ctx["family_name"])) if x)
    return {
        "visit_id": visit_id, "invoice_id": ctx["invoice_id"], "work_date": ctx["work_date"],
        "work_date_long": jalali_long(ctx["work_date"]),
        "name": name or f"پرونده {ctx['patient_id']}",
        "identity_ok": bool(person_id) or bool(ctx["identity_ok"]),
        "mobile": ctx["person_mobile"] or ctx["phone"] or "",
        "national_id_masked": mask_national_id(ctx["person_nid"] or ctx["national_id"]),
        "tags": {t: (tags.get(t) == "active") or bool(pending_tags.get(t)) for t in TAGS},
        "invoice_services": [LABELS_FA[c] for c in categories if c in LABELS_FA],
        "has_bs_test": "bs_test" in categories, "has_bp_check": "bp_check" in categories,
        "open_journeys": open_journeys,
        "encounter": None if enc is None else {
            "decision": enc["decision"], "note": enc["note"],
            "editable": enc["created_at"][:10] == today,
            "journeys": [j["template_code"] for j in repo.journeys_from_origin(conn, "encounter", enc["id"])
                         if j["status"] in repo.OPEN_STATUSES]},
    }


# ------------------------------------------------------------------ validation
def _int_in(value: Any, lo: int, hi: int, message: str) -> int:
    if type(value) is not int or not lo <= value <= hi:
        raise EncounterError(message)
    return value


def plan_from_form(form: dict[str, Any]) -> tuple[list[tuple[str, dict]], dict[str, bool], list[dict]]:
    """→ (journeys as (template, params), chronic tags, measurements). Raises EncounterError."""
    if not isinstance(form, dict):
        raise EncounterError("فرم نامعتبر است")
    tags_in = form.get("tags") or {}
    tags = {t: bool(tags_in.get(t)) for t in TAGS}
    out: list[tuple[str, dict]] = []

    months = form.get("renewal_months")
    if months is not None:
        months = _int_in(months, 1, 3, "بازهٔ تمدید باید ۱، ۲ یا ۳ ماه باشد")
        out.append(("renewal", {"interval_months": months, "due_day": 30 * months}))
    if form.get("quarterly_lab"):
        if not tags["diabetes"]:
            raise EncounterError("آزمایش دوره‌ای دیابت فقط وقتی ثبت می‌شود که «دیابت» انتخاب شده باشد")
        out.append(("quarterly_lab", {}))
    for key, code in (("series_bs", "control_series_bs"), ("series_bp", "control_series_bp")):
        series = form.get(key)
        if series:
            count = _int_in(series.get("count"), *SERIES_COUNT, "تعداد نوبت سری باید بین ۱ و ۱۰ باشد")
            every = _int_in(series.get("every_days"), *SERIES_EVERY, "فاصلهٔ سری باید بین ۱ و ۷ روز باشد")
            out.append((code, {"count": count, "every_days": every}))
    if form.get("lab_order"):
        out.append(("lab_order", {}))
    wound = form.get("wound")
    if wound:
        suture = wound.get("suture_day")
        if suture is None:
            raise EncounterError("روز کشیدن بخیه را انتخاب کنید")
        suture = _int_in(suture, 2, 30, "روز کشیدن بخیه باید بین ۲ و ۳۰ باشد")
        every = wound.get("dressing_every")
        if every not in DRESSING_EVERY:
            raise EncounterError("فاصلهٔ تعویض پانسمان را انتخاب کنید (یا «ندارد»)")
        out.append(("wound_care", {"suture_day": suture, "dressing_every": every}))
    ear = form.get("ear_wax")
    if ear is not None:
        if ear not in ("rx", "norx"):
            raise EncounterError("برای جرم گوش «تجویز شد» یا «تجویز نشد» را انتخاب کنید")
        out.append(("ear_wax_rx" if ear == "rx" else "ear_wax_norx", {}))

    measurements = []
    bp = form.get("bp")
    if bp:
        s = _int_in(bp.get("systolic"), 50, 300, "فشار سیستولیک باید بین ۵۰ و ۳۰۰ باشد")
        d = _int_in(bp.get("diastolic"), 30, 200, "فشار دیاستولیک باید بین ۳۰ و ۲۰۰ باشد")
        if d >= s:
            raise EncounterError("فشار دیاستولیک باید کمتر از سیستولیک باشد")
        measurements.append({"kind": "bp", "systolic": s, "diastolic": d})
    bs = form.get("bs")
    if bs:
        g = _int_in(bs.get("glucose"), 20, 700, "قند باید بین ۲۰ و ۷۰۰ باشد")
        if bs.get("glucose_type") not in ("fasting", "random"):
            raise EncounterError("ناشتا یا غیرناشتا بودن قند را انتخاب کنید")
        measurements.append({"kind": "bs", "glucose": g, "glucose_type": bs["glucose_type"]})
    return out, tags, measurements


# ------------------------------------------------------------------ save
def save(conn: sqlite3.Connection, visit_id: int, form: dict[str, Any], *, staff_id: int, actor: str,
         now: datetime) -> dict[str, Any]:
    at, today = now.strftime(TS_FORMAT), now.date().isoformat()
    decision = form.get("decision") if isinstance(form, dict) else None
    if decision not in ("followup", "no_followup"):
        raise EncounterError("نوع ثبت نامعتبر است")
    note = (form.get("note") or "").strip() or None
    if note and len(note) > 200:
        raise EncounterError("یادداشت حداکثر ۲۰۰ نویسه است")
    planned, tags, measurements = plan_from_form(form) if decision == "followup" else ([], {}, [])
    if decision == "followup" and not planned:
        raise EncounterError("دست‌کم یک پیگیری انتخاب کنید، یا «بدون پیگیری» را بزنید")

    with transaction(conn):
        ctx = _context(conn, visit_id, staff_id)
        enc = repo.encounter_by_visit(conn, visit_id)
        if enc is not None and enc["created_at"][:10] != today:
            raise EncounterError("پنل این ویزیت فقط تا پایان همان روز قابل ویرایش بود", 409)
        person_id = ctx["person_id"]
        fields = dict(visit_id=visit_id, invoice_id=ctx["invoice_id"], patient_id=ctx["patient_id"],
                      person_id=person_id, doctor_staff_id=staff_id, decision=decision, note=note,
                      chronic_tags=None if person_id or not tags else json.dumps(tags), at=at)
        if enc is None:
            enc_id = repo.insert_encounter(conn, **fields)
        else:
            enc_id = enc["id"]
            for j in repo.journeys_from_origin(conn, "encounter", enc_id):
                journeys.cancel(conn, j["id"], "manual", actor, at)
            repo.delete_measurements_of_encounter(conn, enc_id)
            repo.update_encounter(conn, enc_id, **fields)

        if person_id and decision == "followup":
            for tag, active in tags.items():
                current = repo.chronic_tags(conn, person_id).get(tag)
                if active or current == "active":
                    repo.set_chronic_tag(conn, person_id, tag, active, staff_id, at)
        for m in measurements:
            repo.insert_measurement(conn, person_id=person_id, source="encounter", encounter_id=enc_id,
                                    at=at, by=actor, **m)
        created = [journeys.create(conn, code=code, person_id=person_id, params=params,
                                   origin_kind="encounter", origin_id=enc_id,
                                   origin_invoice_id=ctx["invoice_id"], origin_doctor_staff_id=staff_id,
                                   start_date=ctx["work_date"], actor=actor, at=at)
                   for code, params in planned]
        account_repo.audit(conn, at, actor, "encounter.save" if enc is None else "encounter.edit", "encounter",
                           enc_id, after={"decision": decision, "journeys": [c for c, _ in planned],
                                          "tags": tags, "measurements": measurements})

    if decision == "no_followup":
        message = "برای این ویزیت «بدون پیگیری» ثبت شد"
    else:
        message = f"ثبت شد — {fa_digits(len(created))} پیگیری برای بیمار ساخته شد"
        if person_id is None:
            message += "؛ پس از تکمیل هویت توسط پذیرش فعال می‌شوند"
    return {"encounter_id": enc_id, "journeys": created, "message": message}


def apply_pending_tags(conn: sqlite3.Connection, person_id: int, at: str) -> None:
    """Identity just got completed: chronic tags chosen earlier move onto the person (inside caller's txn)."""
    for enc in repo.encounters_pending_tags(conn, person_id):
        for tag, active in json.loads(enc["chronic_tags"]).items():
            if tag in TAGS and active:
                repo.set_chronic_tag(conn, person_id, tag, True, enc["doctor_staff_id"], at)
        repo.update_encounter(conn, enc["id"], person_id=person_id, decision=enc["decision"], note=enc["note"],
                              chronic_tags=None, at=enc["updated_at"])
