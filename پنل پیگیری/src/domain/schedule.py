"""Appointment suggestions from the usual doctor schedule (docs/05 §10). Pure."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

WEEKS = 12
SHIFT_ORDER = {"morning": 0, "evening": 1, "night": 2}


@dataclass(frozen=True)
class Slot:
    day: date
    shift: str
    doctor_id: int


def usual_combos(rows: list[tuple[str, str, int | None]], doctor_id: int, today: date) -> set[tuple[int, str]]:
    """(weekday, shift) pairs the doctor covered in at least half of the last 12 weeks."""
    since = today - timedelta(weeks=WEEKS)
    seen: dict[tuple[int, str], set[date]] = defaultdict(set)
    for work_date, shift, doc in rows:
        d = date.fromisoformat(work_date)
        if doc == doctor_id and since <= d < today:
            seen[(d.weekday(), shift)].add(d)
    return {combo for combo, days in seen.items() if len(days) >= WEEKS / 2}


def suggest(rows: list[tuple[str, str, int | None]], doctor_ids: list[int], start: date,
            days: int = 14) -> list[Slot]:
    """Upcoming slots, origin doctor first then follow-up doctors (D20), in date order per doctor."""
    out: list[Slot] = []
    seen_ids: list[int] = []
    for doc in doctor_ids:
        if doc is None or doc in seen_ids:
            continue
        seen_ids.append(doc)
        combos = usual_combos(rows, doc, start)
        for n in range(days):
            d = start + timedelta(days=n)
            for shift in sorted({s for (wd, s) in combos if wd == d.weekday()}, key=SHIFT_ORDER.get):
                out.append(Slot(d, shift, doc))
    return out
