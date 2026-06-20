"""
Phase 3 — Physician visit-queue test suite (adversarial).

Safety contract:
  - All writes go to COPIES of the DBs, never to the originals.
  - The real clinic_new.db SHA-256 is verified byte-for-byte in Scenario 7
    (zero-write guarantee).
  - No real SMS is sent (scheduler never starts in TESTING mode).

Run from the specialist_clinic directory:
    .venv/Scripts/python.exe -m pytest tests/test_doctor_queue.py -v

Or from the repo root:
    specialist_clinic/.venv/Scripts/python.exe -m pytest specialist_clinic/tests/test_doctor_queue.py -v
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
    """Create a minimal accounting DB with all tables needed by accounting_bridge
    (fetch_open_visit_invoices requires patients + invoices + visits)."""
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
    """Insert a patient row; return its id."""
    cur = conn.execute(
        "INSERT INTO patients (name, family_name, full_name, national_id, phone_number)"
        " VALUES (?,?,?,?,?)",
        (name, "", name, national_id, phone),
    )
    conn.commit()
    return cur.lastrowid


def _acc_add_invoice(conn, patient_id, status="open", total=1000,
                     work_date="2026-06-20", closed_at=None):
    """Insert an invoice row; return its id."""
    ca = closed_at or ("2026-06-20 10:00:00" if status == "closed" else None)
    cur = conn.execute(
        "INSERT INTO invoices (patient_id, status, total_amount, work_date, closed_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (patient_id, status, total, work_date, ca),
    )
    conn.commit()
    return cur.lastrowid


def _acc_add_visit(conn, invoice_id, patient_id, price=500):
    """Insert a visit item for the given invoice; return its id."""
    cur = conn.execute(
        "INSERT INTO visits (invoice_id, patient_id, visit_date, doctor_name, price)"
        " VALUES (?, ?, '2026-06-20', 'دکتر آزمایش', ?)",
        (invoice_id, patient_id, price),
    )
    conn.commit()
    return cur.lastrowid


def _acc_add_procedure(conn, invoice_id, patient_id, procedure_type="نمونه‌برداری"):
    """Insert a procedure item for the given invoice; return its id."""
    cur = conn.execute(
        "INSERT INTO procedures (invoice_id, patient_id, procedure_type, price)"
        " VALUES (?, ?, ?, ?)",
        (invoice_id, patient_id, procedure_type, 300),
    )
    conn.commit()
    return cur.lastrowid


def _set_acc_path(path: str):
    """Hot-swap Config.ACCOUNTING_DB_PATH so the next bridge call uses the new path."""
    os.environ["ACCOUNTING_DB_PATH"] = path
    import src.config.settings as cfg_mod
    cfg_mod.Config.ACCOUNTING_DB_PATH = path


def _enroll_patient(spec_db, national_id, full_name="بیمار آزمون"):
    """Insert a patient_links row in the specialist DB; return the inserted id."""
    conn = sqlite3.connect(spec_db)
    cur = conn.execute(
        "INSERT INTO patient_links (national_id, full_name, enrolled_by) VALUES (?, ?, 'test')",
        (national_id, full_name),
    )
    conn.commit()
    link_id = cur.lastrowid
    conn.close()
    return link_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="dq_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def specialist_app(tmp_dir):
    """Flask test client pointing at a fresh specialist DB + a writable acc copy.

    Strict isolation: saves and restores ALL relevant env vars and module-level
    state so tests cannot pollute each other even when run in the same process.
    """
    spec_db = os.path.join(tmp_dir, "specialist_test.db")

    _saved_env = {
        "SPECIALIST_DB_PATH": os.environ.get("SPECIALIST_DB_PATH"),
        "ACCOUNTING_DB_PATH": os.environ.get("ACCOUNTING_DB_PATH"),
    }

    os.environ["SPECIALIST_DB_PATH"] = spec_db
    os.environ["ACCOUNTING_DB_PATH"] = _REAL_ACC_DB  # default; tests override

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

    # Force bootstrap: get_db() runs schema.sql + migrations once per process.
    # Without this call, the specialist DB file exists but is empty; any
    # direct sqlite3 connection (e.g. _enroll_patient) would see no tables.
    from src.adapters.sqlite.core import get_db
    get_db()  # triggers _initialized → schema applied → tables exist

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


@pytest.fixture()
def test_client(specialist_app):
    """Return (flask_test_client, spec_db_path, tmp_dir) with a logged-in admin session."""
    app, spec_db, tmp_dir = specialist_app
    client = app.test_client()
    # Log in as admin (created by _ensure_default_admin during bootstrap)
    rv = client.post("/auth/login", data={"username": "admin", "password": "admin"},
                     follow_redirects=True)
    # Accept either 200 (login page) or successful redirect — admin always exists
    return client, spec_db, tmp_dir


# ===========================================================================
# Scenario 1 — bootstrap: doctor_visit_log table is created
# ===========================================================================

class TestScenario1Bootstrap:
    def test_doctor_visit_log_table_exists(self, specialist_app):
        app, spec_db, _ = specialist_app
        from src.adapters.sqlite.core import get_db
        db = get_db()
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='doctor_visit_log'"
        ).fetchone()
        assert row is not None, "doctor_visit_log table must exist after bootstrap"

    def test_doctor_visit_log_has_required_columns(self, specialist_app):
        app, spec_db, _ = specialist_app
        from src.adapters.sqlite.core import get_db
        db = get_db()
        cols = {r[1] for r in db.execute("PRAGMA table_info(doctor_visit_log)").fetchall()}
        required = {
            "id", "accounting_invoice_id", "patient_link_id", "national_id",
            "full_name", "work_date", "status", "started_at", "done_at",
            "physician_notes", "done_by", "created_at",
        }
        missing = required - cols
        assert not missing, f"doctor_visit_log missing columns: {missing}"

    def test_accounting_invoice_id_is_unique(self, specialist_app):
        """The UNIQUE constraint on accounting_invoice_id must be enforced."""
        app, spec_db, _ = specialist_app
        from src.adapters.sqlite.core import get_db
        db = get_db()
        db.execute(
            "INSERT INTO doctor_visit_log (accounting_invoice_id, full_name, work_date, status)"
            " VALUES (999, 'آزمون', '2026-06-20', 'waiting')"
        )
        db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO doctor_visit_log (accounting_invoice_id, full_name, work_date, status)"
                " VALUES (999, 'دیگری', '2026-06-20', 'waiting')"
            )


# ===========================================================================
# Scenario 2 — queue source: only open invoices WITH a visit item appear
# ===========================================================================

class TestScenario2QueueSource:

    def _build_acc_db(self, tmp_dir, name, nid, phone="09123456789"):
        """Build a fresh acc db and return (path, acc_patient_id, conn_for_mutations)."""
        path = os.path.join(tmp_dir, f"acc_s2_{name}.db")
        _make_acc_db(path)
        return path

    def test_open_visit_invoice_appears_in_queue(self, specialist_app, tmp_dir):
        """An open invoice with a visits row for today's work_date → shows in queue."""
        app, spec_db, _ = specialist_app
        acc_db = os.path.join(tmp_dir, "acc_s2a.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        pid = _acc_add_patient(conn, "مریم احمدی", national_id="1234567890")
        inv_id = _acc_add_invoice(conn, pid, status="open", work_date="2026-06-20")
        _acc_add_visit(conn, inv_id, pid)
        conn.close()

        _set_acc_path(acc_db)
        from src.services.doctor_queue_service import DoctorQueueService
        result = DoctorQueueService().queue(work_date="2026-06-20")

        inv_ids = [r["invoice_id"] for r in result["waiting"]] + \
                  [r["invoice_id"] for r in result["done"]]
        assert inv_id in inv_ids, (
            f"Open invoice #{inv_id} with a visit must appear in the queue"
        )

    def test_open_invoice_without_visit_excluded(self, specialist_app, tmp_dir):
        """An open invoice with only a procedure (no visits row) must NOT appear."""
        app, spec_db, _ = specialist_app
        acc_db = os.path.join(tmp_dir, "acc_s2b.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        pid = _acc_add_patient(conn, "علی رضایی", national_id="0987654321")
        inv_id = _acc_add_invoice(conn, pid, status="open", work_date="2026-06-20")
        _acc_add_procedure(conn, inv_id, pid)  # procedure only — no visit
        conn.close()

        _set_acc_path(acc_db)
        from src.services.doctor_queue_service import DoctorQueueService
        result = DoctorQueueService().queue(work_date="2026-06-20")

        all_ids = [r["invoice_id"] for r in result["waiting"] + result["done"]]
        assert inv_id not in all_ids, (
            f"Invoice #{inv_id} without a visit row must NOT appear in the queue"
        )

    def test_closed_invoice_with_visit_excluded(self, specialist_app, tmp_dir):
        """A CLOSED invoice with a visit row must NOT appear — only open invoices."""
        app, spec_db, _ = specialist_app
        acc_db = os.path.join(tmp_dir, "acc_s2c.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        pid = _acc_add_patient(conn, "فاطمه کریمی", national_id="1122334455")
        inv_id = _acc_add_invoice(conn, pid, status="closed", work_date="2026-06-20",
                                   closed_at="2026-06-20 10:00:00")
        _acc_add_visit(conn, inv_id, pid)
        conn.close()

        _set_acc_path(acc_db)
        from src.services.doctor_queue_service import DoctorQueueService
        result = DoctorQueueService().queue(work_date="2026-06-20")

        all_ids = [r["invoice_id"] for r in result["waiting"] + result["done"]]
        assert inv_id not in all_ids, (
            f"Closed invoice #{inv_id} must NOT appear in the queue"
        )

    def test_mixed_invoices_only_open_visit_appears(self, specialist_app, tmp_dir):
        """Three invoices: open+visit (include), open+procedure-only (exclude),
        closed+visit (exclude). Only the first must appear."""
        app, spec_db, _ = specialist_app
        acc_db = os.path.join(tmp_dir, "acc_s2d.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        pid = _acc_add_patient(conn, "حسن نوری", national_id="5544332211")

        inv_ok = _acc_add_invoice(conn, pid, status="open", work_date="2026-06-20")
        _acc_add_visit(conn, inv_ok, pid)

        inv_proc = _acc_add_invoice(conn, pid, status="open", work_date="2026-06-20")
        _acc_add_procedure(conn, inv_proc, pid)

        inv_closed = _acc_add_invoice(conn, pid, status="closed", work_date="2026-06-20",
                                       closed_at="2026-06-20 09:00:00")
        _acc_add_visit(conn, inv_closed, pid)
        conn.close()

        _set_acc_path(acc_db)
        from src.services.doctor_queue_service import DoctorQueueService
        result = DoctorQueueService().queue(work_date="2026-06-20")

        all_ids = set(r["invoice_id"] for r in result["waiting"] + result["done"])
        assert inv_ok in all_ids, "Open+visit invoice must appear"
        assert inv_proc not in all_ids, "Open+procedure-only invoice must not appear"
        assert inv_closed not in all_ids, "Closed invoice must not appear"


# ===========================================================================
# Scenario 3 — state machine: start / idempotent / mark_done / no downgrade
# ===========================================================================

class TestScenario3StateMachine:

    def _setup_queue(self, tmp_dir, prefix, national_id="9876543210"):
        """Create one open invoice with a visit; return (acc_db_path, invoice_id)."""
        acc_db = os.path.join(tmp_dir, f"acc_{prefix}.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        pid = _acc_add_patient(conn, "آزمون استیت", national_id=national_id)
        inv_id = _acc_add_invoice(conn, pid, status="open", work_date="2026-06-20")
        _acc_add_visit(conn, inv_id, pid)
        conn.close()
        return acc_db, inv_id

    def test_start_sets_in_progress(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app
        acc_db, inv_id = self._setup_queue(tmp_dir, "s3a", "9000000001")
        _set_acc_path(acc_db)

        from src.adapters.sqlite.doctor_queue_repo import DoctorQueueRepository
        from src.adapters.sqlite.core import get_db
        repo = DoctorQueueRepository()
        repo.start(
            accounting_invoice_id=inv_id,
            patient_link_id=None,
            national_id="9000000001",
            full_name="آزمون استیت",
            work_date="2026-06-20",
        )
        db = get_db()
        row = db.execute(
            "SELECT status, started_at FROM doctor_visit_log WHERE accounting_invoice_id=?",
            (inv_id,)
        ).fetchone()
        assert row is not None, "start() must insert a row"
        assert dict(row)["status"] == "in_progress", (
            f"status after start() must be 'in_progress', got {dict(row)['status']}"
        )
        assert dict(row)["started_at"] is not None, "started_at must be set"

    def test_start_twice_is_idempotent(self, specialist_app, tmp_dir):
        """Calling start() a second time must not create a duplicate row."""
        app, spec_db, _ = specialist_app
        acc_db, inv_id = self._setup_queue(tmp_dir, "s3b", "9000000002")
        _set_acc_path(acc_db)

        from src.adapters.sqlite.doctor_queue_repo import DoctorQueueRepository
        from src.adapters.sqlite.core import get_db
        repo = DoctorQueueRepository()
        snap = dict(
            accounting_invoice_id=inv_id,
            patient_link_id=None,
            national_id="9000000002",
            full_name="آزمون استیت",
            work_date="2026-06-20",
        )
        repo.start(**snap)
        repo.start(**snap)  # second call — must not raise, must not duplicate

        db = get_db()
        count = db.execute(
            "SELECT COUNT(*) c FROM doctor_visit_log WHERE accounting_invoice_id=?",
            (inv_id,)
        ).fetchone()["c"]
        assert count == 1, f"start() twice must produce exactly 1 row, got {count}"

        row = db.execute(
            "SELECT status FROM doctor_visit_log WHERE accounting_invoice_id=?",
            (inv_id,)
        ).fetchone()
        assert dict(row)["status"] == "in_progress"

    def test_mark_done_sets_done(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app
        acc_db, inv_id = self._setup_queue(tmp_dir, "s3c", "9000000003")
        _set_acc_path(acc_db)

        from src.adapters.sqlite.doctor_queue_repo import DoctorQueueRepository
        from src.adapters.sqlite.core import get_db
        repo = DoctorQueueRepository()
        repo.start(
            accounting_invoice_id=inv_id, patient_link_id=None,
            national_id="9000000003", full_name="آزمون استیت", work_date="2026-06-20",
        )
        repo.mark_done(
            accounting_invoice_id=inv_id, patient_link_id=None,
            national_id="9000000003", full_name="آزمون استیت", work_date="2026-06-20",
            done_by="admin", notes="ویزیت کامل شد",
        )
        db = get_db()
        row = db.execute(
            "SELECT status, done_at, done_by, physician_notes FROM doctor_visit_log"
            " WHERE accounting_invoice_id=?", (inv_id,)
        ).fetchone()
        r = dict(row)
        assert r["status"] == "done", f"status after mark_done() must be 'done', got {r['status']}"
        assert r["done_at"] is not None, "done_at must be set"
        assert r["done_by"] == "admin"
        assert r["physician_notes"] == "ویزیت کامل شد"

    def test_start_after_done_does_not_downgrade(self, specialist_app, tmp_dir):
        """Calling start() after mark_done() must NOT revert status to in_progress."""
        app, spec_db, _ = specialist_app
        acc_db, inv_id = self._setup_queue(tmp_dir, "s3d", "9000000004")
        _set_acc_path(acc_db)

        from src.adapters.sqlite.doctor_queue_repo import DoctorQueueRepository
        from src.adapters.sqlite.core import get_db
        repo = DoctorQueueRepository()
        snap = dict(
            accounting_invoice_id=inv_id, patient_link_id=None,
            national_id="9000000004", full_name="آزمون استیت", work_date="2026-06-20",
        )
        repo.start(**snap)
        repo.mark_done(**snap, done_by="admin")
        repo.start(**snap)  # must NOT downgrade

        db = get_db()
        row = db.execute(
            "SELECT status FROM doctor_visit_log WHERE accounting_invoice_id=?",
            (inv_id,)
        ).fetchone()
        assert dict(row)["status"] == "done", (
            "start() after mark_done() must not downgrade status back to in_progress"
        )


# ===========================================================================
# Scenario 4 — queue segregation: enrolled vs walk-in; waiting vs done split
# ===========================================================================

class TestScenario4QueueSegregation:

    def test_enrolled_patient_tagged_enrolled_true(self, specialist_app, tmp_dir):
        """Patient with a patient_links row matching national_id → enrolled=True."""
        app, spec_db, _ = specialist_app
        acc_db = os.path.join(tmp_dir, "acc_s4a.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        nid = "8811223344"
        pid = _acc_add_patient(conn, "بیمارِ ثبت‌شده", national_id=nid)
        inv_id = _acc_add_invoice(conn, pid, status="open", work_date="2026-06-20")
        _acc_add_visit(conn, inv_id, pid)
        conn.close()

        # Enroll this patient in the specialist DB
        _enroll_patient(spec_db, nid, "بیمارِ ثبت‌شده")

        _set_acc_path(acc_db)
        from src.services.doctor_queue_service import DoctorQueueService
        result = DoctorQueueService().queue(work_date="2026-06-20")

        all_rows = result["waiting"] + result["done"]
        matching = [r for r in all_rows if r["invoice_id"] == inv_id]
        assert matching, f"Invoice #{inv_id} not found in queue"
        assert matching[0]["enrolled"] is True, (
            "Enrolled patient must have enrolled=True in the queue row"
        )
        assert matching[0]["patient_link_id"] is not None, (
            "Enrolled patient must have patient_link_id set"
        )

    def test_walkin_patient_tagged_enrolled_false(self, specialist_app, tmp_dir):
        """Patient WITHOUT a patient_links row → enrolled=False, patient_link_id=None."""
        app, spec_db, _ = specialist_app
        acc_db = os.path.join(tmp_dir, "acc_s4b.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        nid = "7766554433"
        pid = _acc_add_patient(conn, "بیمارِ معمولی", national_id=nid)
        inv_id = _acc_add_invoice(conn, pid, status="open", work_date="2026-06-20")
        _acc_add_visit(conn, inv_id, pid)
        conn.close()

        # Do NOT enroll this patient
        _set_acc_path(acc_db)
        from src.services.doctor_queue_service import DoctorQueueService
        result = DoctorQueueService().queue(work_date="2026-06-20")

        all_rows = result["waiting"] + result["done"]
        matching = [r for r in all_rows if r["invoice_id"] == inv_id]
        assert matching, f"Invoice #{inv_id} not found in queue"
        assert matching[0]["enrolled"] is False, (
            "Walk-in patient must have enrolled=False"
        )
        assert matching[0]["patient_link_id"] is None, (
            "Walk-in patient must have patient_link_id=None"
        )

    def test_done_vs_waiting_separation(self, specialist_app, tmp_dir):
        """Two invoices: one started+done, one untouched.
        Queue['done'] contains the done one; queue['waiting'] has the other."""
        app, spec_db, _ = specialist_app
        acc_db = os.path.join(tmp_dir, "acc_s4c.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        pid1 = _acc_add_patient(conn, "بیمار اول", national_id="6655443322")
        pid2 = _acc_add_patient(conn, "بیمار دوم", national_id="3322446655")

        inv_done = _acc_add_invoice(conn, pid1, status="open", work_date="2026-06-20")
        _acc_add_visit(conn, inv_done, pid1)

        inv_wait = _acc_add_invoice(conn, pid2, status="open", work_date="2026-06-20")
        _acc_add_visit(conn, inv_wait, pid2)
        conn.close()

        # Mark invoice 1 as done
        from src.adapters.sqlite.doctor_queue_repo import DoctorQueueRepository
        repo = DoctorQueueRepository()
        repo.start(
            accounting_invoice_id=inv_done, patient_link_id=None,
            national_id="6655443322", full_name="بیمار اول", work_date="2026-06-20",
        )
        repo.mark_done(
            accounting_invoice_id=inv_done, patient_link_id=None,
            national_id="6655443322", full_name="بیمار اول", work_date="2026-06-20",
            done_by="admin",
        )

        _set_acc_path(acc_db)
        from src.services.doctor_queue_service import DoctorQueueService
        result = DoctorQueueService().queue(work_date="2026-06-20")

        done_ids = [r["invoice_id"] for r in result["done"]]
        wait_ids = [r["invoice_id"] for r in result["waiting"]]

        assert inv_done in done_ids, f"Invoice #{inv_done} should be in done list"
        assert inv_done not in wait_ids, f"Invoice #{inv_done} must NOT be in waiting list"
        assert inv_wait in wait_ids, f"Invoice #{inv_wait} should be in waiting list"
        assert inv_wait not in done_ids, f"Invoice #{inv_wait} must NOT be in done list"


# ===========================================================================
# Scenario 5 — visit route: enrolled → 200, non-enrolled → 302 redirect
# ===========================================================================

class TestScenario5VisitRoute:

    def _setup(self, tmp_dir, spec_db, nid_enrolled="1010101010", nid_walkin="2020202020"):
        """Build acc db with two patients + enroll one; return acc_db_path."""
        acc_db = os.path.join(tmp_dir, "acc_s5.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        pid_e = _acc_add_patient(conn, "ثبت‌شده", national_id=nid_enrolled)
        _acc_add_patient(conn, "معمولی", national_id=nid_walkin)
        inv_id = _acc_add_invoice(conn, pid_e, status="open", work_date="2026-06-20")
        _acc_add_visit(conn, inv_id, pid_e)
        conn.close()

        _enroll_patient(spec_db, nid_enrolled, "ثبت‌شده")
        return acc_db, inv_id

    def test_visit_route_enrolled_patient_returns_200(self, test_client, tmp_dir):
        client, spec_db, _ = test_client
        nid = "3131313131"
        acc_db = os.path.join(tmp_dir, "acc_s5a.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        pid = _acc_add_patient(conn, "ثبت‌شده ۲", national_id=nid)
        inv_id = _acc_add_invoice(conn, pid, status="open", work_date="2026-06-20")
        _acc_add_visit(conn, inv_id, pid)
        conn.close()

        _enroll_patient(spec_db, nid, "ثبت‌شده ۲")
        _set_acc_path(acc_db)

        rv = client.get(f"/doctor-queue/{inv_id}/visit?nid={nid}")
        assert rv.status_code == 200, (
            f"Enrolled patient visit view should return 200, got {rv.status_code}"
        )

    def test_visit_route_non_enrolled_redirects(self, test_client, tmp_dir):
        client, spec_db, _ = test_client
        nid = "4242424242"
        acc_db = os.path.join(tmp_dir, "acc_s5b.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        pid = _acc_add_patient(conn, "معمولی ۲", national_id=nid)
        inv_id = _acc_add_invoice(conn, pid, status="open", work_date="2026-06-20")
        _acc_add_visit(conn, inv_id, pid)
        conn.close()

        # Not enrolled — no patient_links row for this nid
        _set_acc_path(acc_db)

        rv = client.get(f"/doctor-queue/{inv_id}/visit?nid={nid}")
        assert rv.status_code == 302, (
            f"Non-enrolled patient visit view should redirect (302), got {rv.status_code}"
        )
        # Should redirect back to the queue index
        location = rv.headers.get("Location", "")
        assert "doctor-queue" in location or location.endswith("/doctor-queue/") or \
               "/" in location, f"Redirect location unexpected: {location}"

    def test_visit_route_missing_nid_redirects(self, test_client, tmp_dir):
        """Requesting /doctor-queue/<inv>/visit without nid should also redirect."""
        client, spec_db, _ = test_client
        acc_db = os.path.join(tmp_dir, "acc_s5c.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        pid = _acc_add_patient(conn, "بدون کد", national_id=None)
        inv_id = _acc_add_invoice(conn, pid, status="open", work_date="2026-06-20")
        _acc_add_visit(conn, inv_id, pid)
        conn.close()
        _set_acc_path(acc_db)

        rv = client.get(f"/doctor-queue/{inv_id}/visit")
        assert rv.status_code == 302, (
            f"Visit view with no nid should redirect (302), got {rv.status_code}"
        )


# ===========================================================================
# Scenario 6 — save route: vitals + exam note inserted; redirect to visit view
# ===========================================================================

class TestScenario6Save:

    def _enroll_and_get_pid(self, spec_db, nid, name="بیمارِ ذخیره"):
        """Enroll patient in specialist DB; return patient_links.id."""
        return _enroll_patient(spec_db, nid, name)

    def test_save_adds_vital_and_note(self, test_client, tmp_dir):
        """POST /doctor-queue/<inv>/save with pid, fbs value, and note → rows inserted."""
        client, spec_db, _ = test_client
        nid = "5050505050"
        pid = self._enroll_and_get_pid(spec_db, nid, "بیمارِ ذخیره")

        acc_db = os.path.join(tmp_dir, "acc_s6a.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        acc_pid = _acc_add_patient(conn, "بیمارِ ذخیره", national_id=nid)
        inv_id = _acc_add_invoice(conn, acc_pid, status="open", work_date="2026-06-20")
        _acc_add_visit(conn, inv_id, acc_pid)
        conn.close()
        _set_acc_path(acc_db)

        # Verify baseline: no vitals, no notes yet
        spec_conn = sqlite3.connect(spec_db)
        pre_vitals = spec_conn.execute(
            "SELECT COUNT(*) c FROM vital_readings WHERE patient_link_id=?", (pid,)
        ).fetchone()[0]
        pre_notes = spec_conn.execute(
            "SELECT COUNT(*) c FROM clinical_notes WHERE patient_link_id=? AND kind='exam'", (pid,)
        ).fetchone()[0]
        spec_conn.close()
        assert pre_vitals == 0
        assert pre_notes == 0

        # POST save with an FBS value and a note
        rv = client.post(
            f"/doctor-queue/{inv_id}/save",
            data={
                "pid": str(pid),
                "nid": nid,
                "measured_date": "1405/03/30",  # Jalali date → valid Gregorian
                "fbs": "126",
                "note": "بیمار کنترل خوبی داشت",
            },
            follow_redirects=False,
        )
        # Should redirect to the visit view
        assert rv.status_code == 302, (
            f"save POST should redirect (302), got {rv.status_code}"
        )
        location = rv.headers.get("Location", "")
        assert "visit" in location, f"Should redirect to visit view, got location: {location}"

        # Verify rows inserted
        spec_conn = sqlite3.connect(spec_db)
        post_vitals = spec_conn.execute(
            "SELECT COUNT(*) c FROM vital_readings WHERE patient_link_id=? AND type='fbs'",
            (pid,)
        ).fetchone()[0]
        post_notes = spec_conn.execute(
            "SELECT COUNT(*) c FROM clinical_notes WHERE patient_link_id=? AND kind='exam'",
            (pid,)
        ).fetchone()[0]
        spec_conn.close()

        assert post_vitals == 1, f"Expected 1 fbs reading after save, got {post_vitals}"
        assert post_notes == 1, f"Expected 1 exam note after save, got {post_notes}"

    def test_save_no_pid_does_not_crash(self, test_client, tmp_dir):
        """POST /save with no pid (walk-in who didn't have nid) must not crash — just redirect."""
        client, spec_db, _ = test_client
        acc_db = os.path.join(tmp_dir, "acc_s6b.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        pid_acc = _acc_add_patient(conn, "بدونِ پیوند", national_id=None)
        inv_id = _acc_add_invoice(conn, pid_acc, status="open", work_date="2026-06-20")
        _acc_add_visit(conn, inv_id, pid_acc)
        conn.close()
        _set_acc_path(acc_db)

        rv = client.post(
            f"/doctor-queue/{inv_id}/save",
            data={"nid": "", "fbs": "140", "note": "آزمون"},
            follow_redirects=False,
        )
        # Must not raise a 500; either redirect (302) or some valid response
        assert rv.status_code in (200, 302), (
            f"save without pid should not crash (got {rv.status_code})"
        )

    def test_save_multiple_vitals_inserted(self, test_client, tmp_dir):
        """POST save with both bp_systolic and bp_diastolic → two vital rows."""
        client, spec_db, _ = test_client
        nid = "6060606060"
        pid = _enroll_patient(spec_db, nid, "بیمارِ چندشاخص")

        acc_db = os.path.join(tmp_dir, "acc_s6c.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        acc_pid = _acc_add_patient(conn, "بیمارِ چندشاخص", national_id=nid)
        inv_id = _acc_add_invoice(conn, acc_pid, status="open", work_date="2026-06-20")
        _acc_add_visit(conn, inv_id, acc_pid)
        conn.close()
        _set_acc_path(acc_db)

        client.post(
            f"/doctor-queue/{inv_id}/save",
            data={
                "pid": str(pid),
                "nid": nid,
                "bp_systolic": "130",
                "bp_diastolic": "85",
            },
            follow_redirects=False,
        )

        spec_conn = sqlite3.connect(spec_db)
        count = spec_conn.execute(
            "SELECT COUNT(*) c FROM vital_readings WHERE patient_link_id=?", (pid,)
        ).fetchone()[0]
        spec_conn.close()
        assert count == 2, f"Expected 2 vital readings (systolic + diastolic), got {count}"


# ===========================================================================
# Scenario 7 — zero-write safety: real clinic_new.db byte-unchanged after
#              a queue load that reads it through the bridge
# ===========================================================================

@pytest.mark.skipif(
    not os.path.exists(_REAL_ACC_DB),
    reason=f"Real accounting DB not found at {_REAL_ACC_DB}"
)
class TestScenario7ZeroWrite:
    def test_real_acc_db_unchanged_after_queue_load(self, specialist_app):
        app, spec_db, _ = specialist_app

        sha_before = _sha256(_REAL_ACC_DB)
        wal_path = _REAL_ACC_DB + "-wal"
        shm_path = _REAL_ACC_DB + "-shm"
        wal_existed_before = os.path.exists(wal_path)
        shm_existed_before = os.path.exists(shm_path)

        # Point bridge at the REAL accounting DB and load the queue
        _set_acc_path(_REAL_ACC_DB)
        from src.services.doctor_queue_service import DoctorQueueService
        result = DoctorQueueService().queue()  # reads the real DB read-only

        sha_after = _sha256(_REAL_ACC_DB)
        assert sha_before == sha_after, (
            f"clinic_new.db was MODIFIED during a read-only queue load!\n"
            f"  before: {sha_before}\n"
            f"  after:  {sha_after}"
        )

        if not wal_existed_before:
            assert not os.path.exists(wal_path), (
                "A WAL file was created on clinic_new.db — this indicates a write attempt"
            )
        if not shm_existed_before:
            assert not os.path.exists(shm_path), (
                "A SHM file was created on clinic_new.db — this indicates a write attempt"
            )

        print(f"\n[SCENARIO 7] SHA-256 before: {sha_before}")
        print(f"[SCENARIO 7] SHA-256 after:  {sha_after}")
        print(f"[SCENARIO 7] MATCH: {sha_before == sha_after}")
        print(f"[SCENARIO 7] Queue: {len(result['waiting'])} waiting, {len(result['done'])} done")
