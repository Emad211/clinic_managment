"""Keeps the accounting bridge honest: schema check at startup and hourly (docs/03 §7).

A failed check disables the bridge (pages keep working from the mirror and show
a banner); a later successful check re-enables it.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from ..adapters.accounting.bridge import AccountingBridge, CycleSkipped
from ..adapters.accounting.schema_check import check_schema
from ..common import iran_time

log = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 3600


@dataclass(frozen=True)
class BridgeStatus:
    state: str               # 'ok' | 'disabled' | 'unchecked'
    detail: str
    checked_at: str | None


class BridgeMonitor:
    def __init__(self, bridge: AccountingBridge) -> None:
        self.bridge = bridge
        self._lock = threading.Lock()
        self._status = BridgeStatus("unchecked", "", None)

    @property
    def status(self) -> BridgeStatus:
        with self._lock:
            return self._status

    def _set(self, state: str, detail: str) -> None:
        with self._lock:
            self._status = BridgeStatus(state, detail, iran_time.now_str())

    def check_now(self) -> BridgeStatus:
        if not self.bridge.path:
            self._set("disabled", self.bridge.disabled_reason or "")
            return self.status
        try:
            result = self.bridge.read(check_schema, force=True)
        except CycleSkipped as exc:
            if exc.reason in ("busy", "timeout"):
                # Accounting was writing; not a schema verdict. Keep the previous state.
                log.info("schema check skipped (%s); will retry", exc.reason)
                if self.status.state == "unchecked":
                    self._set("unchecked", f"check skipped: {exc.reason}")
                return self.status
            self.bridge.disable(str(exc))
            self._set("disabled", str(exc))
            return self.status
        report = result.value
        if report.ok:
            self.bridge.enable()
            self._set("ok", f"schema ok ({result.elapsed_ms:.1f} ms)")
        else:
            self.bridge.disable("accounting schema mismatch: " + report.summary())
            self._set("disabled", report.summary())
        return self.status

    def run(self, stop: threading.Event) -> None:
        """Thread body: check now, then hourly. Retries after 30 s while unchecked."""
        while not stop.is_set():
            try:
                status = self.check_now()
            except Exception:  # never let the thread die
                log.exception("schema check crashed")
                status = self.status
            wait = 30 if status.state == "unchecked" else CHECK_INTERVAL_SECONDS
            stop.wait(wait)
