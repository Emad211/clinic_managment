"""Current shift (docs/03 §10, Q-2, D09).

The detected value is the shift most recently started by a reception user in
accounting (``user_active_shift``, mirrored by the poller). A manual override
is stored with the detected value of that moment; once accounting's detected
shift changes (reception switched shift), the override is dropped.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from ..adapters.sqlite import account_repo, state_repo
from ..adapters.sqlite.core import transaction
from ..common.iran_time import TS_FORMAT

SHIFTS = ("morning", "evening", "night")
SHIFT_LABELS = {"morning": "صبح", "evening": "عصر", "night": "شب"}
OVERRIDE_KEY = "shift_override"


@dataclass(frozen=True)
class ShiftInfo:
    work_date: str
    shift: str
    source: str            # 'accounting' | 'manual' | 'clock'

    @property
    def label(self) -> str:
        return SHIFT_LABELS.get(self.shift, self.shift)


def _clock_shift(now: datetime) -> ShiftInfo:
    h = now.hour
    shift = "morning" if 7 <= h < 14 else "evening" if 14 <= h < 21 else "night"
    return ShiftInfo(now.date().isoformat(), shift, "clock")


def detected(conn: sqlite3.Connection) -> dict | None:
    raw = state_repo.sync_get(conn).get("acc_active_shift")
    return json.loads(raw) if raw else None


def current(conn: sqlite3.Connection, now: datetime) -> ShiftInfo:
    det = detected(conn)
    override = state_repo.setting_get(conn, OVERRIDE_KEY)
    if override is not None:
        if override.get("detected") == det:
            return ShiftInfo(override["work_date"], override["shift"], "manual")
        with transaction(conn):                     # reception changed shift in accounting
            state_repo.setting_delete(conn, OVERRIDE_KEY)
    if det:
        return ShiftInfo(det["work_date"], det["shift"], "accounting")
    return _clock_shift(now)


class ShiftError(ValueError):
    pass


def set_override(conn: sqlite3.Connection, work_date: str, shift: str, *, actor: str, now: datetime) -> ShiftInfo:
    if shift not in SHIFTS:
        raise ShiftError("شیفت نامعتبر است")
    try:
        datetime.strptime(work_date, "%Y-%m-%d")
    except ValueError:
        raise ShiftError("تاریخ نامعتبر است") from None
    ts = now.strftime(TS_FORMAT)
    value = {"work_date": work_date, "shift": shift, "detected": detected(conn)}
    with transaction(conn):
        state_repo.setting_set(conn, OVERRIDE_KEY, value, actor, ts)
        account_repo.audit(conn, ts, actor, "shift.override", "setting", OVERRIDE_KEY, after=value)
    return ShiftInfo(work_date, shift, "manual")


def clear_override(conn: sqlite3.Connection, *, actor: str, now: datetime) -> None:
    ts = now.strftime(TS_FORMAT)
    with transaction(conn):
        state_repo.setting_delete(conn, OVERRIDE_KEY)
        account_repo.audit(conn, ts, actor, "shift.override_clear", "setting", OVERRIDE_KEY)
