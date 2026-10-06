"""Local-only performance check on a production-sized copy (docs/08 §3).

Set PEYGIRI_PERF_DB to a *copy* of the clinic DB; skipped when unset. The copy
is PHI and must never be committed.
"""
from __future__ import annotations

import os
import statistics
from pathlib import Path

import pytest

from src.adapters.accounting.bridge import run_cycle
from src.adapters.accounting.reader import PollRequest, read_poll
from src.adapters.accounting.schema_check import check_schema

PERF_DB = os.environ.get("PEYGIRI_PERF_DB")
pytestmark = pytest.mark.skipif(not PERF_DB, reason="PEYGIRI_PERF_DB not set")


def cycle(work):
    return run_cycle(Path(PERF_DB), work, budget_ms=200, busy_timeout_ms=250)


def test_schema_ok_on_production_copy():
    report = cycle(check_schema).value
    assert report.ok, report.summary()


def test_steady_state_cycle_p99_under_5ms():
    def probe(s):
        (mx,), = s.fetch("SELECT max(id) FROM invoices")
        (ml,), = s.fetch("SELECT max(id) FROM activity_logs")
        open_ids = frozenset(r[0] for r in s.fetch("SELECT id FROM invoices WHERE status = 'open'"))
        (day,), = s.fetch("SELECT max(work_date) FROM invoices")
        return PollRequest(mx - 2, ml - 20, open_ids, day)

    req = cycle(probe).value
    for _ in range(20):                            # warm the OS file cache
        cycle(lambda s: read_poll(s, req))
    times = [cycle(lambda s: read_poll(s, req)).elapsed_ms for _ in range(500)]
    p50, p99 = statistics.median(times), statistics.quantiles(times, n=100)[98]
    print(f"\ncycle open->close: p50 {p50:.2f} ms, p99 {p99:.2f} ms, max {max(times):.2f} ms")
    assert p99 < 5
