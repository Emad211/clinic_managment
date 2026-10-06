"""The poller (docs/03 §4, ADR-0003): reads accounting every few seconds and updates the mirror.

One step:
1. Load watermarks and the watched set from the panel DB.
2. One bridge cycle (one read transaction) → snapshot. Accounting is closed again.
3. One panel transaction: apply the snapshot (differ), advance watermarks,
   remember the detected shift and statistics, hand events to ``on_events``.

A skipped cycle (accounting busy, budget exceeded, bridge disabled) changes no
mirror data; it only updates the failure counters.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from ..adapters.accounting.bridge import AccountingBridge, CycleSkipped
from ..adapters.accounting.reader import (PollRequest, read_initial_watermarks, read_poll, read_shift_staff,
                                          read_staff)
from ..adapters.sqlite import core, mirror_repo, state_repo
from ..common import iran_time
from ..domain import categories as cat
from ..domain.events import DomainEvent
from .differ import apply_snapshot

log = logging.getLogger(__name__)

STAFF_REFRESH_SECONDS = 60
SHIFT_HISTORY_DAYS = 84
STATS_WINDOW = 720                  # ~1 hour at 5 s

EventSink = Callable[[sqlite3.Connection, list[DomainEvent]], None]


@dataclass(frozen=True)
class StepResult:
    ok: bool
    reason: str = ""
    cycle_ms: float = 0.0
    events: int = 0


class Poller:
    def __init__(self, bridge: AccountingBridge, panel_db_path, *, interval_seconds: float,
                 clock: Callable[[], datetime] = iran_time.now, on_events: EventSink | None = None) -> None:
        self.bridge = bridge
        self.db_path = panel_db_path
        self.interval = interval_seconds
        self.clock = clock
        self.on_events = on_events
        self._cycle_ms: deque[float] = deque(maxlen=STATS_WINDOW)
        self._last_staff_at = 0.0
        self._service_ids: cat.ServiceIds | None = None
        self._lock = threading.Lock()      # step() is never re-entered

    # ------------------------------------------------------------ public
    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            started = time.monotonic()
            try:
                self.step()
            except Exception:                       # never let the thread die
                log.exception("poll step crashed")
            stop.wait(max(0.0, self.interval - (time.monotonic() - started)))

    def step(self) -> StepResult:
        with self._lock:
            conn = core.connect(self.db_path)
            try:
                return self._step(conn)
            finally:
                conn.close()

    # ------------------------------------------------------------ internals
    def _now_str(self) -> str:
        return self.clock().strftime(iran_time.TS_FORMAT)

    def _step(self, conn: sqlite3.Connection) -> StepResult:
        try:
            state = state_repo.sync_get(conn)
            if "wm_invoice_id" not in state:
                self._initialize(conn)
                state = state_repo.sync_get(conn)
            self._refresh_staff_if_due(conn, state)

            hints = set(json.loads(state.get("hint_invoice_ids", "[]")))
            watched = frozenset(mirror_repo.open_invoice_ids(conn) | hints)
            yesterday = (self.clock().date() - timedelta(days=1)).isoformat()
            req = PollRequest(int(state["wm_invoice_id"]), int(state["wm_activity_log_id"]), watched, yesterday)
            cycle = self.bridge.read(lambda s: read_poll(s, req))
        except CycleSkipped as exc:
            self._record_skip(conn, exc)
            return StepResult(False, exc.reason)

        snap = cycle.value
        now = self._now_str()
        with core.transaction(conn):
            diff = apply_snapshot(conn, snap, self._service_ids or cat.ServiceIds(), now)
            wm_invoice = max([req.wm_invoice_id, *(i.id for i in snap.new_invoices)])
            wm_log = max([req.wm_activity_log_id, *(l.id for l in snap.logs)])
            # Logs that touched an older invoice we are not watching → read it next cycle.
            new_hints = {l.invoice_id for l in snap.logs
                         if l.invoice_id is not None and l.invoice_id <= wm_invoice} - snap.item_invoice_ids
            self._cycle_ms.append(cycle.elapsed_ms)
            values = {
                "wm_invoice_id": str(wm_invoice), "wm_activity_log_id": str(wm_log),
                "hint_invoice_ids": sorted(new_hints), "acc_active_shift": None,
                "last_ok_at": now, "consecutive_failures": "0",
                "cycles_ok": str(int(state.get("cycles_ok", "0")) + 1),
                **self._percentiles(),
            }
            if snap.active_shift is not None:
                a = snap.active_shift
                values["acc_active_shift"] = {"work_date": a.work_date, "shift": a.active_shift,
                                              "started_at": a.shift_started_at, "user_id": a.user_id}
            state_repo.sync_set(conn, values)
            if self.on_events and diff.events:
                self.on_events(conn, diff.events)
        if diff.events:
            log.debug("poll: %d events", len(diff.events))
        return StepResult(True, cycle_ms=cycle.elapsed_ms, events=len(diff.events))

    def _initialize(self, conn: sqlite3.Connection) -> None:
        """First run: start from today's invoices and the current log tail (docs/03 §4)."""
        today = self.clock().date()
        since = (today - timedelta(days=SHIFT_HISTORY_DAYS)).isoformat()

        def work(s):
            return read_initial_watermarks(s, today.isoformat()), read_shift_staff(s, since)
        (wm_invoice, wm_log), shifts = self.bridge.read(work).value
        with core.transaction(conn):
            mirror_repo.upsert_shift_staff(conn, shifts)
            state_repo.sync_set(conn, {"wm_invoice_id": str(wm_invoice), "wm_activity_log_id": str(wm_log),
                                       "initialized_at": self._now_str()})
        log.info("poller initialized: wm_invoice_id=%d wm_activity_log_id=%d", wm_invoice, wm_log)

    def _refresh_staff_if_due(self, conn: sqlite3.Connection, state: dict[str, str]) -> None:
        if self._service_ids is None and "service_ids" in state:
            raw = json.loads(state["service_ids"])
            self._service_ids = cat.ServiceIds(*(frozenset(raw[k]) for k in ("bs_test", "bp_check", "nebulizer")))
        if self._service_ids is not None and time.monotonic() - self._last_staff_at < STAFF_REFRESH_SECONDS:
            return
        staff, services = self.bridge.read(read_staff).value
        ids = cat.resolve_service_ids([(s.id, s.service_name) for s in services])
        with core.transaction(conn):
            mirror_repo.replace_staff(conn, staff, self._now_str())
            state_repo.sync_set(conn, {"service_ids": {"bs_test": sorted(ids.bs_test),
                                                       "bp_check": sorted(ids.bp_check),
                                                       "nebulizer": sorted(ids.nebulizer)}})
        self._service_ids = ids
        self._last_staff_at = time.monotonic()

    def _percentiles(self) -> dict[str, str]:
        data = list(self._cycle_ms)
        if len(data) < 2:
            return {"cycle_ms_p50": f"{data[0]:.2f}"} if data else {}
        return {"cycle_ms_p50": f"{statistics.median(data):.2f}",
                "cycle_ms_p99": f"{statistics.quantiles(data, n=100)[98]:.2f}"}

    def _record_skip(self, conn: sqlite3.Connection, exc: CycleSkipped) -> None:
        log.info("poll cycle skipped: %s", exc)
        with core.transaction(conn):
            state = state_repo.sync_get(conn)
            state_repo.sync_set(conn, {
                "last_error": str(exc)[:300], "last_error_reason": exc.reason, "last_error_at": self._now_str(),
                "consecutive_failures": str(int(state.get("consecutive_failures", "0")) + 1),
                "cycles_skipped": str(int(state.get("cycles_skipped", "0")) + 1),
            })
