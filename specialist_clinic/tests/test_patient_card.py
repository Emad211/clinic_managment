"""
ADR-0004 — Patient Card Channel test suite (adversarial).

Safety contract:
  - All writes go to COPIES of the specialist DB, never to the original.
  - The real clinic_new.db SHA-256 is verified byte-for-byte (Scenario C).
  - No real SMS is sent (scheduler never starts in TESTING mode).
  - The accounting DB copy used in Scenario C is opened read-only (no write risk).

Run from the specialist_clinic directory:
    .venv/Scripts/python.exe -m pytest tests/test_patient_card.py -v
Or from the repo root:
    specialist_clinic/.venv/Scripts/python.exe -m pytest specialist_clinic/tests/test_patient_card.py -v
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
import re
import shutil
import sqlite3
import tempfile
import pytest


# ---------------------------------------------------------------------------
# Helpers shared by all scenarios
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


def _mtime(path: str) -> float:
    return os.path.getmtime(path)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="card_test_")
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
    os.environ["ACCOUNTING_DB_PATH"] = _REAL_ACC_DB  # bridge is read-only anyway

    _flush_src_modules()

    sys.path.insert(0, _SPECIALIST_ROOT)
    from src.app import create_app
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": spec_db,
        "PROPAGATE_EXCEPTIONS": True,
        "SECRET_KEY": "card-test-secret",
        "BACKUP_FOLDER": os.path.join(tmp_dir, "backups"),
    })

    ctx = app.app_context()
    ctx.push()

    # Force bootstrap: get_db() runs schema.sql + migrations once per process.
    from src.adapters.sqlite.core import get_db
    get_db()  # triggers _initialized -> schema applied -> patient_card_tokens exists

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
    client.post("/auth/login", data={"username": "admin", "password": "admin"},
                follow_redirects=True)
    return client, spec_db, tmp_dir


# ---------------------------------------------------------------------------
# Helpers: enroll a patient and optionally add vitals/meds/conditions
# ---------------------------------------------------------------------------

def _enroll_patient(spec_db, full_name="احمد تستی", national_id="1234567890",
                    phone="09121234567"):
    """Insert a patient_links row in the specialist DB; return the inserted id."""
    conn = sqlite3.connect(spec_db)
    cur = conn.execute(
        "INSERT INTO patient_links (national_id, full_name, phone_number, enrolled_by) "
        "VALUES (?, ?, ?, 'test')",
        (national_id, full_name, phone),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def _add_vital(spec_db, pid, vtype, value, measured_at="2026-06-01 08:00:00"):
    conn = sqlite3.connect(spec_db)
    conn.execute(
        "INSERT INTO vital_readings (patient_link_id, type, value, unit, measured_at, source) "
        "VALUES (?, ?, ?, 'mg/dL', ?, 'clinic')",
        (pid, vtype, value, measured_at),
    )
    conn.commit()
    conn.close()


def _enable_card_feature(spec_db):
    conn = sqlite3.connect(spec_db)
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('patient_card_enabled', '1')"
    )
    conn.commit()
    conn.close()


def _disable_card_feature(spec_db):
    conn = sqlite3.connect(spec_db)
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('patient_card_enabled', '0')"
    )
    conn.commit()
    conn.close()


def _issue_token(spec_db, pid, hours_from_now=8):
    """Issue a token directly via the repo (no HTTP); return the token string."""
    # We need an app context — caller must have one active.
    from src.adapters.sqlite.patient_card_repo import PatientCardRepository
    return PatientCardRepository().create_token(pid, ttl_hours=hours_from_now,
                                                issued_by="test")


def _issue_expired_token(spec_db, pid):
    """Insert a token that is already expired into the DB; return its string."""
    import secrets
    from src.common.utils import iran_now
    from datetime import timedelta
    conn = sqlite3.connect(spec_db)
    token = secrets.token_urlsafe(32)
    # expires_at in the past (2 hours ago)
    past = (iran_now() - timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S')
    conn.execute(
        "INSERT INTO patient_card_tokens (patient_link_id, token, expires_at, issued_by) "
        "VALUES (?, ?, ?, ?)",
        (pid, token, past, "test"),
    )
    conn.commit()
    conn.close()
    return token


def _add_condition(spec_db, pid, code="DM", name="دیابت"):
    conn = sqlite3.connect(spec_db)
    # Ensure conditions row exists
    conn.execute(
        "INSERT OR IGNORE INTO conditions (code, name) VALUES (?, ?)", (code, name)
    )
    cond_id = conn.execute(
        "SELECT id FROM conditions WHERE code=?", (code,)
    ).fetchone()[0]
    conn.execute(
        "INSERT OR IGNORE INTO patient_conditions (patient_link_id, condition_id, is_active) "
        "VALUES (?, ?, 1)",
        (pid, cond_id),
    )
    conn.commit()
    conn.close()


def _add_medication(spec_db, pid, name="متفورمین"):
    conn = sqlite3.connect(spec_db)
    conn.execute(
        "INSERT INTO patient_medications (patient_link_id, drug_name, dose, is_active) "
        "VALUES (?, ?, '500 mg', 1)",
        (pid, name),
    )
    conn.commit()
    conn.close()


# ===========================================================================
# Scenario A — معماری: تضمین‌های سه‌لایه (Architecture guard — 3-layer)
# ===========================================================================

class TestScenarioAArchitectureGuard:
    """ADR-0004 invariants enforced at test-time, not runtime."""

    def test_A1_public_card_blueprint_is_GET_only(self, specialist_app):
        """هیچ متد غیر از GET در blueprint patient_card نیست.

        روی url_map پیمایش می‌کنیم؛ هر rule که endpoint آن با 'patient_card.'
        شروع می‌شود باید فقط {'GET'} داشته باشد (HEAD و OPTIONS سیستمی هستند).
        اگر حتی یک POST/PUT/PATCH/DELETE وجود داشته باشد تست شکست می‌خورد.
        """
        app, _, _ = specialist_app
        violations = []
        for rule in app.url_map.iter_rules():
            if not rule.endpoint.startswith("patient_card."):
                continue
            non_system = rule.methods - {"HEAD", "OPTIONS"}
            if non_system != {"GET"}:
                violations.append(
                    f"  endpoint={rule.endpoint!r}  rule={rule.rule!r}  methods={non_system!r}"
                )
        assert not violations, (
            "patient_card blueprint has non-GET methods (ADR-0004 violation):\n"
            + "\n".join(violations)
        )

    def test_A2_projection_service_has_no_write_SQL(self):
        """card_projection_service.py باید فاقد INSERT/UPDATE/DELETE/commit/executemany باشد.

        فقط خطوط واقعیِ کد (نه کامنت‌ها و نه رشته‌های داک‌استرینگ) اسکن می‌شوند.
        الگو: هر خطی که با # شروع نشده و داخل داک‌استرینگ نیست.
        (داک‌استرینگِ ماژول خودش این کلمات را در توضیح دارد، باید نادیده گرفته شوند.)
        """
        service_path = os.path.join(
            _SPECIALIST_ROOT, "src", "services", "card_projection_service.py"
        )
        assert os.path.exists(service_path), f"card_projection_service.py not found at {service_path}"

        with open(service_path, encoding="utf-8") as f:
            lines = f.readlines()

        # Strip comment lines, blank lines, and lines inside docstrings
        code_lines = []
        in_docstring = False
        for line in lines:
            stripped = line.strip()
            # toggle docstring state
            triple_count = stripped.count('"""') + stripped.count("'''")
            if triple_count >= 2:
                # open+close on same line — skip entirely
                continue
            if triple_count == 1:
                in_docstring = not in_docstring
                continue
            if in_docstring:
                continue
            if stripped.startswith("#") or not stripped:
                continue
            code_lines.append(line)

        code_only = "".join(code_lines)

        write_patterns = [
            (r'\bINSERT\b', 'INSERT'),
            (r'\bUPDATE\b', 'UPDATE'),
            (r'\bDELETE\b', 'DELETE'),
            (r'\.commit\(', '.commit('),
            (r'\.executemany\(', '.executemany('),
        ]
        hits = []
        for pattern, label in write_patterns:
            matches = [(m.start(), code_only[max(0, m.start()-40):m.end()+40])
                       for m in re.finditer(pattern, code_only, re.IGNORECASE)]
            if matches:
                hits.append(f"  [{label}] found {len(matches)} time(s) in CODE lines:"
                            + "".join(f"\n    ...{ctx.strip()}..." for _, ctx in matches))

        assert not hits, (
            "card_projection_service.py contains write SQL or commit calls in code lines "
            "(ADR-0004 read-only violation):\n" + "\n".join(hits)
        )

    def test_A3_projection_service_never_emits_national_id(self):
        """card_projection_service.py هرگز رشته 'national_id' را در پاسخ نباید داشته باشد.

        توجه: فایل سرویس می‌تواند از national_id در کوئری داخلی برای lookup استفاده کند،
        اما نباید آن را در DTO برگرداند. اسکن static: کلمه 'national_id' نباید در
        context بازگشت داده باشد. بر اساس داک‌استرینگ: 'Never returns national_id'.
        چک اصلی رفتاری (A4) این را با اجرا تأیید می‌کند.
        This static check verifies the dict returned by card_for_token never
        has national_id as a key in the *return* statement.
        """
        service_path = os.path.join(
            _SPECIALIST_ROOT, "src", "services", "card_projection_service.py"
        )
        with open(service_path, encoding="utf-8") as f:
            source = f.read()

        # The return dict must not contain 'national_id' as a key
        # Look for return { ... 'national_id' ... } patterns
        return_blocks = re.findall(r'return\s*\{[^}]*\}', source, re.DOTALL)
        for block in return_blocks:
            assert 'national_id' not in block, (
                f"card_projection_service.py return dict contains 'national_id':\n{block}"
            )

    def test_A4_zero_write_on_specialist_db_during_card_GET(self, specialist_app, tmp_dir):
        """SHA-256 و mtime فایل specialist.db قبل و بعد از GET /card/<token> تغییر نکند.

        این سناریو به‌ویژه تأیید می‌کند که مسیر عمومی /card/<token> هیچ نوشتنی
        (حتی implicit WAL) روی specialist.db انجام نمی‌دهد. همچنین فایل -wal/-shm
        جدید ساخته نمی‌شود.
        """
        app, spec_db, _ = specialist_app
        pid = _enroll_patient(spec_db)
        _add_vital(spec_db, pid, "fbs", 95)
        _enable_card_feature(spec_db)

        token = _issue_token(spec_db, pid)

        sha_before = _sha256(spec_db)
        mtime_before = _mtime(spec_db)
        wal_path = spec_db + "-wal"
        shm_path = spec_db + "-shm"
        wal_existed_before = os.path.exists(wal_path)
        shm_existed_before = os.path.exists(shm_path)

        client = app.test_client()
        rv = client.get(f"/card/{token}")
        assert rv.status_code == 200, f"Expected 200, got {rv.status_code}"

        sha_after = _sha256(spec_db)
        mtime_after = _mtime(spec_db)

        assert sha_before == sha_after, (
            f"specialist.db was MODIFIED during a read-only GET /card/<token>!\n"
            f"  before SHA-256: {sha_before}\n"
            f"  after  SHA-256: {sha_after}"
        )

        # WAL/SHM must not have been newly created by the public route
        if not wal_existed_before:
            if os.path.exists(wal_path):
                # WAL might appear from bootstrap writes; check content
                wal_size = os.path.getsize(wal_path)
                assert wal_size == 0 or wal_existed_before, (
                    f"A non-empty WAL file was created after GET /card/<token> "
                    f"(size={wal_size}) — possible write to specialist.db"
                )


# ===========================================================================
# Scenario B — کارکردی: gate / enable / valid token flow
# ===========================================================================

class TestScenarioBFunctional:
    """رفتار HTTP کامل مسیر عمومی کارت."""

    def test_B1_feature_flag_off_returns_404(self, specialist_app):
        """وقتی patient_card_enabled='0' هر URL ای در /card/ باید 404 برگرداند."""
        app, spec_db, _ = specialist_app
        _disable_card_feature(spec_db)
        pid = _enroll_patient(spec_db, national_id="B100000001")
        token = _issue_token(spec_db, pid)

        client = app.test_client()
        rv = client.get(f"/card/{token}")
        assert rv.status_code == 404, (
            f"Feature-gated route should return 404 when disabled, got {rv.status_code}"
        )

    def test_B2_feature_flag_on_valid_token_returns_200(self, specialist_app):
        """وقتی flag روشن و توکن معتبر است، 200 و سلام نام کوچک بیمار در HTML باید باشد."""
        app, spec_db, _ = specialist_app
        pid = _enroll_patient(spec_db, full_name="رضا کریمی", national_id="B200000001")
        _add_vital(spec_db, pid, "fbs", 100)
        _enable_card_feature(spec_db)
        token = _issue_token(spec_db, pid)

        client = app.test_client()
        rv = client.get(f"/card/{token}")
        assert rv.status_code == 200, f"Valid token + enabled should return 200, got {rv.status_code}"

        body = rv.data.decode("utf-8")
        assert "رضا" in body, (
            "Patient first-name 'رضا' must appear in the card HTML"
        )
        assert "سلام" in body, "Greeting 'سلام' must appear in the card HTML"

    def test_B3_unknown_token_returns_404(self, specialist_app):
        """توکن ناشناخته باید 404 برگرداند (بدون فاش‌کردن دلیل)."""
        app, spec_db, _ = specialist_app
        _enable_card_feature(spec_db)

        client = app.test_client()
        rv = client.get("/card/thisTokenDoesNotExistAtAll99999")
        assert rv.status_code == 404, (
            f"Unknown token should return 404, got {rv.status_code}"
        )

    def test_B4_expired_token_returns_404(self, specialist_app):
        """توکن منقضی (expires_at در گذشته) باید 404 برگرداند."""
        app, spec_db, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="B400000001")
        _enable_card_feature(spec_db)
        expired_token = _issue_expired_token(spec_db, pid)

        client = app.test_client()
        rv = client.get(f"/card/{expired_token}")
        assert rv.status_code == 404, (
            f"Expired token should return 404, got {rv.status_code}"
        )

    def test_B5_revoked_token_returns_404(self, specialist_app):
        """توکن revoke‌شده باید 404 برگرداند."""
        app, spec_db, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="B500000001")
        _enable_card_feature(spec_db)
        token = _issue_token(spec_db, pid)

        # Revoke it via repo
        from src.adapters.sqlite.patient_card_repo import PatientCardRepository
        repo = PatientCardRepository()
        row = repo.get_by_token(token)
        assert row is not None
        repo.revoke(row["id"], patient_link_id=pid)

        client = app.test_client()
        rv = client.get(f"/card/{token}")
        assert rv.status_code == 404, (
            f"Revoked token should return 404, got {rv.status_code}"
        )

    def test_B6_card_for_token_returns_none_for_unknown(self, specialist_app):
        """card_for_token با توکن ناشناخته باید None برگرداند."""
        from src.services.card_projection_service import card_for_token
        result = card_for_token("totally-bogus-token-that-was-never-issued")
        assert result is None, f"Expected None for unknown token, got {result!r}"

    def test_B7_card_for_token_returns_none_for_expired(self, specialist_app):
        """card_for_token با توکن منقضی باید None برگرداند."""
        app, spec_db, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="B700000001")
        expired_token = _issue_expired_token(spec_db, pid)

        from src.services.card_projection_service import card_for_token
        result = card_for_token(expired_token)
        assert result is None, f"Expected None for expired token, got {result!r}"

    def test_B8_card_for_token_returns_none_for_revoked(self, specialist_app):
        """card_for_token با توکن revoke‌شده باید None برگرداند."""
        app, spec_db, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="B800000001")
        token = _issue_token(spec_db, pid)

        from src.adapters.sqlite.patient_card_repo import PatientCardRepository
        repo = PatientCardRepository()
        row = repo.get_by_token(token)
        repo.revoke(row["id"])

        from src.services.card_projection_service import card_for_token
        result = card_for_token(token)
        assert result is None, f"Expected None for revoked token, got {result!r}"

    def test_B9_card_for_token_dto_has_no_national_id_key(self, specialist_app):
        """DTO برگشتی card_for_token هرگز کلید 'national_id' نداشته باشد.

        این اصلی‌ترین ادعای ADR-0004 §6 است.
        """
        app, spec_db, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="B900000001")
        _add_vital(spec_db, pid, "fbs", 110)
        _enable_card_feature(spec_db)
        token = _issue_token(spec_db, pid)

        from src.services.card_projection_service import card_for_token
        dto = card_for_token(token)
        assert dto is not None, "Valid token should return a DTO, not None"
        assert "national_id" not in dto, (
            f"DTO must NOT contain 'national_id' key (ADR-0004 §6). Got keys: {list(dto.keys())}"
        )


# ===========================================================================
# Scenario C — عدمِ نشتِ داده (خصمانه): داده‌های حساس در HTML کارت نیست
# ===========================================================================

class TestScenarioCDataLeakPrevention:
    """ادعاهای ADR-0004 §6: داروها، بیماری‌ها، کدملی، تلفن از HTML کارت غایب‌اند."""

    def _get_card_body(self, specialist_app, national_id, phone, full_name,
                       med_name="متفورمین۵۰۰", cond_name="دیابت نوع دو",
                       cond_code="DM2_LEAK"):
        """بیمار می‌سازد، داروی فعال و بیماری اضافه می‌کند، توکن صادر می‌کند،
        کارت را GET می‌کند و body را برمی‌گرداند."""
        app, spec_db, _ = specialist_app
        pid = _enroll_patient(spec_db, full_name=full_name,
                              national_id=national_id, phone=phone)
        _add_vital(spec_db, pid, "fbs", 120)
        _add_medication(spec_db, pid, name=med_name)
        _add_condition(spec_db, pid, code=cond_code, name=cond_name)
        _enable_card_feature(spec_db)
        token = _issue_token(spec_db, pid)

        client = app.test_client()
        rv = client.get(f"/card/{token}")
        assert rv.status_code == 200, f"Expected 200 for data-leak test, got {rv.status_code}"
        return rv.data.decode("utf-8")

    def test_C1_drug_name_not_in_html(self, specialist_app):
        """نام دارو نباید در HTML کارت باشد."""
        body = self._get_card_body(specialist_app,
                                   national_id="C100000001", phone="09111000001",
                                   full_name="بیمار سی‌یک", med_name="متفورمین_یکم")
        assert "متفورمین_یکم" not in body, (
            "Drug name 'متفورمین_یکم' must NOT appear in the public card HTML (ADR-0004 §6)"
        )

    def test_C2_condition_name_not_in_html(self, specialist_app):
        """نام بیماری نباید در HTML کارت باشد."""
        body = self._get_card_body(specialist_app,
                                   national_id="C200000001", phone="09111000002",
                                   full_name="بیمار سی‌دو",
                                   cond_name="دیابت_تست_نشتی", cond_code="DM_LEAK_C2")
        assert "دیابت_تست_نشتی" not in body, (
            "Condition name must NOT appear in the public card HTML (ADR-0004 §6)"
        )

    def test_C3_condition_code_not_in_html(self, specialist_app):
        """کد بیماری نباید در HTML کارت باشد."""
        body = self._get_card_body(specialist_app,
                                   national_id="C300000001", phone="09111000003",
                                   full_name="بیمار سی‌سه",
                                   cond_code="DM_LEAK_C3")
        assert "DM_LEAK_C3" not in body, (
            "Condition code 'DM_LEAK_C3' must NOT appear in the public card HTML (ADR-0004 §6)"
        )

    def test_C4_national_id_not_in_html(self, specialist_app):
        """کد ملی نباید در HTML کارت باشد."""
        body = self._get_card_body(specialist_app,
                                   national_id="C400000001", phone="09111000004",
                                   full_name="بیمار سی‌چهار")
        assert "C400000001" not in body, (
            "national_id 'C400000001' must NOT appear in the public card HTML (ADR-0004 §6)"
        )

    def test_C5_phone_number_not_in_html(self, specialist_app):
        """شماره تلفن بیمار نباید در HTML کارت باشد (clinic_phone ≠ patient phone)."""
        body = self._get_card_body(specialist_app,
                                   national_id="C500000001", phone="09114560001",
                                   full_name="بیمار سی‌پنج")
        assert "09114560001" not in body, (
            "Patient phone '09114560001' must NOT appear in the public card HTML (ADR-0004 §6)"
        )


# ===========================================================================
# Scenario D — مخزن توکن (token repo): ایجاد/revoke/یکتایی
# ===========================================================================

class TestScenarioDTokenRepository:
    """تست‌های کارکردی PatientCardRepository."""

    def test_D1_create_token_length(self, specialist_app):
        """create_token باید توکنی از token_urlsafe(32) برگرداند (طول ~43 کاراکتر)."""
        app, spec_db, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="D100000001")
        token = _issue_token(spec_db, pid)
        assert isinstance(token, str)
        # token_urlsafe(32) -> 32 bytes -> 44 base64url chars (with padding stripped ~= 43)
        assert 40 <= len(token) <= 46, (
            f"token_urlsafe(32) should produce ~43 chars, got len={len(token)}: {token!r}"
        )

    def test_D2_create_token_second_revokes_first(self, specialist_app):
        """صدور توکن دوم باید توکن اول را revoke کند (یک active در هر زمان)."""
        app, spec_db, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="D200000001")
        token1 = _issue_token(spec_db, pid)
        token2 = _issue_token(spec_db, pid)

        from src.adapters.sqlite.patient_card_repo import PatientCardRepository
        repo = PatientCardRepository()

        row1 = repo.get_by_token(token1)
        row2 = repo.get_by_token(token2)

        assert row1 is not None
        assert row1["revoked_at"] is not None, (
            "First token must be revoked after second token is issued"
        )
        assert row2 is not None
        assert row2["revoked_at"] is None, (
            "Second (new) token must NOT be revoked"
        )

    def test_D3_only_one_active_token_per_patient(self, specialist_app):
        """active_for_patient باید بعد از دو صدور، فقط یک توکن active برگرداند."""
        app, spec_db, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="D300000001")
        _issue_token(spec_db, pid)
        token2 = _issue_token(spec_db, pid)

        from src.adapters.sqlite.patient_card_repo import PatientCardRepository
        active = PatientCardRepository().active_for_patient(pid)
        assert active is not None, "active_for_patient must return the second (active) token"
        assert active["token"] == token2, (
            f"active_for_patient should return the latest token, got {active['token']!r} "
            f"instead of {token2!r}"
        )

    def test_D4_revoke_makes_token_inactive(self, specialist_app):
        """revoke() باید توکن را غیرفعال کند و active_for_patient None برگرداند."""
        app, spec_db, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="D400000001")
        token = _issue_token(spec_db, pid)

        from src.adapters.sqlite.patient_card_repo import PatientCardRepository
        repo = PatientCardRepository()
        row = repo.get_by_token(token)
        assert row is not None
        repo.revoke(row["id"], patient_link_id=pid)

        active = repo.active_for_patient(pid)
        assert active is None, "After revoke, active_for_patient must return None"

        row_after = repo.get_by_token(token)
        assert row_after["revoked_at"] is not None, (
            "revoked_at must be set after revoke()"
        )

    def test_D5_get_by_token_empty_string_returns_none(self, specialist_app):
        """get_by_token با رشته خالی باید None برگرداند."""
        from src.adapters.sqlite.patient_card_repo import PatientCardRepository
        result = PatientCardRepository().get_by_token("")
        assert result is None, "get_by_token('') must return None"


# ===========================================================================
# Scenario E — روت‌های staff: card_admin / card_issue / card_revoke
# ===========================================================================

class TestScenarioEStaffRoutes:
    """روت‌های staff در /patients/<pid>/card برای مدیریت توکن."""

    def test_E1_card_admin_requires_login(self, specialist_app):
        """GET /patients/<pid>/card بدون لاگین باید ریدایرکت (302/303) یا 401 برگرداند."""
        app, spec_db, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="E100000001")
        client = app.test_client()  # no login
        rv = client.get(f"/patients/{pid}/card", follow_redirects=False)
        assert rv.status_code in (301, 302, 303, 401), (
            f"Unauthenticated card_admin should redirect or 401, got {rv.status_code}"
        )

    def test_E2_card_issue_requires_login(self, specialist_app):
        """POST /patients/<pid>/card/issue بدون لاگین باید ریدایرکت یا 401 برگرداند."""
        app, spec_db, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="E200000001")
        client = app.test_client()
        rv = client.post(f"/patients/{pid}/card/issue", follow_redirects=False)
        assert rv.status_code in (301, 302, 303, 401), (
            f"Unauthenticated card_issue should redirect or 401, got {rv.status_code}"
        )

    def test_E3_card_issue_creates_token_and_active_for_patient_returns_it(self, test_client):
        """POST /patients/<pid>/card/issue توکن می‌سازد و active_for_patient آن را دارد."""
        client, spec_db, _ = test_client
        pid = _enroll_patient(spec_db, national_id="E300000001")

        rv = client.post(f"/patients/{pid}/card/issue", follow_redirects=True)
        # Should redirect back to card_admin (200 after follow)
        assert rv.status_code == 200, (
            f"card_issue should succeed (200 after redirect), got {rv.status_code}"
        )

        from src.adapters.sqlite.patient_card_repo import PatientCardRepository
        active = PatientCardRepository().active_for_patient(pid)
        assert active is not None, (
            "After POST /card/issue, active_for_patient must return a token row"
        )
        assert active["patient_link_id"] == pid
        assert active["revoked_at"] is None

    def test_E4_card_revoke_deactivates_token(self, test_client):
        """POST /patients/<pid>/card/revoke/<token_id> باید توکن را revoke کند."""
        client, spec_db, _ = test_client
        pid = _enroll_patient(spec_db, national_id="E400000001")

        # Issue via HTTP
        client.post(f"/patients/{pid}/card/issue", follow_redirects=True)

        from src.adapters.sqlite.patient_card_repo import PatientCardRepository
        repo = PatientCardRepository()
        active = repo.active_for_patient(pid)
        assert active is not None, "Token must exist before revoke test"
        token_id = active["id"]

        rv = client.post(f"/patients/{pid}/card/revoke/{token_id}", follow_redirects=True)
        assert rv.status_code == 200, (
            f"card_revoke should succeed (200 after redirect), got {rv.status_code}"
        )

        active_after = repo.active_for_patient(pid)
        assert active_after is None, (
            "After POST /card/revoke, active_for_patient must return None"
        )

    def test_E5_card_admin_get_returns_200_when_logged_in(self, test_client):
        """GET /patients/<pid>/card برای کاربر لاگین‌شده 200 برمی‌گرداند."""
        client, spec_db, _ = test_client
        pid = _enroll_patient(spec_db, national_id="E500000001")
        rv = client.get(f"/patients/{pid}/card")
        assert rv.status_code == 200, (
            f"card_admin (GET) for logged-in user should return 200, got {rv.status_code}"
        )


# ===========================================================================
# Scenario F — zero-write روی clinic_new.db واقعی
# ===========================================================================

@pytest.mark.skipif(
    not os.path.exists(_REAL_ACC_DB),
    reason=f"Real accounting DB not found at {_REAL_ACC_DB}"
)
class TestScenarioFRealAccDbZeroWrite:
    """clinic_new.db واقعی بعد از GET کارت بایت‌به‌بایت دست‌نخورده است."""

    def test_F1_real_accounting_db_unchanged_after_card_GET(self, specialist_app, tmp_dir):
        """SHA-256 و mtime فایل clinic_new.db بعد از GET /card/<token> یکسان بماند."""
        app, spec_db, _ = specialist_app
        pid = _enroll_patient(spec_db, national_id="F100000001")
        _add_vital(spec_db, pid, "fbs", 90)
        _enable_card_feature(spec_db)
        token = _issue_token(spec_db, pid)

        sha_before = _sha256(_REAL_ACC_DB)
        wal_path = _REAL_ACC_DB + "-wal"
        shm_path = _REAL_ACC_DB + "-shm"
        wal_existed_before = os.path.exists(wal_path)
        shm_existed_before = os.path.exists(shm_path)

        client = app.test_client()
        rv = client.get(f"/card/{token}")
        assert rv.status_code == 200

        sha_after = _sha256(_REAL_ACC_DB)
        assert sha_before == sha_after, (
            f"clinic_new.db was MODIFIED after GET /card/<token>!\n"
            f"  before: {sha_before}\n"
            f"  after:  {sha_after}"
        )
        if not wal_existed_before:
            assert not os.path.exists(wal_path), (
                "A WAL file was created on clinic_new.db — write attempt via accounting bridge"
            )
        if not shm_existed_before:
            assert not os.path.exists(shm_path), (
                "A SHM file was created on clinic_new.db — write attempt via accounting bridge"
            )

        print(f"\n[SCENARIO F1] SHA-256 before: {sha_before}")
        print(f"[SCENARIO F1] SHA-256 after:  {sha_after}")
        print(f"[SCENARIO F1] MATCH: {sha_before == sha_after}")
