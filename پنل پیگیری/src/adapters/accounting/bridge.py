"""The only code that opens the accounting database (docs/03, ADR-0002).

Safety contract (docs/03 §1), enforced here and proven by tests/test_bridge_safety.py:

* URI ``file:…?mode=ro`` + ``PRAGMA query_only=ON``; never WAL, immutable,
  nolock, ATTACH or file copies.
* ``isolation_level=None`` and exactly one explicit read transaction per cycle,
  so every table is read from the same snapshot.
* Busy wait ≤ 250 ms of wall-clock time (retried in Python, SQLite timeout=0):
  if accounting is still writing, the cycle is skipped.
* Hard budget ≤ 200 ms through ``set_progress_handler``: the query is
  interrupted and the cycle skipped.
* Every result is ``fetchall()``-ed and the connection is closed at the end of
  every cycle — no lock, cursor or cache survives between cycles.

Work functions never see the raw connection. They get a :class:`ReadSession`
that only runs read statements.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

IN_BATCH = 500  # docs/03 §4: IN parameters are sent in batches of at most 500

# Only these statement shapes may reach the accounting connection.
_ALLOWED_SQL = re.compile(
    r"^\s*(SELECT\b|WITH\b|EXPLAIN\s+QUERY\s+PLAN\b|PRAGMA\s+(table_xinfo|index_list)\s*\()",
    re.IGNORECASE,
)

# Tests install a guard that rejects any path outside their temp folders, so the
# real accounting file can never be opened from a test run (docs/03 §11.2).
_path_guard: Callable[[Path], None] | None = None


def set_path_guard(guard: Callable[[Path], None] | None) -> None:
    global _path_guard
    _path_guard = guard


class CycleSkipped(Exception):
    """A read cycle did not complete. Accounting was not affected.

    ``reason`` is one of: ``busy`` (accounting held the write lock past the busy
    timeout), ``timeout`` (read budget exceeded), ``missing`` (file not found),
    ``readonly`` (e.g. a hot journal left by an accounting crash), ``disabled``
    or ``error``.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


class ReadSession:
    """Read-only facade over the accounting connection for one cycle."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def fetch(self, sql: str, params: Sequence[Any] = ()) -> list[tuple]:
        if not _ALLOWED_SQL.match(sql):
            raise PermissionError("only read statements may run on the accounting database")
        cur = self._conn.execute(sql, params)
        try:
            return cur.fetchall()
        finally:
            cur.close()

    def fetch_in(self, sql: str, ids: Iterable[int], prefix: Sequence[Any] = ()) -> list[tuple]:
        """Run ``sql`` containing one ``({ids})`` placeholder, batching ``ids``."""
        unique = sorted(set(ids))
        rows: list[tuple] = []
        for start in range(0, len(unique), IN_BATCH):
            batch = unique[start:start + IN_BATCH]
            marks = ",".join("?" * len(batch))
            rows.extend(self.fetch(sql.format(ids=marks), [*prefix, *batch]))
        return rows


def _uri(path: Path) -> str:
    # as_uri() percent-encodes spaces and Persian characters.
    return path.resolve().as_uri() + "?mode=ro"


def open_accounting_ro(path: str | Path) -> sqlite3.Connection:
    """Open the accounting DB strictly read-only (docs/03 §3).

    ``timeout=0``: SQLite's own busy handler is off. On Windows its sleeps are
    rounded up to the timer tick, so a nominal 250 ms wait measured 770 ms.
    :func:`run_cycle` retries on a monotonic clock instead.
    """
    p = Path(path)
    if _path_guard is not None:
        _path_guard(p.resolve())
    if not p.is_file():
        raise CycleSkipped("missing", str(p))
    conn = sqlite3.connect(_uri(p), uri=True, timeout=0, isolation_level=None, check_same_thread=True)
    try:
        conn.execute("PRAGMA query_only = ON")
    except BaseException:
        conn.close()
        raise
    return conn


def _classify(exc: sqlite3.Error) -> str:
    msg = str(exc).lower()
    if "interrupted" in msg:
        return "timeout"
    if "locked" in msg or "busy" in msg:
        return "busy"
    if "readonly" in msg or "read-only" in msg:
        return "readonly"
    if "unable to open" in msg:
        return "missing"
    return "error"


@dataclass(frozen=True)
class CycleResult:
    value: Any
    elapsed_ms: float     # last attempt, open → close: the longest a SHARED lock could have been held
    attempts: int = 1     # >1 when accounting was busy and the cycle was retried
    total_ms: float = 0.0 # including busy retries (no lock is held while waiting)


_RETRY_SLEEP_S = 0.010


def _attempt(path: str | Path, work: Callable[[ReadSession], T], budget_ms: int) -> tuple[T, float]:
    started = time.perf_counter()
    try:
        conn = open_accounting_ro(path)
    except sqlite3.Error as exc:
        raise CycleSkipped(_classify(exc), str(exc)) from exc
    deadline = time.monotonic() + budget_ms / 1000
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
    try:
        conn.execute("BEGIN")                 # SHARED lock is taken by the first SELECT
        value = work(ReadSession(conn))
        conn.execute("COMMIT")                # releases the lock
    except sqlite3.Error as exc:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise CycleSkipped(_classify(exc), str(exc)) from exc
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.set_progress_handler(None, 0)
        conn.close()
    return value, (time.perf_counter() - started) * 1000


def run_cycle(
    path: str | Path, work: Callable[[ReadSession], T], *, budget_ms: int, busy_timeout_ms: int,
) -> CycleResult:
    """Open, run ``work`` in one read transaction, close. Raise CycleSkipped on any failure.

    If accounting holds a write lock, the attempt fails at its first SELECT
    without taking any lock; it is retried every 10 ms until ``busy_timeout_ms``
    of wall-clock time, then the cycle is skipped. ``work`` must be a pure read
    so a retry is safe.
    """
    started = time.monotonic()
    give_up = started + busy_timeout_ms / 1000
    attempts = 0
    while True:
        attempts += 1
        try:
            value, elapsed = _attempt(path, work, budget_ms)
        except CycleSkipped as exc:
            if exc.reason != "busy" or time.monotonic() + _RETRY_SLEEP_S > give_up:
                raise
            time.sleep(_RETRY_SLEEP_S)
            continue
        return CycleResult(value, elapsed, attempts, (time.monotonic() - started) * 1000)


class AccountingBridge:
    """Configured entry point used by the poller, login and identity lookup.

    The bridge can be disabled (no path configured, or the schema check
    failed). While disabled every read raises ``CycleSkipped('disabled')`` and
    the rest of the app keeps working from the mirror.
    """

    def __init__(self, path: str, *, budget_ms: int, busy_timeout_ms: int) -> None:
        self.path = path
        self.budget_ms = budget_ms
        self.busy_timeout_ms = busy_timeout_ms
        # Disabled until the first schema check passes (services/bridge_monitor.py).
        self._disabled_reason: str | None = (
            "accounting schema not checked yet" if path else "db_path is not set in config.ini")

    @property
    def enabled(self) -> bool:
        return self._disabled_reason is None

    @property
    def disabled_reason(self) -> str | None:
        return self._disabled_reason

    def disable(self, reason: str) -> None:
        if self._disabled_reason != reason:
            log.error("accounting bridge disabled: %s", reason)
        self._disabled_reason = reason

    def enable(self) -> None:
        if self._disabled_reason is not None and self.path:
            log.info("accounting bridge enabled")
            self._disabled_reason = None

    def read(self, work: Callable[[ReadSession], T], *, force: bool = False) -> CycleResult:
        """Run one cycle. ``force`` is only for the schema check that re-enables the bridge."""
        if not self.path:
            raise CycleSkipped("disabled", "db_path is not set in config.ini")
        if not force and self._disabled_reason is not None:
            raise CycleSkipped("disabled", self._disabled_reason)
        return run_cycle(self.path, work, budget_ms=self.budget_ms, busy_timeout_ms=self.busy_timeout_ms)
