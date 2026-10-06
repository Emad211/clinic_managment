"""Tehran time, independent of the OS timezone.

Iran has had no DST since 1401, so Tehran is a fixed UTC+3:30. Timestamps are
stored as naive ``YYYY-MM-DD HH:MM:SS`` strings in Tehran time (same format as
the accounting app). Never use naive ``datetime.now()``.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

TEHRAN = timezone(timedelta(hours=3, minutes=30), "Asia/Tehran")
TS_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"


def now() -> datetime:
    """Current Tehran time as a naive datetime."""
    return datetime.now(timezone.utc).astimezone(TEHRAN).replace(tzinfo=None)


def now_str() -> str:
    return now().strftime(TS_FORMAT)


def today() -> date:
    return now().date()


def today_str() -> str:
    return today().strftime(DATE_FORMAT)
