"""
clinical/engagement_settings.py — engagement guardrail settings (step 52, cluster L).

Per-tenant, manager-editable guardrail configuration backed by platform.settings:
  - engagement_quiet_start  "HH:MM"  (default 08:00) — send window opens
  - engagement_quiet_end    "HH:MM"  (default 21:00) — send window closes
  - engagement_daily_cap    int      (default 50)    — max SMS per tenant per day

Design
──────
  - Reads fall back to the module defaults when the key is absent (backward
    compatible — the dispatcher behaves exactly as before until a manager edits
    a value).  This keeps existing idempotency / guardrails untouched.
  - Values are validated on WRITE (the PUT endpoint), so reads can trust them;
    a defensive parse on read still falls back to the default on garbage.
  - DELIBERATELY does NOT change consent policy: this module only governs the
    quiet-hours window and the (currently informational) daily cap.

daily_cap ENFORCEMENT (step 52, owner decision): the value stored here IS now
   enforced.  engagement_service.dispatch_patient reads get_engagement_settings()
   and suppresses SMS enqueue once the tenant's SMS budget for the current Tehran
   day is reached (combined ledger-sends + enqueued-today-unsent count).  cap=0
   means unlimited → the gate is inert (backward compatible).  quiet-hours is
   enforced separately at SEND time (send_approved_sms, via get_quiet_window).
"""
from __future__ import annotations

import logging
from typing import Optional

from platform_core.platform_settings_service import get_settings, set_setting

logger = logging.getLogger(__name__)

# Setting keys (platform.settings)
KEY_QUIET_START = "engagement_quiet_start"
KEY_QUIET_END = "engagement_quiet_end"
KEY_DAILY_CAP = "engagement_daily_cap"

# Defaults — mirror the constants in engagement_service for backward compat.
# Importing them here keeps a single source of truth for the quiet window.
from clinical.engagement_service import QUIET_START_DEFAULT, QUIET_END_DEFAULT

DEFAULT_QUIET_START = QUIET_START_DEFAULT  # "08:00"
DEFAULT_QUIET_END = QUIET_END_DEFAULT      # "21:00"
DEFAULT_DAILY_CAP = 50


def _valid_hhmm(s: str) -> bool:
    """Return True if s is a valid 'HH:MM' 24h time string."""
    if not isinstance(s, str) or len(s) != 5 or s[2] != ":":
        return False
    try:
        hh = int(s[:2])
        mm = int(s[3:])
    except ValueError:
        return False
    return 0 <= hh <= 23 and 0 <= mm <= 59


def get_engagement_settings(tenant_id: int) -> dict:
    """
    Return {quiet_start, quiet_end, daily_cap} for a tenant.

    Falls back to module defaults for any key that is absent or malformed.
    Single batched read of platform.settings (no N+1).
    """
    raw = get_settings(tenant_id, [KEY_QUIET_START, KEY_QUIET_END, KEY_DAILY_CAP])

    quiet_start = raw.get(KEY_QUIET_START, DEFAULT_QUIET_START)
    if not _valid_hhmm(quiet_start):
        quiet_start = DEFAULT_QUIET_START

    quiet_end = raw.get(KEY_QUIET_END, DEFAULT_QUIET_END)
    if not _valid_hhmm(quiet_end):
        quiet_end = DEFAULT_QUIET_END

    daily_cap = DEFAULT_DAILY_CAP
    if KEY_DAILY_CAP in raw:
        try:
            daily_cap = int(raw[KEY_DAILY_CAP])
            if daily_cap < 0:
                daily_cap = DEFAULT_DAILY_CAP
        except (ValueError, TypeError):
            daily_cap = DEFAULT_DAILY_CAP

    return {
        "quiet_start": quiet_start,
        "quiet_end": quiet_end,
        "daily_cap": daily_cap,
    }


def get_quiet_window(tenant_id: int) -> tuple[str, str]:
    """Convenience: (quiet_start, quiet_end) for the dispatcher's quiet-hours gate."""
    s = get_engagement_settings(tenant_id)
    return s["quiet_start"], s["quiet_end"]


def save_engagement_settings(
    tenant_id: int,
    *,
    quiet_start: str,
    quiet_end: str,
    daily_cap: int,
    updated_by: Optional[str] = None,
) -> dict:
    """
    Validate + upsert the three engagement guardrail keys.

    Raises ValueError on invalid input (the endpoint maps this to 422).
    Returns the persisted settings dict (re-read for round-trip confirmation).
    """
    if not _valid_hhmm(quiet_start):
        raise ValueError(f"quiet_start must be 'HH:MM' (got {quiet_start!r})")
    if not _valid_hhmm(quiet_end):
        raise ValueError(f"quiet_end must be 'HH:MM' (got {quiet_end!r})")
    if not isinstance(daily_cap, int) or daily_cap < 0:
        raise ValueError(f"daily_cap must be a non-negative integer (got {daily_cap!r})")

    set_setting(tenant_id, KEY_QUIET_START, quiet_start, updated_by=updated_by)
    set_setting(tenant_id, KEY_QUIET_END, quiet_end, updated_by=updated_by)
    set_setting(tenant_id, KEY_DAILY_CAP, str(daily_cap), updated_by=updated_by)

    return get_engagement_settings(tenant_id)
