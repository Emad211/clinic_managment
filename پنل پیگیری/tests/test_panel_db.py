from __future__ import annotations

import sqlite3

import pytest

from src.adapters.sqlite import core


def test_fresh_install(tmp_path):
    db, backups = tmp_path / "p.db", tmp_path / "backups"
    assert core.init_db(db, backups) == core.SCHEMA_VERSION
    conn = core.connect(db)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        version = conn.execute("SELECT value FROM schema_meta WHERE key = 'version'").fetchone()[0]
        assert version == str(core.SCHEMA_VERSION)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"person", "journey", "journey_step", "return_evidence", "acc_invoice", "acc_item",
                "sync_state", "audit_log", "doctor_account", "cutoff_ruleset"} <= tables
    finally:
        conn.close()
    assert not backups.exists()                       # nothing to back up on a new file


def test_rerun_is_idempotent_and_takes_no_backup(tmp_path):
    db, backups = tmp_path / "p.db", tmp_path / "backups"
    core.init_db(db, backups)
    core.init_db(db, backups)
    assert not backups.exists()


def test_upgrade_takes_backup_first(tmp_path):
    db, backups = tmp_path / "p.db", tmp_path / "backups"
    core.init_db(db, backups)
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO setting VALUES ('k', 'keep me', 'test', '2026-10-06 10:00:00')")
        c.execute("UPDATE schema_meta SET value = '0' WHERE key = 'version'")
    core.init_db(db, backups)
    (copy,) = backups.glob("peygiri_panel_pre-migration-v0_*.db")
    with sqlite3.connect(copy) as c:
        assert c.execute("SELECT value FROM setting WHERE key = 'k'").fetchone()[0] == "keep me"
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT value FROM schema_meta WHERE key = 'version'").fetchone()[0] == str(core.SCHEMA_VERSION)
        assert c.execute("SELECT value FROM setting WHERE key = 'k'").fetchone()[0] == "keep me"


def test_newer_schema_refuses_to_start(tmp_path):
    db = tmp_path / "p.db"
    core.init_db(db, tmp_path / "b")
    with sqlite3.connect(db) as c:
        c.execute("UPDATE schema_meta SET value = '99' WHERE key = 'version'")
    with pytest.raises(RuntimeError, match="newer"):
        core.init_db(db, tmp_path / "b")


def test_backup_retention(tmp_path, monkeypatch):
    db = tmp_path / "p.db"
    core.init_db(db, tmp_path / "b")
    conn = core.connect(db)
    stamps = iter(f"2026010{i}-000000" for i in range(1, 8))

    class FakeNow:
        def strftime(self, _fmt):
            return next(stamps)

    monkeypatch.setattr(core.iran_time, "now", lambda: FakeNow())
    for _ in range(6):
        core.backup(conn, tmp_path / "b", "weekly")
    conn.close()
    kept = sorted(p.name for p in (tmp_path / "b").glob("peygiri_panel_weekly_*.db"))
    assert len(kept) == core.KEEP_BACKUPS and kept[0].endswith("20260103-000000.db")


def test_transaction_rolls_back(tmp_path):
    db = tmp_path / "p.db"
    core.init_db(db, tmp_path / "b")
    conn = core.connect(db)
    try:
        with pytest.raises(ZeroDivisionError):
            with core.transaction(conn):
                conn.execute("INSERT INTO setting VALUES ('a', '1', 't', 't')")
                1 / 0
        assert conn.execute("SELECT count(*) FROM setting").fetchone()[0] == 0
    finally:
        conn.close()


def test_schema_constraints_hold(tmp_path):
    db = tmp_path / "p.db"
    core.init_db(db, tmp_path / "b")
    conn = core.connect(db)
    try:
        with pytest.raises(sqlite3.IntegrityError):    # mobile must start with 09
            conn.execute("INSERT INTO person(national_id, first_name, last_name, mobile, created_at, "
                         "created_by, updated_at, updated_by) "
                         "VALUES ('0012345678', 'a', 'b', '08123456789', 't', 't', 't', 't')")
        with pytest.raises(sqlite3.IntegrityError):    # foreign keys are enforced
            conn.execute("INSERT INTO person_acc_link VALUES (1, 999, 'manual', 't', 't')")
    finally:
        conn.close()


def test_m0_upgrade_adds_visit_time_and_preserves_data(tmp_path):
    """M0 v1 did not have acc_item.item_at; an existing install must migrate."""
    db, backups = tmp_path / "m0.db", tmp_path / "backups"
    m0_schema = chr(10).join(line for line in core.schema_sql().splitlines() if not line.strip().startswith("item_at TEXT"))
    with sqlite3.connect(db) as conn:
        conn.executescript(m0_schema)
        conn.execute("INSERT INTO schema_meta VALUES ('version', '1')")
        conn.execute("INSERT INTO setting VALUES ('keep', 'value', 'test', '2026-10-06 10:00:00')")
        conn.execute("INSERT INTO acc_item(item_type, item_id, acc_invoice_id) VALUES ('visit', 1, 1)")
    assert core.init_db(db, backups) == core.SCHEMA_VERSION
    with sqlite3.connect(db) as conn:
        assert 'item_at' in {row[1] for row in conn.execute('PRAGMA table_info(acc_item)')}
        assert conn.execute("SELECT item_at FROM acc_item WHERE item_id = 1").fetchone() == (None,)
        assert conn.execute("SELECT value FROM setting WHERE key = 'keep'").fetchone() == ('value',)
    (copy,) = backups.glob('peygiri_panel_pre-migration-v1_*.db')
    with sqlite3.connect(copy) as conn:
        assert 'item_at' not in {row[1] for row in conn.execute('PRAGMA table_info(acc_item)')}
        assert conn.execute("SELECT value FROM schema_meta WHERE key = 'version'").fetchone() == ('1',)
    core.init_db(db, backups)
    assert len(list(backups.glob('*.db'))) == 1
