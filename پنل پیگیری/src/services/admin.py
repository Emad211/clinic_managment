"""Manager tools (docs/06 §6, docs/08 M5): report, audit log, procedure-name mapping, call texts, maintenance."""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from ..adapters.sqlite import account_repo, admin_repo, core, mirror_repo, state_repo
from ..adapters.sqlite.core import transaction
from ..common.iran_time import TS_FORMAT
from ..common.jalali import gregorian_from_jalali, jalali_datetime
from ..common.persian_text import normalize
from ..domain import categories as cat
from . import journeys
from .calls import PURPOSE_LABELS
from .sync_status import status as sync_status

log = logging.getLogger(__name__)

STATUS_FA = {"awaiting_identity": "منتظر تکمیل هویت", "active": "در جریان", "needs_review": "نیازمند بررسی",
             "succeeded": "موفق", "partial": "نیمه‌کامل", "failed": "ناموفق", "cancelled": "لغوشده"}
OUTCOME_FA = {"booked": "نوبت داده شد", "no_answer": "پاسخ نداد", "refused": "مراجعه نمی‌کند",
              "lab_not_done": "هنوز آزمایش نداده"}
MAPPABLE = (cat.DRESSING, cat.SUTURE_REMOVAL, cat.EAR_IRRIGATION)
BASELINE_RETURN_RATE = 8          # % of visits followed by a return without the panel (docs/07)
MIRROR_RETENTION_DAYS = 120
BACKUP_EVERY_DAYS = 7


class AdminError(ValueError):
    pass


def parse_range(text: str) -> tuple[str, str]:
    """'۱۴۰۵/۰۷/۰۱ - ۱۴۰۵/۰۷/۱۴' (or a single date) → Gregorian (start, end)."""
    parts = [p.strip() for p in str(text or "").split(" - ") if p.strip()]
    if not parts:
        raise AdminError("بازهٔ تاریخ را از تقویم انتخاب کنید")
    try:
        start, end = gregorian_from_jalali(parts[0]), gregorian_from_jalali(parts[-1])
    except ValueError as exc:
        raise AdminError(str(exc)) from None
    if start > end:
        raise AdminError("تاریخ شروع باید پیش از تاریخ پایان باشد")
    return start, end


# ------------------------------------------------------------------ report
def report(conn: sqlite3.Connection, start: str, end: str) -> dict[str, Any]:
    by_template: dict[str, dict] = {}
    for r in admin_repo.journeys_by_template_status(conn, start, end):
        row = by_template.setdefault(r["template_code"], {"title": r["title"], "total": 0,
                                                          **{s: 0 for s in STATUS_FA}})
        row[r["status"]] += r["n"]
        row["total"] += r["n"]
    for row in by_template.values():
        closed = row["succeeded"] + row["partial"] + row["failed"]
        row["success_rate"] = round(100 * (row["succeeded"] + row["partial"]) / closed) if closed else None
    doctors = []
    for r in admin_repo.outcomes_by_doctor(conn, start, end):
        closed = r["succeeded"] + r["partial"] + r["failed"]
        doctors.append({"doctor": r["doctor"], "succeeded": r["succeeded"], "partial": r["partial"],
                        "failed": r["failed"],
                        "success_rate": round(100 * (r["succeeded"] + r["partial"]) / closed) if closed else None,
                        "return_visits": r["return_visits"], "same_doctor_visits": r["same_doctor_visits"]})
    calls: dict[str, dict] = {}
    for r in admin_repo.calls_by_user(conn, start, end):
        row = calls.setdefault(r["by_user"].split(":", 1)[-1], {o: 0 for o in OUTCOME_FA} | {"total": 0})
        row[r["outcome"]] += r["n"]
        row["total"] += r["n"]
    return {"templates": list(by_template.values()), "doctors": doctors,
            "calls": [{"user": u, **v} for u, v in sorted(calls.items())],
            "statuses": STATUS_FA, "outcomes": OUTCOME_FA, "baseline_rate": BASELINE_RETURN_RATE}


# ------------------------------------------------------------------ audit log
AUDIT_FA = {
    "auth.login": "ورود", "auth.fail": "ورود ناموفق", "doctor.create": "ساخت حساب پزشک",
    "doctor.update": "تغییر حساب پزشک", "shift.override": "تغییر دستی شیفت",
    "shift.override_clear": "برگشت به شیفت حسابداری", "encounter.save": "ثبت پیگیری توسط پزشک",
    "encounter.edit": "ویرایش پیگیری توسط پزشک", "journey.create": "ساخت پیگیری",
    "journey.cancelled": "لغو پیگیری", "journey.succeeded": "پیگیری موفق", "journey.partial": "پیگیری نیمه‌کامل",
    "journey.failed": "پیگیری ناموفق", "journey.identity_ready": "فعال شدن پس از تکمیل هویت",
    "journey.reopened": "بازگشایی پیگیری", "evidence.match": "ثبت بازگشت بیمار", "evidence.revoke": "ابطال بازگشت",
    "call.outcome": "نتیجهٔ تماس", "walkin.enter": "ورود برگهٔ پرستار", "walkin.no_paper": "برگهٔ پرستار موجود نبود",
    "cutoff.draft": "پیش‌نویس کات‌آف", "cutoff.approve": "تأیید کات‌آف", "identity.create": "ثبت هویت",
    "identity.update": "اصلاح هویت", "identity.link": "اتصال پرونده", "identity.foreign": "ثبت تبعهٔ خارجی",
    "setting.followup_doctors": "پزشکان پیگیری", "setting.call_text": "متن تماس",
    "procedure.map": "نگاشت نام کار عملی", "app.stop": "توقف برنامه", "maintenance.backup": "پشتیبان‌گیری",
    "maintenance.purge": "پاک‌سازی دادهٔ قدیمی آینه",
    "encounter.source_deleted": "حذف ویزیتِ پیگیری در حسابداری", "journey.needs_review": "نیازمند بررسی شد",
    "journey.review_keep": "ادامهٔ پیگیری پس از بررسی",
}


def _actor_fa(actor: str) -> str:
    kind, _, name = actor.partition(":")
    return {"doctor": f"پزشک {name}", "acc": name, "system": "سامانه", "dev": "توسعه"}.get(kind, actor) \
        if name else actor


def audit(conn: sqlite3.Connection, *, start: str, end: str, actor: str | None, action: str | None,
          page: int) -> dict[str, Any]:
    size = 100
    rows = admin_repo.audit_page(conn, start=start, end=end, actor=actor or None, action=action or None,
                                 limit=size + 1, offset=page * size)
    return {
        "rows": [{"at_fa": jalali_datetime(r["at"]), "actor": _actor_fa(r["actor"]),
                  "action": AUDIT_FA.get(r["action"], r["action"]), "entity": r["entity"],
                  "entity_id": r["entity_id"], "detail": r["after_json"] or r["before_json"] or ""}
                 for r in rows[:size]],
        "has_more": len(rows) > size, "page": page,
        "actions": [(a, AUDIT_FA.get(a, a)) for a in admin_repo.audit_actions(conn)],
    }


# ------------------------------------------------------------------ procedure-name mapping
def procedure_names(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Names that need a decision first (no category / ambiguous), then the rest."""
    manual = mirror_repo.procedure_category_map(conn)
    grouped: dict[str, dict] = {}
    for r in admin_repo.procedure_names(conn):
        key = normalize(r["raw_name"])
        g = grouped.setdefault(key, {"name": key, "count": 0, "variants": 0})
        g["count"] += r["n"]
        g["variants"] += 1
    out = []
    for key, g in grouped.items():
        auto = sorted(cat.procedure_keyword_categories(key))
        mapped = key in manual
        out.append({**g, "auto": [cat.LABELS_FA[c] for c in auto], "ambiguous": cat.is_ambiguous_procedure(key),
                    "mapped": mapped, "manual": manual.get(key) if mapped else None,
                    "needs_decision": not mapped and (not auto or cat.is_ambiguous_procedure(key))})
    out.sort(key=lambda x: (not x["needs_decision"], -x["count"]))
    return out


def map_procedure(conn: sqlite3.Connection, name: str, choice: str, *, actor: str, now: datetime) -> int:
    """choice: a category, 'none' (unrelated) or 'auto' (remove the manual decision). Re-categorizes the mirror."""
    key = normalize(name)
    if not key:
        raise AdminError("نام کار عملی خالی است")
    if choice not in (*MAPPABLE, "none", "auto"):
        raise AdminError("دستهٔ انتخاب‌شده نامعتبر است")
    at = now.strftime(TS_FORMAT)
    changed = 0
    with transaction(conn):
        if choice == "auto":
            admin_repo.delete_procedure_map(conn, key)
        else:
            admin_repo.set_procedure_map(conn, key, None if choice == "none" else choice, actor, at)
        proc_map = mirror_repo.procedure_category_map(conn)
        for item in admin_repo.procedure_items(conn):
            if normalize(item["raw_name"]) == key:
                mirror_repo.replace_item_categories(conn, ("procedure", item["item_id"]),
                                                    cat.procedure_categories(item["raw_name"], proc_map))
                changed += 1
        account_repo.audit(conn, at, actor, "procedure.map", "procedure_category_map", key, after={"choice": choice})
    return changed


# ------------------------------------------------------------------ call texts
def call_texts(conn: sqlite3.Connection) -> list[dict[str, str]]:
    return [{"purpose": p, "label": label,
             "text": state_repo.setting_get(conn, journeys.CALL_TEXT_PREFIX + p) or ""}
            for p, label in PURPOSE_LABELS.items()]


def save_call_text(conn: sqlite3.Connection, purpose: str, text: str, *, actor: str, now: datetime) -> None:
    if purpose not in PURPOSE_LABELS:
        raise AdminError("نوع تماس نامعتبر است")
    text = (text or "").strip()
    if not text or len(text) > 400:
        raise AdminError("متن تماس باید بین ۱ تا ۴۰۰ نویسه باشد")
    try:
        journeys.validate_call_text(purpose, text)
    except journeys.JourneyError as exc:
        raise AdminError(str(exc)) from None
    at = now.strftime(TS_FORMAT)
    with transaction(conn):
        before = state_repo.setting_get(conn, journeys.CALL_TEXT_PREFIX + purpose)
        state_repo.setting_set(conn, journeys.CALL_TEXT_PREFIX + purpose, text, actor, at)
        account_repo.audit(conn, at, actor, "setting.call_text", "setting", purpose, before, text)


def record_stop(conn: sqlite3.Connection, *, actor: str, now: datetime) -> None:
    with transaction(conn):
        account_repo.audit(conn, now.strftime(TS_FORMAT), actor, "app.stop", "app", None)


# ------------------------------------------------------------------ maintenance: weekly backup + mirror retention
class Maintenance:
    """Daemon: once a week back up the panel DB (keep 4) and purge mirror rows older than 120 days."""

    def __init__(self, db_path: Path, backups_dir: Path, clock: Callable[[], datetime]) -> None:
        self.db_path, self.backups_dir, self.clock = db_path, backups_dir, clock

    def due(self, conn: sqlite3.Connection) -> bool:
        last = state_repo.sync_get(conn).get("last_backup_at")
        return last is None or self.clock() - datetime.strptime(last, TS_FORMAT) >= timedelta(days=BACKUP_EVERY_DAYS)

    def run_once(self, force: bool = False) -> dict[str, Any] | None:
        conn = core.connect(self.db_path)
        try:
            if not force and not self.due(conn):
                return None
            now = self.clock()
            at = now.strftime(TS_FORMAT)
            dest = core.backup(conn, self.backups_dir, "weekly", now)
            before = (now.date() - timedelta(days=MIRROR_RETENTION_DAYS)).isoformat()
            with transaction(conn):
                purged = admin_repo.purge_mirror(conn, before)
                state_repo.sync_set(conn, {"last_backup_at": at, "last_backup_file": dest.name})
                account_repo.audit(conn, at, "system:maintenance", "maintenance.backup", "backup", dest.name)
                account_repo.audit(conn, at, "system:maintenance", "maintenance.purge", "mirror", before, after=purged)
            log.info("weekly maintenance: backup %s, purged %s", dest.name, purged)
            return {"backup": dest.name, "purged": purged}
        finally:
            conn.close()

    def run(self, stop: threading.Event) -> None:
        stop.wait(60)                                  # let startup and the first polls finish
        while not stop.is_set():
            try:
                self.run_once()
            except Exception:                          # never let the thread die
                log.exception("maintenance failed")
            stop.wait(3600)


def health(conn: sqlite3.Connection, settings, bridge, monitor, now: datetime) -> dict[str, Any]:
    st = state_repo.sync_get(conn)
    sync = sync_status(conn, bridge, now)
    backups = sorted(settings.backups_dir.glob("peygiri_panel_*.db")) if settings.backups_dir.exists() else []
    return {
        "sync": sync, "bridge_state": monitor.status.state, "bridge_detail": monitor.status.detail,
        "bridge_checked_fa": jalali_datetime(monitor.status.checked_at),
        "last_ok_fa": jalali_datetime(st.get("last_ok_at")), "last_error_fa": jalali_datetime(st.get("last_error_at")),
        "last_backup_fa": jalali_datetime(st.get("last_backup_at")), "backups": [b.name for b in backups[-6:]],
        "db_mb": round(settings.panel_db_path.stat().st_size / 1_048_576, 1),
        "counts": admin_repo.table_counts(conn, ("person", "journey", "journey_step", "return_evidence",
                                                 "acc_invoice", "acc_item", "audit_log")),
    }
