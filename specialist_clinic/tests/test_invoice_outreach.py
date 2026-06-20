"""
Phase 2 — Invoice-triggered outreach (thank-you + procedure-invite) test suite.

Safety contract:
  - All writes go to COPIES of the DBs, never the originals.
  - The real clinic_new.db SHA-256 is verified byte-for-byte after any test that
    reads it (Scenario 7).
  - No real SMS is sent (scheduler never starts in TESTING mode; provider is
    NullProvider / Kavenegar-430 in this env; enqueue_event_for_patient only
    inserts into engagement_approvals, it does NOT call send_single).

Run from the specialist_clinic directory:
    .venv/Scripts/python.exe -m pytest tests/test_invoice_outreach.py -v

Or from the repo root:
    specialist_clinic/.venv/Scripts/python.exe -m pytest specialist_clinic/tests/test_invoice_outreach.py -v
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
# Helpers (mirrors test_invoice_sync.py conventions)
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
    """Create a minimal accounting DB with all tables needed by accounting_bridge."""
    conn = sqlite3.connect(path)
    conn.executescript("""
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
        );
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            status TEXT DEFAULT 'open',
            total_amount REAL DEFAULT 0,
            work_date TEXT,
            closed_at TEXT,
            opened_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        );
        CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER,
            patient_id INTEGER,
            visit_date TEXT,
            doctor_name TEXT,
            price REAL DEFAULT 0,
            insurance_type TEXT,
            supplementary_insurance TEXT
        );
        CREATE TABLE IF NOT EXISTS injections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER,
            patient_id INTEGER,
            injection_type TEXT,
            total_price REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS procedures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER,
            patient_id INTEGER,
            procedure_type TEXT,
            price REAL DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()


def _acc_add_patient(conn, name, national_id=None, phone=None):
    cur = conn.execute(
        "INSERT INTO patients (name, family_name, full_name, national_id, phone_number)"
        " VALUES (?,?,?,?,?)",
        (name, "", name, national_id, phone),
    )
    conn.commit()
    return cur.lastrowid


def _acc_add_invoice(conn, patient_id, status="closed", total=1000,
                     work_date="2026-01-01", closed_at=None, invoice_id=None):
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


def _acc_add_procedure(conn, invoice_id, patient_id, procedure_type):
    cur = conn.execute(
        "INSERT INTO procedures (invoice_id, patient_id, procedure_type, price)"
        " VALUES (?, ?, ?, ?)",
        (invoice_id, patient_id, procedure_type, 500),
    )
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="outreach_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def specialist_app(tmp_dir):
    """Flask test app pointing at a fresh specialist DB in tmp_dir.

    Strict isolation: saves and restores ALL relevant env vars and module-level
    state so tests cannot pollute each other even when run in the same process.
    """
    spec_db = os.path.join(tmp_dir, "specialist_test.db")

    _saved_env = {
        "SPECIALIST_DB_PATH": os.environ.get("SPECIALIST_DB_PATH"),
        "ACCOUNTING_DB_PATH": os.environ.get("ACCOUNTING_DB_PATH"),
    }

    os.environ["SPECIALIST_DB_PATH"] = spec_db
    os.environ["ACCOUNTING_DB_PATH"] = _REAL_ACC_DB  # default; overridden per test

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

    for key, val in _saved_env.items():
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val

    try:
        import src.config.settings as cfg_mod
        cfg_mod.Config.ACCOUNTING_DB_PATH = _REAL_ACC_DB
    except Exception:
        pass

    try:
        import src.adapters.sqlite.core as core_mod
        core_mod._initialized = False
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _set_acc_path(path: str):
    """Hot-swap Config.ACCOUNTING_DB_PATH so the next bridge call uses the new path."""
    os.environ["ACCOUNTING_DB_PATH"] = path
    import src.config.settings as cfg_mod
    cfg_mod.Config.ACCOUNTING_DB_PATH = path


def _enroll_patient(national_id, full_name, phone_number=None, sms_opt_out=0):
    """Insert a patient_links row via the Flask-managed get_db() connection.

    Must be called inside an active app_context (i.e. after the specialist_app
    fixture has pushed its context). Using get_db() guarantees the schema has
    already been bootstrapped by the factory before we try to insert.
    """
    from src.adapters.sqlite.core import get_db
    db = get_db()
    cur = db.execute(
        """INSERT INTO patient_links (national_id, full_name, phone_number, sms_opt_out, enrolled_by)
           VALUES (?, ?, ?, ?, 'test')""",
        (national_id, full_name, phone_number, sms_opt_out),
    )
    db.commit()
    return cur.lastrowid


def _get_approvals(spec_db_conn, event_key=None, patient_link_id=None):
    """Fetch engagement_approvals rows matching optional filters."""
    clauses = []
    params = []
    if event_key is not None:
        clauses.append("event_key=?")
        params.append(event_key)
    if patient_link_id is not None:
        clauses.append("patient_link_id=?")
        params.append(patient_link_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return spec_db_conn.execute(
        f"SELECT * FROM engagement_approvals {where}", params
    ).fetchall()


# ===========================================================================
# Scenario 1 — Seed: three new engagement events are present after bootstrap
# ===========================================================================

class TestScenario1Seed:
    def test_thank_you_event_seeded(self, specialist_app):
        app, spec_db, _ = specialist_app
        from src.adapters.sqlite.core import get_db
        db = get_db()
        row = db.execute(
            "SELECT * FROM engagement_events WHERE event_key='thank_you'"
        ).fetchone()
        assert row is not None, "thank_you event must be seeded in engagement_events"
        assert row["channel"] == "sms", f"thank_you channel should be 'sms', got {row['channel']}"
        assert row["is_active"] == 1, "thank_you event must be active"

    def test_ear_wash_invite_event_seeded(self, specialist_app):
        app, spec_db, _ = specialist_app
        from src.adapters.sqlite.core import get_db
        db = get_db()
        row = db.execute(
            "SELECT * FROM engagement_events WHERE event_key='ear_wash_invite'"
        ).fetchone()
        assert row is not None, "ear_wash_invite event must be seeded in engagement_events"
        assert row["channel"] == "sms"
        assert row["is_active"] == 1

    def test_wound_care_invite_event_seeded(self, specialist_app):
        app, spec_db, _ = specialist_app
        from src.adapters.sqlite.core import get_db
        db = get_db()
        row = db.execute(
            "SELECT * FROM engagement_events WHERE event_key='wound_care_invite'"
        ).fetchone()
        assert row is not None, "wound_care_invite event must be seeded in engagement_events"
        assert row["channel"] == "sms"
        assert row["is_active"] == 1

    def test_engagement_approvals_table_exists(self, specialist_app):
        app, spec_db, _ = specialist_app
        from src.adapters.sqlite.core import get_db
        db = get_db()
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='engagement_approvals'"
        ).fetchone()
        assert row is not None, "engagement_approvals table must exist after bootstrap"


# ===========================================================================
# Scenario 2 — enrolled patient → thank_you approval is queued (pending)
# ===========================================================================

class TestScenario2EnrolledThankYou:
    def test_enrolled_patient_gets_thank_you_approval(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app

        # Build a minimal accounting DB with one enrolled patient + closed invoice
        acc_db = os.path.join(tmp_dir, "acc_s2.db")
        _make_acc_db(acc_db)
        acc_conn = sqlite3.connect(acc_db)
        pid_acc = _acc_add_patient(acc_conn, "علی رضایی", national_id="7700000001",
                                   phone="09120000001")
        inv_id = _acc_add_invoice(acc_conn, pid_acc, "closed",
                                  work_date="2026-06-10",
                                  closed_at="2026-06-10 10:00:00")
        acc_conn.close()

        # Enroll the patient in the specialist DB (must use get_db() so schema is bootstrapped)
        from src.adapters.sqlite.core import get_db
        db = get_db()
        plid = _enroll_patient("7700000001", "علی رضایی",
                               phone_number="09120000001")

        _set_acc_path(acc_db)
        from src.services.invoice_sync_service import InvoiceSyncService
        res = InvoiceSyncService().run()
        assert res["new"] == 1, f"Expected 1 new invoice, got {res['new']}"

        # Verify engagement_approvals has a pending thank_you row
        rows = db.execute(
            "SELECT * FROM engagement_approvals WHERE event_key='thank_you' AND status='pending'"
        ).fetchall()
        assert len(rows) == 1, (
            f"Expected exactly 1 pending thank_you approval, got {len(rows)}"
        )
        row = dict(rows[0])
        assert row["patient_link_id"] == plid, (
            f"Approval patient_link_id should be {plid}, got {row['patient_link_id']}"
        )
        assert row["status"] == "pending"
        # period_key should be thank_you:<work_date>
        assert row["period_key"] == "thank_you:2026-06-10", (
            f"Expected period_key 'thank_you:2026-06-10', got {row['period_key']}"
        )


# ===========================================================================
# Scenario 3 — idempotency: second sync with same invoice → no duplicate approval
# ===========================================================================

class TestScenario3Idempotency:
    def test_duplicate_thank_you_not_created_on_second_sync(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app

        acc_db = os.path.join(tmp_dir, "acc_s3.db")
        _make_acc_db(acc_db)
        acc_conn = sqlite3.connect(acc_db)
        pid_acc = _acc_add_patient(acc_conn, "سارا احمدی", national_id="7700000002",
                                   phone="09120000002")
        _acc_add_invoice(acc_conn, pid_acc, "closed",
                         work_date="2026-06-11",
                         closed_at="2026-06-11 09:00:00")
        acc_conn.close()

        _enroll_patient("7700000002", "سارا احمدی",
                        phone_number="09120000002")

        _set_acc_path(acc_db)
        from src.services.invoice_sync_service import InvoiceSyncService

        # First sync
        res1 = InvoiceSyncService().run()
        assert res1["new"] == 1

        # Reset cursor to force re-processing the same invoice
        from src.adapters.sqlite.core import get_db
        db = get_db()
        db.execute("DELETE FROM settings WHERE key='invoice_sync_last_id'")
        db.commit()

        # Second sync (same invoice; processed_invoices UNIQUE prevents re-insert)
        res2 = InvoiceSyncService().run()
        assert res2["new"] == 0, (
            f"Second sync must produce 0 new (idempotent), got {res2['new']}"
        )

        # Approval queue must still have exactly ONE pending thank_you row
        rows = db.execute(
            "SELECT * FROM engagement_approvals WHERE event_key='thank_you'"
        ).fetchall()
        assert len(rows) == 1, (
            f"Expected exactly 1 thank_you approval (no duplicate), got {len(rows)}"
        )


# ===========================================================================
# Scenario 4 — walk-in (pending_link): no approval created
# ===========================================================================

class TestScenario4WalkIn:
    def test_walk_in_patient_produces_no_approval(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app

        acc_db = os.path.join(tmp_dir, "acc_s4.db")
        _make_acc_db(acc_db)
        acc_conn = sqlite3.connect(acc_db)
        # Patient NOT enrolled in specialist (no patient_links row)
        pid_acc = _acc_add_patient(acc_conn, "بیمارِ گذری", national_id="7700000003",
                                   phone="09120000003")
        _acc_add_invoice(acc_conn, pid_acc, "closed",
                         work_date="2026-06-12",
                         closed_at="2026-06-12 11:00:00")
        acc_conn.close()

        _set_acc_path(acc_db)
        from src.services.invoice_sync_service import InvoiceSyncService
        res = InvoiceSyncService().run()

        assert res["new"] == 1
        assert res["pending_link"] == 1, "Walk-in patient should be pending_link"

        from src.adapters.sqlite.core import get_db
        db = get_db()
        rows = db.execute("SELECT * FROM engagement_approvals").fetchall()
        assert len(rows) == 0, (
            f"Walk-in (no patient_links row) must produce zero approvals, got {len(rows)}"
        )


# ===========================================================================
# Scenario 5 — guardrails: no phone OR sms_opt_out=1 → no approval
# ===========================================================================

class TestScenario5Guardrails:
    def test_no_phone_produces_no_approval(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app

        acc_db = os.path.join(tmp_dir, "acc_s5a.db")
        _make_acc_db(acc_db)
        acc_conn = sqlite3.connect(acc_db)
        pid_acc = _acc_add_patient(acc_conn, "بدون موبایل", national_id="7700000004",
                                   phone=None)  # no phone
        _acc_add_invoice(acc_conn, pid_acc, "closed",
                         work_date="2026-06-13",
                         closed_at="2026-06-13 10:00:00")
        acc_conn.close()

        _enroll_patient("7700000004", "بدون موبایل",
                        phone_number=None)  # enrolled but no phone

        _set_acc_path(acc_db)
        from src.services.invoice_sync_service import InvoiceSyncService
        InvoiceSyncService().run()

        from src.adapters.sqlite.core import get_db
        db = get_db()
        rows = db.execute("SELECT * FROM engagement_approvals").fetchall()
        assert len(rows) == 0, (
            f"Enrolled patient without phone must produce zero approvals, got {len(rows)}"
        )

    def test_sms_opt_out_produces_no_approval(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app

        acc_db = os.path.join(tmp_dir, "acc_s5b.db")
        _make_acc_db(acc_db)
        acc_conn = sqlite3.connect(acc_db)
        pid_acc = _acc_add_patient(acc_conn, "انصراف‌داده", national_id="7700000005",
                                   phone="09120000005")
        _acc_add_invoice(acc_conn, pid_acc, "closed",
                         work_date="2026-06-14",
                         closed_at="2026-06-14 10:00:00")
        acc_conn.close()

        _enroll_patient("7700000005", "انصراف‌داده",
                        phone_number="09120000005", sms_opt_out=1)  # opted out

        _set_acc_path(acc_db)
        from src.services.invoice_sync_service import InvoiceSyncService
        InvoiceSyncService().run()

        from src.adapters.sqlite.core import get_db
        db = get_db()
        rows = db.execute("SELECT * FROM engagement_approvals").fetchall()
        assert len(rows) == 0, (
            f"sms_opt_out=1 patient must produce zero approvals, got {len(rows)}"
        )


# ===========================================================================
# Scenario 6 — procedure invite routing
# ===========================================================================

class TestScenario6ProcedureInvites:

    def _setup_acc_with_procedure(self, tmp_dir, suffix, national_id, procedure_type):
        acc_db = os.path.join(tmp_dir, f"acc_s6_{suffix}.db")
        _make_acc_db(acc_db)
        acc_conn = sqlite3.connect(acc_db)
        pid_acc = _acc_add_patient(acc_conn, f"بیمار{suffix}", national_id=national_id,
                                   phone=f"0912000{suffix}")
        inv_id = _acc_add_invoice(acc_conn, pid_acc, "closed",
                                  work_date="2026-06-15",
                                  closed_at="2026-06-15 10:00:00")
        if procedure_type:
            _acc_add_procedure(acc_conn, inv_id, pid_acc, procedure_type)
        acc_conn.close()
        return acc_db, national_id

    def test_ear_wash_procedure_creates_ear_wash_invite(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app
        acc_db, nid = self._setup_acc_with_procedure(
            tmp_dir, "ear", "7700000006", "شستشوی گوش"
        )

        _enroll_patient(nid, "بیمارear", phone_number="09120006001")

        _set_acc_path(acc_db)
        from src.services.invoice_sync_service import InvoiceSyncService
        InvoiceSyncService().run()

        from src.adapters.sqlite.core import get_db
        db = get_db()
        # Should have: thank_you + ear_wash_invite
        keys = {r["event_key"] for r in db.execute(
            "SELECT event_key FROM engagement_approvals").fetchall()}
        assert "thank_you" in keys, "thank_you approval must exist for enrolled patient"
        assert "ear_wash_invite" in keys, (
            "ear_wash_invite approval must exist when procedure_type contains 'شستشوی گوش'"
        )
        assert "wound_care_invite" not in keys, (
            "wound_care_invite must NOT appear for an ear-wash procedure"
        )

    def test_wound_care_procedure_creates_wound_care_invite(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app
        acc_db, nid = self._setup_acc_with_procedure(
            tmp_dir, "wound", "7700000007", "پانسمان زخم"
        )

        _enroll_patient(nid, "بیمارwound", phone_number="09120007001")

        _set_acc_path(acc_db)
        from src.services.invoice_sync_service import InvoiceSyncService
        InvoiceSyncService().run()

        from src.adapters.sqlite.core import get_db
        db = get_db()
        keys = {r["event_key"] for r in db.execute(
            "SELECT event_key FROM engagement_approvals").fetchall()}
        assert "thank_you" in keys
        assert "wound_care_invite" in keys, (
            "wound_care_invite must exist when procedure_type contains 'پانسمان'"
        )
        assert "ear_wash_invite" not in keys

    def test_suture_removal_creates_wound_care_invite(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app
        acc_db, nid = self._setup_acc_with_procedure(
            tmp_dir, "suture", "7700000008", "کشیدن بخیه"
        )

        _enroll_patient(nid, "بیمارsuture", phone_number="09120008001")

        _set_acc_path(acc_db)
        from src.services.invoice_sync_service import InvoiceSyncService
        InvoiceSyncService().run()

        from src.adapters.sqlite.core import get_db
        db = get_db()
        keys = {r["event_key"] for r in db.execute(
            "SELECT event_key FROM engagement_approvals").fetchall()}
        assert "wound_care_invite" in keys, (
            "wound_care_invite must exist for 'کشیدن بخیه' (suture-removal keyword)"
        )

    def test_unrelated_procedure_produces_only_thank_you(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app
        # A procedure that doesn't match any keyword
        acc_db, nid = self._setup_acc_with_procedure(
            tmp_dir, "other", "7700000009", "ویزیت عمومی"
        )

        _enroll_patient(nid, "بیمارother", phone_number="09120009001")

        _set_acc_path(acc_db)
        from src.services.invoice_sync_service import InvoiceSyncService
        InvoiceSyncService().run()

        from src.adapters.sqlite.core import get_db
        db = get_db()
        rows = db.execute("SELECT event_key FROM engagement_approvals").fetchall()
        keys = {r["event_key"] for r in rows}
        assert "thank_you" in keys, "thank_you must still be created for enrolled patient"
        assert "ear_wash_invite" not in keys, (
            "ear_wash_invite must NOT appear for unrelated procedure"
        )
        assert "wound_care_invite" not in keys, (
            "wound_care_invite must NOT appear for unrelated procedure"
        )
        assert len(rows) == 1, (
            f"Only 1 approval (thank_you) expected for unrelated procedure, got {len(rows)}"
        )


# ===========================================================================
# Scenario 7 — zero-write safety: real clinic_new.db byte-unchanged
# ===========================================================================

@pytest.mark.skipif(
    not os.path.exists(_REAL_ACC_DB),
    reason=f"Real accounting DB not found at {_REAL_ACC_DB}"
)
class TestScenario7ZeroWrite:
    def test_real_acc_db_unchanged_after_outreach_sync(self, specialist_app, tmp_dir):
        """on_invoice_processed (Phase 2) reads accounting_bridge.fetch_invoice_items
        read-only. Verify the real clinic_new.db bytes are untouched."""
        app, spec_db, _ = specialist_app

        sha_before = _sha256(_REAL_ACC_DB)
        wal_path = _REAL_ACC_DB + "-wal"
        shm_path = _REAL_ACC_DB + "-shm"
        wal_existed_before = os.path.exists(wal_path)
        shm_existed_before = os.path.exists(shm_path)

        # Run against the real accounting DB
        _set_acc_path(_REAL_ACC_DB)
        from src.services.invoice_sync_service import InvoiceSyncService
        res = InvoiceSyncService().run()

        sha_after = _sha256(_REAL_ACC_DB)
        assert sha_before == sha_after, (
            f"clinic_new.db was MODIFIED during a read-only sync!\n"
            f"  before: {sha_before}\n"
            f"  after:  {sha_after}"
        )

        if not wal_existed_before:
            assert not os.path.exists(wal_path), (
                "A WAL file was created on clinic_new.db — indicates a write attempt"
            )
        if not shm_existed_before:
            assert not os.path.exists(shm_path), (
                "A SHM file was created on clinic_new.db — indicates a write attempt"
            )

        print(f"\n[SCENARIO 7] SHA-256 before: {sha_before}")
        print(f"[SCENARIO 7] SHA-256 after:  {sha_after}")
        print(f"[SCENARIO 7] MATCH: {sha_before == sha_after} | fetched={res['fetched']}")
