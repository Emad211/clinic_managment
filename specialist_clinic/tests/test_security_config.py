"""
Security hardening config — test suite (adversarial).

Verifies the two guarantees of the 2026-06 security hardening:
  1. Nothing existing is broken (regression via fixture isolation).
  2. The new production-guard and cookie-hardening behave correctly.

Safety contract:
  - All DB access uses :memory: or tmp files — specialist.db and clinic_new.db
    are never modified.
  - No SMS is sent (TESTING=True / scheduler never starts).
  - No real PRODUCTION env var leaks between tests (saved and restored).
  - src.* modules are flushed before every test that depends on Config state
    (Config.PRODUCTION / Config.DEBUG are baked in at import time).

Run from specialist_clinic/:
    .venv\\Scripts\\python.exe -m pytest tests/test_security_config.py -v
"""

import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

# ── Project root resolution (before any src import) ──────────────────────────
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_SPECIALIST_ROOT = os.path.join(_REPO_ROOT, "specialist_clinic")

sys.path.insert(0, _SPECIALIST_ROOT)

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENV_KEYS = ("PRODUCTION", "SECRET_KEY", "DEBUG", "SPECIALIST_DB_PATH", "ACCOUNTING_DB_PATH")


def _flush_src_modules():
    """Remove all src.* entries from sys.modules so the next import
    re-evaluates env vars (Config.PRODUCTION / Config.DEBUG are baked
    in at class-body evaluation time)."""
    for mod in list(sys.modules.keys()):
        if mod == "src" or mod.startswith("src."):
            del sys.modules[mod]


def _reset_core_initialized():
    """Reset the DB bootstrap flag so a new :memory: app bootstraps cleanly."""
    try:
        import src.adapters.sqlite.core as core_mod
        core_mod._initialized = False
    except Exception:
        pass


def _save_env():
    return {k: os.environ.get(k) for k in _ENV_KEYS}


def _restore_env(saved: dict):
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ---------------------------------------------------------------------------
# Fixture: a minimal no-op accounting DB so the bridge does not raise
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def fake_acc_db(tmp_path_factory):
    """A tiny read-only accounting DB (just the tables the bridge queries)."""
    import sqlite3, tempfile, shutil
    d = tmp_path_factory.mktemp("acc")
    path = str(d / "fake_clinic.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, family_name TEXT, full_name TEXT,
            national_id TEXT UNIQUE, phone_number TEXT,
            birthdate TEXT, gender TEXT
        );
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER, work_date TEXT, status TEXT, amount INTEGER
        );
        CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER, price INTEGER
        );
        CREATE TABLE IF NOT EXISTS injections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER, total_price INTEGER
        );
        CREATE TABLE IF NOT EXISTS procedures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER, price INTEGER
        );
    """)
    conn.commit()
    conn.close()
    yield path


# ---------------------------------------------------------------------------
# Scenario (الف) — PRODUCTION=1, no custom SECRET_KEY, no TESTING
#   → create_app() must raise RuntimeError before touching DB or scheduler
# ---------------------------------------------------------------------------

class TestProductionGuardRaisesWithDefaultKey:

    def test_raises_runtime_error_when_no_secret_key(self, fake_acc_db):
        """PRODUCTION=1 + default/missing SECRET_KEY + TESTING absent
        must cause create_app() to raise RuntimeError immediately."""
        saved = _save_env()
        try:
            # Ensure SECRET_KEY is absent from env so Config picks up DEFAULT_SECRET_KEY
            os.environ.pop("SECRET_KEY", None)
            os.environ["PRODUCTION"] = "1"
            os.environ["ACCOUNTING_DB_PATH"] = fake_acc_db
            # Use :memory: path so even if the guard were bypassed (it won't be)
            # no real file DB is created
            os.environ["SPECIALIST_DB_PATH"] = ":memory:"

            _flush_src_modules()

            from src.app import create_app

            # Call WITHOUT test_config so TESTING defaults to False
            with pytest.raises(RuntimeError, match="SECRET_KEY"):
                create_app()

        finally:
            _restore_env(saved)
            _flush_src_modules()
            _reset_core_initialized()

    def test_raises_runtime_error_when_secret_key_is_default_value(self, fake_acc_db):
        """PRODUCTION=1 + SECRET_KEY explicitly set to the DEFAULT_SECRET_KEY
        constant must also raise (same code path)."""
        saved = _save_env()
        try:
            # Import the constant before flushing (it is module-level, safe to grab now)
            _flush_src_modules()
            # We'll re-import after setting env; grab constant text directly
            DEFAULT = "specialist-clinic-secret-change-in-prod"

            os.environ["SECRET_KEY"] = DEFAULT
            os.environ["PRODUCTION"] = "1"
            os.environ["ACCOUNTING_DB_PATH"] = fake_acc_db
            os.environ["SPECIALIST_DB_PATH"] = ":memory:"

            _flush_src_modules()

            from src.app import create_app

            with pytest.raises(RuntimeError, match="SECRET_KEY"):
                create_app()

        finally:
            _restore_env(saved)
            _flush_src_modules()
            _reset_core_initialized()

    def test_guard_fires_before_any_db_or_scheduler_side_effect(self, fake_acc_db,
                                                                  tmp_path):
        """When RuntimeError is raised, no DB file is created next to the tmp path
        (confirms the guard fires before DB bootstrap)."""
        saved = _save_env()
        spec_path = str(tmp_path / "should_not_exist.db")
        try:
            os.environ.pop("SECRET_KEY", None)
            os.environ["PRODUCTION"] = "1"
            os.environ["SPECIALIST_DB_PATH"] = spec_path
            os.environ["ACCOUNTING_DB_PATH"] = fake_acc_db

            _flush_src_modules()

            from src.app import create_app

            with pytest.raises(RuntimeError):
                create_app()

            assert not os.path.exists(spec_path), (
                f"DB file was created before the security guard raised: {spec_path}"
            )

        finally:
            _restore_env(saved)
            _flush_src_modules()
            _reset_core_initialized()


# ---------------------------------------------------------------------------
# Scenario (ب) — PRODUCTION=1 + real SECRET_KEY + TESTING=True
#   → create_app() must NOT raise (TESTING bypasses the guard)
# ---------------------------------------------------------------------------

class TestProductionWithRealKeyDoesNotRaise:

    def test_no_raise_with_strong_key_and_testing(self, fake_acc_db):
        """PRODUCTION=1 + strong SECRET_KEY + TESTING=True must start cleanly."""
        saved = _save_env()
        try:
            os.environ["PRODUCTION"] = "1"
            os.environ["SECRET_KEY"] = "a-very-strong-random-secret-key-for-testing-32!"
            os.environ["ACCOUNTING_DB_PATH"] = fake_acc_db
            os.environ.pop("SPECIALIST_DB_PATH", None)

            _flush_src_modules()

            from src.app import create_app

            # Must not raise
            app = create_app({
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "PROPAGATE_EXCEPTIONS": True,
                "SECRET_KEY": "a-very-strong-random-secret-key-for-testing-32!",
                "PRODUCTION": True,
            })
            assert app is not None

        finally:
            _restore_env(saved)
            _flush_src_modules()
            _reset_core_initialized()

    def test_testing_true_suppresses_guard_even_without_env_production(self, fake_acc_db):
        """In local/test mode (PRODUCTION absent), TESTING=True must always work
        regardless of SECRET_KEY value."""
        saved = _save_env()
        try:
            os.environ.pop("PRODUCTION", None)
            os.environ.pop("SECRET_KEY", None)
            os.environ["ACCOUNTING_DB_PATH"] = fake_acc_db

            _flush_src_modules()

            from src.app import create_app

            app = create_app({
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "PROPAGATE_EXCEPTIONS": True,
            })
            assert app is not None

        finally:
            _restore_env(saved)
            _flush_src_modules()
            _reset_core_initialized()


# ---------------------------------------------------------------------------
# Scenario (ج) — Local mode (PRODUCTION not set)
#   → SESSION_COOKIE_SECURE=False, SameSite=Lax, HttpOnly=True
# ---------------------------------------------------------------------------

class TestLocalModeSessionCookies:

    @pytest.fixture(autouse=True)
    def _local_env(self, fake_acc_db):
        saved = _save_env()
        os.environ.pop("PRODUCTION", None)
        os.environ.pop("SECRET_KEY", None)
        os.environ["ACCOUNTING_DB_PATH"] = fake_acc_db
        _flush_src_modules()
        yield
        _restore_env(saved)
        _flush_src_modules()
        _reset_core_initialized()

    def _make_app(self):
        from src.app import create_app
        return create_app({
            "TESTING": True,
            "DATABASE_PATH": ":memory:",
            "PROPAGATE_EXCEPTIONS": True,
        })

    def test_session_cookie_secure_is_false_in_local_mode(self):
        """HTTP (non-HTTPS) local logins must not be broken: SECURE must be False."""
        app = self._make_app()
        assert app.config["SESSION_COOKIE_SECURE"] is False, (
            f"Expected SESSION_COOKIE_SECURE=False in local mode, "
            f"got {app.config['SESSION_COOKIE_SECURE']!r}"
        )

    def test_session_cookie_samesite_is_lax(self):
        app = self._make_app()
        assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax", (
            f"Expected SESSION_COOKIE_SAMESITE='Lax', "
            f"got {app.config['SESSION_COOKIE_SAMESITE']!r}"
        )

    def test_session_cookie_httponly_is_true(self):
        app = self._make_app()
        assert app.config["SESSION_COOKIE_HTTPONLY"] is True, (
            f"Expected SESSION_COOKIE_HTTPONLY=True, "
            f"got {app.config['SESSION_COOKIE_HTTPONLY']!r}"
        )

    def test_permanent_session_lifetime_is_8_hours(self):
        from datetime import timedelta
        app = self._make_app()
        lifetime = app.config.get("PERMANENT_SESSION_LIFETIME")
        assert lifetime == timedelta(hours=8), (
            f"Expected PERMANENT_SESSION_LIFETIME=8h, got {lifetime!r}"
        )


# ---------------------------------------------------------------------------
# Scenario (د) — PRODUCTION=1 + strong key
#   → SESSION_COOKIE_SECURE=True
# ---------------------------------------------------------------------------

class TestProductionModeSecureCookie:

    @pytest.fixture(autouse=True)
    def _prod_env(self, fake_acc_db):
        saved = _save_env()
        os.environ["PRODUCTION"] = "1"
        os.environ["SECRET_KEY"] = "ultra-secure-random-key-for-prod-test-xyz123!"
        os.environ["ACCOUNTING_DB_PATH"] = fake_acc_db
        _flush_src_modules()
        yield
        _restore_env(saved)
        _flush_src_modules()
        _reset_core_initialized()

    def _make_app(self):
        from src.app import create_app
        return create_app({
            "TESTING": True,
            "DATABASE_PATH": ":memory:",
            "PROPAGATE_EXCEPTIONS": True,
            "SECRET_KEY": "ultra-secure-random-key-for-prod-test-xyz123!",
            "PRODUCTION": True,
        })

    def test_session_cookie_secure_is_true_in_production(self):
        """In production mode, SESSION_COOKIE_SECURE must be True (HTTPS enforced)."""
        app = self._make_app()
        assert app.config["SESSION_COOKIE_SECURE"] is True, (
            f"Expected SESSION_COOKIE_SECURE=True in production mode, "
            f"got {app.config['SESSION_COOKIE_SECURE']!r}"
        )

    def test_samesite_lax_and_httponly_also_set_in_production(self):
        """Cookie SameSite and HttpOnly must be set regardless of PRODUCTION."""
        app = self._make_app()
        assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
        assert app.config["SESSION_COOKIE_HTTPONLY"] is True


# ---------------------------------------------------------------------------
# Scenario (ه) — Config.DEBUG flag
#   → False when DEBUG env absent; True when DEBUG=1
# ---------------------------------------------------------------------------

class TestDebugFlag:

    def test_debug_is_false_when_env_unset(self):
        """Config.DEBUG must be False when the DEBUG env var is not set."""
        saved = _save_env()
        try:
            os.environ.pop("DEBUG", None)
            _flush_src_modules()

            from src.config.settings import Config
            assert Config.DEBUG is False, (
                f"Expected Config.DEBUG=False when DEBUG env is unset, got {Config.DEBUG!r}"
            )
        finally:
            _restore_env(saved)
            _flush_src_modules()

    def test_debug_is_true_when_env_is_1(self):
        """Config.DEBUG must be True when DEBUG=1 is in the environment."""
        saved = _save_env()
        try:
            os.environ["DEBUG"] = "1"
            _flush_src_modules()

            from src.config.settings import Config
            assert Config.DEBUG is True, (
                f"Expected Config.DEBUG=True when DEBUG=1, got {Config.DEBUG!r}"
            )
        finally:
            _restore_env(saved)
            _flush_src_modules()

    def test_debug_is_true_when_env_is_true_string(self):
        """Config.DEBUG must handle 'true' (case-insensitive)."""
        saved = _save_env()
        try:
            os.environ["DEBUG"] = "true"
            _flush_src_modules()

            from src.config.settings import Config
            assert Config.DEBUG is True, (
                f"Expected Config.DEBUG=True when DEBUG='true', got {Config.DEBUG!r}"
            )
        finally:
            _restore_env(saved)
            _flush_src_modules()

    def test_debug_is_false_for_arbitrary_string(self):
        """Config.DEBUG must be False for an unrecognised string like 'yes_please'."""
        saved = _save_env()
        try:
            os.environ["DEBUG"] = "yes_please"
            _flush_src_modules()

            from src.config.settings import Config
            # _env_flag only accepts '1','true','yes','on' — 'yes_please' is not in the set
            assert Config.DEBUG is False, (
                f"Expected Config.DEBUG=False for DEBUG='yes_please', got {Config.DEBUG!r}"
            )
        finally:
            _restore_env(saved)
            _flush_src_modules()

    def test_production_flag_also_obeys_env_flag_logic(self):
        """Config.PRODUCTION is True for '1' and False when absent."""
        saved = _save_env()
        try:
            os.environ.pop("PRODUCTION", None)
            _flush_src_modules()
            from src.config.settings import Config
            assert Config.PRODUCTION is False

            _restore_env(saved)
            os.environ["PRODUCTION"] = "1"
            _flush_src_modules()
            from src.config.settings import Config as Config2  # re-import after flush
            assert Config2.PRODUCTION is True

        finally:
            _restore_env(saved)
            _flush_src_modules()


# ---------------------------------------------------------------------------
# Scenario (و) — Idempotency: calling create_app twice with :memory: in the
#   same process (distinct apps) — both must produce well-formed apps and
#   neither must raise (regression: _initialized flag must not bleed).
# ---------------------------------------------------------------------------

class TestCreateAppIdempotency:

    def test_two_independent_test_apps_do_not_interfere(self, fake_acc_db):
        """Creating two separate :memory: test apps in sequence must both succeed
        and return distinct Flask app objects (regression guard)."""
        saved = _save_env()
        try:
            os.environ.pop("PRODUCTION", None)
            os.environ.pop("SECRET_KEY", None)
            os.environ["ACCOUNTING_DB_PATH"] = fake_acc_db

            _flush_src_modules()
            from src.app import create_app
            app1 = create_app({
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "PROPAGATE_EXCEPTIONS": True,
            })

            _reset_core_initialized()
            _flush_src_modules()

            from src.app import create_app as create_app2
            app2 = create_app2({
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "PROPAGATE_EXCEPTIONS": True,
            })

            assert app1 is not app2, "Expected two distinct Flask app objects"
            assert app1.config["TESTING"] is True
            assert app2.config["TESTING"] is True

        finally:
            _restore_env(saved)
            _flush_src_modules()
            _reset_core_initialized()
