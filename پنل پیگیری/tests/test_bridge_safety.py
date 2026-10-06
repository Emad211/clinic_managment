"""Bridge safety tests — docs/03 §11. A merge gate for adapters/accounting and sync."""
from __future__ import annotations

import sqlite3
import statistics
import threading
import time
from pathlib import Path

import pytest

from accounting_factory import build_accounting_db
from src.adapters.accounting import bridge
from src.adapters.accounting.bridge import CycleSkipped, ReadSession, open_accounting_ro, run_cycle
from src.adapters.accounting.reader import QUERIES, PollRequest, read_poll
from src.adapters.accounting.schema_check import check_schema, unsafe_plan_lines
from src.services.bridge_monitor import BridgeMonitor

BUDGET, BUSY = 200, 250


def cycle(path, work):
    return run_cycle(path, work, budget_ms=BUDGET, busy_timeout_ms=BUSY)


def p99(values):
    return statistics.quantiles(values, n=100)[98]


# 1 ─────────────────────────────────────────────── writing is impossible
def test_raw_connection_rejects_writes(acc_db):
    conn = open_accounting_ro(acc_db)
    try:
        with pytest.raises(sqlite3.OperationalError, match="attempt to write a readonly database"):
            conn.execute("INSERT INTO settings(key, value) VALUES ('x', 'y')")
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("UPDATE patients SET name = 'x'")
        conn.execute("PRAGMA query_only = OFF")    # even if someone turned the pragma off…
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM visits")    # …mode=ro still refuses
    finally:
        conn.close()


def test_journal_mode_cannot_be_switched_to_wal(acc_db):
    conn = open_accounting_ro(acc_db)
    try:
        try:
            mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        except sqlite3.OperationalError:
            mode = "delete"
        assert mode == "delete"
    finally:
        conn.close()
    with sqlite3.connect(acc_db) as check:
        assert check.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


@pytest.mark.parametrize("sql", [
    "INSERT INTO settings(key) VALUES ('x')", "DELETE FROM visits", "UPDATE users SET role='x'",
    "PRAGMA journal_mode = WAL", "ATTACH DATABASE 'x.db' AS x", "VACUUM", "CREATE TABLE t(x)",
    "PRAGMA wal_checkpoint", "PRAGMA optimize", "ANALYZE",
])
def test_read_session_refuses_non_read_statements(acc_db, sql):
    with pytest.raises(PermissionError):
        cycle(acc_db, lambda s: s.fetch(sql))


def test_file_is_byte_identical_after_cycles(acc_db):
    before = acc_db.read_bytes()
    req = PollRequest(0, 0, frozenset(range(1, 50)), "2026-01-01")
    for _ in range(20):
        cycle(acc_db, lambda s: read_poll(s, req))
    cycle(acc_db, check_schema)
    assert acc_db.read_bytes() == before
    assert not acc_db.with_name(acc_db.name + "-journal").exists()
    assert not acc_db.with_name(acc_db.name + "-wal").exists()


# 2 ─────────────────────────────────────────────── file guard
def test_guard_rejects_paths_outside_temp():
    real_looking = Path(__file__).resolve().parents[2] / "webapp" / "clinic_new.db"
    with pytest.raises(AssertionError, match="non-temporary"):
        open_accounting_ro(real_looking)


def test_missing_file_is_skipped_not_created(tmp_path):
    missing = tmp_path / "nope.db"
    with pytest.raises(CycleSkipped) as info:
        cycle(missing, lambda s: s.fetch("SELECT 1"))
    assert info.value.reason == "missing"
    assert not missing.exists()


# 3 ─────────────────────────────────────────────── lock test
def _writer(path: Path, stop: threading.Event, latencies: list, errors: list, rng_seed: int = 1):
    """Plays accounting: python sqlite3 defaults (timeout=5, DELETE journal), commit every 20–50 ms.

    synchronous=OFF isolates lock waiting from disk fsync noise; the locking
    protocol is unchanged.
    """
    import random
    rng = random.Random(rng_seed)
    conn = sqlite3.connect(str(path), timeout=5)
    conn.execute("PRAGMA synchronous = OFF")
    try:
        n = 0
        while not stop.is_set():
            n += 1
            t0 = time.perf_counter()
            try:
                conn.execute("INSERT INTO activity_logs(action_type, action_category, invoice_id) "
                             "VALUES ('visit_add', 'invoice', ?)", (n % 300 + 1,))
                conn.execute("UPDATE invoice_item_payments SET is_paid = 1 - is_paid "
                             "WHERE invoice_id = ? AND item_type = 'visit'", (300 - n % 10,))
                conn.commit()
            except sqlite3.OperationalError as exc:
                errors.append(str(exc))
                conn.rollback()
            latencies.append((time.perf_counter() - t0) * 1000)
            time.sleep(rng.uniform(0.020, 0.050))
    finally:
        conn.close()


def test_lock_poller_never_blocks_accounting(acc_db):
    """1000 poll cycles at ~100/s — 500× the production rate (one per 5 s) — against a writer.

    Pass criteria (docs/03 §11.3):
    * accounting never gets an error (its timeout is 5 s);
    * the worst extra delay of an accounting commit stays under 100 ms, i.e.
      50× below that timeout. A colliding commit waits in SQLite's busy
      handler, whose shortest sleep on Windows is one timer tick (~15 ms);
    * the poller skips at most 5% of cycles.
    """
    watched = frozenset(range(291, 301))      # the open invoices
    req = PollRequest(300, 0, watched, "2026-10-05")

    stop, lat, errors = threading.Event(), [], []
    w = threading.Thread(target=_writer, args=(acc_db, stop, lat, errors, 2))
    w.start()
    done = skipped = 0
    deadline = time.monotonic() + 60
    try:
        while (done < 1000 or len(lat) < 100) and time.monotonic() < deadline:
            try:
                cycle(acc_db, lambda s: read_poll(s, req))
                done += 1
            except CycleSkipped as exc:
                assert exc.reason == "busy", exc
                skipped += 1
            time.sleep(0.008)
    finally:
        stop.set()
        w.join()

    assert done >= 1000
    assert errors == [], f"accounting got errors: {errors[:3]}"
    assert len(lat) >= 100
    assert max(lat) < 100, f"worst accounting commit {max(lat):.1f} ms (p99 {p99(lat):.1f} ms)"
    assert skipped <= done * 0.05


def test_busy_accounting_skips_cycle_without_holding_locks(acc_db):
    writer = sqlite3.connect(str(acc_db), timeout=5, isolation_level=None)
    writer.execute("BEGIN EXCLUSIVE")
    try:
        t0 = time.perf_counter()
        with pytest.raises(CycleSkipped) as info:
            cycle(acc_db, lambda s: s.fetch("SELECT count(*) FROM invoices"))
        waited = (time.perf_counter() - t0) * 1000
        assert info.value.reason == "busy"
        assert BUSY - 20 <= waited < BUSY + 25, f"waited {waited:.0f} ms"  # never past the limit
        writer.execute("INSERT INTO settings(key, value) VALUES ('k', 'v')")
    finally:
        writer.execute("COMMIT")
        writer.close()


# 4 ─────────────────────────────────────────────── hard time budget
def test_slow_query_is_interrupted_at_budget(acc_db):
    slow = ("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) "
            "SELECT count(*) FROM (SELECT x FROM c LIMIT 1000000000)")
    t0 = time.perf_counter()
    with pytest.raises(CycleSkipped) as info:
        cycle(acc_db, lambda s: s.fetch(slow))
    elapsed = (time.perf_counter() - t0) * 1000
    assert info.value.reason == "timeout"
    assert BUDGET <= elapsed < BUDGET + 100
    # Lock released: a writer commits immediately afterwards.
    with sqlite3.connect(str(acc_db), timeout=0.05) as w:
        w.execute("INSERT INTO settings(key, value) VALUES ('after', '1')")


# 6 ─────────────────────────────────────────────── schema drift
def test_missing_column_disables_bridge(tmp_path):
    path = build_accounting_db(tmp_path / "old" / "clinic_new.db", drop_columns={"visits": "visit_date"})
    b = bridge.AccountingBridge(str(path), budget_ms=BUDGET, busy_timeout_ms=BUSY)
    status = BridgeMonitor(b).check_now()
    assert status.state == "disabled"
    assert not b.enabled and "visits: visit_date" in b.disabled_reason
    with pytest.raises(CycleSkipped, match="disabled"):
        b.read(lambda s: s.fetch("SELECT 1"))


def test_missing_index_disables_bridge(tmp_path):
    path = build_accounting_db(tmp_path / "noidx" / "clinic_new.db", drop_indexes=("idx_visits_invoice_id",))
    b = bridge.AccountingBridge(str(path), budget_ms=BUDGET, busy_timeout_ms=BUSY)
    assert BridgeMonitor(b).check_now().state == "disabled"
    assert "Q3 would scan" in b.disabled_reason


def test_good_schema_enables_bridge(acc_db):
    b = bridge.AccountingBridge(str(acc_db), budget_ms=BUDGET, busy_timeout_ms=BUSY)
    assert not b.enabled                      # disabled until checked
    assert BridgeMonitor(b).check_now().state == "ok"
    assert b.enabled


def test_extra_columns_are_harmless(tmp_path):
    path = build_accounting_db(tmp_path / "new" / "clinic_new.db")
    with sqlite3.connect(str(path)) as w:
        w.execute("ALTER TABLE users ADD COLUMN staff_id INTEGER")   # the repo HEAD has it, prod does not
    assert cycle(path, check_schema).value.ok


# 7 ─────────────────────────────────────────────── query plans
@pytest.mark.parametrize("name", list(QUERIES))
def test_query_plan_uses_key_or_index(acc_db, name):
    assert cycle(acc_db, lambda s: unsafe_plan_lines(s, name)).value == []


def test_every_contract_query_runs(acc_db):
    from src.adapters.accounting.reader import sample_params

    def run_all(s: ReadSession):
        for name in QUERIES:
            s.fetch(*sample_params(name))
        return True
    assert cycle(acc_db, run_all).value
