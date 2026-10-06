"""Header sync indicator (docs/02 §9): green < 15 s, yellow < 60 s, red otherwise."""
from __future__ import annotations

from datetime import datetime

GREEN_SECONDS = 15
YELLOW_SECONDS = 60


def indicator(last_ok_at: datetime | None, now: datetime, bridge_enabled: bool) -> tuple[str, int | None]:
    """Returns (color, seconds since the last successful cycle)."""
    if last_ok_at is None:
        return "red", None
    age = max(0, int((now - last_ok_at).total_seconds()))
    if not bridge_enabled or age >= YELLOW_SECONDS:
        return "red", age
    return ("green" if age < GREEN_SECONDS else "yellow"), age
