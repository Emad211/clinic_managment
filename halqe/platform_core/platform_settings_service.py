"""
platform_core/platform_settings_service.py — tenant-scoped key/value settings.

A thin accessor over the platform.settings table (PK (tenant_id, key)).
Centralises the raw SQL so callers never embed SQL.  Used for cross-cutting
per-tenant configuration that has no dedicated table, e.g.:
  - 'clinic_name'              (card_projection_service)
  - 'engagement_quiet_start'   (engagement guardrail, step 52)
  - 'engagement_quiet_end'
  - 'engagement_daily_cap'

Design
──────
  - tenant-scoped: every read/write filters on tenant_id (WHERE tenant_id=%s),
    mirroring platform.users / platform.tenants (RLS is enabled only on the
    clinical schema; platform tables are app-scoped).
  - upsert: set_setting uses ON CONFLICT (tenant_id, key) DO UPDATE.
  - resilient reads: get_setting returns the default if the row (or the table)
    is absent — never raises on a missing key.  Writes DO raise on failure so
    the endpoint can surface a real error.
  - timezone.now() (USE_TZ=True) → aware TIMESTAMPTZ for updated_at.

This is the ONLY module that issues SQL against platform.settings.
"""
from __future__ import annotations

import logging
from typing import Optional

from django.db import connection

logger = logging.getLogger(__name__)


def get_setting(tenant_id: int, key: str, default: Optional[str] = None) -> Optional[str]:
    """
    Return the string value for (tenant_id, key), or `default` if absent.

    Never raises on a missing key/table — a config lookup must be safe even
    before the row exists.  A real DB error (connection dead) still surfaces.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT value FROM platform.settings "
                "WHERE tenant_id = %s AND key = %s",
                [tenant_id, key],
            )
            row = cursor.fetchone()
        if row and row[0] is not None:
            return row[0]
    except Exception as exc:  # noqa: BLE001
        # missing table / transient error — fall back to default, don't crash
        logger.warning(
            "get_setting: read failed for tenant=%s key=%r: %s", tenant_id, key, exc
        )
    return default


def get_settings(tenant_id: int, keys: list[str]) -> dict[str, str]:
    """
    Batch-read several keys for one tenant in a single query.

    Returns {key: value} only for keys that exist (missing keys are absent —
    callers apply their own fallback).  Empty dict on any error.
    """
    if not keys:
        return {}
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT key, value FROM platform.settings "
                "WHERE tenant_id = %s AND key = ANY(%s)",
                [tenant_id, list(keys)],
            )
            return {k: v for k, v in cursor.fetchall() if v is not None}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "get_settings: batch read failed for tenant=%s keys=%r: %s",
            tenant_id, keys, exc,
        )
        return {}


def set_setting(
    tenant_id: int,
    key: str,
    value: Optional[str],
    *,
    updated_by: Optional[str] = None,
) -> None:
    """
    Upsert (tenant_id, key) → value.  Raises on DB failure (caller surfaces it).

    Uses ON CONFLICT (tenant_id, key) DO UPDATE — idempotent, last-write-wins.
    """
    from django.utils import timezone

    now = timezone.now()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO platform.settings (tenant_id, key, value, updated_at, updated_by)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, key) DO UPDATE
                SET value = EXCLUDED.value,
                    updated_at = EXCLUDED.updated_at,
                    updated_by = EXCLUDED.updated_by
            """,
            [tenant_id, key, value, now, updated_by],
        )
