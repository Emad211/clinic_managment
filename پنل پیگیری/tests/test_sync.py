"""Poller + differ against a synthetic accounting DB driven like reception would drive it."""
from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from accounting_factory import BP_CHECK_ID, BS_TEST_ID, TODAY, Reception
from src.adapters.accounting.bridge import AccountingBridge
from src.adapters.sqlite import core
from src.domain import events as ev
from src.services.bridge_monitor import BridgeMonitor
from src.sync.poller import Poller

NOW = datetime(2026, 10, 6, 10, 0, 0)
T = TODAY.isoformat()
VALID_NID = "0499370899"          # checksum-valid, synthetic


@pytest.fixture
def env(tmp_path, acc_db):
    panel = tmp_path / "peygiri_panel.db"
    core.init_db(panel, tmp_path / "backups")
    bridge = AccountingBridge(str(acc_db), budget_ms=200, busy_timeout_ms=250)
    assert BridgeMonitor(bridge).check_now().state == "ok"
    seen: list = []
    poller = Poller(bridge, panel, interval_seconds=0.05, clock=lambda: NOW,
                    on_events=lambda conn, events: seen.extend(events))
    db = sqlite3.connect(panel)
    yield poller, Reception(acc_db), db, seen
    db.close()


def q(db, sql, *params):
    return db.execute(sql, params).fetchall()


def test_first_run_starts_from_today_and_loads_history(env):
    poller, rec, db, seen = env
    assert poller.step().ok
    state = dict(q(db, "SELECT key, value FROM sync_state"))
    max_before_today = q(sqlite3.connect(rec.path), "SELECT max(id) FROM invoices WHERE work_date < ?", T)[0][0]
    assert int(state["wm_invoice_id"]) == max_before_today
    assert q(db, "SELECT count(*) FROM acc_invoice")[0][0] == 0           # history is not mirrored
    assert q(db, "SELECT count(*) FROM acc_shift_staff")[0][0] >= 84 * 3
    assert q(db, "SELECT count(*) FROM acc_staff")[0][0] == 3
    assert '"bs_test": [22]' in state["service_ids"] and '"bp_check": [31]' in state["service_ids"]
    assert '"shift": "morning"' in state["acc_active_shift"]
    assert seen == []


def test_visit_lifecycle_emits_events_once(env):
    poller, rec, db, seen = env
    poller.step()
    pid = rec.add_patient("مریم", "احمدی", VALID_NID, "09121234567")
    iid = rec.open_invoice(pid, T, "morning")
    vid = rec.add_visit(iid, doctor_id=1, at=f"{T} 09:40:00")
    jid = rec.add_injection(iid, BS_TEST_ID, "تست قند")
    poller.step()
    assert ev.ItemAdded("visit", vid, iid, frozenset({"visit"})) in seen
    assert ev.ItemAdded("injection", jid, iid, frozenset({"bs_test"})) in seen
    assert ev.PatientChanged(pid, True) in seen
    assert q(db, "SELECT identity_ok FROM acc_patient WHERE acc_id = ?", pid) == [(1,)]
    assert q(db, "SELECT item_at, doctor_staff_id FROM acc_item WHERE item_type='visit' AND item_id=?", vid) \
        == [(f"{T} 09:40:00", 1)]

    seen.clear()
    poller.step()
    assert seen == []                                                      # idempotent

    rec.set_paid(iid, "visit", vid)
    poller.step()
    assert seen == [ev.ItemPaid("visit", vid, iid)]

    seen.clear()
    rec.set_paid(iid, "visit", vid, paid=False)
    poller.step()
    assert seen == [ev.PaymentRemoved("visit", vid, iid)]

    seen.clear()
    rec.delete_item(iid, "injection", jid)
    poller.step()
    assert seen == [ev.ItemDeleted("injection", jid, iid)]
    assert q(db, "SELECT deleted_at IS NOT NULL FROM acc_item WHERE item_type='injection' AND item_id=?", jid) == [(1,)]

    seen.clear()
    rec.set_paid(iid, "visit", vid)
    rec.close_invoice(iid, 0)
    poller.step()
    assert ev.InvoiceClosed(iid, 0) in seen and ev.ItemPaid("visit", vid, iid) in seen
    assert q(db, "SELECT status FROM acc_invoice WHERE acc_id = ?", iid) == [("closed",)]

    seen.clear()
    poller.step()                                   # closed invoice is no longer watched
    assert seen == []


def test_placeholder_identity_is_flagged(env):
    poller, rec, db, seen = env
    poller.step()
    pid = rec.add_patient("خ", "حسینی", None, None, is_foreign=1)
    rec.add_visit(rec.open_invoice(pid, T, "morning"), doctor_id=1)
    poller.step()
    assert q(db, "SELECT identity_ok FROM acc_patient WHERE acc_id = ?", pid) == [(0,)]
    rec.update_patient(pid, name="فاطمه", national_id=VALID_NID, phone_number="09351112233", is_foreign=0)
    seen.clear()
    poller.step()
    assert ev.PatientChanged(pid, True) in seen


def test_categories(env):
    poller, rec, db, seen = env
    poller.step()
    iid = rec.open_invoice(rec.add_patient("علی", "رضایی"), T, "evening")
    names = {"کشیدن بخیه": "suture_removal", "زدن بخیه": None, "پانسمان": "dressing",
             "شستشوی گوش": "ear_irrigation", "سوراخ کردن گوش": None}
    ids = {name: rec.add_procedure(iid, name) for name in names}
    bp = rec.add_injection(iid, BP_CHECK_ID, "کنترل فشار")
    poller.step()
    for name, expected in names.items():
        got = q(db, "SELECT category FROM acc_item_category WHERE item_type='procedure' AND item_id=?", ids[name])
        assert got == ([(expected,)] if expected else []), name
    assert q(db, "SELECT category FROM acc_item_category WHERE item_type='injection' AND item_id=?", bp) \
        == [("bp_check",)]


def test_manual_procedure_map_wins(env):
    poller, rec, db, seen = env
    db.execute("INSERT INTO procedure_category_map VALUES ('بخیه', 'suture_removal', 'm', 't')")
    db.commit()
    poller.step()
    iid = rec.open_invoice(rec.add_patient("علی", "رضایی"), T, "evening")
    rid = rec.add_procedure(iid, "بخیه")
    poller.step()
    assert q(db, "SELECT category FROM acc_item_category WHERE item_id=?", rid) == [("suture_removal",)]


def test_activity_log_hint_brings_in_an_unwatched_old_invoice(env):
    poller, rec, db, seen = env
    poller.step()
    wm = int(q(db, "SELECT value FROM sync_state WHERE key='wm_invoice_id'")[0][0])
    vid = rec.add_visit(wm, doctor_id=2)            # yesterday's invoice, not mirrored, gets a visit
    poller.step()                                   # log seen → hinted
    assert "visit" not in {r[0] for r in q(db, "SELECT item_type FROM acc_item WHERE acc_invoice_id=?", wm)}
    poller.step()                                   # hinted invoice read in full
    assert q(db, "SELECT item_id FROM acc_item WHERE item_type='visit' AND item_id=?", vid) == [(vid,)]


def test_skipped_cycle_is_counted_and_changes_nothing(env):
    poller, rec, db, seen = env
    poller.step()
    w = sqlite3.connect(str(rec.path), isolation_level=None, timeout=5)
    w.execute("BEGIN EXCLUSIVE")
    try:
        result = poller.step()
    finally:
        w.execute("COMMIT")
        w.close()
    assert not result.ok and result.reason == "busy"
    state = dict(q(db, "SELECT key, value FROM sync_state"))
    assert state["consecutive_failures"] == "1" and state["last_error_reason"] == "busy"
    assert poller.step().ok
    assert dict(q(db, "SELECT key, value FROM sync_state"))["consecutive_failures"] == "0"


def test_new_shift_is_detected(env):
    poller, rec, db, seen = env
    poller.step()
    rec.start_shift(3, "evening", T, f"{T} 14:59:00")
    poller.step()
    assert '"shift": "evening"' in q(db, "SELECT value FROM sync_state WHERE key='acc_active_shift'")[0][0]


def test_missing_active_shift_clears_stale_detection(env):
    poller, rec, db, _ = env
    assert poller.step().ok
    rec._run("DELETE FROM user_active_shift")
    assert poller.step().ok
    assert dict(q(db, "SELECT key, value FROM sync_state"))["acc_active_shift"] == "null"


def test_accounting_is_closed_before_mirror_transaction(env, monkeypatch):
    poller, rec, db, _ = env
    assert poller.step().ok
    iid = rec.open_invoice(rec.add_patient("مریم", "احمدی"), T, "morning")
    rec.add_visit(iid, doctor_id=1)
    import src.sync.poller as module
    original = module.apply_snapshot
    def checked(*args):
        writer = sqlite3.connect(rec.path, isolation_level=None, timeout=0)
        try:
            writer.execute("BEGIN EXCLUSIVE")
            return original(*args)
        finally:
            writer.execute("ROLLBACK")
            writer.close()
    monkeypatch.setattr(module, "apply_snapshot", checked)
    assert poller.step().ok


def test_event_sink_failure_rolls_back_mirror_and_watermarks(env):
    poller, rec, db, _ = env
    assert poller.step().ok
    before = dict(q(db, "SELECT key, value FROM sync_state"))
    iid = rec.open_invoice(rec.add_patient("مریم", "احمدی"), T, "morning")
    vid = rec.add_visit(iid, doctor_id=1)
    sink = poller.on_events
    def fail(conn, events):
        raise RuntimeError("engine failure")
    poller.on_events = fail
    with pytest.raises(RuntimeError, match="engine failure"):
        poller.step()
    assert q(db, "SELECT item_id FROM acc_item WHERE item_id=?", vid) == []
    assert dict(q(db, "SELECT key, value FROM sync_state")) == before
    poller.on_events = sink
    assert poller.step().ok
    assert q(db, "SELECT item_id FROM acc_item WHERE item_type='visit' AND item_id=?", vid) == [(vid,)]


def test_restart_resumes_watermark_and_handles_over_500_watched_invoices(env):
    poller, rec, db, _ = env
    assert poller.step().ok
    pid = rec.add_patient("مریم", "احمدی")
    writer = sqlite3.connect(rec.path)
    try:
        writer.executemany("INSERT INTO invoices(patient_id, status, work_date, shift) VALUES (?, 'open', ?, 'morning')",
                           [(pid, T)] * 510)
        writer.commit()
    finally:
        writer.close()
    assert poller.step().ok
    assert q(db, "SELECT count(*) FROM acc_invoice")[0][0] == 500
    restarted = Poller(poller.bridge, poller.db_path, interval_seconds=5, clock=lambda: NOW)
    assert restarted.step().ok
    assert q(db, "SELECT count(*) FROM acc_invoice")[0][0] == 510
    assert restarted.step().ok
    assert q(db, "SELECT count(*) FROM acc_invoice")[0][0] == 510


def test_identity_failure_never_stops_the_mirror(env, monkeypatch):
    """A crash in panel-only identity code is isolated; the mirror and watermarks still advance."""
    poller, rec, db, seen = env
    poller.step()

    def boom(*_args, **_kwargs):
        raise RuntimeError("identity bug")
    monkeypatch.setattr("src.sync.differ.sync_patients", boom)
    pid = rec.add_patient("مریم", "احمدی", VALID_NID, "09121234567")
    vid = rec.add_visit(rec.open_invoice(pid, T, "morning"), doctor_id=1)
    assert poller.step().ok
    assert q(db, "SELECT item_id FROM acc_item WHERE item_type='visit' AND item_id=?", vid) == [(vid,)]
    assert q(db, "SELECT count(*) FROM person") == [(0,)]                 # identity writes undone
    assert q(db, "SELECT count(*) FROM identity_observation") == [(0,)]

    monkeypatch.undo()
    rec.set_paid(*q(db, "SELECT acc_invoice_id, 'visit', item_id FROM acc_item WHERE item_id=?", vid)[0])
    assert poller.step().ok                                               # next cycle heals
    assert q(db, "SELECT count(*) FROM person") == [(1,)]
