"""
ADR-0003 D3+ — Invoice-sync outreach RETRY test suite.

باگی که رفع شد: قبلاً outreach (thank-you SMS) به ``inserted==True`` گِیت بود؛
اگر ``on_invoice_processed`` خطا می‌داد، tickِ بعدی چون ``INSERT OR IGNORE`` ردیف را
``inserted=False`` می‌دید، outreach هرگز retry نمی‌شد → پیامک برای همیشه گم می‌شد.
رفع: ستون ``outreach_done`` در ``processed_invoices`` + گِیت به آن + per-row try/except.

این suite آن رفع را ثابت می‌کند (و رگرسیون مسیر عادی را نیز بررسی می‌کند).

Safety contract:
  - تمام نوشتن روی COPY در tmp_dir — هرگز روی DBهای اصلی.
  - SHA-256 فایل حسابداری کپی قبل/بعد یکسان (گارد صفر-نوشتن).
  - هیچ پیامک واقعی: scheduler در TESTING غیرفعال است؛ enqueue_event_for_patient
    فقط در engagement_approvals درج می‌کند، send_single صدا نمی‌زند.
  - سورس را تغییر نمی‌دهیم — فقط monkey-patch روی توابع bridge/service.

اجرا از پوشه specialist_clinic:
    .venv/Scripts/python.exe -m pytest tests/test_invoice_outreach_retry.py -v
"""
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

# ── مسیرها قبل از هر import از src تنظیم می‌شوند ─────────────────────────────
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
    """تمام ماژول‌های src.* را از sys.modules پاک کن تا import بعدی clean باشد."""
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
    """یک accounting DB با جداول مورد نیاز bridge می‌سازد."""
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
            invoice_id INTEGER, patient_id INTEGER,
            visit_date TEXT, doctor_name TEXT,
            price REAL DEFAULT 0, insurance_type TEXT,
            supplementary_insurance TEXT
        );
        CREATE TABLE IF NOT EXISTS injections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER, patient_id INTEGER,
            injection_type TEXT, total_price REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS procedures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER, patient_id INTEGER,
            procedure_type TEXT, price REAL DEFAULT 0
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


def _set_acc_path(path: str):
    """hot-swap آدرس DB حسابداری بدون reload ماژول."""
    os.environ["ACCOUNTING_DB_PATH"] = path
    import src.config.settings as cfg_mod
    cfg_mod.Config.ACCOUNTING_DB_PATH = path


def _enroll_patient(national_id, full_name, phone_number=None, sms_opt_out=0):
    """یک ردیف patient_links در DB جاری می‌سازد (داخل app_context)."""
    from src.adapters.sqlite.core import get_db
    db = get_db()
    cur = db.execute(
        """INSERT INTO patient_links
               (national_id, full_name, phone_number, sms_opt_out, enrolled_by)
           VALUES (?, ?, ?, ?, 'test')""",
        (national_id, full_name, phone_number, sms_opt_out),
    )
    db.commit()
    return cur.lastrowid


def _count_approvals(db, event_key=None, patient_link_id=None):
    clauses, params = [], []
    if event_key is not None:
        clauses.append("event_key=?")
        params.append(event_key)
    if patient_link_id is not None:
        clauses.append("patient_link_id=?")
        params.append(patient_link_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return db.execute(
        f"SELECT COUNT(*) c FROM engagement_approvals {where}", params
    ).fetchone()["c"]


def _get_pi_row(db, inv_id):
    r = db.execute(
        "SELECT * FROM processed_invoices WHERE accounting_invoice_id=?", (inv_id,)
    ).fetchone()
    return dict(r) if r else None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="retry_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def specialist_app(tmp_dir):
    """Flask test-app با DB تازه در tmp_dir — ایزولاسیون کامل env/module."""
    spec_db = os.path.join(tmp_dir, "specialist_test.db")

    _saved_env = {
        "SPECIALIST_DB_PATH": os.environ.get("SPECIALIST_DB_PATH"),
        "ACCOUNTING_DB_PATH": os.environ.get("ACCOUNTING_DB_PATH"),
    }
    os.environ["SPECIALIST_DB_PATH"] = spec_db
    os.environ["ACCOUNTING_DB_PATH"] = _REAL_ACC_DB

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


# ===========================================================================
# Scenario 1 — رفعِ باگ (مهم‌ترین)
# pass1: outreach خطا → ردیف ثبت شد، outreach_done=False، صفر approval
# pass2: retry  → outreach_done=True، یک approval thank_you (پیامک بازیابی شد)
# pass3: outreach_done=1 → دوباره صدا زده نمی‌شود، approval تکرار نمی‌شود
# ===========================================================================

class TestScenario1RetryBugFix:
    def test_outreach_retry_recovers_lost_sms(self, specialist_app, tmp_dir):
        """کامل‌ترین تست: سه pass متوالی."""
        app, spec_db, _ = specialist_app

        # ── ساخت accounting DB ──────────────────────────────────────────────
        acc_db = os.path.join(tmp_dir, "acc_s1.db")
        _make_acc_db(acc_db)
        acc_conn = sqlite3.connect(acc_db)
        pid_acc = _acc_add_patient(acc_conn, "رضا امینی", national_id="8800000001",
                                   phone="09121111111")
        inv_id = _acc_add_invoice(acc_conn, pid_acc, "closed",
                                  work_date="2026-06-01",
                                  closed_at="2026-06-01 10:00:00")
        acc_conn.close()

        # ── ثبت بیمار enrolled با تلفن ─────────────────────────────────────
        plid = _enroll_patient("8800000001", "رضا امینی", phone_number="09121111111")

        _set_acc_path(acc_db)

        from src.services import invoice_sync_service as svc_mod
        from src.adapters import accounting_bridge as bridge_mod

        # ── Patch bridge تا فقط همین فاکتور را برگرداند ───────────────────
        orig_fetch_closed = bridge_mod.fetch_closed_invoices
        orig_fetch_items = bridge_mod.fetch_invoice_items
        bridge_mod.fetch_closed_invoices = lambda **kw: [{
            "invoice_id": inv_id,
            "national_id": "8800000001",
            "full_name": "رضا امینی",
            "work_date": "2026-06-01",
            "closed_at": "2026-06-01 10:00:00",
            "total_amount": 1000,
        }]
        bridge_mod.fetch_invoice_items = lambda inv: []

        # ── Patch on_invoice_processed تا بار اول raise کند ────────────────
        from src.services.invoice_sync_service import InvoiceSyncService
        call_count = [0]
        orig_on_invoice = InvoiceSyncService.on_invoice_processed

        def failing_on_invoice(self_inner, pid_inner, invoice_inner):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("خطای شبیه‌سازی‌شده در outreach pass1")
            return orig_on_invoice(self_inner, pid_inner, invoice_inner)

        InvoiceSyncService.on_invoice_processed = failing_on_invoice

        from src.adapters.sqlite.core import get_db
        db = get_db()

        try:
            # ── PASS 1: outreach خطا می‌دهد ────────────────────────────────
            res1 = InvoiceSyncService().run()
            pi1 = _get_pi_row(db, inv_id)

            assert pi1 is not None, \
                f"PASS1: ردیف processed_invoices باید ثبت شده باشد (inv_id={inv_id})"
            assert pi1["outreach_done"] == 0, \
                f"PASS1: outreach_done باید 0 باشد (outreach خطا داد)، got {pi1['outreach_done']}"
            approvals_after_pass1 = _count_approvals(db, event_key="thank_you",
                                                      patient_link_id=plid)
            assert approvals_after_pass1 == 0, \
                f"PASS1: هیچ approval نباید باشد (outreach شکست خورد)، got {approvals_after_pass1}"

            # ── PASS 2: retry — outreach موفق می‌شود ───────────────────────
            # cursor را reset کن تا همان فاکتور دوباره دیده شود
            db.execute("DELETE FROM settings WHERE key='invoice_sync_last_id'")
            db.commit()

            res2 = InvoiceSyncService().run()
            pi2 = _get_pi_row(db, inv_id)

            assert pi2["outreach_done"] == 1, \
                f"PASS2: outreach_done باید 1 باشد (retry موفق شد)، got {pi2['outreach_done']}"
            approvals_after_pass2 = _count_approvals(db, event_key="thank_you",
                                                      patient_link_id=plid)
            assert approvals_after_pass2 == 1, \
                f"PASS2: باید دقیقاً ۱ approval thank_you باشد (پیامک بازیابی شد)، " \
                f"got {approvals_after_pass2}"

            # ── PASS 3: outreach_done=1 → دیگر تلاش نشود ──────────────────
            db.execute("DELETE FROM settings WHERE key='invoice_sync_last_id'")
            db.commit()
            call_count_before_pass3 = call_count[0]

            res3 = InvoiceSyncService().run()
            # on_invoice_processed نباید دوباره صدا زده شود
            assert call_count[0] == call_count_before_pass3, \
                f"PASS3: on_invoice_processed نباید دوباره صدا زده شود، " \
                f"call_count قبل={call_count_before_pass3}، بعد={call_count[0]}"

            approvals_after_pass3 = _count_approvals(db, event_key="thank_you",
                                                      patient_link_id=plid)
            assert approvals_after_pass3 == 1, \
                f"PASS3: approval تکرار نشود، باید همچنان ۱ باشد، got {approvals_after_pass3}"

        finally:
            # بازیابی patchها
            InvoiceSyncService.on_invoice_processed = orig_on_invoice
            bridge_mod.fetch_closed_invoices = orig_fetch_closed
            bridge_mod.fetch_invoice_items = orig_fetch_items


# ===========================================================================
# Scenario 2 — per-row guard
# batch با دو فاکتور: A همیشه در outreach خطا، B سالم.
# B باید outreach کامل کند؛ A همچنان outreach_done=False.
# cursor به max id پیشروی کند (یک ردیف خراب نه cursor نه B را بلاک نکند).
# ===========================================================================

class TestScenario2PerRowGuard:
    def test_bad_row_does_not_block_good_row_or_cursor(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app

        acc_db = os.path.join(tmp_dir, "acc_s2.db")
        _make_acc_db(acc_db)
        acc_conn = sqlite3.connect(acc_db)
        pid_acc = _acc_add_patient(acc_conn, "مریم صادقی", national_id="8800000002",
                                   phone="09122222222")
        inv_a = _acc_add_invoice(acc_conn, pid_acc, "closed",
                                 work_date="2026-06-02",
                                 closed_at="2026-06-02 10:00:00",
                                 invoice_id=100)
        inv_b = _acc_add_invoice(acc_conn, pid_acc, "closed",
                                 work_date="2026-06-02",
                                 closed_at="2026-06-02 11:00:00",
                                 invoice_id=200)
        acc_conn.close()

        plid = _enroll_patient("8800000002", "مریم صادقی", phone_number="09122222222")

        _set_acc_path(acc_db)

        from src.adapters import accounting_bridge as bridge_mod
        from src.services.invoice_sync_service import InvoiceSyncService

        orig_fetch_closed = bridge_mod.fetch_closed_invoices
        orig_fetch_items = bridge_mod.fetch_invoice_items

        bridge_mod.fetch_closed_invoices = lambda **kw: [
            {
                "invoice_id": inv_a,
                "national_id": "8800000002",
                "full_name": "مریم صادقی",
                "work_date": "2026-06-02",
                "closed_at": "2026-06-02 10:00:00",
                "total_amount": 500,
            },
            {
                "invoice_id": inv_b,
                "national_id": "8800000002",
                "full_name": "مریم صادقی",
                "work_date": "2026-06-02",
                "closed_at": "2026-06-02 11:00:00",
                "total_amount": 700,
            },
        ]
        bridge_mod.fetch_invoice_items = lambda inv: []

        # Patch: فاکتور A همیشه در outreach خطا می‌دهد
        orig_on_invoice = InvoiceSyncService.on_invoice_processed

        def selective_fail(self_inner, pid_inner, invoice_inner):
            if invoice_inner.get("invoice_id") == inv_a:
                raise RuntimeError(f"خطای شبیه‌سازی: invoice_id={inv_a} همیشه شکست")
            return orig_on_invoice(self_inner, pid_inner, invoice_inner)

        InvoiceSyncService.on_invoice_processed = selective_fail

        from src.adapters.sqlite.core import get_db
        db = get_db()

        try:
            res = InvoiceSyncService().run()

            # cursor باید به max(inv_a, inv_b)=200 رفته باشد
            cursor_row = db.execute(
                "SELECT value FROM settings WHERE key='invoice_sync_last_id'"
            ).fetchone()
            cursor_val = int(cursor_row["value"]) if cursor_row else 0
            assert cursor_val == inv_b, \
                f"cursor باید به {inv_b} برسد، got {cursor_val}"

            # فاکتور A: outreach_done=False
            pi_a = _get_pi_row(db, inv_a)
            assert pi_a is not None, f"فاکتور A (id={inv_a}) باید در ledger باشد"
            assert pi_a["outreach_done"] == 0, \
                f"فاکتور A: outreach_done باید 0 باشد (همیشه شکست)، got {pi_a['outreach_done']}"

            # فاکتور B: outreach_done=True + approval ثبت شد
            pi_b = _get_pi_row(db, inv_b)
            assert pi_b is not None, f"فاکتور B (id={inv_b}) باید در ledger باشد"
            assert pi_b["outreach_done"] == 1, \
                f"فاکتور B: outreach_done باید 1 باشد (سالم بود)، got {pi_b['outreach_done']}"

            approvals_b = db.execute(
                "SELECT COUNT(*) c FROM engagement_approvals "
                "WHERE patient_link_id=? AND event_key='thank_you'", (plid,)
            ).fetchone()["c"]
            assert approvals_b == 1, \
                f"فاکتور B: باید ۱ approval thank_you داشته باشد، got {approvals_b}"

        finally:
            InvoiceSyncService.on_invoice_processed = orig_on_invoice
            bridge_mod.fetch_closed_invoices = orig_fetch_closed
            bridge_mod.fetch_invoice_items = orig_fetch_items


# ===========================================================================
# Scenario 3 — walk-in (pending_link)
# فاکتور بدون بیمار enrolled: ردیف ledger با status=pending_link،
# outreach اصلاً تلاش نمی‌شود، صفر approval، صفر خطا.
# ===========================================================================

class TestScenario3WalkIn:
    def test_walk_in_no_outreach_no_error(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app

        acc_db = os.path.join(tmp_dir, "acc_s3.db")
        _make_acc_db(acc_db)
        acc_conn = sqlite3.connect(acc_db)
        pid_acc = _acc_add_patient(acc_conn, "بیمار گذری", national_id="8800000003",
                                   phone="09123333333")
        inv_id = _acc_add_invoice(acc_conn, pid_acc, "closed",
                                  work_date="2026-06-03",
                                  closed_at="2026-06-03 10:00:00")
        acc_conn.close()

        # هیچ patient_link ثبت نمی‌کنیم

        _set_acc_path(acc_db)

        from src.adapters import accounting_bridge as bridge_mod
        from src.services.invoice_sync_service import InvoiceSyncService

        orig_fetch_closed = bridge_mod.fetch_closed_invoices
        orig_fetch_items = bridge_mod.fetch_invoice_items
        bridge_mod.fetch_closed_invoices = lambda **kw: [{
            "invoice_id": inv_id,
            "national_id": "8800000003",
            "full_name": "بیمار گذری",
            "work_date": "2026-06-03",
            "closed_at": "2026-06-03 10:00:00",
            "total_amount": 800,
        }]
        bridge_mod.fetch_invoice_items = lambda inv: []

        # ردیابی صدا زده‌شدن on_invoice_processed
        call_count = [0]
        orig_on_invoice = InvoiceSyncService.on_invoice_processed

        def tracking_on_invoice(self_inner, pid_inner, invoice_inner):
            call_count[0] += 1
            return orig_on_invoice(self_inner, pid_inner, invoice_inner)

        InvoiceSyncService.on_invoice_processed = tracking_on_invoice

        from src.adapters.sqlite.core import get_db
        db = get_db()

        try:
            res = InvoiceSyncService().run()

            # باید در ledger ثبت شده باشد
            pi = _get_pi_row(db, inv_id)
            assert pi is not None, "فاکتور walk-in باید در processed_invoices ثبت شود"
            assert pi["status"] == "pending_link", \
                f"status باید pending_link باشد، got {pi['status']}"
            assert pi["patient_link_id"] is None, \
                f"patient_link_id باید NULL باشد، got {pi['patient_link_id']}"

            # outreach اصلاً نباید تلاش شده باشد (plid=None → skip)
            assert call_count[0] == 0, \
                f"on_invoice_processed نباید برای walk-in صدا زده شود، count={call_count[0]}"

            # صفر approval
            total_approvals = _count_approvals(db)
            assert total_approvals == 0, \
                f"صفر approval برای walk-in انتظار می‌رود، got {total_approvals}"

        finally:
            InvoiceSyncService.on_invoice_processed = orig_on_invoice
            bridge_mod.fetch_closed_invoices = orig_fetch_closed
            bridge_mod.fetch_invoice_items = orig_fetch_items


# ===========================================================================
# Scenario 4 — migration idempotency
# یک processed_invoices بدون ستون outreach_done بساز (DDL دستی)،
# سپس _run_migrations را اجرا کن → ستون اضافه شود؛
# اجرای دوباره migration خطا ندهد.
# ===========================================================================

class TestScenario4MigrationIdempotency:
    def test_ensure_column_adds_outreach_done_and_is_safe_to_rerun(self, tmp_dir):
        """
        مستقل از Flask app: مستقیماً _ensure_column را با یک SQLite connection آزمایش می‌کند.
        """
        _flush_src_modules()
        sys.path.insert(0, _SPECIALIST_ROOT)

        import sqlite3
        tmp_db = os.path.join(tmp_dir, "migration_test.db")
        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row

        # ساخت جدول بدون ستون outreach_done
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                accounting_invoice_id INTEGER NOT NULL UNIQUE,
                patient_link_id INTEGER,
                national_id TEXT,
                full_name TEXT,
                work_date TEXT,
                closed_at TEXT,
                total_amount REAL,
                status TEXT NOT NULL DEFAULT 'applied',
                processed_at TIMESTAMP
            )
        """)
        conn.commit()

        # تأیید ستون وجود ندارد
        cols_before = [r["name"] for r in conn.execute("PRAGMA table_info(processed_invoices)")]
        assert "outreach_done" not in cols_before, \
            f"ستون outreach_done نباید قبل از migration باشد، cols={cols_before}"

        # اجرای اول _ensure_column
        from src.adapters.sqlite.core import _ensure_column
        _ensure_column(conn, "processed_invoices", "outreach_done", "INTEGER NOT NULL DEFAULT 0")

        cols_after = [r["name"] for r in conn.execute("PRAGMA table_info(processed_invoices)")]
        assert "outreach_done" in cols_after, \
            f"ستون outreach_done باید بعد از migration اضافه شده باشد، cols={cols_after}"

        # اجرای دوم (idempotency) — نباید خطا بدهد
        try:
            _ensure_column(conn, "processed_invoices", "outreach_done", "INTEGER NOT NULL DEFAULT 0")
        except Exception as e:
            pytest.fail(f"اجرای دوم _ensure_column خطا داد: {e}")

        conn.close()

    def test_bootstrap_adds_outreach_done_to_existing_db(self, tmp_dir):
        """
        اگر یک DB موجود بدون outreach_done داریم،
        create_app باید آن را اضافه کند.
        """
        _flush_src_modules()
        sys.path.insert(0, _SPECIALIST_ROOT)

        spec_db = os.path.join(tmp_dir, "bootstrap_migration.db")

        # DB اولیه بدون bootstrap — جدول را دستی می‌سازیم بدون outreach_done
        conn = sqlite3.connect(spec_db)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                accounting_invoice_id INTEGER NOT NULL UNIQUE,
                patient_link_id INTEGER,
                national_id TEXT,
                full_name TEXT,
                work_date TEXT,
                closed_at TEXT,
                total_amount REAL,
                status TEXT NOT NULL DEFAULT 'applied',
                processed_at TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

        _saved_env = {
            "SPECIALIST_DB_PATH": os.environ.get("SPECIALIST_DB_PATH"),
            "ACCOUNTING_DB_PATH": os.environ.get("ACCOUNTING_DB_PATH"),
        }
        os.environ["SPECIALIST_DB_PATH"] = spec_db
        os.environ["ACCOUNTING_DB_PATH"] = _REAL_ACC_DB

        try:
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
            try:
                from src.adapters.sqlite.core import get_db
                db = get_db()
                cols = [r["name"] for r in db.execute("PRAGMA table_info(processed_invoices)")]
                assert "outreach_done" in cols, \
                    f"bootstrap باید outreach_done را اضافه کند، cols={cols}"
            finally:
                ctx.pop()
        finally:
            for key, val in _saved_env.items():
                if val is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = val
            try:
                import src.adapters.sqlite.core as core_mod
                core_mod._initialized = False
            except Exception:
                pass
            _flush_src_modules()


# ===========================================================================
# Scenario 5 — رگرسیون (normal happy path)
# جریان عادی بدون خطا: record + thank_you enqueue + cursor پیشروی
# ===========================================================================

class TestScenario5NormalFlow:
    def test_normal_flow_records_and_enqueues_thank_you(self, specialist_app, tmp_dir):
        app, spec_db, _ = specialist_app

        acc_db = os.path.join(tmp_dir, "acc_s5.db")
        _make_acc_db(acc_db)
        acc_conn = sqlite3.connect(acc_db)
        pid_acc = _acc_add_patient(acc_conn, "فاطمه کاظمی", national_id="8800000005",
                                   phone="09125555555")
        inv_id = _acc_add_invoice(acc_conn, pid_acc, "closed",
                                  work_date="2026-06-05",
                                  closed_at="2026-06-05 09:00:00")
        acc_conn.close()

        plid = _enroll_patient("8800000005", "فاطمه کاظمی", phone_number="09125555555")

        _set_acc_path(acc_db)

        from src.adapters import accounting_bridge as bridge_mod
        from src.services.invoice_sync_service import InvoiceSyncService

        orig_fetch_closed = bridge_mod.fetch_closed_invoices
        orig_fetch_items = bridge_mod.fetch_invoice_items
        bridge_mod.fetch_closed_invoices = lambda **kw: [{
            "invoice_id": inv_id,
            "national_id": "8800000005",
            "full_name": "فاطمه کاظمی",
            "work_date": "2026-06-05",
            "closed_at": "2026-06-05 09:00:00",
            "total_amount": 1500,
        }]
        bridge_mod.fetch_invoice_items = lambda inv: []

        from src.adapters.sqlite.core import get_db
        db = get_db()

        try:
            res = InvoiceSyncService().run()

            # ردیف ثبت شد
            pi = _get_pi_row(db, inv_id)
            assert pi is not None, "ردیف باید در processed_invoices باشد"
            assert pi["status"] == "applied"
            assert pi["outreach_done"] == 1, \
                f"outreach_done باید 1 باشد (مسیر عادی)، got {pi['outreach_done']}"

            # approval thank_you
            count = _count_approvals(db, event_key="thank_you", patient_link_id=plid)
            assert count == 1, f"باید ۱ approval thank_you باشد، got {count}"

            # cursor پیشروی کرد
            cursor_row = db.execute(
                "SELECT value FROM settings WHERE key='invoice_sync_last_id'"
            ).fetchone()
            cursor_val = int(cursor_row["value"]) if cursor_row else 0
            assert cursor_val == inv_id, \
                f"cursor باید {inv_id} باشد، got {cursor_val}"

        finally:
            bridge_mod.fetch_closed_invoices = orig_fetch_closed
            bridge_mod.fetch_invoice_items = orig_fetch_items


# ===========================================================================
# Scenario 6 — صفر نوشتن حسابداری
# SHA-256 یک کپی از accounting DB قبل/بعد از sync یکسان.
# ===========================================================================

class TestScenario6ZeroWriteAccounting:
    def test_accounting_db_copy_unchanged_after_sync(self, specialist_app, tmp_dir):
        """
        یک کپی نوشتنی از accounting DB می‌سازیم (ACCOUNTING_DB_PATH → کپی).
        بعد از sync: SHA-256 قبل == SHA-256 بعد.
        """
        app, spec_db, _ = specialist_app

        # ساخت یک accounting DB جدید (نه real DB) و کپی آن
        acc_orig = os.path.join(tmp_dir, "acc_orig_s6.db")
        acc_copy = os.path.join(tmp_dir, "acc_copy_s6.db")
        _make_acc_db(acc_orig)
        acc_conn = sqlite3.connect(acc_orig)
        pid_acc = _acc_add_patient(acc_conn, "حامد نوری", national_id="8800000006",
                                   phone="09126666666")
        _acc_add_invoice(acc_conn, pid_acc, "closed",
                         work_date="2026-06-06",
                         closed_at="2026-06-06 10:00:00")
        acc_conn.close()

        shutil.copy2(acc_orig, acc_copy)
        sha_before = _sha256(acc_copy)

        # sync با کپی
        _set_acc_path(acc_copy)

        from src.adapters import accounting_bridge as bridge_mod
        from src.services.invoice_sync_service import InvoiceSyncService

        orig_fetch_closed = bridge_mod.fetch_closed_invoices
        orig_fetch_items = bridge_mod.fetch_invoice_items

        # bridge را به کپی هدایت می‌کنیم
        # (Config.ACCOUNTING_DB_PATH قبلاً set شد؛ کافی است)
        bridge_mod.fetch_closed_invoices = None  # تابع اصلی از Config می‌خواند
        bridge_mod.fetch_closed_invoices = orig_fetch_closed
        bridge_mod.fetch_invoice_items = orig_fetch_items

        try:
            InvoiceSyncService().run()
        finally:
            bridge_mod.fetch_closed_invoices = orig_fetch_closed
            bridge_mod.fetch_invoice_items = orig_fetch_items

        sha_after = _sha256(acc_copy)
        assert sha_before == sha_after, (
            f"accounting DB کپی دستکاری شد!\n"
            f"  before: {sha_before}\n"
            f"  after:  {sha_after}"
        )

        # WAL/SHM نباید تازه ساخته شده باشد
        wal = acc_copy + "-wal"
        shm = acc_copy + "-shm"
        assert not os.path.exists(wal), \
            "WAL file روی accounting copy ساخته شد — نشانه نوشتن"
        assert not os.path.exists(shm), \
            "SHM file روی accounting copy ساخته شد — نشانه نوشتن"

        print(f"\n[S6] SHA-256 before: {sha_before}")
        print(f"[S6] SHA-256 after:  {sha_after}")
        print(f"[S6] MATCH: {sha_before == sha_after}")
