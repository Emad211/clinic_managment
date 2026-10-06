"""Jalali display helpers. Storage stays Gregorian; every date shown to a user is Jalali."""
from __future__ import annotations

from datetime import date, datetime

import jdatetime

from .persian_text import digits_only, fa_digits

MONTHS = ("فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
          "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند")
WEEKDAYS = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه")   # date.weekday() order


def _to_date(value: str | date | datetime | None) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def jalali_date(value: str | date | None) -> str:
    """'2026-10-06' → '۱۴۰۵/۰۷/۱۴'. Empty string for missing/invalid input."""
    d = _to_date(value)
    if d is None:
        return ""
    return fa_digits(jdatetime.date.fromgregorian(date=d).strftime("%Y/%m/%d"))


def jalali_month_start(value: date) -> date:
    """The Gregorian date of the 1st of value's Jalali month: 2026-10-06 (۱۴ مهر) → 2026-09-23 (۱ مهر)."""
    j = jdatetime.date.fromgregorian(date=value)
    return jdatetime.date(j.year, j.month, 1).togregorian()


def jalali_long(value: str | date | None, *, weekday: bool = True, year: bool = True) -> str:
    """'2026-10-06' → 'سه‌شنبه ۱۴ مهر ۱۴۰۵'."""
    d = _to_date(value)
    if d is None:
        return ""
    j = jdatetime.date.fromgregorian(date=d)
    text = f"{fa_digits(j.day)} {MONTHS[j.month - 1]}" + (f" {fa_digits(j.year)}" if year else "")
    return f"{WEEKDAYS[d.weekday()]} {text}" if weekday else text


def jalali_datetime(value: str | None) -> str:
    """'2026-10-06 14:05:00' → '۱۴ مهر ۱۴۰۵، ساعت ۱۴:۰۵'."""
    d = _to_date(value)
    if d is None:
        return ""
    clock = str(value)[11:16]
    return jalali_long(d, weekday=False) + (f"، ساعت {fa_digits(clock)}" if len(clock) == 5 else "")


def gregorian_from_jalali(text: str) -> str:
    """'۱۴۰۵/۰۷/۱۴' or '1405/7/14' → '2026-10-06'. Raises ValueError with a Persian message."""
    parts = [digits_only(p) for p in str(text).strip().replace("-", "/").split("/")]
    if len(parts) != 3 or not all(parts):
        raise ValueError("تاریخ باید به شکل ۱۴۰۵/۰۷/۱۴ باشد")
    y, m, d = map(int, parts)
    try:
        return jdatetime.date(y, m, d).togregorian().isoformat()
    except ValueError:
        raise ValueError("این تاریخ در تقویم وجود ندارد") from None
