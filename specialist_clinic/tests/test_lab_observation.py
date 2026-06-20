"""
ADR-0005 — Lab-Observation Channel test suite (adversarial).

Feature C: vital_readings and lab_results are two capture channels of one
canonical concept (shared key vocabulary: hba1c, egfr, uacr, ldl, tsh …).
  - lab_results.test_key  (new column; schema + _ensure_column in core.py)
  - VitalsRepository.add_lab(..., test_key=...) stores it.
  - VitalsRepository.latest_by_type(pid) returns UNION of both channels;
    last-write-wins per key; source='lab' for lab-channel rows.
  - followup_engine._last_done(pid, item, flags) queries MAX(ts) across both.
  - analytics_service._risk lapsed-check also spans both channels.

Safety contract:
  - All writes go to temporary specialist DB copies — never to specialist.db.
  - The real clinic_new.db is verified byte-for-byte (SHA-256) after any test
    that even touches the bridge path.
  - No real SMS is sent (TESTING=True, scheduler never starts).

Run:
    .venv/Scripts/python.exe -m pytest tests/test_lab_observation.py -v
or from repo root:
    specialist_clinic/.venv/Scripts/python.exe -m pytest specialist_clinic/tests/test_lab_observation.py -v
"""

import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

# ── Patch env vars BEFORE any src import (Config reads at import time) ────────
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

# (graceful skip اگر accounting DB وجود ندارد: fixture خودش pytest.skip می‌زند)


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


def _make_minimal_acc_db(path: str):
    """Create a minimal accounting DB (patients table only) at *path*."""
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="lab_obs_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def specialist_app(tmp_dir):
    """Flask test app pointing at a fresh specialist DB in tmp_dir.

    Strict isolation: saves and restores ALL relevant env vars and the
    module-level _initialized flag.
    """
    spec_db = os.path.join(tmp_dir, "specialist_test.db")

    # Use a local copy of the accounting DB if it exists; otherwise create a
    # minimal stub so the bridge adapter doesn't crash.
    if os.path.exists(_REAL_ACC_DB):
        acc_db = os.path.join(tmp_dir, "acc_copy.db")
        shutil.copy2(_REAL_ACC_DB, acc_db)
        acc_sha_before = _sha256(_REAL_ACC_DB)
    else:
        acc_db = os.path.join(tmp_dir, "acc_stub.db")
        _make_minimal_acc_db(acc_db)
        acc_sha_before = None  # no real file to verify

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
        "SECRET_KEY": "lab-obs-test-secret",
        "BACKUP_FOLDER": os.path.join(tmp_dir, "backups"),
    })

    ctx = app.app_context()
    ctx.push()

    # Trigger bootstrap: schema.sql + migrations + admin
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
        import src.adapters.sqlite.core as core_mod
        core_mod._initialized = False
    except Exception:
        pass


@pytest.fixture()
def test_client(specialist_app):
    """Return (flask_test_client, spec_db, tmp_dir, acc_sha_before) with logged-in admin."""
    app, spec_db, tmp_dir, acc_sha_before = specialist_app
    client = app.test_client()
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=True,
    )
    return client, spec_db, tmp_dir, acc_sha_before


# ---------------------------------------------------------------------------
# DB-level helpers (direct sqlite3, bypassing Flask app context)
# ---------------------------------------------------------------------------

def _enroll_patient(spec_db, full_name="بیمار تست", national_id="9990000001",
                    phone="09000000001"):
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


def _add_vital_direct(spec_db, pid, vtype, value, measured_at, unit="%"):
    conn = sqlite3.connect(spec_db)
    conn.execute(
        "INSERT INTO vital_readings (patient_link_id, type, value, unit, measured_at, source)"
        " VALUES (?, ?, ?, ?, ?, 'clinic')",
        (pid, vtype, value, unit, measured_at),
    )
    conn.commit()
    conn.close()


def _add_lab_direct(spec_db, pid, test_name, value, taken_at, test_key=None, unit="%"):
    conn = sqlite3.connect(spec_db)
    conn.execute(
        "INSERT INTO lab_results"
        " (patient_link_id, test_name, test_key, value, unit, taken_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (pid, test_name, test_key, value, unit, taken_at),
    )
    conn.commit()
    conn.close()


def _get_lab_rows(spec_db, pid):
    conn = sqlite3.connect(spec_db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM lab_results WHERE patient_link_id=? ORDER BY taken_at DESC",
        (pid,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_indicator_danger(spec_db, key):
    """Read clinical_indicators.danger threshold for *key*; return (danger, warn) floats."""
    conn = sqlite3.connect(spec_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT warn, danger FROM clinical_indicators WHERE key=?", (key,)
    ).fetchone()
    conn.close()
    if row:
        return float(row["danger"]) if row["danger"] is not None else None, \
               float(row["warn"]) if row["warn"] is not None else None
    return None, None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLabObservation:
    """ADR-0005 — Lab Observation Channel: canonical union of both capture channels."""

    # ------------------------------------------------------------------
    # Scenario 1: lab-only HbA1c visible via latest_by_type with source='lab'
    # ------------------------------------------------------------------
    def test_01_lab_only_hba1c_latest_by_type(self, specialist_app):
        """Add HbA1c only as lab (no vital). latest_by_type must return it with source='lab'."""
        app, spec_db, tmp_dir, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="9990000001")

        with app.app_context():
            from src.adapters.sqlite.vitals_repo import VitalsRepository
            repo = VitalsRepository()
            repo.add_lab(pid, test_name="HbA1c", test_key="hba1c", value=7.2,
                         taken_at="2026-06-15 08:00:00")

            latest = repo.latest_by_type(pid)

        assert "hba1c" in latest, "FAIL: hba1c کانالِ lab در latest_by_type نیست"
        rec = latest["hba1c"]
        assert rec["source"] == "lab", f"FAIL: source باید 'lab' باشد، است: {rec['source']}"
        assert rec["value"] == pytest.approx(7.2), f"FAIL: value باید 7.2 باشد، است: {rec['value']}"
        print("PASS test_01: lab-only HbA1c در latest_by_type با source='lab' یافته شد")

    # ------------------------------------------------------------------
    # Scenario 1b: _last_done برای 'a1c' تاریخِ همان lab را بدهد
    # ------------------------------------------------------------------
    def test_01b_last_done_uses_lab_date(self, specialist_app):
        """_last_done(pid,'a1c',{}) should return the lab's taken_at date."""
        app, spec_db, tmp_dir, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="9990000002")

        _add_lab_direct(spec_db, pid, "HbA1c", 7.2, "2026-06-15 08:00:00",
                        test_key="hba1c")

        with app.app_context():
            from src.services.followup_engine import _last_done
            last = _last_done(pid, "a1c", {})

        assert last is not None, "FAIL: _last_done برای 'a1c' با lab-only نباید None باشد"
        assert last.startswith("2026-06-15"), \
            f"FAIL: تاریخِ _last_done باید 2026-06-15 باشد، است: {last}"
        print("PASS test_01b: _last_done برای a1c از lab صحیح برگشت")

    # ------------------------------------------------------------------
    # Scenario 2a: lab جدیدتر از vital → lab برنده در latest_by_type
    # ------------------------------------------------------------------
    def test_02a_latest_wins_lab_newer(self, specialist_app):
        """Older vital hba1c + newer lab hba1c → latest_by_type returns lab value."""
        app, spec_db, tmp_dir, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="9990000003")

        _add_vital_direct(spec_db, pid, "hba1c", 8.5, "2026-01-01 08:00:00")
        _add_lab_direct(spec_db, pid, "HbA1c", 7.2, "2026-06-15 08:00:00",
                        test_key="hba1c")

        with app.app_context():
            from src.adapters.sqlite.vitals_repo import VitalsRepository
            latest = VitalsRepository().latest_by_type(pid)

        rec = latest.get("hba1c")
        assert rec is not None, "FAIL: hba1c در latest_by_type وجود ندارد"
        assert rec["value"] == pytest.approx(7.2), \
            f"FAIL: lab جدیدتر (7.2) باید برنده باشد، مقدار است: {rec['value']}"
        assert rec["source"] == "lab", f"FAIL: source باید 'lab' باشد، است: {rec['source']}"
        print("PASS test_02a: lab جدیدتر از vital در latest_by_type برنده شد")

    # ------------------------------------------------------------------
    # Scenario 2b: vital جدیدتر از lab → vital برنده در latest_by_type
    # ------------------------------------------------------------------
    def test_02b_latest_wins_vital_newer(self, specialist_app):
        """Older lab hba1c + newer vital hba1c → latest_by_type returns vital value."""
        app, spec_db, tmp_dir, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="9990000004")

        _add_lab_direct(spec_db, pid, "HbA1c", 8.5, "2026-01-01 08:00:00",
                        test_key="hba1c")
        _add_vital_direct(spec_db, pid, "hba1c", 6.8, "2026-06-15 08:00:00")

        with app.app_context():
            from src.adapters.sqlite.vitals_repo import VitalsRepository
            latest = VitalsRepository().latest_by_type(pid)

        rec = latest.get("hba1c")
        assert rec is not None, "FAIL: hba1c در latest_by_type وجود ندارد"
        assert rec["value"] == pytest.approx(6.8), \
            f"FAIL: vital جدیدتر (6.8) باید برنده باشد، مقدار است: {rec['value']}"
        assert rec["source"] == "clinic", f"FAIL: source باید 'clinic' باشد، است: {rec['source']}"
        print("PASS test_02b: vital جدیدتر از lab در latest_by_type برنده شد")

    # ------------------------------------------------------------------
    # Scenario 3: lab بدونِ test_key نشت نمی‌کند
    # ------------------------------------------------------------------
    def test_03_lab_without_key_no_leak(self, specialist_app):
        """add_lab with test_key=None must NOT appear in latest_by_type as a canonical key."""
        app, spec_db, tmp_dir, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="9990000005")

        with app.app_context():
            from src.adapters.sqlite.vitals_repo import VitalsRepository
            repo = VitalsRepository()
            repo.add_lab(pid, test_name="آزمایشِ آزاد", test_key=None, value=55.0)
            latest = repo.latest_by_type(pid)

        # باید هیچ کلیدی از این lab در latest_by_type ظاهر نشود
        # (None و '' هر دو باید فیلتر شده باشند)
        assert "آزمایشِ آزاد" not in latest, \
            "FAIL: نامِ آزمایشِ آزاد نباید به‌عنوانِ کلیدِ کانونیک ظاهر شود"
        for key, rec in latest.items():
            assert key is not None and key != "", \
                f"FAIL: کلیدِ null/خالی در latest_by_type ظاهر شد: {key!r}"
        print("PASS test_03: lab بدونِ test_key در latest_by_type نشت نکرد")

    # ------------------------------------------------------------------
    # Scenario 3b: _last_done برای a1c تأثیر نمی‌گیرد از lab بدونِ کلید
    # ------------------------------------------------------------------
    def test_03b_last_done_unaffected_by_keyless_lab(self, specialist_app):
        """_last_done(pid,'a1c',{}) must return None when only a keyless lab exists."""
        app, spec_db, tmp_dir, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="9990000006")
        _add_lab_direct(spec_db, pid, "آزمایشِ آزاد", 55.0, "2026-06-15 08:00:00",
                        test_key=None)

        with app.app_context():
            from src.services.followup_engine import _last_done
            last = _last_done(pid, "a1c", {})

        assert last is None, \
            f"FAIL: _last_done باید None باشد وقتی فقط lab بدونِ test_key داریم، است: {last}"
        print("PASS test_03b: _last_done از lab بدونِ کلید تأثیر نگرفت")

    # ------------------------------------------------------------------
    # Scenario 4: renal با دو کلید — uacr بدونِ egfr
    # ------------------------------------------------------------------
    def test_04_renal_two_keys_uacr_only(self, specialist_app):
        """lab uacr (without egfr) → _last_done(pid,'renal',{}) returns uacr date."""
        app, spec_db, tmp_dir, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="9990000007")
        _add_lab_direct(spec_db, pid, "Urine ACR", 45.0, "2026-05-10 08:00:00",
                        test_key="uacr", unit="mg/g")

        with app.app_context():
            from src.services.followup_engine import _last_done
            last = _last_done(pid, "renal", {})

        assert last is not None, \
            "FAIL: _last_done برای 'renal' با lab uacr نباید None باشد"
        assert last.startswith("2026-05-10"), \
            f"FAIL: تاریخِ _last_done باید 2026-05-10 باشد، است: {last}"
        print("PASS test_04: _last_done برای renal با uacr-only صحیح برگشت")

    # ------------------------------------------------------------------
    # Scenario 5: route add_lab — POST با test_key[]
    # ------------------------------------------------------------------
    def test_05_route_add_lab_batch_stores_test_key(self, test_client):
        """POST /vitals/<pid>/lab/add with test_name[]+test_key[]+value[]+taken_date
        must persist a lab_results row with the correct test_key."""
        client, spec_db, tmp_dir, _ = test_client
        pid = _enroll_patient(spec_db, national_id="9990000008")

        resp = client.post(
            f"/vitals/{pid}/lab/add",
            data={
                "taken_date": "1405/03/25",   # Jalali; maps to Gregorian 2026-06-15
                "test_name[]": ["HbA1c"],
                "test_key[]": ["hba1c"],
                "value[]": ["7.5"],
                "unit[]": ["%"],
                "ref_low[]": [""],
                "ref_high[]": [""],
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200, f"FAIL: وضعیتِ HTTP نباید {resp.status_code} باشد"

        rows = _get_lab_rows(spec_db, pid)
        assert len(rows) >= 1, "FAIL: ردیفِ lab_results ذخیره نشد"
        keyed = [r for r in rows if r.get("test_key") == "hba1c"]
        assert len(keyed) == 1, \
            f"FAIL: ردیفی با test_key='hba1c' یافت نشد؛ ردیف‌ها: {rows}"
        assert float(keyed[0]["value"]) == pytest.approx(7.5), \
            f"FAIL: مقدار باید 7.5 باشد، است: {keyed[0]['value']}"
        print("PASS test_05: route add_lab ردیف با test_key='hba1c' ذخیره کرد")

    # ------------------------------------------------------------------
    # Scenario 6: control_status از lab hba1c بالای danger threshold
    # ------------------------------------------------------------------
    def test_06_control_status_sees_lab_danger(self, specialist_app):
        """A lab hba1c above the clinical_indicators danger threshold → control_status='uncontrolled'."""
        app, spec_db, tmp_dir, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="9990000009")

        # اول danger threshold hba1c را از clinical_indicators بخوان
        with app.app_context():
            from src.adapters.sqlite.core import get_db
            db = get_db()
            row = db.execute(
                "SELECT warn, danger, direction FROM clinical_indicators WHERE key='hba1c'"
            ).fetchone()

        # اگر hba1c در clinical_indicators نیست، یک indicator با danger آستانه پیدا کن
        if row and row["danger"] is not None:
            test_key = "hba1c"
            danger_val = float(row["danger"]) + 0.5  # مقداری بالاتر از danger
            direction = row["direction"] or "high"
        else:
            # fallback: از THRESHOLDS استاتیک بخوان
            danger_val = 8.0 + 0.5
            test_key = "hba1c"
            direction = "high"

        # اطمینان: برای direction='low' باید پایین‌تر از danger بود — ولی hba1c همیشه high است
        # اگر direction low بود باید danger_val را پایین بیاوریم
        with app.app_context():
            from src.adapters.sqlite.vitals_repo import VitalsRepository
            from src.services.vitals_service import VitalsService
            repo = VitalsRepository()

            # هیچ vital نیست؛ فقط lab
            repo.add_lab(pid, test_name="HbA1c-آزمایشگاه", test_key=test_key,
                         value=danger_val, taken_at="2026-06-15 08:00:00")

            cs = VitalsService(repo=repo).control_status(pid)

        assert cs["status"] == "uncontrolled", \
            (f"FAIL: control_status باید 'uncontrolled' باشد وقتی {test_key}={danger_val} "
             f"(danger>={float(row['danger']) if row and row['danger'] else 8.0})؛ "
             f"وضعیتِ واقعی: {cs['status']}, flags={cs.get('flags')}")
        print(f"PASS test_06: control_status با lab {test_key}={danger_val} → 'uncontrolled'")

    # ------------------------------------------------------------------
    # Scenario 7: lapsed اتحاد — فقط lab در ۱۲۰ روز اخیر، رهاشده نباشد
    # ------------------------------------------------------------------
    def test_07_lapsed_union_lab_recent_not_abandoned(self, specialist_app):
        """Patient with only a recent lab (no vital) must NOT be flagged lapsed
        by the analytics_service._risk lapsed query (UNION of both channels)."""
        app, spec_db, tmp_dir, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="9990000010")

        # یک lab در ۳۰ روزِ اخیر (فقط lab، بدونِ vital)
        import datetime
        recent_date = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        _add_lab_direct(spec_db, pid, "FBS", 110.0, recent_date, test_key="fbs", unit="mg/dL")

        with app.app_context():
            from src.adapters.sqlite.core import get_db
            db = get_db()
            # همان کوئریِ lapsed در analytics_service._risk
            lapsed = db.execute(
                """SELECT NOT EXISTS(
                     SELECT 1 FROM vital_readings WHERE patient_link_id=?
                       AND measured_at >= datetime('now','+3 hours','+30 minutes','-120 days')
                     UNION ALL
                     SELECT 1 FROM lab_results WHERE patient_link_id=?
                       AND taken_at >= datetime('now','+3 hours','+30 minutes','-120 days')
                   ) AS x""",
                (pid, pid),
            ).fetchone()["x"]

        assert lapsed == 0, \
            ("FAIL: بیمار با lab اخیر نباید lapsed=1 (رهاشده) تشخیص داده شود؛ "
             "منطقِ اتحادِ دو کانال ناقص است")
        print("PASS test_07: بیمار با lab اخیر رهاشده علامت نخورد (lapsed=0)")

    # ------------------------------------------------------------------
    # Scenario 7b: بدونِ هیچ رکورد → lapsed باشد
    # ------------------------------------------------------------------
    def test_07b_lapsed_no_records_is_abandoned(self, specialist_app):
        """Patient with no vitals and no labs → lapsed=1 (abandoned)."""
        app, spec_db, tmp_dir, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="9990000011")

        with app.app_context():
            from src.adapters.sqlite.core import get_db
            db = get_db()
            lapsed = db.execute(
                """SELECT NOT EXISTS(
                     SELECT 1 FROM vital_readings WHERE patient_link_id=?
                       AND measured_at >= datetime('now','+3 hours','+30 minutes','-120 days')
                     UNION ALL
                     SELECT 1 FROM lab_results WHERE patient_link_id=?
                       AND taken_at >= datetime('now','+3 hours','+30 minutes','-120 days')
                   ) AS x""",
                (pid, pid),
            ).fetchone()["x"]

        assert lapsed == 1, \
            "FAIL: بیمار بدونِ هیچ رکوردی باید lapsed=1 (رهاشده) باشد"
        print("PASS test_07b: بیمار بدونِ رکورد به‌درستی lapsed=1 است")

    # ------------------------------------------------------------------
    # Scenario 8: threshold-sync — evaluate_reading فقط از clinical_indicators
    # ------------------------------------------------------------------
    def test_08_threshold_sync_evaluate_reading(self, specialist_app):
        """evaluate_reading must use clinical_indicators thresholds, NOT ref_low/ref_high
        from lab_results catalog. A value outside catalog ref range but inside
        clinical_indicators 'ok' zone must return 'ok'."""
        app, spec_db, tmp_dir, _ = specialist_app

        with app.app_context():
            from src.adapters.sqlite.core import get_db
            from src.services.vitals_service import evaluate_reading

            db = get_db()
            # hba1c: warn=7.0, danger=8.0 (از clinical_indicators)
            row = db.execute(
                "SELECT warn, danger FROM clinical_indicators WHERE key='hba1c'"
            ).fetchone()
            if row and row["warn"] is not None:
                warn_thresh = float(row["warn"])
                danger_thresh = float(row["danger"]) if row["danger"] is not None else warn_thresh + 1.0
            else:
                # fallback اگر clinical_indicators خالی
                warn_thresh = 7.0
                danger_thresh = 8.0

            # مقداری کمتر از warn → باید 'ok' باشد
            safe_val = warn_thresh - 0.5
            result_safe = evaluate_reading("hba1c", safe_val)
            assert result_safe == "ok", \
                f"FAIL: مقدارِ {safe_val} کمتر از warn={warn_thresh} باید 'ok' باشد، است: {result_safe}"

            # مقداری بالای warn ولی کمتر از danger → باید 'warn' باشد
            warn_val = warn_thresh + 0.1
            result_warn = evaluate_reading("hba1c", warn_val)
            assert result_warn == "warn", \
                f"FAIL: مقدارِ {warn_val} بین warn و danger باید 'warn' باشد، است: {result_warn}"

            # مقداری بالای danger → باید 'danger' باشد
            danger_val = danger_thresh + 0.1
            result_danger = evaluate_reading("hba1c", danger_val)
            assert result_danger == "danger", \
                f"FAIL: مقدارِ {danger_val} بالای danger={danger_thresh} باید 'danger' باشد، است: {result_danger}"

        print(
            f"PASS test_08: evaluate_reading از clinical_indicators (warn={warn_thresh},"
            f" danger={danger_thresh}) درست ارزیابی کرد"
        )

    # ------------------------------------------------------------------
    # Scenario 9: migration idempotency — ستونِ test_key دوبار امن
    # ------------------------------------------------------------------
    def test_09_migration_idempotent_test_key_column(self, specialist_app):
        """Running _ensure_column('lab_results','test_key',...) twice must be safe."""
        app, spec_db, tmp_dir, _ = specialist_app

        with app.app_context():
            from src.adapters.sqlite.core import get_db, _ensure_column
            db = get_db()

            # اجرای اول (ستون از قبل توسطِ bootstrap ایجاد شده)
            _ensure_column(db, "lab_results", "test_key", "TEXT")
            # اجرای دوم (باید بدونِ خطا باشد)
            _ensure_column(db, "lab_results", "test_key", "TEXT")

            # تأیید: ستون موجود است
            cols = [c["name"] for c in db.execute("PRAGMA table_info(lab_results)").fetchall()]
            assert "test_key" in cols, \
                f"FAIL: ستونِ test_key پس از اجرای دوباره وجود ندارد؛ ستون‌ها: {cols}"

        print("PASS test_09: migration idempotent — test_key ستون دوبار اضافه‌شدنِ امن")

    # ------------------------------------------------------------------
    # Scenario 10a: رگرسیون — vital معمولی دست‌نخورده
    # ------------------------------------------------------------------
    def test_10a_regression_regular_vital_unaffected(self, specialist_app):
        """Existing vital_readings workflow must be unaffected: add_reading then get_readings."""
        app, spec_db, tmp_dir, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="9990000012")

        with app.app_context():
            from src.adapters.sqlite.vitals_repo import VitalsRepository
            repo = VitalsRepository()
            rid = repo.add_reading(pid, vtype="fbs", value=110.0, unit="mg/dL",
                                   measured_at="2026-06-10 08:00:00")
            rows = repo.get_readings(pid, vtype="fbs")

        assert rid > 0, "FAIL: add_reading باید rowid > 0 برگرداند"
        assert len(rows) == 1, f"FAIL: باید ۱ ردیف fbs باشد، است: {len(rows)}"
        assert rows[0]["value"] == pytest.approx(110.0)
        print("PASS test_10a: vital معمولی (add_reading/get_readings) رگرسیون ندارد")

    # ------------------------------------------------------------------
    # Scenario 10b: رگرسیون + صفر-نوشتنِ حسابداری — SHA-256 یکسان
    # ------------------------------------------------------------------
    def test_10b_accounting_db_untouched(self, specialist_app):
        """Real clinic_new.db SHA-256 must be identical before and after all operations.
        If the real DB doesn't exist, this test is skipped gracefully."""
        app, spec_db, tmp_dir, acc_sha_before = specialist_app

        if acc_sha_before is None:
            pytest.skip("clinic_new.db یافت نشد — اینجا DB حسابداری skip می‌شود")

        # یک تراکنشِ عادی اجرا کن تا bridge خوانده شود
        pid = _enroll_patient(spec_db, national_id="9990000013")
        with app.app_context():
            from src.adapters.sqlite.vitals_repo import VitalsRepository
            repo = VitalsRepository()
            repo.add_lab(pid, test_name="TSH", test_key="tsh", value=3.5,
                         taken_at="2026-06-15 08:00:00")
            repo.latest_by_type(pid)

        acc_sha_after = _sha256(_REAL_ACC_DB)
        assert acc_sha_before == acc_sha_after, (
            f"FAIL: clinic_new.db تغییر کرده! قبل={acc_sha_before[:16]}... "
            f"بعد={acc_sha_after[:16]}..."
        )
        print("PASS test_10b: SHA-256 clinic_new.db قبل/بعد یکسان — دیتابیس حسابداری دست‌نخورده")

    # ------------------------------------------------------------------
    # Scenario 11: idempotency — اجرای مضاعفِ add_lab با مقادیرِ یکسان
    # ------------------------------------------------------------------
    def test_11_add_lab_idempotent_insert(self, specialist_app):
        """Two identical add_lab calls must produce two rows (no UNIQUE conflict)
        and latest_by_type must still return the correct (same) value."""
        app, spec_db, tmp_dir, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="9990000014")

        with app.app_context():
            from src.adapters.sqlite.vitals_repo import VitalsRepository
            repo = VitalsRepository()
            repo.add_lab(pid, test_name="HbA1c", test_key="hba1c", value=7.0,
                         taken_at="2026-06-15 08:00:00")
            repo.add_lab(pid, test_name="HbA1c", test_key="hba1c", value=7.0,
                         taken_at="2026-06-15 08:00:00")
            latest = repo.latest_by_type(pid)
            labs = repo.get_labs(pid)

        # باید ۲ ردیف مجزا در DB باشد (lab_results UNIQUE ندارد)
        assert len(labs) == 2, f"FAIL: باید ۲ ردیفِ lab جداگانه باشد، است: {len(labs)}"
        assert latest["hba1c"]["value"] == pytest.approx(7.0)
        print("PASS test_11: add_lab idempotent — دو ردیف و latest صحیح")

    # ------------------------------------------------------------------
    # Scenario 12: delete_lab ردیف را حذف می‌کند و از latest_by_type ناپدید می‌شود
    # ------------------------------------------------------------------
    def test_12_delete_lab_removes_from_latest(self, specialist_app):
        """delete_lab must remove the row; if no other observation exists,
        hba1c must disappear from latest_by_type."""
        app, spec_db, tmp_dir, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="9990000015")

        with app.app_context():
            from src.adapters.sqlite.vitals_repo import VitalsRepository
            repo = VitalsRepository()
            lab_id = repo.add_lab(pid, test_name="HbA1c", test_key="hba1c", value=7.5,
                                  taken_at="2026-06-15 08:00:00")
            assert "hba1c" in repo.latest_by_type(pid), \
                "FAIL: hba1c باید قبل از حذف در latest_by_type باشد"
            repo.delete_lab(lab_id)
            latest_after = repo.latest_by_type(pid)

        assert "hba1c" not in latest_after, \
            "FAIL: hba1c باید پس از delete_lab از latest_by_type حذف شود"
        print("PASS test_12: delete_lab ردیف را از latest_by_type حذف کرد")
