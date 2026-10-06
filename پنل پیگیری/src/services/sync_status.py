"""Sync indicator and health figures (docs/02 §9, docs/06 §2)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from ..adapters.accounting.bridge import AccountingBridge
from ..adapters.sqlite import state_repo
from ..domain.sync_status import indicator


@dataclass(frozen=True)
class SyncStatus:
    color: str                     # green | yellow | red
    age_seconds: int | None
    message: str                   # Persian; empty when green
    last_ok_at: str | None
    cycle_ms_p50: str | None
    cycle_ms_p99: str | None
    consecutive_failures: int
    last_error: str | None
    cycles_ok: int
    cycles_skipped: int


def _bridge_message(reason: str) -> str:
    r = reason.lower()
    if "db_path" in r:
        return "مسیر دیتابیس حسابداری در config.ini تنظیم نشده است"
    if r.startswith("missing"):
        return "فایل حسابداری در مسیر تنظیم‌شده پیدا نشد؛ config.ini را بررسی کنید"
    if "schema mismatch" in r:
        return "نسخهٔ حسابداری با پنل سازگار نیست؛ با پشتیبانی تماس بگیرید. صفحه‌ها با آخرین دادهٔ همگام کار می‌کنند"
    if "not checked" in r:
        return "در حال بررسی اتصال به حسابداری…"
    return "اتصال به حسابداری قطع است: " + reason


def status(conn: sqlite3.Connection, bridge: AccountingBridge, now: datetime) -> SyncStatus:
    st = state_repo.sync_get(conn)
    last_ok = st.get("last_ok_at")
    last_ok_dt = datetime.strptime(last_ok, "%Y-%m-%d %H:%M:%S") if last_ok else None
    color, age = indicator(last_ok_dt, now, bridge.enabled)
    if not bridge.enabled:
        message = _bridge_message(bridge.disabled_reason or "")
    elif color == "red":
        message = ("هنوز هیچ همگام‌سازی موفقی انجام نشده است" if age is None
                   else f"آخرین همگام‌سازی موفق {age} ثانیه پیش بود؛ حسابداری در دسترس نیست یا مشغول است")
    else:
        message = ""
    return SyncStatus(color, age, message, last_ok, st.get("cycle_ms_p50"), st.get("cycle_ms_p99"),
                      int(st.get("consecutive_failures", "0")), st.get("last_error"),
                      int(st.get("cycles_ok", "0")), int(st.get("cycles_skipped", "0")))
