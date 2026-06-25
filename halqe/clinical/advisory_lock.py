"""
clinical/advisory_lock.py — Step 51 (cluster L): production no-concurrent-run guard.

WHY
---
halqe is a cloud Django app: it has NO in-process daemon thread (unlike the Flask
desktop apps).  The production engagement tick comes from an EXTERNAL scheduler
(managed cron now; Celery beat later — see docs/runbook_engagement.md).  An external
scheduler can fire an overlapping tick before the previous one finished (slow run,
manual run + cron run, two cron hosts).  Two concurrent engagement runs would race.

The engagement ledger (engagement_dispatch + UNIQUE constraint) is already a strong
idempotency backstop — a duplicate dispatch row is rejected.  But a global
no-concurrent-run lock is cheaper and cleaner: it prevents the wasted work and the
log noise of two runs fighting over the same rows.

MECHANISM
---------
Postgres SESSION-level advisory locks (pg_try_advisory_lock / pg_advisory_unlock).
A single GLOBAL key (not per-tenant) guarantees "only one engagement run at a time"
across the whole cluster.  This is intentionally global, NOT tenant-scoped: it is an
operational concurrency guard, completely orthogonal to RLS / tenant isolation.

  - pg_try_advisory_lock(key) is NON-blocking: returns TRUE if acquired, FALSE if
    another session already holds it.  We never block — a second run reports
    "skipped_locked" and exits cleanly (exit 0), it does NOT crash or wait.
  - The lock is held on the connection's SESSION until explicitly released (or the
    connection closes).  We hold it for the whole command and release in finally.

CONN_MAX_AGE INTERACTION (ADR-0008)
-----------------------------------
CONN_MAX_AGE=0 only affects the WSGI request/response cycle (each HTTP request opens
& closes a fresh connection).  Inside a management command there is no request cycle:
`django.db.connection` stays open for the command's lifetime, so the session-level
advisory lock is held on that single connection for the whole run — exactly what we
want.  We acquire/release on the SAME `connection` object to be safe regardless of
how CONN_MAX_AGE is configured.

USAGE
-----
    from clinical.advisory_lock import engagement_run_lock

    with engagement_run_lock() as acquired:
        if not acquired:
            ... report skipped_locked, exit 0 ...
        else:
            ... do the run ...
    # lock auto-released on exit
"""
from __future__ import annotations

import contextlib
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global lock key — a single fixed bigint shared by ALL engagement runs.
#
# Chosen as a readable constant: the ASCII bytes of "halqEng" packed would be
# arbitrary; instead we pick an explicit, documented integer.  pg advisory lock
# keys are bigint; this value is well within int8 range and unlikely to collide
# with any other advisory lock the app might add later (document new keys here).
#
#   0x68 0x61 0x6c 0x71 = 'h' 'a' 'l' 'q'  → 0x68616c71 = 1751215217
# ---------------------------------------------------------------------------
ENGAGEMENT_RUN_LOCK_KEY = 0x68616C71  # 1751215217 — global engagement run lock


@contextlib.contextmanager
def engagement_run_lock(key: int = ENGAGEMENT_RUN_LOCK_KEY):
    """
    Context manager that tries to acquire the global engagement advisory lock.

    Yields:
        True  — lock acquired; the caller owns the run.  Released on exit.
        False — another run holds the lock; caller MUST skip cleanly (no work,
                no error).  Nothing to release.

    Never raises on the lock path itself: a DB error while *acquiring* propagates
    (the caller wants to know the DB is unreachable), but the *release* in finally
    is best-effort and never masks the body's outcome.
    """
    from django.db import connection

    acquired = False
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", [key])
            row = cur.fetchone()
            acquired = bool(row and row[0])
        if acquired:
            logger.debug("engagement_run_lock: acquired global lock key=%s", key)
        else:
            logger.info(
                "engagement_run_lock: NOT acquired — another engagement run "
                "holds the global lock key=%s (will skip)", key,
            )
        yield acquired
    finally:
        if acquired:
            try:
                with connection.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s)", [key])
                logger.debug("engagement_run_lock: released global lock key=%s", key)
            except Exception:  # noqa: BLE001
                # Best-effort release.  If it fails the connection close will drop
                # the session lock anyway; never mask the run's outcome.
                logger.warning(
                    "engagement_run_lock: failed to release lock key=%s "
                    "(will be released on connection close)", key,
                )
