"""Nurse paper → panel (docs/06 §5-2, docs/02 §4-3, W-*).

Reception types what the nurse wrote. The panel then decides, from the
cut-offs the director doctor approved, whether to invite the patient or start a
control series (D19). Before any approval the entry is only recorded.
A renewal journey is created whenever the patient takes medication and a
renewal date is given, independent of cut-offs (W-4).
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from ..adapters.sqlite import account_repo, journey_repo as repo
from ..adapters.sqlite.core import transaction
from ..common.iran_time import TS_FORMAT
from ..common.jalali import gregorian_from_jalali, jalali_date
from ..domain import cutoffs as cutoff_rules
from ..domain.identity import mask_national_id
from . import cutoffs, journeys
from .encounters import EncounterError, plan_from_form

ACTION_LABELS = {"invite_visit": "دعوت به ویزیت", "control_series_bp": "سری کنترل فشار",
                 "control_series_bs": "سری کنترل قند", "renewal": "تمدید نسخه"}
QUICK_RENEWAL_DAYS = (10, 20, 30)


class WalkinError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _since(now: datetime) -> str:
    return (now.date() - timedelta(days=1)).isoformat()        # today and yesterday (docs/06 §5)


def worklist(conn: sqlite3.Connection, now: datetime) -> dict[str, Any]:
    rows = []
    for r in repo.walkin_candidates(conn, _since(now)):
        cats = set((r["categories"] or "").split(","))
        name = " ".join(x for x in ((r["first_name"] or r["name"]), (r["last_name"] or r["family_name"])) if x)
        rows.append({"invoice_id": r["invoice_id"], "work_date": r["work_date"],
                     "work_date_fa": jalali_date(r["work_date"]), "name": name,
                     "identity_ok": bool(r["person_id"]) or bool(r["identity_ok"]),
                     "national_id_masked": mask_national_id(r["national_id"]),
                     "bp": "bp_check" in cats, "bs": "bs_test" in cats})
    return {"rows": rows, "cutoff_approved": cutoffs.approved_rules(conn) is not None}


def _renewal_date(raw: Any, start: str) -> str | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, int) and raw in QUICK_RENEWAL_DAYS:
        return (date.fromisoformat(start) + timedelta(days=raw)).isoformat()
    try:
        return gregorian_from_jalali(str(raw))
    except ValueError as exc:
        raise WalkinError(str(exc)) from None


def save(conn: sqlite3.Connection, invoice_id: int, form: dict[str, Any], *, actor: str,
         now: datetime) -> dict[str, Any]:
    if not isinstance(form, dict) or form.get("status") not in ("entered", "no_paper"):
        raise WalkinError("فرم نامعتبر است")
    at = now.strftime(TS_FORMAT)
    with transaction(conn):
        row = repo.walkin_candidate(conn, invoice_id, _since(now))
        if row is None:
            raise WalkinError("این مراجعه در فهرست کاغذ پرستار نیست؛ فهرست را تازه کنید", 409)
        person_id, start = row["person_id"], row["work_date"]
        cats = set((row["categories"] or "").split(","))
        base = dict(invoice_id=invoice_id, patient_id=row["patient_id"], person_id=person_id,
                    nurse_staff_id=row["nurse_staff_id"], by=actor, at=at)
        if form["status"] == "no_paper":
            wid = repo.insert_walkin(conn, status="no_paper", ruleset_id=None, **base)
            account_repo.audit(conn, at, actor, "walkin.no_paper", "walkin_entry", wid)
            return {"walkin_id": wid, "actions": [], "message": "ثبت شد — کاغذ موجود نیست"}

        try:
            _, _, measurements = plan_from_form({"bp": form.get("bp"), "bs": form.get("bs")})
        except EncounterError as exc:
            raise WalkinError(str(exc)) from None
        kinds = {m["kind"] for m in measurements}
        if not measurements:
            raise WalkinError("دست‌کم یک عدد (فشار یا قند) از کاغذ پرستار وارد کنید")
        if "bp" in kinds and "bp_check" not in cats or "bs" in kinds and "bs_test" not in cats:
            raise WalkinError("عدد واردشده با خدمت ثبت‌شده روی فاکتور جور نیست")
        on_med = form.get("on_medication")
        if on_med not in (True, False, None):
            raise WalkinError("«مصرف دارو» باید بله یا خیر باشد")
        renewal = _renewal_date(form.get("renewal"), start) if on_med else None
        if renewal is not None and renewal <= start:
            raise WalkinError("تاریخ تمدید باید بعد از روز مراجعه باشد")

        approved = cutoffs.approved_rules(conn)
        wid = repo.insert_walkin(conn, status="entered", ruleset_id=approved[0] if approved else None, **base)
        for m in measurements:
            repo.insert_measurement(conn, person_id=person_id, source="walkin", walkin_entry_id=wid,
                                    on_medication=None if on_med is None else int(on_med),
                                    approx_renewal_date=renewal, at=at, by=actor, **m)
        if person_id is not None and form.get("has_device") in (True, False):
            repo.set_person_device(conn, person_id, form["has_device"], actor, at)

        actions: list[str] = []
        if approved is not None:
            for m in measurements:
                for a in cutoff_rules.evaluate(approved[1], m["kind"], m):
                    if a not in actions:
                        actions.append(a)
        series = approved[1]["series"] if approved else None
        for action in actions:
            params = {"count": series["count"], "every_days": series["every_days"]} \
                if action.startswith("control_series") else {}
            journeys.create(conn, code=action, person_id=person_id, params=params, origin_kind="walkin",
                            origin_id=wid, origin_invoice_id=invoice_id, origin_doctor_staff_id=None,
                            start_date=start, actor=actor, at=at)
        if renewal is not None:
            due = max(1, journeys.days_between(start, renewal))
            journeys.create(conn, code="renewal", person_id=person_id, params={"due_day": due},
                            origin_kind="walkin", origin_id=wid, origin_invoice_id=invoice_id,
                            origin_doctor_staff_id=None, start_date=start, actor=actor, at=at)
            actions.append("renewal")
        account_repo.audit(conn, at, actor, "walkin.enter", "walkin_entry", wid,
                           after={"measurements": measurements, "actions": actions,
                                  "cutoff_ruleset_id": approved[0] if approved else None})

    if approved is None:
        message = "ثبت شد. کات‌آف هنوز توسط پزشک مدیر تأیید نشده؛ اقدام خودکاری ساخته نشد"
        if "renewal" in actions:
            message += " (فقط تمدید نسخه ساخته شد)"
    elif actions:
        message = "ثبت شد — " + "، ".join(ACTION_LABELS[a] for a in actions) + " ساخته شد"
    else:
        message = "ثبت شد — بدون اقدام"
    if actions and person_id is None:
        message += ". پیگیری‌ها پس از تکمیل هویت فعال می‌شوند"
    return {"walkin_id": wid, "actions": actions, "message": message}
