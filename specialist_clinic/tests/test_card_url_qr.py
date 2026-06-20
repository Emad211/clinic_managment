"""
تست‌های افزایشی — _card_url / _qr_svg / card_admin render (ADR-0004, فاز QR)

سناریوها:
  G1  _card_url وقتی public_base_url ست است (بدونِ slash مضاعف)
  G2  _card_url وقتی public_base_url خالی/نیست (fallback به request host)
  G3  _qr_svg با URL معتبر → str شروع‌شده با '<svg' و طولِ غیرصفر
  G4  _qr_svg graceful وقتی segno وجود ندارد → None، نه استثنا
  G5  GET /patients/<pid>/card (لاگین‌شده) پس از صدورِ توکن و ست public_base_url:
        - کد 200
        - بدنه شاملِ '<svg' (QR رندر شده)
        - بدنه شاملِ LAN IP (public_base_url در href/input)
  G6  رگرسیون A1: blueprint عمومی patient_card هنوز GET-only است
  G7  رگرسیون A2: card_projection_service.py هنوز فاقد SQL نوشتنی است

قوانینِ امنیت:
  - همه نوشتن‌ها روی کپیِ موقت DB (tmp_dir) — هرگز specialist.db واقعی لمس نمی‌شود
  - بدونِ ارسالِ SMS واقعی (TESTING=True → scheduler غیرفعال)
  - accounting DB تغییر نمی‌کند (پل read-only است)
"""

import sys
import os
import re

sys.stdout.reconfigure(encoding="utf-8")

# مسیرهای ثابت
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
# ابزارهای مشترک (کپی از test_patient_card.py برای استقلالِ کامل)
# ---------------------------------------------------------------------------

def _flush_src_modules():
    for mod in list(sys.modules.keys()):
        if mod == "src" or mod.startswith("src."):
            del sys.modules[mod]


def _enroll_patient(spec_db, full_name="بیمارِ QR تست", national_id="QR00000001",
                    phone="09120000001"):
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


def _set_setting(spec_db, key, value):
    conn = sqlite3.connect(spec_db)
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="qr_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def specialist_app(tmp_dir):
    """Flask test app با DB موقت — کاملاً ایزوله."""
    spec_db = os.path.join(tmp_dir, "specialist_qr_test.db")

    _saved_env = {
        "SPECIALIST_DB_PATH": os.environ.get("SPECIALIST_DB_PATH"),
        "ACCOUNTING_DB_PATH": os.environ.get("ACCOUNTING_DB_PATH"),
    }

    os.environ["SPECIALIST_DB_PATH"] = spec_db
    # اگر accounting DB موجود نبود، مسیر فرضی بده — پل graceful fallback دارد
    acc_path = _REAL_ACC_DB if os.path.exists(_REAL_ACC_DB) else spec_db
    os.environ["ACCOUNTING_DB_PATH"] = acc_path

    _flush_src_modules()
    if _SPECIALIST_ROOT not in sys.path:
        sys.path.insert(0, _SPECIALIST_ROOT)

    from src.app import create_app
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": spec_db,
        "PROPAGATE_EXCEPTIONS": True,
        "SECRET_KEY": "qr-test-secret-9x7z",
        "BACKUP_FOLDER": os.path.join(tmp_dir, "backups"),
    })

    ctx = app.app_context()
    ctx.push()

    from src.adapters.sqlite.core import get_db
    get_db()  # bootstrap: schema.sql + migrations + seed

    yield app, spec_db, tmp_dir

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
def logged_client(specialist_app):
    """test_client با session لاگین‌شدهٔ admin."""
    app, spec_db, tmp_dir = specialist_app
    client = app.test_client()
    client.post("/auth/login", data={"username": "admin", "password": "admin"},
                follow_redirects=True)
    return client, spec_db, tmp_dir, app


# ===========================================================================
# G — _card_url و _qr_svg
# ===========================================================================

class TestScenarioGCardUrlQr:

    # -----------------------------------------------------------------------
    # G1 — _card_url با public_base_url ست (بدونِ slash مضاعف)
    # -----------------------------------------------------------------------
    def test_G1_card_url_uses_public_base_url_without_double_slash(self, specialist_app):
        """وقتی setting 'public_base_url' == 'http://192.168.1.10:8090/' باشد،
        _card_url('ABC') باید دقیقاً 'http://192.168.1.10:8090/card/ABC' بدهد.
        (هیچ slash مضاعفی بینِ base و /card نباشد.)
        """
        app, spec_db, _ = specialist_app

        # ست‌کردنِ public_base_url با trailing slash (نمونه‌ای که مدیر می‌دهد)
        _set_setting(spec_db, "public_base_url", "http://192.168.1.10:8090/")

        from src.api.patients import _card_url
        with app.test_request_context("/"):
            result = _card_url("ABC")

        expected = "http://192.168.1.10:8090/card/ABC"
        assert result == expected, (
            f"_card_url('ABC') with public_base_url='http://192.168.1.10:8090/' "
            f"should return {expected!r}, got {result!r}"
        )

    # -----------------------------------------------------------------------
    # G2 — _card_url بدونِ تنظیم → fallback به host فعلی
    # -----------------------------------------------------------------------
    def test_G2_card_url_falls_back_to_request_host_when_no_setting(self, specialist_app):
        """وقتی public_base_url ست نیست، _card_url باید URL‌ای بسازد که:
          - شامل '/card/ABC' باشد
          - یک URL مطلق باشد (شروع با http)
        """
        app, spec_db, _ = specialist_app

        # اطمینان از اینکه setting خالی است
        _set_setting(spec_db, "public_base_url", "")

        from src.api.patients import _card_url
        with app.test_request_context("/"):
            result = _card_url("ABC")

        assert "/card/ABC" in result, (
            f"_card_url without setting must contain '/card/ABC', got {result!r}"
        )
        assert result.startswith("http"), (
            f"_card_url fallback must return absolute URL (starts with http), got {result!r}"
        )
        # نباید base_url ست‌شده را به‌کار ببرد
        assert "192.168" not in result, (
            "Fallback should NOT use LAN IP when setting is empty"
        )

    # -----------------------------------------------------------------------
    # G3 — _qr_svg با URL معتبر → <svg با طولِ غیرصفر + شاملِ توکن‌انکود
    # -----------------------------------------------------------------------
    def test_G3_qr_svg_returns_svg_string(self, specialist_app):
        """_qr_svg با یک URL معتبر باید str‌ای برگرداند که:
          - با '<svg' شروع شود
          - طولِ آن > 0 باشد
        """
        app, _, _ = specialist_app
        from src.api.patients import _qr_svg

        url = "http://192.168.1.10:8090/card/TOKENABC123"
        with app.test_request_context("/"):
            result = _qr_svg(url)

        assert result is not None, "_qr_svg must return a non-None value for a valid URL"
        assert isinstance(result, str), f"_qr_svg must return str, got {type(result)}"
        assert len(result) > 0, "_qr_svg must return non-empty string"
        assert result.lstrip().startswith("<svg"), (
            f"_qr_svg must return SVG starting with '<svg', got: {result[:60]!r}"
        )

    # -----------------------------------------------------------------------
    # G4 — _qr_svg graceful اگر segno نبود → None، نه استثنا
    # -----------------------------------------------------------------------
    def test_G4_qr_svg_returns_none_when_segno_unavailable(self, specialist_app):
        """وقتی segno از sys.modules حذف شود (ImportError شبیه‌سازی)،
        _qr_svg باید None برگرداند و هیچ استثنایی پرتاب نکند.
        """
        app, _, _ = specialist_app

        # پشتیبان گرفتن از segno واقعی
        real_segno = sys.modules.get("segno")

        try:
            # شبیه‌سازیِ عدمِ وجودِ segno
            sys.modules["segno"] = None  # type: ignore

            # باید core را هم flush کنیم چون _qr_svg با import داخلی عمل می‌کند
            # اما import داخلی (try: import segno) در بدنهٔ تابع است — monkeypatch کافی است
            from src.api.patients import _qr_svg

            with app.test_request_context("/"):
                result = _qr_svg("http://192.168.1.10:8090/card/TEST")

            assert result is None, (
                f"_qr_svg must return None when segno is unavailable, got {result!r}"
            )
        finally:
            # بازگرداندنِ segno واقعی به sys.modules
            if real_segno is not None:
                sys.modules["segno"] = real_segno
            else:
                sys.modules.pop("segno", None)

    # -----------------------------------------------------------------------
    # G5 — رندرِ صفحهٔ card_admin: 200 + QR svg + public_base_url در بدنه
    # -----------------------------------------------------------------------
    def test_G5_card_admin_renders_svg_and_base_url(self, logged_client):
        """GET /patients/<pid>/card پس از صدورِ توکن و ست public_base_url:
          - باید 200 برگرداند
          - بدنه باید '<svg' داشته باشد (QR رندرشده)
          - بدنه باید آدرسِ LAN را داشته باشد (public_base_url در input/link)
        """
        client, spec_db, _, app = logged_client
        pid = _enroll_patient(spec_db, national_id="G500000001", full_name="گلناز G5")

        lan_base = "http://10.0.0.5:8090"
        _set_setting(spec_db, "public_base_url", lan_base)
        _set_setting(spec_db, "patient_card_enabled", "1")

        # صدورِ توکن از طریقِ HTTP (staff route)
        rv_issue = client.post(f"/patients/{pid}/card/issue", follow_redirects=True)
        assert rv_issue.status_code == 200, (
            f"card/issue must succeed, got {rv_issue.status_code}"
        )

        rv = client.get(f"/patients/{pid}/card")
        assert rv.status_code == 200, (
            f"card_admin GET must return 200, got {rv.status_code}"
        )

        body = rv.data.decode("utf-8")

        assert "<svg" in body, (
            "card_admin page must render the QR SVG (segno installed and url is set); "
            "expected '<svg' in body"
        )

        assert lan_base in body, (
            f"card_admin page must show the public_base_url '{lan_base}' in the card URL "
            f"input/link — not found in body"
        )

    # -----------------------------------------------------------------------
    # G6 — رگرسیون A1: blueprint عمومی patient_card هنوز GET-only است
    #       (پس از اضافه‌شدنِ _qr_svg / _card_url در patients.py نباید شکسته باشد)
    # -----------------------------------------------------------------------
    def test_G6_regression_public_blueprint_still_get_only(self, specialist_app):
        """blueprint عمومی patient_card هنوز GET-only است (ADR-0004 رگرسیون).

        _qr_svg و _card_url در patients.py هستند — نه در patient_card blueprint —
        پس نباید هیچ POST/PUT/DELETE جدیدی به آن بلوپرینت اضافه شده باشد.
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
            "patient_card blueprint has non-GET methods (ADR-0004 regression):\n"
            + "\n".join(violations)
        )

    # -----------------------------------------------------------------------
    # G7 — رگرسیون A2: card_projection_service.py هنوز SQL نوشتنی ندارد
    # -----------------------------------------------------------------------
    def test_G7_regression_projection_service_still_read_only(self):
        """card_projection_service.py هنوز فاقدِ INSERT/UPDATE/DELETE/commit است.

        چک static روی خطوطِ کدِ واقعی (نه کامنت/داک‌استرینگ).
        """
        service_path = os.path.join(
            _SPECIALIST_ROOT, "src", "services", "card_projection_service.py"
        )
        assert os.path.exists(service_path), (
            f"card_projection_service.py not found at {service_path}"
        )

        with open(service_path, encoding="utf-8") as f:
            lines = f.readlines()

        code_lines = []
        in_docstring = False
        for line in lines:
            stripped = line.strip()
            triple_count = stripped.count('"""') + stripped.count("'''")
            if triple_count >= 2:
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
            matches = list(re.finditer(pattern, code_only, re.IGNORECASE))
            if matches:
                hits.append(
                    f"  [{label}] found {len(matches)} time(s) in code lines"
                )

        assert not hits, (
            "card_projection_service.py contains write SQL/commit (ADR-0004 regression):\n"
            + "\n".join(hits)
        )
