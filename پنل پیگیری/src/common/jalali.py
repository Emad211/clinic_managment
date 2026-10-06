"""Jalali display helpers. Storage stays Gregorian; only the UI shows Jalali."""
from __future__ import annotations

from datetime import date

import jdatetime

from .persian_text import digits_only, fa_digits


def jalali_date(iso: str | date | None) -> str:
    """'2026-10-06' → '۱۴۰۵/۰۷/۱۴'. Empty string for missing/invalid input."""
    if not iso:
        return ""
    try:
        d = iso if isinstance(iso, date) else date.fromisoformat(str(iso)[:10])
    except ValueError:
        return ""
    return fa_digits(jdatetime.date.fromgregorian(date=d).strftime("%Y/%m/%d"))


def gregorian_from_jalali(text: str) -> str:
    """'۱۴۰۵/۰۷/۱۴' or '1405/7/14' → '2026-10-06'. Raises ValueError."""
    parts = [digits_only(p) for p in str(text).replace("-", "/").split("/")]
    if len(parts) != 3 or not all(parts):
        raise ValueError("تاریخ باید به شکل ۱۴۰۵/۰۷/۱۴ باشد")
    y, m, d = map(int, parts)
    try:
        return jdatetime.date(y, m, d).togregorian().isoformat()
    except ValueError:
        raise ValueError("تاریخ جلالی نامعتبر است") from None
