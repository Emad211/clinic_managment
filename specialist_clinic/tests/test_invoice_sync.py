"""
ADR-0003 D3+ — Invoice-sync consumer test suite (adversarial).

Safety contract:
  - All writes go to COPIES of the DBs, never to the originals.
  - The real clinic_new.db SHA-256 is verified byte-for-byte after any test
    that even reads it (scenario 9).
  - No real SMS is sent (scheduler never starts in TESTING mode).

Run from the specialist_clinic directory:
    .venv/Scripts/python.exe -m pytest tests/test_invoice_sync.py -v
Or from the repo root:
    specialist_clinic/.venv/Scripts/python.exe -m pytest specialist_clinic/tests/test_invoice_sync.py -v
"""
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

# ── Patch env vars BEFORE any src import (Config is read at import time) ─────
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_REAL_ACC_DB = os.path.join(_REPO_ROOT, "webapp", "clinic_new.db")
_SPECIALIST_ROOT = os.path.join(_REPO_ROOT, "specialist_clinic")

import hashlib
import shutil
import sqlite3
import tempfile
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flush_src_modules():
    """Delete all src.* modules from sys.modules so the next import re-reads
    env vars and produces a clean Config / core._initialized state."""
    for mod in list(sys.modules.keys()):
        if mod == "src" or mod.startswith("src."):
            del sys.modules[mod]


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_acc_db(path: str):
    """Create a minimal accounting DB (invoices + patients) at *path*."""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            family_name TEXT,
            full_name TEXT,
            national_id TEXT UNIQUE,
            phone_number TEXT,
            birthdate TEXT,
            gender TEXT,
            insurance_type TEXT,
            insurance_expiry TEXT,
            address TEXT,
            is_foreign INTEGER DEFAULT 0,
            created_by TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            status TEXT DEFAULT 'open',
            total_amount REAL DEFAULT 0,
            work_date TEXT,
            closed_at TEXT,
            opened_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        )
    """)
    conn.commit()
    conn.close()


def _acc_add_patient(conn, name, national_id=None, phone=None):
    """Insert a patient row; return its id."""
    cur = conn.execute(
        "INSERT INTO patients (name, family_name, full_name, national_id, phone_number) VALUES (?,?,?,?,?)",
        (name, "", name, national_id, phone),
    )
    conn.commit()
    return cur.lastrowid


def _acc_add_invoice(conn, patient_id, status, total=1000, work_date="2026-01-01",
                     closed_at=None, invoice_id=None):
    """Insert an invoice row. If invoice_id is given it is used as rowid."""
    ca = closed_at or ("2026-01-01 10:00:00" if status == "closed" else None)
    if invoice_id is not None:
        cur = conn.execute(
            "INSERT INTO invoices (id, patient_id, status, total_amount, work_date, closed_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (invoice_id, patient_id, status, total, work_date, ca),
        )
    else:
        cur = conn.execute(
            "INSERT INTO invoices (patient_id, status, total_amount, work_date, closed_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (patient_id, status, total, work_date, ca),
        )
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="inv_sync_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def specialist_app(tmp_dir):
    """Flask test app pointing at a fresh specialist DB in tmp_dir.

    Strict isolation: saves and restores ALL relevant env vars and module-level
    state so tests cannot pollute each other even when run in the same process.
    """
    spec_db = os.path.join(tmp_dir, "specialist_test.db")

    # ── Save environment state ────────────────────────────────────────────────
    _saved_env = {
        "SPECIALIST_DB_PATH": os.environ.get("SPECIALIST_DB_PATH"),
        "ACCOUNTING_DB_PATH": os.environ.get("ACCOUNTING_DB_PATH"),
    }

    # Point both paths at this test's tmp dir before any import
    os.environ["SPECIALIST_DB_PATH"] = spec_db
    os.environ["ACCOUNTING_DB_PATH"] = _REAL_ACC_DB  # default; overridden per test

    # ── Flush cached modules so Config re-reads env vars ─────────────────────
    _flush_src_modules()

    sys.path.insert(0, _SPECIALIST_ROOT)
    from src.app import create_app
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": spec_db,
        "PROPAGATE_EXCEPTIONS": True,
        "SECRET_KEY": "test-secret",
        "BACKUP_FOLDER": os.path.join(tmp_dir, "backups"),
    })

    ctx = app.app_context()
    ctx.push()

    yield app, spec_db, tmp_dir

    ctx.pop()

    # ── Restore env vars to pre-test state ───────────────────────────────────
    for key, val in _saved_env.items():
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val

    # ── Also reset Config class attribute to a clean state ───────────────────
    try:
        import src.config.settings as cfg_mod
        cfg_mod.Config.ACCOUNTING_DB_PATH = _REAL_ACC_DB
    except Exception:
        pass

    # ── Reset _initialized so next test bootstraps fresh ─────────────────────
    try:
        import src.adapters.sqlite.core as core_mod
        core_mod._initialized = False
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Utilities to re-point accounting bridge at a different path mid-test
# ---------------------------------------------------------------------------

def _set_acc_path(path: str):
    """Hot-swap Config.ACCOUNTING_DB_PATH so the next bridge call uses the new path.

    Patches both os.environ and the Config class attribute (which _connect_ro reads
    at call time). Does NOT need to reload accounting_bridge — _connect_ro reads
    Config.ACCOUNTING_DB_PATH dynamically, so patching the class attribute is
    sufficient. Reloading invoice_sync_service is also avoided; it holds a module
    reference to accounting_bridge but calls Config at runtime through it.
    """
    os.environ["ACCOUNTING_DB_PATH"] = path
    import src.config.settings as cfg_mod
    cfg_mod.Config.ACCOUNTING_DB_PATH = path


def _reset_cursor(app_ctx_app):
    """Reset the invoice_sync_last_id cursor to 0 in the settings table."""
    from src.adapters.sqlite.core import get_db
    db = get_db()
    db.execute("DELETE FROM settings WHERE key = 'invoice_sync_last_id'")
    db.commit()


# ===========================================================================
# Scenario 1 — bootstrap: processed_invoices table exists + PRAGMA busy_timeout
# ===========================================================================

class TestScenario1Bootstrap:
    def test_table_exists_after_bootstrap(self, specialist_app):
        app, spec_db, _ = specialist_app
        from src.adapters.sqlite.core import get_db
        db = get_db()
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='processed_invoices'"
        ).fetchone()
        assert row is not None, "processed_invoices table should exist after bootstrap"

    def test_busy_timeout_is_set(self, specialist_app):
        """get_db() sets PRAGMA busy_timeout = 3000 on every specialist connection."""
        app, spec_db, _ = specialist_app
        from src.adapters.sqlite.core import get_db
        db = get_db()
        row = db.execute("PRAGMA busy_timeout").fetchone()
        # SQLite returns the current busy_timeout value
        timeout_val = row[0] if row else None
        assert timeout_val == 3000, (
            f"PRAGMA busy_timeout should be 3000, got {timeout_val}"
        )


# ===========================================================================
# Scenario 2 — only CLOSED invoices are recorded; OPEN ones are skipped
# ===========================================================================

class TestScenario2ClosedVsOpen:
    def test_only_closed_invoices_recorded(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app
        acc_db = os.path.join(tmp_dir, "acc_s2.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        pid = _acc_add_patient(conn, "علی محمدی", national_id="1111111111")
        _acc_add_invoice(conn, pid, "closed", total=5000, work_date="2026-03-01",
                         closed_at="2026-03-01 09:00:00")
        _acc_add_invoice(conn, pid, "open", total=2000)
        _acc_add_invoice(conn, pid, "open", total=3000)
        conn.close()

        _set_acc_path(acc_db)
        from src.services.invoice_sync_service import InvoiceSyncService
        res = InvoiceSyncService().run()

        assert res["fetched"] == 1, f"Only 1 closed invoice should be fetched, got {res['fetched']}"
        assert res["new"] == 1, f"1 new record expected, got {res['new']}"

        from src.adapters.sqlite.core import get_db
        db = get_db()
        count = db.execute("SELECT COUNT(*) c FROM processed_invoices").fetchone()["c"]
        assert count == 1, f"processed_invoices should have 1 row, got {count}"


# ===========================================================================
# Scenario 3 — idempotency: running twice inserts nothing the second time
# ===========================================================================

class TestScenario3Idempotency:
    def test_second_run_inserts_zero(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app
        acc_db = os.path.join(tmp_dir, "acc_s3.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        pid = _acc_add_patient(conn, "سارا احمدی", national_id="2222222222")
        _acc_add_invoice(conn, pid, "closed", total=1000,
                         closed_at="2026-03-01 10:00:00")
        _acc_add_invoice(conn, pid, "closed", total=1500,
                         closed_at="2026-03-02 10:00:00")
        conn.close()

        _set_acc_path(acc_db)
        from src.services.invoice_sync_service import InvoiceSyncService

        # First run
        res1 = InvoiceSyncService().run()
        assert res1["new"] == 2, f"Expected 2 new on first run, got {res1['new']}"

        # Reset cursor to 0 to simulate a re-run from scratch (worst-case idempotency)
        _reset_cursor(app)
        res2 = InvoiceSyncService().run()
        assert res2["new"] == 0, (
            f"Second run with reset cursor should find 0 new (all already recorded), "
            f"got {res2['new']}"
        )

        # No duplicate accounting_invoice_ids
        from src.adapters.sqlite.core import get_db
        db = get_db()
        dups = db.execute(
            "SELECT accounting_invoice_id, COUNT(*) c FROM processed_invoices "
            "GROUP BY accounting_invoice_id HAVING c > 1"
        ).fetchall()
        assert len(dups) == 0, f"Duplicate accounting_invoice_ids found: {list(dups)}"


# ===========================================================================
# Scenario 4 — cursor advancement: a new high-id closed invoice is picked up
# ===========================================================================

class TestScenario4CursorAdvancement:
    def test_new_high_id_invoice_picked_up(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app
        acc_db = os.path.join(tmp_dir, "acc_s4.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        pid = _acc_add_patient(conn, "رضا کریمی", national_id="3333333333")
        inv_id1 = _acc_add_invoice(conn, pid, "closed", total=500,
                                   closed_at="2026-03-01 10:00:00")
        conn.close()

        _set_acc_path(acc_db)
        from src.services.invoice_sync_service import InvoiceSyncService
        res1 = InvoiceSyncService().run()
        assert res1["new"] == 1
        cursor_after_first = res1["cursor"]

        # Add a new higher-id closed invoice
        conn = sqlite3.connect(acc_db)
        inv_id2 = _acc_add_invoice(conn, pid, "closed", total=750,
                                   closed_at="2026-03-10 10:00:00")
        conn.close()
        assert inv_id2 > inv_id1, "New invoice should have higher id"

        res2 = InvoiceSyncService().run()
        assert res2["new"] == 1, (
            f"Second run should pick up exactly 1 new invoice, got {res2['new']}"
        )
        assert res2["cursor"] == inv_id2, (
            f"Cursor should advance to {inv_id2}, got {res2['cursor']}"
        )

        from src.adapters.sqlite.core import get_db
        db = get_db()
        total = db.execute("SELECT COUNT(*) c FROM processed_invoices").fetchone()["c"]
        assert total == 2, f"Total records should be 2, got {total}"


# ===========================================================================
# Scenario 5 — floor branch: late-closed low-id invoice is caught by closed_at
# ===========================================================================

class TestScenario5FloorBranch:
    def test_late_closed_low_id_is_caught(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app
        acc_db = os.path.join(tmp_dir, "acc_s5.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        pid = _acc_add_patient(conn, "مینا حسینی", national_id="4444444444")

        # Insert a batch of closed invoices with id 1..10 then advance cursor to 10
        for i in range(1, 11):
            _acc_add_invoice(conn, pid, "closed", total=100 * i,
                             invoice_id=i,
                             closed_at="2025-01-01 10:00:00")
        conn.close()

        _set_acc_path(acc_db)
        from src.services.invoice_sync_service import InvoiceSyncService
        res1 = InvoiceSyncService().run()
        assert res1["new"] == 10

        # Now insert a low-id (id=5 already exists — use 11 but manually set a
        # small enough id). Instead, simulate: a NEW invoice with id=3 that was
        # somehow missed. Since the UNIQUE key prevents re-inserting id=3, we
        # instead use a different approach: set cursor to 100 (past all existing
        # ids), then insert a late-closed invoice with id=11 but closed_at within
        # the last 30 days (which is the floor window).
        from src.adapters.sqlite.core import get_db
        db = get_db()
        db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('invoice_sync_last_id', '100')")
        db.commit()

        # New invoice: id=11 (past cursor) but also one with id=5 that is being
        # "late-closed" now — we can't insert id=5 again (already in processed_invoices).
        # The real test: insert id=50 (below cursor=100) with a RECENT closed_at
        # (within 30 days from today). The floor branch should catch it.
        conn = sqlite3.connect(acc_db)
        late_closed_at = "2026-06-19 15:00:00"  # within FLOOR_DAYS=30 of 2026-06-20
        _acc_add_invoice(conn, pid, "closed", total=9999, invoice_id=50,
                         closed_at=late_closed_at)
        conn.close()

        res2 = InvoiceSyncService().run()
        assert res2["new"] == 1, (
            f"Floor branch should catch the late-closed low-id invoice (id=50 < cursor=100), "
            f"got new={res2['new']}, fetched={res2['fetched']}"
        )

        rows = db.execute(
            "SELECT * FROM processed_invoices WHERE accounting_invoice_id = 50"
        ).fetchall()
        assert len(rows) == 1, "Late-closed invoice id=50 must appear in processed_invoices"


# ===========================================================================
# Scenario 6 — applied vs pending_link mapping
# ===========================================================================

class TestScenario6StatusMapping:
    def test_applied_when_patient_enrolled_pending_when_not(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app
        acc_db = os.path.join(tmp_dir, "acc_s6.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)

        # Patient A — has a patient_link in specialist
        pid_a = _acc_add_patient(conn, "علی رضایی", national_id="5555555555")
        inv_a = _acc_add_invoice(conn, pid_a, "closed", total=2000,
                                  closed_at="2026-03-05 10:00:00")

        # Patient B — no patient_link in specialist
        pid_b = _acc_add_patient(conn, "بیتا موسوی", national_id="6666666666")
        inv_b = _acc_add_invoice(conn, pid_b, "closed", total=3000,
                                  closed_at="2026-03-06 10:00:00")
        conn.close()

        # Insert patient_link for patient A only
        from src.adapters.sqlite.core import get_db
        db = get_db()
        db.execute(
            """INSERT INTO patient_links (national_id, full_name, enrolled_by)
               VALUES ('5555555555', 'علی رضایی', 'test')"""
        )
        db.commit()

        _set_acc_path(acc_db)
        from src.services.invoice_sync_service import InvoiceSyncService
        res = InvoiceSyncService().run()
        assert res["new"] == 2

        row_a = db.execute(
            "SELECT * FROM processed_invoices WHERE accounting_invoice_id = ?", (inv_a,)
        ).fetchone()
        row_b = db.execute(
            "SELECT * FROM processed_invoices WHERE accounting_invoice_id = ?", (inv_b,)
        ).fetchone()

        assert row_a is not None, "Invoice A should be recorded"
        assert dict(row_a)["status"] == "applied", (
            f"Invoice A (enrolled patient) should be 'applied', got {dict(row_a)['status']}"
        )
        assert dict(row_a)["patient_link_id"] is not None, "patient_link_id must be set for enrolled patient"

        assert row_b is not None, "Invoice B should be recorded"
        assert dict(row_b)["status"] == "pending_link", (
            f"Invoice B (unenrolled patient) should be 'pending_link', got {dict(row_b)['status']}"
        )
        assert dict(row_b)["patient_link_id"] is None, "patient_link_id must be NULL for unenrolled"


# ===========================================================================
# Scenario 7 — patient with no national_id → pending_link, no crash
# ===========================================================================

class TestScenario7NullNationalId:
    def test_null_national_id_becomes_pending_link(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app
        acc_db = os.path.join(tmp_dir, "acc_s7.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        # Patient with no national_id
        pid = _acc_add_patient(conn, "بیمار ناشناس", national_id=None)
        inv_id = _acc_add_invoice(conn, pid, "closed", total=500,
                                   closed_at="2026-03-07 10:00:00")
        conn.close()

        _set_acc_path(acc_db)
        from src.services.invoice_sync_service import InvoiceSyncService
        # Must not raise
        res = InvoiceSyncService().run()

        assert res["new"] == 1, f"Invoice with null national_id should still be recorded, got new={res['new']}"
        assert res["pending_link"] == 1, "Should be pending_link since national_id is null"

        from src.adapters.sqlite.core import get_db
        db = get_db()
        row = db.execute(
            "SELECT * FROM processed_invoices WHERE accounting_invoice_id = ?", (inv_id,)
        ).fetchone()
        assert row is not None
        assert dict(row)["status"] == "pending_link"
        assert dict(row)["patient_link_id"] is None
        assert dict(row)["national_id"] is None


# ===========================================================================
# Scenario 8 — fail-loud: missing invoices table → exception propagates;
#              cursor does NOT advance; missing file → [] (no crash)
# ===========================================================================

class TestScenario8FailLoud:
    def test_missing_invoices_table_raises_exception(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app

        # Create an accounting DB with NO invoices table (just patients)
        bad_acc_db = os.path.join(tmp_dir, "acc_bad.db")
        conn = sqlite3.connect(bad_acc_db)
        conn.execute("CREATE TABLE patients (id INTEGER PRIMARY KEY, national_id TEXT)")
        conn.commit()
        conn.close()

        _set_acc_path(bad_acc_db)

        # Record the cursor BEFORE the bad run
        from src.adapters.sqlite.core import get_db
        db = get_db()
        db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('invoice_sync_last_id', '42')")
        db.commit()

        from src.services.invoice_sync_service import InvoiceSyncService
        with pytest.raises(Exception):
            InvoiceSyncService().run()

        # Cursor must NOT have advanced
        cursor_row = db.execute(
            "SELECT value FROM settings WHERE key='invoice_sync_last_id'"
        ).fetchone()
        cursor_val = int(cursor_row["value"] if cursor_row else 0)
        assert cursor_val == 42, (
            f"Cursor must not advance on failure; expected 42, got {cursor_val}"
        )

    def test_missing_accounting_file_returns_empty_no_crash(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app
        nonexistent = os.path.join(tmp_dir, "does_not_exist.db")
        _set_acc_path(nonexistent)

        from src.services.invoice_sync_service import InvoiceSyncService
        # Must NOT raise — returns [] gracefully
        res = InvoiceSyncService().run()
        assert res["fetched"] == 0, f"Missing acc file should return fetched=0, got {res['fetched']}"
        assert res["new"] == 0


# ===========================================================================
# Scenario 9 — zero-write safety: real clinic_new.db byte-unchanged after read
# ===========================================================================

@pytest.mark.skipif(
    not os.path.exists(_REAL_ACC_DB),
    reason=f"Real accounting DB not found at {_REAL_ACC_DB}"
)
class TestScenario9ZeroWrite:
    def test_real_acc_db_unchanged_after_sync(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app

        sha_before = _sha256(_REAL_ACC_DB)

        # Also verify no WAL or SHM sidecar files appeared
        wal_path = _REAL_ACC_DB + "-wal"
        shm_path = _REAL_ACC_DB + "-shm"
        wal_existed_before = os.path.exists(wal_path)
        shm_existed_before = os.path.exists(shm_path)

        _set_acc_path(_REAL_ACC_DB)
        from src.services.invoice_sync_service import InvoiceSyncService
        # Run the sync — this reads the real DB read-only
        res = InvoiceSyncService().run()

        sha_after = _sha256(_REAL_ACC_DB)
        assert sha_before == sha_after, (
            f"clinic_new.db was MODIFIED during a read-only sync!\n"
            f"  before: {sha_before}\n"
            f"  after:  {sha_after}"
        )

        # WAL/SHM must not have been newly created (a new WAL = a write occurred)
        if not wal_existed_before:
            assert not os.path.exists(wal_path), (
                "A WAL file was created on clinic_new.db — this indicates a write attempt"
            )
        if not shm_existed_before:
            assert not os.path.exists(shm_path), (
                "A SHM file was created on clinic_new.db — this indicates a write attempt"
            )

        print(f"\n[SCENARIO 9] SHA-256 before: {sha_before}")
        print(f"[SCENARIO 9] SHA-256 after:  {sha_after}")
        print(f"[SCENARIO 9] MATCH: {sha_before == sha_after} | fetched={res['fetched']}")
