"""
ADR-0005 — Canonical Consistency test suite (تکمیل ADR-0005).

هدف: ثابت کند یک HbA1c «فقط‌آزمایش‌محور» (lab-only) در همه مصرف‌کننده‌ها
     یک‌جور دیده می‌شود:
     - VitalsService.control_status → uncontrolled
     - AnalyticsService.patient_analytics → کاشیِ hba1c با latest و level
     - followup_engine._last_done → تاریخِ lab
     - RuleEngine.build_facts → indicator['hba1c']['latest'] و level
     - زنجیرهٔ no-refire با due_clinical_events
     - get_readings_canonical (اتحاد سری ascending)
     - کلیدِ vital-only رگرسیون
     - کلیدِ بدونِ داده → سریِ خالی

قوانین ایمنی:
  - فقط روی کپیِ موقت specialist DB؛ هرگز specialist.db اصلی لمس نشود.
  - SHA-256 حسابداری قبل/بعد یکسان (اگر clinic_new.db وجود داشت).
  - هیچ SMS واقعی (TESTING=True → scheduler خاموش).
  - هیچ رکوردِ بیماریِ آستانه هاردکد نشده؛ از clinical_indicators خوانده می‌شود.

اجرا:
    .venv/Scripts/python.exe -m pytest tests/test_canonical_consistency.py -v
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

import pytest


# ─── helpers ──────────────────────────────────────────────────────────────────

def _flush_src_modules():
    """حذف همهٔ ماژول‌های src.* از sys.modules برای ریست کامل وضعیت."""
    for mod in list(sys.modules.keys()):
        if mod == "src" or mod.startswith("src."):
            del sys.modules[mod]


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_minimal_acc_db(path: str):
    """یک accounting DB حداقلی (stub) برای اجرای آفلاین بساز."""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, family_name TEXT, full_name TEXT,
            national_id TEXT UNIQUE, phone_number TEXT,
            birthdate TEXT, gender TEXT, is_foreign INTEGER DEFAULT 0,
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
            work_date TEXT, closed_at TEXT,
            opened_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        )
    """)
    conn.commit()
    conn.close()


def _enroll_patient(spec_db: str, full_name="بیمار canonical", national_id="CC0000001",
                    phone="09100000001"):
    """بیمار جدید مستقیم در specialist DB ثبت کن؛ pid برگردان."""
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
    """شرطِ بیماری (مثلاً 'diabetes') مستقیم به patient_conditions اضافه کن."""
    conn = sqlite3.connect(spec_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id FROM conditions WHERE code=? AND is_active=1", (condition_code,)
    ).fetchone()
    if row is None:
        conn.close()
        raise ValueError(f"condition با code={condition_code!r} در DB نیست")
    condition_id = row["id"]
    conn.execute(
        "INSERT INTO patient_conditions (patient_link_id, condition_id, is_active)"
        " VALUES (?, ?, 1)",
        (pid, condition_id),
    )
    conn.commit()
    conn.close()
    return condition_id


def _add_lab_direct(spec_db: str, pid: int, test_name: str, value: float,
                    taken_at: str, test_key: str, unit: str = "%"):
    """lab_results مستقیم در DB بنویس (بدونِ app context)."""
    conn = sqlite3.connect(spec_db)
    conn.execute(
        "INSERT INTO lab_results"
        " (patient_link_id, test_name, test_key, value, unit, taken_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (pid, test_name, test_key, value, unit, taken_at),
    )
    conn.commit()
    conn.close()


def _add_vital_direct(spec_db: str, pid: int, vtype: str, value: float,
                      measured_at: str, unit: str = "%"):
    """vital_readings مستقیم در DB بنویس."""
    conn = sqlite3.connect(spec_db)
    conn.execute(
        "INSERT INTO vital_readings (patient_link_id, type, value, unit, measured_at, source)"
        " VALUES (?, ?, ?, ?, ?, 'clinic')",
        (pid, vtype, value, unit, measured_at),
    )
    conn.commit()
    conn.close()


def _get_hba1c_thresholds(spec_db: str):
    """آستانه‌های warn و danger برای hba1c از clinical_indicators بخوان."""
    conn = sqlite3.connect(spec_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT warn, danger, direction FROM clinical_indicators WHERE key='hba1c'"
    ).fetchone()
    conn.close()
    if row and row["danger"] is not None:
        return float(row["danger"]), float(row["warn"]) if row["warn"] is not None else None
    # fallback از THRESHOLDS استاتیک vitals_service
    return 8.0, 7.0


# ─── fixture ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="canon_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def specialist_app(tmp_dir):
    """Flask test app با یک specialist DB تمیز در tmp_dir.

    SHA-256 accounting DB قبل از fixture ذخیره می‌شود؛ بعد از تست verify می‌شود.
    اگر clinic_new.db واقعی نبود، یک stub حداقلی ساخته می‌شود.
    """
    spec_db = os.path.join(tmp_dir, "specialist_canon_test.db")

    if os.path.exists(_REAL_ACC_DB):
        acc_db = os.path.join(tmp_dir, "acc_copy.db")
        shutil.copy2(_REAL_ACC_DB, acc_db)
        acc_sha_before = _sha256(_REAL_ACC_DB)
    else:
        acc_db = os.path.join(tmp_dir, "acc_stub.db")
        _make_minimal_acc_db(acc_db)
        acc_sha_before = None

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
        "SECRET_KEY": "canon-consistency-test",
        "BACKUP_FOLDER": os.path.join(tmp_dir, "backups"),
    })

    ctx = app.app_context()
    ctx.push()

    # اجبارِ bootstrap: schema + migrations + seed
    from src.adapters.sqlite.core import get_db
    get_db()

    yield app, spec_db, tmp_dir, acc_sha_before

    ctx.pop()

    for key, val in _saved_env.items():
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val

    try:
        import src.adapters.sqlite.core as _core
        _core._initialized = False
    except Exception:
        pass


# ─── کلاس اصلی تست ────────────────────────────────────────────────────────────

class TestCanonicalConsistency:
    """
    سازگاریِ canonical: یک HbA1c lab-only در همهٔ مصرف‌کننده‌ها یک‌جور دیده می‌شود.
    """

    # ── setup مشترک: بیمار enrolled + شرطِ diabetes + یک lab hba1c بالاتر از danger ─────

    def _setup_patient(self, app, spec_db: str, national_id: str, lab_value: float,
                       taken_at: str = "2026-06-01 08:00:00"):
        """بیمار با diabetes + lab hba1c آماده کن؛ pid را برگردان."""
        pid = _enroll_patient(spec_db, national_id=national_id,
                              full_name=f"بیمارِ canonical {national_id}")
        _add_condition(spec_db, pid, "diabetes")
        _add_lab_direct(spec_db, pid, "HbA1c-آزمایشگاه", lab_value, taken_at,
                        test_key="hba1c", unit="%")
        return pid

    # ──────────────────────────────────────────────────────────────────────────
    # تست ۱: control_status → uncontrolled (lab danger را می‌بیند)
    # ──────────────────────────────────────────────────────────────────────────

    def test_01_control_status_uncontrolled_lab_only(self, specialist_app):
        """VitalsService.control_status باید با یک HbA1c فقط‌آزمایش‌محور بالاتر از danger
        وضعیتِ 'uncontrolled' برگرداند."""
        app, spec_db, tmp_dir, _ = specialist_app
        danger_thresh, _ = _get_hba1c_thresholds(spec_db)
        lab_val = danger_thresh + 0.5  # مشخصاً بالاتر از danger

        pid = self._setup_patient(app, spec_db, "CC0000001", lab_val)

        with app.app_context():
            from src.adapters.sqlite.vitals_repo import VitalsRepository
            from src.services.vitals_service import VitalsService
            cs = VitalsService(repo=VitalsRepository()).control_status(pid)

        assert cs["status"] == "uncontrolled", (
            f"FAIL: control_status='{{cs['status']}}' — "
            f"انتظار 'uncontrolled' با hba1c={lab_val} (danger>={danger_thresh}). "
            f"flags={cs.get('flags')}"
        ).format(cs=cs)
        print(f"PASS test_01: control_status='uncontrolled' با lab hba1c={lab_val}")

    # ──────────────────────────────────────────────────────────────────────────
    # تست ۲: patient_analytics → کاشیِ hba1c با latest و level='danger'؛ charts هم
    # ──────────────────────────────────────────────────────────────────────────

    def test_02_analytics_tile_and_chart_not_none(self, specialist_app):
        """AnalyticsService.patient_analytics باید:
           - کاشیِ hba1c با latest==مقدارِ lab و level=='danger' داشته باشد
           - charts['hba1c'] با مقدارِ lab در values داشته باشد
        این همان تناقضِ on-page بود که ADR-0005 رفع کرد."""
        app, spec_db, tmp_dir, _ = specialist_app
        danger_thresh, _ = _get_hba1c_thresholds(spec_db)
        lab_val = danger_thresh + 0.5

        pid = self._setup_patient(app, spec_db, "CC0000002", lab_val)

        with app.app_context():
            from src.services.analytics_service import AnalyticsService
            result = AnalyticsService().patient_analytics(pid)

        # کاشیِ hba1c
        ind_tile = next((i for i in result.get("indicators", [])
                         if i.get("key") == "hba1c"), None)
        assert ind_tile is not None, (
            "FAIL: کاشیِ 'hba1c' در indicators نیست — "
            f"کلیدهای موجود: {[i.get('key') for i in result.get('indicators', [])]}"
        )
        assert ind_tile["latest"] is not None, (
            "FAIL: کاشیِ hba1c.latest=None است (تناقضِ on-page رفع نشده)"
        )
        assert abs(ind_tile["latest"] - lab_val) < 0.001, (
            f"FAIL: کاشیِ hba1c.latest={ind_tile['latest']} "
            f"باید {lab_val} باشد (مقدارِ lab)"
        )
        assert ind_tile["level"] == "danger", (
            f"FAIL: کاشیِ hba1c.level='{ind_tile['level']}' باید 'danger' باشد"
        )

        # charts
        charts = result.get("charts", {})
        assert "hba1c" in charts, (
            f"FAIL: 'hba1c' در charts نیست — کلیدها: {list(charts.keys())}"
        )
        chart_values = charts["hba1c"].get("values", [])
        assert lab_val in chart_values, (
            f"FAIL: مقدارِ lab ({lab_val}) در charts['hba1c']['values'] نیست: {chart_values}"
        )
        print(
            f"PASS test_02: کاشیِ hba1c.latest={ind_tile['latest']} "
            f"level='{ind_tile['level']}' و charts درست است"
        )

    # ──────────────────────────────────────────────────────────────────────────
    # تست ۳: followup_engine._last_done → تاریخِ lab
    # ──────────────────────────────────────────────────────────────────────────

    def test_03_last_done_returns_lab_date(self, specialist_app):
        """followup_engine._last_done(pid,'a1c',{}) باید تاریخِ lab را برگرداند (recall بسته)."""
        app, spec_db, tmp_dir, _ = specialist_app
        danger_thresh, _ = _get_hba1c_thresholds(spec_db)
        lab_val = danger_thresh + 0.5
        taken_at = "2026-06-01 08:00:00"

        pid = self._setup_patient(app, spec_db, "CC0000003", lab_val, taken_at=taken_at)

        with app.app_context():
            from src.services.followup_engine import _last_done
            last = _last_done(pid, "a1c", {})

        assert last is not None, (
            "FAIL: _last_done برای 'a1c' بعد از lab باید مقدار داشته باشد (نه None)"
        )
        assert last.startswith("2026-06-01"), (
            f"FAIL: _last_done باید تاریخِ lab '2026-06-01' باشد، است: {last!r}"
        )
        print(f"PASS test_03: _last_done='{{last}}' — تاریخِ lab صحیح".format(last=last[:10]))

    # ──────────────────────────────────────────────────────────────────────────
    # تست ۴: RuleEngine.build_facts → indicator['hba1c']['latest'] و level=='danger'
    # ──────────────────────────────────────────────────────────────────────────

    def test_04_rule_engine_build_facts_sees_lab(self, specialist_app):
        """RuleEngine.build_facts باید lab hba1c را در indicator['hba1c'] ببیند
        با latest==مقدارِ lab و level=='danger'."""
        app, spec_db, tmp_dir, _ = specialist_app
        danger_thresh, _ = _get_hba1c_thresholds(spec_db)
        lab_val = danger_thresh + 0.5

        pid = self._setup_patient(app, spec_db, "CC0000004", lab_val)

        with app.app_context():
            from src.services.rule_engine import RuleEngine
            facts = RuleEngine().build_facts(pid)

        ind = facts.get("indicator", {})
        assert "hba1c" in ind, (
            f"FAIL: 'hba1c' در facts['indicator'] نیست — "
            f"کلیدها: {list(ind.keys())}"
        )
        hba1c_fact = ind["hba1c"]
        assert abs(hba1c_fact["latest"] - lab_val) < 0.001, (
            f"FAIL: facts['indicator']['hba1c']['latest']={hba1c_fact['latest']} "
            f"باید {lab_val} باشد"
        )
        assert hba1c_fact["level"] == "danger", (
            f"FAIL: facts['indicator']['hba1c']['level']="
            f"'{hba1c_fact['level']}' باید 'danger' باشد"
        )
        print(
            f"PASS test_04: RuleEngine.build_facts hba1c="
            f"{hba1c_fact['latest']} level='{hba1c_fact['level']}'"
        )

    # ──────────────────────────────────────────────────────────────────────────
    # تست ۵: زنجیرهٔ no-refire
    #   ۵a: پیش از lab، due_clinical_events ممکن است a1c را due ببیند (اگر rule fire شود)
    #   ۵b: پس از lab با تاریخِ امروز، _last_done تازه است پس a1c دیگر due نیست
    # ──────────────────────────────────────────────────────────────────────────

    def test_05_no_refire_after_lab(self, specialist_app):
        """بعد از ثبتِ lab hba1c با تاریخِ امروز، آیتمِ 'a1c' دیگر due نباشد.

        منطق: _last_done برای 'a1c' امروز را برمی‌گرداند؛ interval پیش‌فرضِ 'a1c'
        شش ماه است (ITEM_DEFAULT_MONTHS['a1c']=6). _months_since(today)=0 < 6
        → due_clinical_events آیتمِ 'a1c' را حذف می‌کند.
        """
        app, spec_db, tmp_dir, _ = specialist_app
        danger_thresh, _ = _get_hba1c_thresholds(spec_db)
        lab_val = danger_thresh + 0.5

        pid = _enroll_patient(spec_db, national_id="CC0000005",
                              full_name="بیمارِ no-refire")
        _add_condition(spec_db, pid, "diabetes")

        # ثبتِ lab با تاریخِ امروز (interval پیش‌فرض a1c=6 ماه، 0 ماه گذشته → not due)
        today_str = datetime.datetime.now().strftime("%Y-%m-%d 08:00:00")
        _add_lab_direct(spec_db, pid, "HbA1c-آزمایشگاه", lab_val, today_str,
                        test_key="hba1c", unit="%")

        with app.app_context():
            from src.services.followup_engine import _last_done, ITEM_DEFAULT_MONTHS, _months_since

            last = _last_done(pid, "a1c", {})
            assert last is not None, (
                "FAIL: _last_done پس از lab امروز نباید None باشد"
            )
            months_elapsed = _months_since(last) or 0
            interval = ITEM_DEFAULT_MONTHS.get("a1c", 6)
            # اگر _months_since(today)==0 و interval==6: 0 < 6 → not due
            is_not_due = months_elapsed < interval
            assert is_not_due, (
                f"FAIL: پس از lab امروز، a1c باید not-due باشد. "
                f"months_elapsed={months_elapsed}, interval={interval}"
            )

            # تأییدِ کامل از due_clinical_events
            from src.services.followup_engine import due_clinical_events
            events = due_clinical_events(pid)
            a1c_due = [e for e in events if e.get("item") == "a1c"]
            assert len(a1c_due) == 0, (
                f"FAIL: a1c نباید در due_clinical_events باشد پس از lab امروز. "
                f"events={[e.get('item') for e in events]}"
            )

        print(
            f"PASS test_05: پس از lab امروز، a1c در due_clinical_events نیست "
            f"(months_elapsed={months_elapsed}, interval={interval})"
        )

    # ──────────────────────────────────────────────────────────────────────────
    # تست ۵b: پیش از lab — a1c باید due باشد (اگر rule T2-MON-A1C-01 fire شود)
    # ──────────────────────────────────────────────────────────────────────────

    def test_05b_a1c_due_before_lab(self, specialist_app):
        """پیش از ثبتِ هر lab hba1c، rule T2-MON-A1C-01 (اگر fire شود) باید a1c را due ببیند.

        بیمارِ دیابتی بدونِ هیچ vital/lab → _last_done=None → never-done → due.
        """
        app, spec_db, tmp_dir, _ = specialist_app

        pid = _enroll_patient(spec_db, national_id="CC0000006", full_name="بیمارِ no-lab")
        _add_condition(spec_db, pid, "diabetes")
        # هیچ vital/lab ثبت نشده

        with app.app_context():
            from src.services.followup_engine import due_clinical_events
            events = due_clinical_events(pid)
            a1c_due = [e for e in events if e.get("item") == "a1c"]

        # اگر rule T2-MON-A1C-01 fire نشود (بیمارِ جدید بدونِ vital)، test را skip کن
        if len(a1c_due) == 0:
            # بررسی می‌کنیم rule اصلاً fire شده یا نه
            with app.app_context():
                from src.services.rule_engine import RuleEngine
                fired = RuleEngine().evaluate(pid)
                mon_a1c_fired = any(r.get("rule_code") == "T2-MON-A1C-01" for r in fired)

            if not mon_a1c_fired:
                pytest.skip(
                    "T2-MON-A1C-01 برای بیمارِ بدونِ vital fire نشد (trigger نیاز به HbA1c دارد) — "
                    "این سناریو با تست ۵ (no-refire) پوشانده می‌شود"
                )
            else:
                assert False, (
                    "FAIL: rule T2-MON-A1C-01 fire شد ولی 'a1c' در due_clinical_events نیست. "
                    f"events={[e.get('item') for e in events]}"
                )

        print(
            f"PASS test_05b: قبل از lab، a1c در due_clinical_events است "
            f"(rule fire شد، never-done)"
        )

    # ──────────────────────────────────────────────────────────────────────────
    # تست ۶: get_readings_canonical — اتحادِ سری ascending با دو source
    # ──────────────────────────────────────────────────────────────────────────

    def test_06_canonical_union_ascending_two_members(self, specialist_app):
        """vital قدیمی + lab جدید → سری ۲ عضوی ascending؛ latest عضوِ آخر."""
        app, spec_db, tmp_dir, _ = specialist_app

        pid = _enroll_patient(spec_db, national_id="CC0000007", full_name="اتحادِ canonical")
        old_vital_val = 7.5
        new_lab_val = 8.5

        _add_vital_direct(spec_db, pid, "hba1c", old_vital_val, "2026-01-10 08:00:00")
        _add_lab_direct(spec_db, pid, "HbA1c", new_lab_val, "2026-06-10 08:00:00",
                        test_key="hba1c")

        with app.app_context():
            from src.adapters.sqlite.vitals_repo import VitalsRepository
            series = VitalsRepository().get_readings_canonical(pid, "hba1c", limit=200)

        assert len(series) == 2, (
            f"FAIL: سری باید ۲ عضو داشته باشد، است: {len(series)}. "
            f"rows={[dict(r) for r in series]}"
        )
        # ascending: اولی قدیمی، آخری جدید
        assert abs(series[0]["value"] - old_vital_val) < 0.001, (
            f"FAIL: عضوِ اول (قدیمی) باید {old_vital_val} باشد، است: {series[0]['value']}"
        )
        assert series[0]["source"] != "lab", (
            f"FAIL: عضوِ اول باید vital باشد، source='{series[0]['source']}'"
        )
        assert abs(series[-1]["value"] - new_lab_val) < 0.001, (
            f"FAIL: عضوِ آخر (جدید) باید {new_lab_val} باشد، است: {series[-1]['value']}"
        )
        assert series[-1]["source"] == "lab", (
            f"FAIL: عضوِ آخر باید source='lab' باشد، است: '{series[-1]['source']}'"
        )
        print(
            f"PASS test_06: get_readings_canonical سری ۲ عضوی ascending — "
            f"vital={series[0]['value']} lab={series[-1]['value']}"
        )

    # ──────────────────────────────────────────────────────────────────────────
    # تست ۷: کلیدِ vital-only رگرسیون — bp_systolic بدونِ lab
    # ──────────────────────────────────────────────────────────────────────────

    def test_07_vital_only_key_regression(self, specialist_app):
        """کلیدِ bp_systolic فقط از vital_readings — lab ندارد.
        get_readings_canonical باید همان vitalها را برگرداند (رگرسیون: رفتارِ قبلی)."""
        app, spec_db, tmp_dir, _ = specialist_app

        pid = _enroll_patient(spec_db, national_id="CC0000008", full_name="bp-only رگرسیون")
        _add_vital_direct(spec_db, pid, "bp_systolic", 128.0, "2026-05-01 08:00:00",
                          unit="mmHg")
        _add_vital_direct(spec_db, pid, "bp_systolic", 132.0, "2026-06-01 08:00:00",
                          unit="mmHg")
        # هیچ lab با test_key='bp_systolic' نیست

        with app.app_context():
            from src.adapters.sqlite.vitals_repo import VitalsRepository
            series = VitalsRepository().get_readings_canonical(pid, "bp_systolic", limit=200)

        assert len(series) == 2, (
            f"FAIL: باید ۲ vital bp_systolic باشد، است: {len(series)}"
        )
        values = [r["value"] for r in series]
        assert 128.0 in values and 132.0 in values, (
            f"FAIL: مقادیرِ vital در سری نیستند: {values}"
        )
        # همه از کانالِ vital
        for r in series:
            assert r["source"] != "lab", (
                f"FAIL: bp_systolic نباید source='lab' داشته باشد: {dict(r)}"
            )
        # ascending
        assert series[0]["value"] == pytest.approx(128.0), (
            f"FAIL: اولی باید 128.0 باشد: {series[0]['value']}"
        )
        assert series[1]["value"] == pytest.approx(132.0), (
            f"FAIL: دومی باید 132.0 باشد: {series[1]['value']}"
        )
        print(f"PASS test_07: bp_systolic vital-only، سری ۲ عضوی ascending رگرسیون ندارد")

    # ──────────────────────────────────────────────────────────────────────────
    # تست ۸: کلیدِ بدونِ هیچ داده → سریِ خالی
    # ──────────────────────────────────────────────────────────────────────────

    def test_08_empty_key_returns_empty_series(self, specialist_app):
        """برای کلیدی که هیچ vital یا lab ندارد، get_readings_canonical باید [] برگرداند."""
        app, spec_db, tmp_dir, _ = specialist_app

        pid = _enroll_patient(spec_db, national_id="CC0000009", full_name="بیمارِ بیداده")

        with app.app_context():
            from src.adapters.sqlite.vitals_repo import VitalsRepository
            series = VitalsRepository().get_readings_canonical(pid, "ldl", limit=200)

        assert series == [], (
            f"FAIL: سری برای کلیدِ بیداده باید خالی باشد، است: {series}"
        )
        print("PASS test_08: get_readings_canonical برای کلیدِ بدونِ داده سریِ خالی برگرداند")

    # ──────────────────────────────────────────────────────────────────────────
    # تست ۹: medication_effect از lab-only hba1c استفاده می‌کند
    # ──────────────────────────────────────────────────────────────────────────

    def test_09_medication_effect_uses_lab(self, specialist_app):
        """AnalyticsService.medication_effect برای hba1c باید lab-only را ببیند.

        یک دارو با start_date + یک lab قبل از آن + یک lab بعد از آن → pre و post غیرNone.
        """
        app, spec_db, tmp_dir, _ = specialist_app

        pid = _enroll_patient(spec_db, national_id="CC0000010", full_name="اثرِ دارویی")
        _add_condition(spec_db, pid, "diabetes")

        # ثبتِ دارو در DB
        start_date = "2026-04-01"
        conn = sqlite3.connect(spec_db)
        cur = conn.execute(
            "INSERT INTO patient_medications"
            " (patient_link_id, drug_name, dose, start_date, is_active)"
            " VALUES (?, 'متفورمین', '500mg', ?, 1)",
            (pid, start_date),
        )
        conn.commit()
        med_id = cur.lastrowid
        conn.close()

        # lab قبل از دارو (pre)
        _add_lab_direct(spec_db, pid, "HbA1c", 8.5, "2026-02-01 08:00:00",
                        test_key="hba1c")
        # lab بعد از دارو (post)
        _add_lab_direct(spec_db, pid, "HbA1c", 7.2, "2026-06-01 08:00:00",
                        test_key="hba1c")

        with app.app_context():
            from src.services.analytics_service import AnalyticsService
            result = AnalyticsService().medication_effect(pid, med_id, "hba1c",
                                                          window_days=90)

        assert result.get("ok") is True, (
            f"FAIL: medication_effect.ok باید True باشد: {result}"
        )
        assert result.get("pre") is not None, (
            f"FAIL: pre نباید None باشد؛ lab قبل ثبت شد: {result}"
        )
        assert result.get("post") is not None, (
            f"FAIL: post نباید None باشد؛ lab بعد ثبت شد: {result}"
        )
        assert abs(result["pre"] - 8.5) < 0.001, (
            f"FAIL: pre باید 8.5 باشد، است: {result['pre']}"
        )
        assert abs(result["post"] - 7.2) < 0.001, (
            f"FAIL: post باید 7.2 باشد، است: {result['post']}"
        )
        print(
            f"PASS test_09: medication_effect pre={result['pre']} "
            f"post={result['post']} (از lab-only)"
        )

    # ──────────────────────────────────────────────────────────────────────────
    # تست ۱۰: ایمنیِ accounting — SHA-256 clinic_new.db دست‌نخورده
    # ──────────────────────────────────────────────────────────────────────────

    def test_10_accounting_db_sha256_unchanged(self, specialist_app):
        """SHA-256 accounting DB قبل/بعد از همهٔ عملیات یکسان است.
        اگر clinic_new.db وجود نداشت، skip می‌شود."""
        app, spec_db, tmp_dir, acc_sha_before = specialist_app

        if acc_sha_before is None:
            pytest.skip("clinic_new.db یافت نشد — DB حسابداری در این محیط نیست")

        # یک عملیاتِ عادی اجرا کن
        danger_thresh, _ = _get_hba1c_thresholds(spec_db)
        lab_val = danger_thresh + 0.5
        pid = self._setup_patient(app, spec_db, "CC0000099", lab_val)

        with app.app_context():
            from src.adapters.sqlite.vitals_repo import VitalsRepository
            VitalsRepository().get_readings_canonical(pid, "hba1c")
            VitalsRepository().latest_by_type(pid)

        acc_sha_after = _sha256(_REAL_ACC_DB)
        assert acc_sha_before == acc_sha_after, (
            f"FAIL: clinic_new.db تغییر کرده! "
            f"قبل={acc_sha_before[:16]}... بعد={acc_sha_after[:16]}..."
        )
        print(
            f"PASS test_10: SHA-256 clinic_new.db قبل/بعد یکسان "
            f"({acc_sha_before[:16]}...)"
        )

    # ──────────────────────────────────────────────────────────────────────────
    # تست ۱۱: سازگاریِ سه‌گانه — control_status / analytics / rule_engine
    #          همگی روی یک HbA1c lab-only خروجیِ یکسان می‌دهند
    # ──────────────────────────────────────────────────────────────────────────

    def test_11_triple_consumer_agreement(self, specialist_app):
        """سه مصرف‌کننده بر سرِ یک بیمار باید موافق باشند:
           - control_status['latest']['hba1c']['value'] == lab_val
           - analytics indicators tile['hba1c']['latest'] == lab_val
           - rule_engine build_facts['indicator']['hba1c']['latest'] == lab_val
        این تستِ یکپارچگیِ ADR-0005 است."""
        app, spec_db, tmp_dir, _ = specialist_app
        danger_thresh, _ = _get_hba1c_thresholds(spec_db)
        lab_val = danger_thresh + 0.5

        pid = self._setup_patient(app, spec_db, "CC0000011", lab_val)

        with app.app_context():
            from src.adapters.sqlite.vitals_repo import VitalsRepository
            from src.services.vitals_service import VitalsService
            from src.services.analytics_service import AnalyticsService
            from src.services.rule_engine import RuleEngine

            cs = VitalsService(repo=VitalsRepository()).control_status(pid)
            analytics = AnalyticsService().patient_analytics(pid)
            facts = RuleEngine().build_facts(pid)

        # --- control_status ---
        cs_val = cs.get("latest", {}).get("hba1c", {}).get("value")
        assert cs_val is not None, (
            f"FAIL: control_status.latest.hba1c.value=None (مصرف‌کنندهٔ اول کور است)"
        )
        assert abs(cs_val - lab_val) < 0.001, (
            f"FAIL: control_status.latest.hba1c.value={cs_val} باید {lab_val} باشد"
        )

        # --- analytics tile ---
        tile = next((i for i in analytics.get("indicators", [])
                     if i.get("key") == "hba1c"), None)
        assert tile is not None, "FAIL: کاشیِ hba1c در analytics.indicators نیست"
        tile_val = tile.get("latest")
        assert tile_val is not None, (
            "FAIL: analytics tile hba1c.latest=None (تناقضِ on-page)"
        )
        assert abs(tile_val - lab_val) < 0.001, (
            f"FAIL: analytics tile hba1c.latest={tile_val} باید {lab_val} باشد"
        )

        # --- rule_engine facts ---
        re_val = facts.get("indicator", {}).get("hba1c", {}).get("latest")
        assert re_val is not None, (
            "FAIL: RuleEngine.build_facts indicator.hba1c.latest=None"
        )
        assert abs(re_val - lab_val) < 0.001, (
            f"FAIL: RuleEngine indicator.hba1c.latest={re_val} باید {lab_val} باشد"
        )

        # --- سازگاریِ سه‌گانه ---
        assert abs(cs_val - tile_val) < 0.001, (
            f"FAIL: control_status ({cs_val}) و analytics ({tile_val}) ناسازگارند"
        )
        assert abs(tile_val - re_val) < 0.001, (
            f"FAIL: analytics ({tile_val}) و rule_engine ({re_val}) ناسازگارند"
        )

        print(
            f"PASS test_11: سه مصرف‌کننده موافق‌اند — "
            f"hba1c={cs_val} (control) == {tile_val} (analytics) == {re_val} (rule_engine)"
        )
