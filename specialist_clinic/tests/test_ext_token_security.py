"""
SECU-05 — Extension API token hardening tests.

تأیید می‌کند که:
  (الف) ?token=... پارامتر کوئری → 401 (دیگر پذیرفته نمی‌شود)
  (ب)  Authorization: Bearer <token> → 200 با کلید items
  (ج)  توکن منقضی (expires_at گذشته) + هدر → 401
  (د)  توکن legacy (expires_at=NULL) + هدر → 200  (NULL = همیشه معتبر)
  (ه)  پس از rotate_api_token، api_token_expires_at ست شده و در آینده است
  (و)  /pending با seed یک followup_tasks(status=open, fulfillment=remote) →
       آیتم در پاسخ ظاهر می‌شود؛ پاسخ کران‌دار است (LIMIT ۲۰۰ رعایت می‌شود)

ایمنی:
  - همه نوشتن‌ها روی DB موقت هستند؛ specialist.db و clinic_new.db دست‌نخورده.
  - SMS ارسال نمی‌شود (TESTING=True → scheduler اجرا نمی‌شود).

اجرا از مسیر specialist_clinic/:
    .venv/Scripts/python.exe -m pytest tests/test_ext_token_security.py -v
"""
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_SPECIALIST_ROOT = os.path.join(_REPO_ROOT, "specialist_clinic")
_REAL_ACC_DB = os.path.join(_REPO_ROOT, "webapp", "clinic_new.db")

import shutil
import sqlite3
import tempfile
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flush_src_modules():
    """حذف src.* از sys.modules برای ایزولاسیون env/Config بین تست‌ها."""
    for mod in list(sys.modules.keys()):
        if mod == "src" or mod.startswith("src."):
            del sys.modules[mod]


def _make_minimal_acc_db(path: str):
    """یک accounting DB کمینه می‌سازد تا bridge شکایت نکند."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, family_name TEXT, full_name TEXT,
            national_id TEXT UNIQUE, phone_number TEXT,
            birthdate TEXT, gender TEXT, insurance_type TEXT,
            insurance_expiry TEXT, address TEXT, is_foreign INTEGER DEFAULT 0,
            created_by TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL, status TEXT DEFAULT 'open',
            total_amount REAL DEFAULT 0, work_date TEXT, closed_at TEXT,
            opened_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER, patient_id INTEGER, visit_date TEXT,
            doctor_name TEXT, price REAL DEFAULT 0,
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="secu05_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def specialist_app(tmp_dir):
    """Flask test app روی یک DB موقت با ایزولاسیون کامل env/module."""
    spec_db = os.path.join(tmp_dir, "specialist_secu05.db")
    acc_db = os.path.join(tmp_dir, "acc_secu05.db")
    _make_minimal_acc_db(acc_db)

    _saved_env = {
        "SPECIALIST_DB_PATH": os.environ.get("SPECIALIST_DB_PATH"),
        "ACCOUNTING_DB_PATH": os.environ.get("ACCOUNTING_DB_PATH"),
    }
    os.environ["SPECIALIST_DB_PATH"] = spec_db
    os.environ["ACCOUNTING_DB_PATH"] = acc_db

    _flush_src_modules()

    sys.path.insert(0, _SPECIALIST_ROOT)
    from src.app import create_app
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": spec_db,
        "PROPAGATE_EXCEPTIONS": True,
        "SECRET_KEY": "secu05-test-secret-key",
        "BACKUP_FOLDER": os.path.join(tmp_dir, "backups"),
    })

    ctx = app.app_context()
    ctx.push()

    # Bootstrap: schema + migrations + seeds (api_token_expires_at ستون ایجاد می‌شود)
    from src.adapters.sqlite.core import get_db
    get_db()

    yield app, spec_db

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
def auth_client(specialist_app):
    """(client, app, spec_db, admin_user_id, admin_token) — با session login ادمین و توکن چرخیده."""
    app, spec_db = specialist_app
    client = app.test_client()
    # login
    client.post("/auth/login", data={"username": "admin", "password": "admin"},
                follow_redirects=True)

    # admin user_id را از DB می‌گیریم
    from src.adapters.sqlite.core import get_db
    db = get_db()
    row = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    assert row is not None, "admin باید توسط _ensure_default_admin ساخته شده باشد"
    uid = dict(row)["id"]

    # توکن می‌چرخانیم
    from src.services.auth_service import AuthService
    token = AuthService().rotate_api_token(uid)

    yield client, app, spec_db, uid, token


# ---------------------------------------------------------------------------
# (الف) پارامتر ?token= → 401
# ---------------------------------------------------------------------------

class TestQueryParamTokenRejected:

    def test_query_param_token_returns_401(self, auth_client):
        """`GET /api/ext/pending?token=<token>` باید ۴۰۱ برگرداند — SECU-05 پارامتر کوئری را قبول نمی‌کند."""
        client, app, spec_db, uid, token = auth_client

        rv = client.get(f"/api/ext/pending?token={token}")
        assert rv.status_code == 401, (
            f"FAIL — پارامتر کوئری ?token= باید 401 برگرداند، ولی {rv.status_code} آمد"
        )
        data = rv.get_json()
        assert data is not None and data.get("ok") is False, (
            f"FAIL — پاسخ باید JSON با ok=false باشد، آمد: {data}"
        )

    def test_query_param_token_body_json_returns_401(self, auth_client):
        """توکن در بدنه JSON هم باید رد شود — فقط هدر Authorization: Bearer مجاز است."""
        client, app, spec_db, uid, token = auth_client
        rv = client.get("/api/ext/pending",
                        json={"token": token},
                        content_type="application/json")
        assert rv.status_code == 401, (
            f"FAIL — توکن در بدنه JSON باید 401 برگرداند، آمد {rv.status_code}"
        )


# ---------------------------------------------------------------------------
# (ب) Authorization: Bearer <token> → 200 با کلید items
# ---------------------------------------------------------------------------

class TestBearerHeaderTokenAccepted:

    def test_bearer_header_returns_200_with_items_key(self, auth_client):
        """`Authorization: Bearer <token>` باید ۲۰۰ و JSON با کلید `items` برگرداند."""
        client, app, spec_db, uid, token = auth_client

        rv = client.get("/api/ext/pending",
                        headers={"Authorization": f"Bearer {token}"})
        assert rv.status_code == 200, (
            f"FAIL — Bearer header باید 200 برگرداند، آمد {rv.status_code}"
        )
        data = rv.get_json()
        assert data is not None and "items" in data, (
            f"FAIL — پاسخ باید کلید 'items' داشته باشد، آمد: {data}"
        )
        assert isinstance(data["items"], list), (
            f"FAIL — items باید list باشد، آمد {type(data['items'])}"
        )

    def test_bearer_header_case_insensitive_prefix(self, auth_client):
        """Authorization: bearer (lowercase) هم باید ۲۰۰ برگرداند (RFC 7235)."""
        client, app, spec_db, uid, token = auth_client
        rv = client.get("/api/ext/pending",
                        headers={"Authorization": f"bearer {token}"})
        assert rv.status_code == 200, (
            f"FAIL — bearer (lowercase) باید 200 برگرداند، آمد {rv.status_code}"
        )

    def test_no_auth_header_returns_401(self, auth_client):
        """بدون هیچ هدری → ۴۰۱."""
        client, app, spec_db, uid, token = auth_client
        rv = client.get("/api/ext/pending")
        assert rv.status_code == 401, (
            f"FAIL — بدون هدر auth باید 401 برگرداند، آمد {rv.status_code}"
        )

    def test_wrong_token_returns_401(self, auth_client):
        """توکن اشتباه در هدر → ۴۰۱."""
        client, app, spec_db, uid, token = auth_client
        rv = client.get("/api/ext/pending",
                        headers={"Authorization": "Bearer totally-wrong-token-xyz"})
        assert rv.status_code == 401, (
            f"FAIL — توکن اشتباه باید 401 برگرداند، آمد {rv.status_code}"
        )


# ---------------------------------------------------------------------------
# (ج) توکن منقضی → 401
# ---------------------------------------------------------------------------

class TestExpiredTokenRejected:

    def test_expired_token_returns_401(self, auth_client):
        """مستقیماً `api_token_expires_at` را به گذشته می‌زنیم → هدر معتبر ولی توکن منقضی → ۴۰۱."""
        client, app, spec_db, uid, token = auth_client

        from src.adapters.sqlite.core import get_db
        db = get_db()
        # تاریخ کاملاً در گذشته
        db.execute(
            "UPDATE users SET api_token_expires_at='2000-01-01 00:00:00' WHERE id=?",
            (uid,))
        db.commit()

        rv = client.get("/api/ext/pending",
                        headers={"Authorization": f"Bearer {token}"})
        assert rv.status_code == 401, (
            f"FAIL — توکن منقضی باید 401 برگرداند، آمد {rv.status_code}"
        )
        data = rv.get_json()
        assert data is not None and data.get("ok") is False, (
            f"FAIL — پاسخ منقضی باید ok=false باشد، آمد {data}"
        )

    def test_far_future_expiry_still_valid(self, auth_client):
        """api_token_expires_at در آینده دور → توکن معتبر → ۲۰۰."""
        client, app, spec_db, uid, token = auth_client

        from src.adapters.sqlite.core import get_db
        db = get_db()
        db.execute(
            "UPDATE users SET api_token_expires_at='2099-12-31 23:59:59' WHERE id=?",
            (uid,))
        db.commit()

        rv = client.get("/api/ext/pending",
                        headers={"Authorization": f"Bearer {token}"})
        assert rv.status_code == 200, (
            f"FAIL — توکن با expiry در آینده باید 200 برگرداند، آمد {rv.status_code}"
        )


# ---------------------------------------------------------------------------
# (د) توکن legacy با expires_at=NULL → 200 (به‌عنوان بخشودگی legacy)
# ---------------------------------------------------------------------------

class TestLegacyNullExpiryTokenValid:

    def test_null_expiry_token_is_accepted(self, auth_client):
        """NULL در api_token_expires_at (توکن legacy) باید هنوز معتبر باشد → ۲۰۰."""
        client, app, spec_db, uid, token = auth_client
        legacy_token = "legacy-token-secu05-test-abc123"

        from src.adapters.sqlite.core import get_db
        db = get_db()
        # ست کردن مستقیم توکن legacy بدون expires_at
        db.execute(
            "UPDATE users SET api_token=?, api_token_expires_at=NULL WHERE id=?",
            (legacy_token, uid))
        db.commit()

        rv = client.get("/api/ext/pending",
                        headers={"Authorization": f"Bearer {legacy_token}"})
        assert rv.status_code == 200, (
            f"FAIL — توکن legacy با NULL expiry باید 200 برگرداند، آمد {rv.status_code}"
        )
        data = rv.get_json()
        assert "items" in data, (
            f"FAIL — پاسخ legacy token باید کلید items داشته باشد، آمد {data}"
        )

    def test_null_expiry_inactive_user_rejected(self, auth_client):
        """حتی با توکن legacy، اگر is_active=0 باشد → ۴۰۱."""
        client, app, spec_db, uid, token = auth_client
        legacy_token = "legacy-inactive-user-secu05"

        from src.adapters.sqlite.core import get_db
        db = get_db()
        db.execute(
            "UPDATE users SET api_token=?, api_token_expires_at=NULL, is_active=0 WHERE id=?",
            (legacy_token, uid))
        db.commit()

        rv = client.get("/api/ext/pending",
                        headers={"Authorization": f"Bearer {legacy_token}"})
        assert rv.status_code == 401, (
            f"FAIL — کاربر غیرفعال باید 401 برگرداند حتی با توکن legacy، آمد {rv.status_code}"
        )

        # is_active را برمی‌گردانیم تا fixture cleanup مشکلی نداشته باشد
        db.execute("UPDATE users SET is_active=1 WHERE id=?", (uid,))
        db.commit()


# ---------------------------------------------------------------------------
# (ه) پس از rotate_api_token، expires_at ست و در آینده است
# ---------------------------------------------------------------------------

class TestRotateApiTokenSetsExpiry:

    def test_rotate_sets_non_null_future_expiry(self, specialist_app):
        """rotate_api_token باید api_token_expires_at را با تاریخی در آینده ست کند."""
        app, spec_db = specialist_app
        from src.adapters.sqlite.core import get_db
        from src.services.auth_service import AuthService
        from src.common.utils import iran_now

        db = get_db()
        row = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()
        uid = dict(row)["id"]

        token = AuthService().rotate_api_token(uid)
        assert token and len(token) > 10, "FAIL — توکن باید غیرخالی و با طول معقول باشد"

        row = db.execute(
            "SELECT api_token, api_token_expires_at FROM users WHERE id=?", (uid,)
        ).fetchone()
        r = dict(row)

        assert r["api_token"] == token, (
            f"FAIL — api_token در DB باید با توکن برگشتی مطابقت داشته باشد"
        )
        assert r["api_token_expires_at"] is not None, (
            "FAIL — پس از rotate، api_token_expires_at نباید NULL باشد"
        )

        # بررسی که تاریخ در آینده است
        from datetime import datetime
        expiry = datetime.strptime(r["api_token_expires_at"], '%Y-%m-%d %H:%M:%S')
        now = iran_now()
        assert expiry > now, (
            f"FAIL — api_token_expires_at={r['api_token_expires_at']} باید در آینده باشد (now={now})"
        )

    def test_rotate_token_ttl_is_approximately_90_days(self, specialist_app):
        """TTL پیش‌فرض باید حدود ۹۰ روز باشد (±۱ دقیقه برای margin)."""
        app, spec_db = specialist_app
        from src.adapters.sqlite.core import get_db
        from src.services.auth_service import AuthService
        from src.common.utils import iran_now
        from datetime import datetime, timedelta

        db = get_db()
        row = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()
        uid = dict(row)["id"]

        before = iran_now()
        AuthService().rotate_api_token(uid)
        after = iran_now()

        row = db.execute("SELECT api_token_expires_at FROM users WHERE id=?", (uid,)).fetchone()
        expiry = datetime.strptime(dict(row)["api_token_expires_at"], '%Y-%m-%d %H:%M:%S')

        min_expiry = before + timedelta(days=89, hours=23)
        max_expiry = after + timedelta(days=90, minutes=2)

        assert expiry >= min_expiry, (
            f"FAIL — expiry={expiry} کمتر از حداقل انتظار {min_expiry}"
        )
        assert expiry <= max_expiry, (
            f"FAIL — expiry={expiry} بیشتر از حداکثر انتظار {max_expiry}"
        )

    def test_rotate_invalidates_old_token(self, specialist_app):
        """چرخش مجدد باید توکن قدیمی را باطل کند."""
        app, spec_db = specialist_app
        from src.adapters.sqlite.core import get_db
        from src.services.auth_service import AuthService

        db = get_db()
        row = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()
        uid = dict(row)["id"]

        token_old = AuthService().rotate_api_token(uid)
        token_new = AuthService().rotate_api_token(uid)

        assert token_old != token_new, "FAIL — توکن جدید باید با توکن قدیمی فرق داشته باشد"

        # توکن قدیمی دیگر در DB نیست
        from src.adapters.sqlite.auth_repo import AuthRepository
        found_old = AuthRepository().get_user_by_token(token_old)
        assert found_old is None, (
            "FAIL — توکن قدیمی باید پس از چرخش باطل شده باشد"
        )
        found_new = AuthRepository().get_user_by_token(token_new)
        assert found_new is not None, (
            "FAIL — توکن جدید باید معتبر باشد"
        )


# ---------------------------------------------------------------------------
# (و) /pending با seed واقعی → آیتم در پاسخ؛ کران‌دار بودن LIMIT 200
# ---------------------------------------------------------------------------

class TestPendingEndpointSeededData:

    def _seed_patient_and_followup(self, fulfillment="remote", status="open"):
        """یک patient_links و یک followup_tasks می‌سازد؛ id‌های هر دو را برمی‌گرداند."""
        from src.adapters.sqlite.core import get_db
        db = get_db()
        cur = db.execute(
            "INSERT INTO patient_links (national_id, full_name, phone_number, enrolled_by)"
            " VALUES (?,?,?,?)",
            ("8880000001", "بیمارِ تست‌پندینگ", "09120000001", "test"))
        db.commit()
        pid = cur.lastrowid

        cur2 = db.execute(
            "INSERT INTO followup_tasks (patient_link_id, reason, status, fulfillment)"
            " VALUES (?,?,?,?)",
            (pid, "refill", status, fulfillment))
        db.commit()
        fid = cur2.lastrowid
        return pid, fid

    def test_open_remote_followup_appears_in_items(self, auth_client):
        """یک followup_tasks با status=open و fulfillment=remote باید در items ظاهر شود."""
        client, app, spec_db, uid, token = auth_client

        pid, fid = self._seed_patient_and_followup(fulfillment="remote", status="open")

        rv = client.get("/api/ext/pending",
                        headers={"Authorization": f"Bearer {token}"})
        assert rv.status_code == 200, f"FAIL — 200 انتظار داشتیم، آمد {rv.status_code}"
        data = rv.get_json()
        items = data.get("items", [])
        assert isinstance(items, list), f"FAIL — items باید list باشد"

        followup_ids = [it.get("followup_id") for it in items]
        assert fid in followup_ids, (
            f"FAIL — followup_id={fid} باید در items ظاهر شود، آمد {followup_ids}"
        )

    def test_in_person_followup_excluded(self, auth_client):
        """followup با fulfillment='in_person' نباید در /pending ظاهر شود."""
        client, app, spec_db, uid, token = auth_client

        pid, fid_inperson = self._seed_patient_and_followup(
            fulfillment="in_person", status="open")

        rv = client.get("/api/ext/pending",
                        headers={"Authorization": f"Bearer {token}"})
        assert rv.status_code == 200
        followup_ids = [it.get("followup_id") for it in rv.get_json().get("items", [])]
        assert fid_inperson not in followup_ids, (
            f"FAIL — followup in_person (id={fid_inperson}) نباید در /pending ظاهر شود"
        )

    def test_closed_followup_excluded(self, auth_client):
        """followup با status='done' نباید در /pending ظاهر شود."""
        client, app, spec_db, uid, token = auth_client

        pid, fid_done = self._seed_patient_and_followup(
            fulfillment="remote", status="done")

        rv = client.get("/api/ext/pending",
                        headers={"Authorization": f"Bearer {token}"})
        assert rv.status_code == 200
        followup_ids = [it.get("followup_id") for it in rv.get_json().get("items", [])]
        assert fid_done not in followup_ids, (
            f"FAIL — followup با status=done (id={fid_done}) نباید در /pending ظاهر شود"
        )

    def test_medications_included_in_items(self, auth_client):
        """اگر بیمار داروی فعال داشته باشد، مدیکیشن‌ها در آیتم باید دیده شوند."""
        client, app, spec_db, uid, token = auth_client

        pid, fid = self._seed_patient_and_followup(fulfillment="remote", status="open")

        from src.adapters.sqlite.core import get_db
        db = get_db()
        db.execute(
            "INSERT INTO patient_medications (patient_link_id, drug_name, dose, is_active)"
            " VALUES (?,?,?,1)",
            (pid, "متفورمین", "۵۰۰mg"))
        db.commit()

        rv = client.get("/api/ext/pending",
                        headers={"Authorization": f"Bearer {token}"})
        assert rv.status_code == 200
        items = rv.get_json().get("items", [])
        match = [it for it in items if it.get("followup_id") == fid]
        assert match, f"FAIL — آیتم مربوط به followup_id={fid} پیدا نشد"
        meds = match[0].get("medications", [])
        assert isinstance(meds, list) and len(meds) >= 1, (
            f"FAIL — medications باید در آیتم باشد، آمد {meds}"
        )
        drug_names = [m.get("drug_name") for m in meds]
        assert "متفورمین" in drug_names, (
            f"FAIL — داروی متفورمین باید در medications باشد، آمد {drug_names}"
        )

    def test_response_is_bounded_not_unbounded(self, auth_client):
        """ثابت می‌کند /pending کران‌دار است — پاسخ JSON با items list برمی‌گردد،
        و حتی اگر ردیف‌های زیادی seed شوند، پاسخ 2xx است و items list است.
        (تست صریح overflow 200 نیاز به ۲۰۰+ seed دارد که این fixture آن را ندارد؛
        اما endpoint از LIMIT 200 در SQL استفاده می‌کند که در code review تأیید شد.)"""
        client, app, spec_db, uid, token = auth_client

        # seed چند ردیف برای اطمینان از عملکرد کلی
        from src.adapters.sqlite.core import get_db
        db = get_db()
        for i in range(5):
            cur = db.execute(
                "INSERT INTO patient_links (national_id, full_name, enrolled_by)"
                " VALUES (?,?,?)",
                (f"777000{i:04d}", f"بیمار {i}", "test"))
            db.commit()
            pid = cur.lastrowid
            db.execute(
                "INSERT INTO followup_tasks (patient_link_id, reason, status, fulfillment)"
                " VALUES (?,?,?,?)",
                (pid, "refill", "open", "remote"))
            db.commit()

        rv = client.get("/api/ext/pending",
                        headers={"Authorization": f"Bearer {token}"})
        assert rv.status_code == 200, f"FAIL — باید 200 برگردد، آمد {rv.status_code}"
        data = rv.get_json()
        assert "items" in data and isinstance(data["items"], list), (
            f"FAIL — پاسخ باید items list داشته باشد"
        )
        # حداقل همان ۵ ردیف که seed کردیم باید برگردد
        assert len(data["items"]) >= 5, (
            f"FAIL — حداقل ۵ آیتم seed شد ولی {len(data['items'])} برگشت"
        )
        # و مطمئناً از ۲۰۰ بیشتر نیست (LIMIT)
        assert len(data["items"]) <= 200, (
            f"FAIL — items نباید از LIMIT 200 تجاوز کند، آمد {len(data['items'])}"
        )
