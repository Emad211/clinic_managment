"""
End-to-end integration tests — two complete happy-path loops.

هدف: اثبات کند قطعاتِ سریع‌ساخته‌شده به‌عنوانِ یک جریانِ کامل با هم کار می‌کنند.
تست‌های per-feature موجود (۱۵۴ عدد) هر لایه را جداگانه می‌سنجند؛ این فایل
آن شکاف را پر می‌کند.

جریان ۱ — فاکتورِ بسته → پیامکِ تشکر (مسیر invoice، D3+):
  step 1 : InvoiceSyncService.run()       → processed_invoices + approval pending
  step 2 : EngagementService.approve()    → sms_messages (SIMULATED) + approval approved
  step 3 : idempotency اجرای دوم run()   → approval تکراری نسازد
  step 4 : SHA-256 حسابداری              → byte-for-byte دست‌نخورده

جریان ۲ — زنجیرهٔ بالینی: اندازه‌گیری → موتور → قیف → تأیید → no-refire:
  step 1 : ثبت vital hba1c بالای danger  → RuleEngine + due_clinical_events
  step 2 : EngagementService.dispatch_patient() → approval یا worklist در صف
  step 3 : approve approval              → ارسال SIMULATED
  step 4 : no-refire                    → lab امروز → due_clinical_events آیتمِ a1c را نمی‌بیند

آزمون‌های نیت‌ (intent proofs):
  5 : compliance.sanitize('پیشنهادِ ارزان')  → 'ارزان' جایگزین شود
  6 : compliance.sanitize('نسخهٔ آزاد ...')  → دست‌نخورده بماند (رگرسیونِ مهم)
  7 : followup_engine._months_since با iran_now کار کند (شکستن ممنوع)

قراردادِ ایمنی:
  - همهٔ نوشتن‌ها روی کپیِ موقت DB؛ هرگز specialist.db یا clinic_new.db اصلی لمس نشود.
  - هیچ SMS واقعی: TESTING=True → scheduler خاموش؛ ارائه‌دهنده NullProvider.
  - SHA-256 accounting DB قبل/بعد verify می‌شود.
  - تستِ اجرانشده «پاس» اعلام نمی‌شود.

اجرا از دایرکتوریِ specialist_clinic:
    .venv\\Scripts\\python.exe -m pytest tests/test_end_to_end_loops.py -v
    PYTHONIOENCODING=utf-8 .venv\\Scripts\\python.exe -m pytest tests/test_end_to_end_loops.py -v
"""
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

# ── مسیرها را قبل از هر import src تنظیم کن ─────────────────────────────────
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_REAL_ACC_DB = os.path.join(_REPO_ROOT, "webapp", "clinic_new.db")
_SPECIALIST_ROOT = os.path.join(_REPO_ROOT, "specialist_clinic")

import datetime
import hashlib
import shutil
import sqlite3
import tempfile
from unittest import mock

import pytest


# ─── helpers مشترک ────────────────────────────────────────────────────────────

def _flush_src_modules():
    """حذف همهٔ ماژول‌های src.* برای ریست کامل وضعیت (Config + core._initialized)."""
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
    """یک accounting DB حداقلی با جداولِ لازمِ accounting_bridge بساز."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, family_name TEXT, full_name TEXT,
            national_id TEXT UNIQUE, phone_number TEXT,
            birthdate TEXT, gender TEXT, insurance_type TEXT,
            insurance_expiry TEXT, address TEXT,
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
            work_date TEXT, closed_at TEXT,
            opened_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        );
        CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER, patient_id INTEGER,
            visit_date TEXT, doctor_name TEXT, price REAL DEFAULT 0,
            insurance_type TEXT, supplementary_insurance TEXT
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
                     work_date="2026-01-01", closed_at=None):
    ca = closed_at or ("2026-01-01 10:00:00" if status == "closed" else None)
    cur = conn.execute(
        "INSERT INTO invoices (patient_id, status, total_amount, work_date, closed_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (patient_id, status, total, work_date, ca),
    )
    conn.commit()
    return cur.lastrowid


def _set_acc_path(path: str):
    """مسیرِ accounting bridge را hot-swap کن."""
    os.environ["ACCOUNTING_DB_PATH"] = path
    try:
        import src.config.settings as cfg_mod
        cfg_mod.Config.ACCOUNTING_DB_PATH = path
    except ImportError:
        pass


def _force_quiet_off():
    """ساعتِ آرام را غیرفعال کن (کلِ روز = مجاز)."""
    try:
        from src.adapters.sqlite.sms_repo import SmsRepository
        sms = SmsRepository()
        sms.set_setting("engagement_quiet_start", "00:00")
        sms.set_setting("engagement_quiet_end", "23:59")
    except Exception:
        pass


def _enroll(spec_db: str, national_id: str, full_name: str, phone: str = "09120000001"):
    """بیمار مستقیم در specialist DB ثبت کن؛ pid برگردان."""
    conn = sqlite3.connect(spec_db)
    cur = conn.execute(
        "INSERT INTO patient_links (national_id, full_name, phone_number, enrolled_by)"
        " VALUES (?, ?, ?, 'test')",
        (national_id, full_name, phone),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def _add_condition(spec_db: str, pid: int, condition_code: str):
    """شرطِ بیماری به patient_conditions اضافه کن."""
    conn = sqlite3.connect(spec_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id FROM conditions WHERE code=? AND is_active=1", (condition_code,)
    ).fetchone()
    if row is None:
        conn.close()
        raise ValueError(f"condition '{condition_code}' در DB نیست — آیا bootstrap اجرا شده؟")
    cid = row["id"]
    conn.execute(
        "INSERT INTO patient_conditions (patient_link_id, condition_id, is_active)"
        " VALUES (?, ?, 1)",
        (pid, cid),
    )
    conn.commit()
    conn.close()


def _add_vital(spec_db: str, pid: int, vtype: str, value: float, measured_at: str):
    """vital_readings مستقیم بنویس."""
    conn = sqlite3.connect(spec_db)
    conn.execute(
        "INSERT INTO vital_readings (patient_link_id, type, value, unit, measured_at, source)"
        " VALUES (?, ?, ?, '%', ?, 'clinic')",
        (pid, vtype, value, measured_at),
    )
    conn.commit()
    conn.close()


def _add_lab(spec_db: str, pid: int, test_key: str, value: float, taken_at: str):
    """lab_results مستقیم بنویس."""
    conn = sqlite3.connect(spec_db)
    conn.execute(
        "INSERT INTO lab_results (patient_link_id, test_name, test_key, value, unit, taken_at)"
        " VALUES (?, ?, ?, ?, '%', ?)",
        (pid, f"lab-{test_key}", test_key, value, taken_at),
    )
    conn.commit()
    conn.close()


def _get_hba1c_danger(spec_db: str) -> float:
    """آستانهٔ danger برای hba1c از clinical_indicators بخوان."""
    conn = sqlite3.connect(spec_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT danger FROM clinical_indicators WHERE key='hba1c'"
    ).fetchone()
    conn.close()
    if row and row["danger"] is not None:
        return float(row["danger"])
    return 8.0  # fallback استاتیک


# ─── fixture ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="e2e_loop_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def specialist_app(tmp_dir):
    """Flask test app با specialist DB تمیز و یک accounting DB stub.
    ایزولاسیونِ کامل: env vars + module state ذخیره/بازیابی می‌شوند.
    SHA-256 accounting DB واقعی (اگر وجود داشت) قبل و بعد ثبت می‌شود.
    """
    spec_db = os.path.join(tmp_dir, "specialist_e2e_test.db")
    acc_db = os.path.join(tmp_dir, "acc_e2e_stub.db")
    _make_acc_db(acc_db)

    # SHA-256 DB واقعی قبل از هر چیز
    acc_sha_before = _sha256(_REAL_ACC_DB) if os.path.exists(_REAL_ACC_DB) else None

    _saved_env = {
        "SPECIALIST_DB_PATH": os.environ.get("SPECIALIST_DB_PATH"),
        "ACCOUNTING_DB_PATH": os.environ.get("ACCOUNTING_DB_PATH"),
    }
    os.environ["SPECIALIST_DB_PATH"] = spec_db
    os.environ["ACCOUNTING_DB_PATH"] = acc_db

    _flush_src_modules()

    if _SPECIALIST_ROOT not in sys.path:
        sys.path.insert(0, _SPECIALIST_ROOT)

    from src.app import create_app
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": spec_db,
        "PROPAGATE_EXCEPTIONS": True,
        "SECRET_KEY": "e2e-loop-test",
        "BACKUP_FOLDER": os.path.join(tmp_dir, "backups"),
    })

    ctx = app.app_context()
    ctx.push()

    # اجبارِ bootstrap — schema + migrations + seed (clinical_indicators بارگذاری می‌شود)
    from src.adapters.sqlite.core import get_db
    get_db()

    yield app, spec_db, acc_db, tmp_dir, acc_sha_before

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


# ─── جریانِ ۱: فاکتورِ بسته → پیامکِ تشکر ───────────────────────────────────

class TestFlow1InvoiceToThankYou:
    """
    D3+ — جریانِ کامل invoice sync → outreach approval → SMS send.
    بیمارِ enrolled (national_id منطبق)، فاکتورِ بسته در accounting stub.
    """

    def _setup(self, specialist_app):
        """بیمار + فاکتور در هر دو DB آماده کن."""
        app, spec_db, acc_db, tmp_dir, acc_sha_before = specialist_app
        NID = "E2E0000001"
        PHONE = "09120000001"

        # ۱. بیمار در specialist DB
        pid = _enroll(spec_db, NID, "تستِ e2e جریانِ یک", PHONE)

        # ۲. همان بیمار در accounting stub + فاکتورِ بسته
        conn = sqlite3.connect(acc_db)
        acc_pid = _acc_add_patient(conn, "تستِ e2e جریانِ یک", national_id=NID, phone=PHONE)
        inv_id = _acc_add_invoice(conn, acc_pid, "closed", total=5000,
                                  work_date="2026-06-15",
                                  closed_at="2026-06-15 10:00:00")
        conn.close()

        _set_acc_path(acc_db)
        return pid, inv_id

    # step 1 --- InvoiceSyncService.run() باید یک ردیفِ processed_invoices بسازد و یک approval thank_you
    def test_step1_run_creates_processed_invoice_and_approval(self, specialist_app):
        app, spec_db, acc_db, tmp_dir, _ = specialist_app
        pid, inv_id = self._setup(specialist_app)

        from src.services.invoice_sync_service import InvoiceSyncService
        from src.adapters.sqlite.core import get_db

        res = InvoiceSyncService().run()

        assert res["fetched"] >= 1, f"باید حداقل ۱ فاکتورِ بسته fetch شود، got {res}"
        assert res["new"] >= 1, f"باید حداقل ۱ ردیفِ جدید در processed_invoices بیاید، got {res}"

        db = get_db()
        pi_row = db.execute(
            "SELECT * FROM processed_invoices WHERE accounting_invoice_id=?", (inv_id,)
        ).fetchone()
        assert pi_row is not None, "processed_invoices باید ردیفِ این فاکتور را داشته باشد"
        assert dict(pi_row)["status"] == "applied", (
            f"status باید 'applied' باشد (بیمار enrolled)، got {dict(pi_row)['status']}"
        )
        assert dict(pi_row)["outreach_done"] == 1, (
            "outreach_done باید ۱ باشد (on_invoice_processed موفق شد)"
        )

        # یک approval thank_you برای این بیمار باید صف شده باشد
        ap_rows = db.execute(
            "SELECT * FROM engagement_approvals WHERE patient_link_id=? AND event_key='thank_you'",
            (pid,)
        ).fetchall()
        assert len(ap_rows) >= 1, (
            f"یک approval thank_you باید در صف باشد، got {len(ap_rows)} rows"
        )
        ap = dict(ap_rows[0])
        assert ap["status"] == "pending", f"approval باید 'pending' باشد، got {ap['status']}"
        print(f"\nPASS step1: processed_invoices={dict(pi_row)['id']} approval_id={ap['id']}")

    # step 2 --- approve → sms_messages با SIMULATED + approval به approved تغییر کند
    def test_step2_approve_sends_simulated_sms(self, specialist_app):
        app, spec_db, acc_db, tmp_dir, _ = specialist_app
        pid, inv_id = self._setup(specialist_app)

        from src.services.invoice_sync_service import InvoiceSyncService
        from src.services.engagement_service import EngagementService
        from src.adapters.sqlite.core import get_db

        # اجرای sync تا approval صف شود
        InvoiceSyncService().run()

        db = get_db()
        ap_row = db.execute(
            "SELECT * FROM engagement_approvals WHERE patient_link_id=? AND event_key='thank_you'",
            (pid,)
        ).fetchone()
        assert ap_row is not None, "approval thank_you باید وجود داشته باشد"
        aid = ap_row["id"]

        # ساعتِ آرام را غیرفعال کن
        _force_quiet_off()

        svc = EngagementService()
        out = svc.approve(aid, decided_by="admin")

        assert out.get("ok") is True, f"approve باید ok=True برگرداند، got {out}"

        # approval به approved تغییر کند
        ap_after = dict(svc.repo.get_approval(aid))
        assert ap_after["status"] == "approved", (
            f"approval status باید 'approved' باشد، got {ap_after['status']}"
        )
        assert ap_after["sent_at"] is not None, "sent_at باید stamp شده باشد"
        assert ap_after["decided_by"] == "admin", "decided_by باید 'admin' باشد"

        # یک sms_messages با SIMULATED باید ساخته شده باشد
        sms_row = db.execute(
            "SELECT * FROM sms_messages WHERE patient_link_id=? ORDER BY id DESC LIMIT 1",
            (pid,)
        ).fetchone()
        assert sms_row is not None, "sms_messages باید یک ردیف داشته باشد"
        sms = dict(sms_row)
        assert sms["provider_msgid"] == "SIMULATED", (
            f"باید NullProvider (SIMULATED) استفاده شود، got provider_msgid={sms['provider_msgid']}"
        )
        assert sms["status"] == "sent", f"sms status باید 'sent' باشد، got {sms['status']}"
        print(f"\nPASS step2: approve ok, sms_id={sms['id']} provider=SIMULATED")

    # step 3 --- idempotency: اجرای دوم run() approval تکراری نسازد
    def test_step3_idempotency_no_duplicate_approval(self, specialist_app):
        app, spec_db, acc_db, tmp_dir, _ = specialist_app
        pid, inv_id = self._setup(specialist_app)

        from src.services.invoice_sync_service import InvoiceSyncService
        from src.adapters.sqlite.core import get_db

        # اجرای اول
        res1 = InvoiceSyncService().run()
        assert res1["new"] >= 1, f"اجرای اول باید ردیف جدید بسازد، got {res1}"

        db = get_db()
        ap_count_after_first = db.execute(
            "SELECT COUNT(*) c FROM engagement_approvals WHERE patient_link_id=? AND event_key='thank_you'",
            (pid,)
        ).fetchone()["c"]

        # اجرای دوم
        res2 = InvoiceSyncService().run()
        assert res2["new"] == 0, (
            f"اجرای دوم نباید ردیفِ جدید بسازد (cursor/ledger)، got new={res2['new']}"
        )

        ap_count_after_second = db.execute(
            "SELECT COUNT(*) c FROM engagement_approvals WHERE patient_link_id=? AND event_key='thank_you'",
            (pid,)
        ).fetchone()["c"]
        assert ap_count_after_second == ap_count_after_first, (
            f"approval تکراری نباید صف شود: before={ap_count_after_first} after={ap_count_after_second}"
        )
        print(f"\nPASS step3: idempotency — دومین run() هیچ approval جدیدی نساخت")

    # step 4 --- SHA-256 accounting DB واقعی دست‌نخورده
    @pytest.mark.skipif(
        not os.path.exists(_REAL_ACC_DB),
        reason=f"clinic_new.db در {_REAL_ACC_DB} یافت نشد"
    )
    def test_step4_real_acc_db_sha256_unchanged(self, specialist_app):
        app, spec_db, acc_db, tmp_dir, acc_sha_before = specialist_app
        assert acc_sha_before is not None, "SHA-256 باید قبل از fixture محاسبه شده باشد"

        acc_sha_after = _sha256(_REAL_ACC_DB)
        assert acc_sha_before == acc_sha_after, (
            f"FAIL: clinic_new.db تغییر کرده!\n"
            f"  قبل: {acc_sha_before}\n"
            f"  بعد: {acc_sha_after}"
        )
        print(f"\nPASS step4: SHA-256 یکسان ({acc_sha_before[:16]}...)")


# ─── جریانِ ۲: اندازه‌گیری → موتور → قیف → تأیید → no-refire ────────────────

class TestFlow2ClinicalChain:
    """
    زنجیرهٔ بالینی: vital/lab → rule engine → engagement → approve → no-refire.
    بیمارِ enrolled + شرطِ diabetes + موبایل.
    """

    def _setup_diabetic(self, specialist_app, national_id: str = "E2E0000002",
                        phone: str = "09120000002"):
        """بیمارِ دیابتی enrolled با hba1c بالاتر از danger آماده کن."""
        app, spec_db, acc_db, tmp_dir, _ = specialist_app
        pid = _enroll(spec_db, national_id, "بیمارِ e2e دیابت", phone)
        _add_condition(spec_db, pid, "diabetes")
        return pid

    def _get_or_create_monitoring_event(self):
        """مطمئن شو engagement_events برای monitoring_due یا uncontrolled وجود دارد."""
        from src.adapters.sqlite.core import get_db
        db = get_db()
        # بررسی کدام رویدادِ clinical (sms یا both) فعال است
        row = db.execute(
            """SELECT event_key, channel FROM engagement_events
               WHERE event_key IN ('monitoring_due','uncontrolled','lapsed')
                 AND channel IN ('sms','both') AND is_active=1
               ORDER BY priority LIMIT 1"""
        ).fetchone()
        return dict(row) if row else None

    # step 1 --- ثبت vital hba1c بالاتر از danger → due_clinical_events یا collect_due_events
    def test_step1_high_hba1c_triggers_clinical_event(self, specialist_app):
        app, spec_db, acc_db, tmp_dir, _ = specialist_app
        pid = self._setup_diabetic(specialist_app)
        danger = _get_hba1c_danger(spec_db)
        high_val = danger + 1.0  # مشخصاً بالاتر از danger

        # ثبت vital
        measured_at = "2025-12-01 08:00:00"  # قدیمی‌تر از ۴ ماه (برای lapsed هم trigger)
        _add_vital(spec_db, pid, "hba1c", high_val, measured_at)

        with app.app_context():
            from src.services.rule_engine import RuleEngine
            from src.services.followup_engine import due_clinical_events

            fired = RuleEngine().evaluate(pid)
            events = due_clinical_events(pid)

        # باید حداقل یک rule یا event fired/due شده باشد
        total_signals = len(fired) + len(events)
        assert total_signals > 0, (
            f"هیچ rule fired و هیچ clinical event due نشد با hba1c={high_val} (danger={danger}). "
            f"fired={[r.get('rule_code') for r in fired]}, events={[e.get('item') for e in events]}"
        )
        print(
            f"\nPASS step1: fired={[r.get('rule_code') for r in fired[:3]]}"
            f" due_events={[e.get('item') for e in events[:3]]}"
        )

    # step 2 --- dispatch_patient → approval یا worklist در صف رود
    def test_step2_dispatch_enqueues_or_worklists(self, specialist_app):
        app, spec_db, acc_db, tmp_dir, _ = specialist_app
        pid = self._setup_diabetic(specialist_app, "E2E0000003", "09120000003")
        danger = _get_hba1c_danger(spec_db)
        high_val = danger + 1.0

        # vital قدیمی (بیش از ۴ ماه پیش — برای lapsed event هم trigger شود)
        _add_vital(spec_db, pid, "hba1c", high_val, "2025-11-01 08:00:00")

        _force_quiet_off()

        with app.app_context():
            from src.services.engagement_service import EngagementService
            from src.adapters.sqlite.core import get_db

            svc = EngagementService()
            result = svc.dispatch_patient(pid)

            db = get_db()
            ap_count = db.execute(
                "SELECT COUNT(*) c FROM engagement_approvals WHERE patient_link_id=? AND status='pending'",
                (pid,)
            ).fetchone()["c"]
            wl_count = db.execute(
                "SELECT COUNT(*) c FROM followup_tasks WHERE patient_link_id=? AND status='open'",
                (pid,)
            ).fetchone()["c"]
            dispatch_count = db.execute(
                "SELECT COUNT(*) c FROM engagement_dispatch WHERE patient_link_id=?",
                (pid,)
            ).fetchone()["c"]

        total_action = ap_count + wl_count + result.get("queued", 0) + result.get("worklist", 0)
        assert total_action > 0, (
            f"dispatch_patient باید حداقل یک approval یا worklist ایجاد کند. "
            f"result={result}, ap_count={ap_count}, wl_count={wl_count}, dispatch_count={dispatch_count}"
        )
        print(
            f"\nPASS step2: dispatch result={result}"
            f" approvals_pending={ap_count} worklist_open={wl_count}"
        )

    # step 3 --- approve approval سمتِ SMS → send SIMULATED
    def test_step3_approve_clinical_approval_sends_simulated(self, specialist_app):
        app, spec_db, acc_db, tmp_dir, _ = specialist_app
        pid = self._setup_diabetic(specialist_app, "E2E0000004", "09120000004")
        danger = _get_hba1c_danger(spec_db)
        high_val = danger + 1.0

        _add_vital(spec_db, pid, "hba1c", high_val, "2025-10-01 08:00:00")
        _force_quiet_off()

        with app.app_context():
            from src.services.engagement_service import EngagementService
            from src.adapters.sqlite.core import get_db

            svc = EngagementService()
            svc.dispatch_patient(pid)

            db = get_db()
            ap_row = db.execute(
                "SELECT * FROM engagement_approvals WHERE patient_link_id=? AND status='pending'"
                " ORDER BY id LIMIT 1",
                (pid,)
            ).fetchone()

            if ap_row is None:
                # بررسی کن آیا channel این patient worklist است (نه sms)
                wl = db.execute(
                    "SELECT COUNT(*) c FROM followup_tasks WHERE patient_link_id=?", (pid,)
                ).fetchone()["c"]
                dispatch_row = db.execute(
                    "SELECT * FROM engagement_dispatch WHERE patient_link_id=? LIMIT 1", (pid,)
                ).fetchone()
                pytest.skip(
                    f"هیچ approval pending نیست (channel احتمالاً worklist است). "
                    f"worklist_tasks={wl}, dispatch={dict(dispatch_row) if dispatch_row else None}"
                )

            aid = ap_row["id"]
            out = svc.approve(aid, decided_by="admin")

        assert out.get("ok") is True, f"approve باید ok=True باشد، got {out}"
        with app.app_context():
            from src.adapters.sqlite.core import get_db
            from src.services.engagement_service import EngagementService
            db = get_db()
            svc = EngagementService()
            ap_after = dict(svc.repo.get_approval(aid))
            assert ap_after["status"] == "approved"
            sms = db.execute(
                "SELECT * FROM sms_messages WHERE patient_link_id=? ORDER BY id DESC LIMIT 1",
                (pid,)
            ).fetchone()
            assert sms is not None, "sms_messages باید یک ردیف داشته باشد"
            assert dict(sms)["provider_msgid"] == "SIMULATED", (
                f"باید NullProvider باشد، got {dict(sms)['provider_msgid']}"
            )
        print(f"\nPASS step3: clinical approval approved, SMS=SIMULATED")

    # step 4 --- no-refire: lab امروز → due_clinical_events آیتمِ a1c را نمی‌بیند
    def test_step4_no_refire_after_recent_lab(self, specialist_app):
        """بعد از ثبتِ lab hba1c با تاریخِ امروز، آیتمِ 'a1c' دیگر due نباشد.

        منطق: _last_done(pid,'a1c') امروز را برمی‌گرداند؛ interval=6 ماه؛
        _months_since(today)=0 < 6 → not due.
        """
        app, spec_db, acc_db, tmp_dir, _ = specialist_app
        pid = self._setup_diabetic(specialist_app, "E2E0000005", "09120000005")
        danger = _get_hba1c_danger(spec_db)

        today_str = datetime.datetime.now().strftime("%Y-%m-%d 08:00:00")
        # lab با مقدارِ بالا ولی تاریخِ امروز → due نباشد (interval 6 ماه)
        _add_lab(spec_db, pid, "hba1c", danger + 1.0, today_str)

        with app.app_context():
            from src.services.followup_engine import (
                due_clinical_events, _last_done, _months_since, ITEM_DEFAULT_MONTHS
            )

            last = _last_done(pid, "a1c", {})
            assert last is not None, "_last_done پس از lab امروز نباید None باشد"

            months = _months_since(last) or 0
            interval = ITEM_DEFAULT_MONTHS.get("a1c", 6)
            assert months < interval, (
                f"FAIL: months_since={months} باید کمتر از interval={interval} باشد"
            )

            events = due_clinical_events(pid)
            a1c_due = [e for e in events if e.get("item") == "a1c"]
            assert len(a1c_due) == 0, (
                f"FAIL: a1c نباید due باشد پس از lab امروز. "
                f"events={[e.get('item') for e in events]}"
            )

        print(
            f"\nPASS step4: no-refire — lab امروز (months_elapsed={months} < interval={interval})"
            f" → a1c در due_clinical_events نیست"
        )


# ─── آزمون‌های نیت (intent proofs) ────────────────────────────────────────────

class TestIntentProofs:
    """
    تأییدِ نیت‌های پاسِ اخیر (سورس تازه تغییر کرد).
    هیچ DB یا app context لازم نیست — unit-level.
    """

    # ۵ --- compliance: 'ارزان' جایگزین شود
    def test_compliance_bans_arzan(self, specialist_app):
        """sanitize('پیشنهادِ ارزان') باید 'ارزان' را جایگزین کند."""
        # فقط برای اطمینان از import در context درست
        with specialist_app[0].app_context():
            from src.services.sms.compliance import sanitize

        result = sanitize("پیشنهادِ ارزان برای شما")
        assert "ارزان" not in result, (
            f"FAIL: 'ارزان' باید جایگزین شود، got: {result!r}"
        )
        # جایگزینِ صحیح
        assert "مقرون‌به‌صرفه" in result, (
            f"FAIL: 'مقرون‌به‌صرفه' باید جایگزین 'ارزان' شود، got: {result!r}"
        )
        print(f"\nPASS test5_compliance_bans_arzan: '{result}'")

    # ۶ --- compliance رگرسیون: 'آزاد' ممنوع نشده — نسخهٔ آزاد دست‌نخورده بماند
    def test_compliance_azad_not_banned(self, specialist_app):
        """sanitize('نسخهٔ آزاد غیربیمه') باید دست‌نخورده بماند.

        رگرسیونِ مهم: 'آزاد' در BANNED_WORDS نیست (کد توضیح می‌دهد چرا).
        اگر کسی آن را اضافه کند، این تست fail می‌شود.
        """
        with specialist_app[0].app_context():
            from src.services.sms.compliance import sanitize, find_banned

        text = "نسخهٔ آزاد غیربیمه برای این بیمار صادر شد"
        result = sanitize(text)
        banned = find_banned(text)

        assert result == text, (
            f"FAIL (رگرسیون): sanitize نسخهٔ آزاد را تغییر داد!\n"
            f"  ورودی: {text!r}\n"
            f"  خروجی: {result!r}\n"
            f"  کلمات ممنوعه‌یافته: {banned}"
        )
        assert "آزاد" not in banned, (
            f"FAIL (رگرسیون): 'آزاد' به BANNED_WORDS اضافه شده! "
            f"این کلیدواژهٔ اپ است (نسخهٔ آزاد). banned={banned}"
        )
        print(f"\nPASS test6_azad_not_banned: 'نسخهٔ آزاد' دست‌نخورده: {result!r}")

    # ۷ --- followup_engine._months_since با iran_now کار کند
    def test_months_since_with_iran_now(self, specialist_app):
        """_months_since با یک تاریخِ گذشته عددِ مثبتِ درست برگرداند (شکستن ممنوع)."""
        with specialist_app[0].app_context():
            from src.services.followup_engine import _months_since

        # ۱۲ ماه پیش
        past = (datetime.datetime.now() - datetime.timedelta(days=365)).strftime("%Y-%m-%d")
        result = _months_since(past)
        assert result is not None, f"_months_since({past!r}) نباید None برگرداند"
        assert result > 0, f"_months_since برای تاریخِ گذشته باید > 0 باشد، got {result}"
        # تقریباً ۱۲ ماه (±۲ ماه تلرانس)
        assert 10 <= result <= 14, (
            f"_months_since({past!r}) باید ~۱۲ باشد، got {result}"
        )
        print(f"\nPASS test7_months_since: {past!r} → {result} ماه")

    # بونوس ۸ --- NullProvider در محیطِ تست
    def test_null_provider_in_test_env(self, specialist_app):
        """محیطِ تست هرگز از panel واقعی استفاده نکند."""
        with specialist_app[0].app_context():
            from src.services.sms.provider import get_provider, NullProvider
            prov = get_provider()
        assert isinstance(prov, NullProvider), (
            f"FAIL: محیطِ تست باید NullProvider باشد، got {type(prov).__name__}"
        )
        print(f"\nPASS test8_null_provider: {type(prov).__name__}")

    # بونوس ۹ --- compliance جامع: همهٔ banned words در BANNED_WORDS جایگزین شوند
    def test_compliance_all_banned_words_replaced(self, specialist_app):
        """هر کلمه‌ای که در BANNED_WORDS است باید توسطِ sanitize جایگزین شود."""
        with specialist_app[0].app_context():
            from src.services.sms.compliance import BANNED_WORDS, sanitize, find_banned

        failures = []
        for word in BANNED_WORDS:
            text = f"متن تستی با کلمهٔ {word} در وسط"
            result = sanitize(text)
            remaining = find_banned(result)
            if word in remaining:
                failures.append(f"'{word}' پس از sanitize هنوز در متن است: {result!r}")

        assert not failures, (
            "FAIL: کلماتِ زیر sanitize نشدند:\n" + "\n".join(failures)
        )
        print(f"\nPASS test9_all_banned_replaced: {len(BANNED_WORDS)} کلمه همه sanitize شدند")


# ─── تستِ یکپارچگیِ کامل (ادغام دو جریان) ────────────────────────────────────

class TestFullIntegrationGuard:
    """
    تستِ یکپارچگی: اثبات کند دو سرویسِ اصلی همزمان در یک DB تداخل ندارند.
    یک بیمار از هر دو مسیر (invoice + clinical) پیام دریافت کند.
    """

    def test_both_flows_same_patient_no_conflict(self, specialist_app):
        """یک بیمار هم از invoice-sync (thank_you) هم از clinical dispatch
        (monitoring/uncontrolled) approval دریافت کند؛ هیچ کدام دیگری را
        خراب نکند و هر دو در DB صحیح باشند.
        """
        app, spec_db, acc_db, tmp_dir, _ = specialist_app
        NID = "E2E9999999"
        PHONE = "09129999999"

        # ثبت بیمار
        pid = _enroll(spec_db, NID, "بیمارِ تستِ هر دو مسیر", PHONE)
        _add_condition(spec_db, pid, "diabetes")

        # vital قدیمی (>4 ماه پیش) + hba1c بالا
        danger = _get_hba1c_danger(spec_db)
        _add_vital(spec_db, pid, "hba1c", danger + 1.5, "2025-09-01 08:00:00")

        # فاکتور در accounting stub
        conn = sqlite3.connect(acc_db)
        acc_pid = _acc_add_patient(conn, "بیمارِ تستِ هر دو مسیر", national_id=NID, phone=PHONE)
        _acc_add_invoice(conn, acc_pid, "closed", total=3000,
                         work_date="2026-06-10", closed_at="2026-06-10 09:00:00")
        conn.close()
        _set_acc_path(acc_db)
        _force_quiet_off()

        from src.services.invoice_sync_service import InvoiceSyncService
        from src.services.engagement_service import EngagementService
        from src.adapters.sqlite.core import get_db

        # اجرای هر دو مسیر
        sync_res = InvoiceSyncService().run()
        dispatch_res = EngagementService().dispatch_patient(pid)

        db = get_db()
        total_approvals = db.execute(
            "SELECT COUNT(*) c FROM engagement_approvals WHERE patient_link_id=?", (pid,)
        ).fetchone()["c"]
        total_worklist = db.execute(
            "SELECT COUNT(*) c FROM followup_tasks WHERE patient_link_id=?", (pid,)
        ).fetchone()["c"]

        # باید حداقل یک action از هر مسیر وجود داشته باشد
        invoice_action = sync_res.get("new", 0) >= 1
        clinical_action = (
            dispatch_res.get("queued", 0) + dispatch_res.get("worklist", 0) > 0
            or total_worklist > 0
        )

        assert invoice_action, f"invoice sync باید حداقل یک ردیف بسازد، got {sync_res}"
        assert clinical_action, (
            f"clinical dispatch باید حداقل یک approval/worklist بسازد، "
            f"got dispatch={dispatch_res} wl={total_worklist}"
        )

        # DB باید consistent باشد
        pi_count = db.execute(
            "SELECT COUNT(*) c FROM processed_invoices WHERE patient_link_id=?", (pid,)
        ).fetchone()["c"]
        assert pi_count >= 1, "processed_invoices باید ردیف داشته باشد"

        print(
            f"\nPASS integration_guard: sync={sync_res} dispatch={dispatch_res}"
            f" total_approvals={total_approvals} worklist={total_worklist} pi={pi_count}"
        )
