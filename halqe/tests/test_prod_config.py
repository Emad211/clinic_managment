"""
tests/test_prod_config.py — Production config hardening guard tests.

Tests the pure resolver functions in config/env.py directly — no Django
settings reload, no monkeypatching of os.environ needed.

Coverage:
  1. Production + empty SECRET_KEY            → ImproperlyConfigured (fail-fast)
  2. Production + dev-default SECRET_KEY      → ImproperlyConfigured (fail-fast)
  3. Production + valid SECRET_KEY            → accepted
  4. Production → DEBUG is always False
  5. Dev + DEBUG=true env                     → True  (old default preserved)
  6. Dev + DEBUG=false env                    → False
  7. Dev + no DEBUG env                       → True  (old default)
  8. Production + ALLOWED_HOSTS unset         → ImproperlyConfigured
  9. Production + ALLOWED_HOSTS="*"           → ImproperlyConfigured
  10. Production + ALLOWED_HOSTS valid CSV    → list of hosts
  11. Dev ALLOWED_HOSTS                       → ["*"]  (old default)
  12. Dev SECRET_KEY fallback                 → DEV_SECRET_KEY (no raise)
  13. is_production truthy variants           → True
  14. is_production falsy / absent            → False
  15. resolve_cors_origins dev                → localhost origins
  16. resolve_cors_origins production + env   → parsed origins
  17. resolve_cors_origins production no env  → [] (empty, not localhost)
"""
import pytest
from django.core.exceptions import ImproperlyConfigured

from config.env import (
    DEV_SECRET_KEY,
    is_production,
    resolve_secret_key,
    resolve_debug,
    resolve_allowed_hosts,
    resolve_cors_origins,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prod_env(**kwargs) -> dict:
    """Minimal production env with a valid secret key — extend as needed."""
    base = {
        "PRODUCTION": "1",
        "SECRET_KEY": "super-secret-prod-key-32chars-long!!",
        "ALLOWED_HOSTS": "api.halqe.ir",
    }
    base.update(kwargs)
    return base


def _dev_env(**kwargs) -> dict:
    """Dev env — PRODUCTION unset."""
    base = {}
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# 1–3: resolve_secret_key
# ---------------------------------------------------------------------------

class TestResolveSecretKey:

    def test_production_empty_key_raises(self):
        """Production with no SECRET_KEY → fail-fast."""
        with pytest.raises(ImproperlyConfigured, match="SECRET_KEY is not set"):
            resolve_secret_key({"SECRET_KEY": ""}, production=True)

    def test_production_key_absent_raises(self):
        """Production with SECRET_KEY env var completely absent → fail-fast."""
        with pytest.raises(ImproperlyConfigured, match="SECRET_KEY is not set"):
            resolve_secret_key({}, production=True)

    def test_production_dev_default_key_raises(self):
        """Production with dev-placeholder key → fail-fast."""
        with pytest.raises(ImproperlyConfigured, match="dev default"):
            resolve_secret_key({"SECRET_KEY": DEV_SECRET_KEY}, production=True)

    def test_production_valid_key_accepted(self):
        """Production with a proper key → returned as-is."""
        key = "a-real-production-secret-key-abc123xyz"
        result = resolve_secret_key({"SECRET_KEY": key}, production=True)
        assert result == key

    def test_dev_no_key_returns_dev_default(self):
        """Dev with no SECRET_KEY → returns DEV_SECRET_KEY, no exception."""
        result = resolve_secret_key({}, production=False)
        assert result == DEV_SECRET_KEY

    def test_dev_explicit_key_returned(self):
        """Dev can still override SECRET_KEY via env."""
        key = "dev-override-key"
        result = resolve_secret_key({"SECRET_KEY": key}, production=False)
        assert result == key


# ---------------------------------------------------------------------------
# 4–7: resolve_debug
# ---------------------------------------------------------------------------

class TestResolveDebug:

    def test_production_debug_always_false(self):
        """Production: DEBUG is always False — env var cannot override."""
        assert resolve_debug({"DEBUG": "true"}, production=True) is False
        assert resolve_debug({"DEBUG": "1"}, production=True) is False
        assert resolve_debug({"DEBUG": "yes"}, production=True) is False

    def test_dev_debug_default_true(self):
        """Dev with no DEBUG env → True (preserves old default)."""
        assert resolve_debug({}, production=False) is True

    def test_dev_debug_env_true(self):
        """Dev with DEBUG=true → True."""
        assert resolve_debug({"DEBUG": "true"}, production=False) is True

    def test_dev_debug_env_false(self):
        """Dev with DEBUG=false → False (allow explicit override)."""
        assert resolve_debug({"DEBUG": "false"}, production=False) is False


# ---------------------------------------------------------------------------
# 8–11: resolve_allowed_hosts
# ---------------------------------------------------------------------------

class TestResolveAllowedHosts:

    def test_production_no_allowed_hosts_raises(self):
        """Production with empty ALLOWED_HOSTS → fail-fast."""
        with pytest.raises(ImproperlyConfigured, match="ALLOWED_HOSTS is not set"):
            resolve_allowed_hosts({"ALLOWED_HOSTS": ""}, production=True)

    def test_production_allowed_hosts_absent_raises(self):
        """Production with ALLOWED_HOSTS env var absent → fail-fast."""
        with pytest.raises(ImproperlyConfigured, match="ALLOWED_HOSTS is not set"):
            resolve_allowed_hosts({}, production=True)

    def test_production_wildcard_raises(self):
        """Production with ALLOWED_HOSTS=* → fail-fast."""
        with pytest.raises(ImproperlyConfigured, match="wildcard"):
            resolve_allowed_hosts({"ALLOWED_HOSTS": "*"}, production=True)

    def test_production_wildcard_in_csv_raises(self):
        """Production with wildcard mixed into CSV → fail-fast."""
        with pytest.raises(ImproperlyConfigured, match="wildcard"):
            resolve_allowed_hosts(
                {"ALLOWED_HOSTS": "api.halqe.ir,*"}, production=True
            )

    def test_production_valid_hosts_parsed(self):
        """Production with valid CSV hosts → list."""
        result = resolve_allowed_hosts(
            {"ALLOWED_HOSTS": "api.halqe.ir, clinic.halqe.ir"},
            production=True,
        )
        assert result == ["api.halqe.ir", "clinic.halqe.ir"]

    def test_production_single_host(self):
        """Production with a single host (no comma) → single-element list."""
        result = resolve_allowed_hosts(
            {"ALLOWED_HOSTS": "api.halqe.ir"}, production=True
        )
        assert result == ["api.halqe.ir"]

    def test_dev_allowed_hosts_wildcard(self):
        """Dev always returns ['*'] — old default preserved."""
        result = resolve_allowed_hosts({}, production=False)
        assert result == ["*"]


# ---------------------------------------------------------------------------
# 12–14: is_production
# ---------------------------------------------------------------------------

class TestIsProduction:

    @pytest.mark.parametrize("value", ["1", "true", "True", "TRUE", "yes", "on"])
    def test_truthy_values(self, value):
        assert is_production({"PRODUCTION": value}) is True

    @pytest.mark.parametrize("value", ["0", "false", "False", "no", "off", ""])
    def test_falsy_values(self, value):
        assert is_production({"PRODUCTION": value}) is False

    def test_absent(self):
        """PRODUCTION absent → False (dev is the default)."""
        assert is_production({}) is False


# ---------------------------------------------------------------------------
# 15–17: resolve_cors_origins
# ---------------------------------------------------------------------------

class TestResolveCorsOrigins:

    def test_dev_returns_localhost_origins(self):
        """Dev: returns the standard localhost:3000 origins."""
        result = resolve_cors_origins({}, production=False)
        assert "http://localhost:3000" in result
        assert "http://127.0.0.1:3000" in result

    def test_production_with_env_parsed(self):
        """Production with CORS_ALLOWED_ORIGINS env → parsed list."""
        result = resolve_cors_origins(
            {"CORS_ALLOWED_ORIGINS": "https://app.halqe.ir,https://clinic.halqe.ir"},
            production=True,
        )
        assert result == ["https://app.halqe.ir", "https://clinic.halqe.ir"]

    def test_production_no_env_returns_empty(self):
        """Production with no CORS_ALLOWED_ORIGINS → [] (not localhost defaults)."""
        result = resolve_cors_origins({}, production=True)
        assert result == []
        # Critical: localhost origins must NOT leak into production
        assert "http://localhost:3000" not in result
