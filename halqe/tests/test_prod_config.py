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

  GUC / pooling guard (ADR-0008) — resolve_conn_max_age():
  18. Dev → always 0 regardless of CONN_MAX_AGE env         → 0
  19. Production + CONN_MAX_AGE=0                           → 0  (safe, no ACK needed)
  20. Production + CONN_MAX_AGE absent                      → 0  (default safe)
  21. Production + CONN_MAX_AGE>0, no ACK                   → ImproperlyConfigured
  22. Production + CONN_MAX_AGE>0, wrong ACK                → ImproperlyConfigured
  23. Production + CONN_MAX_AGE>0, correct ACK              → value returned
  24. Production + CONN_MAX_AGE invalid (non-int)           → ImproperlyConfigured
  25. CONN_MAX_AGE=0 in live settings                       → structural invariant
"""
import pytest
from django.core.exceptions import ImproperlyConfigured

from config.env import (
    DEV_SECRET_KEY,
    TENANT_GUC_POOLING_ACK_VALUE,
    is_production,
    resolve_secret_key,
    resolve_debug,
    resolve_allowed_hosts,
    resolve_cors_origins,
    resolve_conn_max_age,
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


# ---------------------------------------------------------------------------
# 18–25: resolve_conn_max_age  (ADR-0008 GUC / pooling guard)
# ---------------------------------------------------------------------------

class TestResolveConnMaxAge:

    def _prod_env_base(self, **kwargs) -> dict:
        """Minimal valid production env — extend as needed."""
        base = {
            "PRODUCTION": "1",
            "SECRET_KEY": "super-secret-prod-key-32chars-long!!",
            "ALLOWED_HOSTS": "api.halqe.ir",
        }
        base.update(kwargs)
        return base

    # 18 — dev always 0
    def test_dev_always_returns_zero(self):
        """Dev: CONN_MAX_AGE is always 0 regardless of env var."""
        assert resolve_conn_max_age({"CONN_MAX_AGE": "60"}, production=False) == 0
        assert resolve_conn_max_age({"CONN_MAX_AGE": "300"}, production=False) == 0
        assert resolve_conn_max_age({}, production=False) == 0

    # 19 — production + CONN_MAX_AGE=0 → safe, no ACK
    def test_production_zero_is_always_allowed(self):
        """Production + CONN_MAX_AGE=0 → 0, no ACK required."""
        result = resolve_conn_max_age({"CONN_MAX_AGE": "0"}, production=True)
        assert result == 0

    # 20 — production + absent CONN_MAX_AGE → default 0
    def test_production_absent_defaults_to_zero(self):
        """Production + CONN_MAX_AGE absent → 0 (safe default)."""
        result = resolve_conn_max_age({}, production=True)
        assert result == 0

    # 21 — production + CONN_MAX_AGE>0, no ACK → fail-fast
    def test_production_persistent_without_ack_raises(self):
        """Production + CONN_MAX_AGE>0 + no ACK → ImproperlyConfigured."""
        with pytest.raises(ImproperlyConfigured, match="TENANT_GUC_POOLING_ACK"):
            resolve_conn_max_age({"CONN_MAX_AGE": "60"}, production=True)

    def test_production_persistent_without_ack_message_mentions_adr(self):
        """Error message must reference ADR-0008 and session-mode-only."""
        with pytest.raises(ImproperlyConfigured, match="ADR-0008"):
            resolve_conn_max_age({"CONN_MAX_AGE": "300"}, production=True)

    def test_production_persistent_without_ack_message_mentions_session_mode(self):
        """Error message must mention session mode to guide the operator."""
        with pytest.raises(ImproperlyConfigured, match="session.mode"):
            resolve_conn_max_age({"CONN_MAX_AGE": "60"}, production=True)

    # 22 — production + CONN_MAX_AGE>0, wrong ACK → fail-fast
    def test_production_persistent_wrong_ack_raises(self):
        """Production + CONN_MAX_AGE>0 + wrong ACK value → ImproperlyConfigured."""
        with pytest.raises(ImproperlyConfigured, match="TENANT_GUC_POOLING_ACK"):
            resolve_conn_max_age(
                {
                    "CONN_MAX_AGE": "60",
                    "TENANT_GUC_POOLING_ACK": "yes-i-know",
                },
                production=True,
            )

    def test_production_persistent_empty_ack_raises(self):
        """Production + CONN_MAX_AGE>0 + empty ACK string → ImproperlyConfigured."""
        with pytest.raises(ImproperlyConfigured):
            resolve_conn_max_age(
                {"CONN_MAX_AGE": "60", "TENANT_GUC_POOLING_ACK": ""},
                production=True,
            )

    # 23 — production + CONN_MAX_AGE>0, correct ACK → value returned
    def test_production_persistent_with_correct_ack_accepted(self):
        """Production + CONN_MAX_AGE>0 + correct ACK → value returned (no raise)."""
        result = resolve_conn_max_age(
            {
                "CONN_MAX_AGE": "60",
                "TENANT_GUC_POOLING_ACK": TENANT_GUC_POOLING_ACK_VALUE,
            },
            production=True,
        )
        assert result == 60

    def test_production_persistent_with_correct_ack_large_value(self):
        """ACK allows any positive CONN_MAX_AGE value."""
        result = resolve_conn_max_age(
            {
                "CONN_MAX_AGE": "3600",
                "TENANT_GUC_POOLING_ACK": TENANT_GUC_POOLING_ACK_VALUE,
            },
            production=True,
        )
        assert result == 3600

    # 24 — production + CONN_MAX_AGE non-int → fail-fast
    def test_production_non_integer_conn_max_age_raises(self):
        """Production + CONN_MAX_AGE='abc' → ImproperlyConfigured."""
        with pytest.raises(ImproperlyConfigured, match="integer"):
            resolve_conn_max_age({"CONN_MAX_AGE": "abc"}, production=True)

    def test_production_float_conn_max_age_raises(self):
        """Production + CONN_MAX_AGE='1.5' → ImproperlyConfigured (not int)."""
        with pytest.raises(ImproperlyConfigured, match="integer"):
            resolve_conn_max_age({"CONN_MAX_AGE": "1.5"}, production=True)

    # 25 — structural invariant: live settings have CONN_MAX_AGE=0
    def test_live_settings_conn_max_age_is_zero(self):
        """
        Structural guard: the live Django settings must have CONN_MAX_AGE=0
        on both DB connections.

        This ensures the test environment itself (and any staging deploy that
        runs this suite) conforms to the ADR-0008 invariant.  If a CI
        environment accidentally sets CONN_MAX_AGE>0, this catches it.
        """
        from django.conf import settings

        default_cma = settings.DATABASES["default"].get("CONN_MAX_AGE", 0)
        assert default_cma == 0, (
            f"DATABASES['default']['CONN_MAX_AGE'] must be 0, got {default_cma}. "
            f"See ADR-0008."
        )
        ar_cma = settings.DATABASES["accounting_read"].get("CONN_MAX_AGE", 0)
        assert ar_cma == 0, (
            f"DATABASES['accounting_read']['CONN_MAX_AGE'] must be 0, "
            f"got {ar_cma}. See ADR-0008."
        )

    def test_ack_constant_value_is_session_mode_only(self):
        """
        The ACK string must be exactly 'session-mode-only'.
        Changing it would invalidate any existing operator documentation
        and ADR-0008 references.
        """
        assert TENANT_GUC_POOLING_ACK_VALUE == "session-mode-only", (
            "TENANT_GUC_POOLING_ACK_VALUE changed — update ADR-0008 and "
            "all operator documentation if this is intentional."
        )


# ---------------------------------------------------------------------------
# clinical.E001 — SMS go-live config boot check (step 76)
# ---------------------------------------------------------------------------
class TestSmsLiveConfigCheck:
    """
    The boot invariant: in PRODUCTION, SMS_LIVE_ENABLED on + KAVENEGAR_API_KEY
    empty → Error (real SMS would silently fall back to NullProvider). Tests the
    pure helper with synthetic env dicts (no os.environ monkeypatching).
    """

    def _errs(self, **env):
        from clinical.apps import _sms_live_config_errors
        return _sms_live_config_errors(env)

    def test_prod_live_without_key_errors(self):
        errs = self._errs(PRODUCTION="1", SMS_LIVE_ENABLED="1")
        assert len(errs) == 1, errs
        assert errs[0].id == "clinical.E001"

    def test_prod_live_with_key_ok(self):
        assert self._errs(
            PRODUCTION="1", SMS_LIVE_ENABLED="1", KAVENEGAR_API_KEY="real-key"
        ) == []

    def test_prod_live_blank_key_errors(self):
        # whitespace-only key counts as empty
        errs = self._errs(PRODUCTION="1", SMS_LIVE_ENABLED="1", KAVENEGAR_API_KEY="   ")
        assert len(errs) == 1 and errs[0].id == "clinical.E001"

    def test_prod_not_live_ok(self):
        assert self._errs(PRODUCTION="1", SMS_LIVE_ENABLED="0") == []

    def test_dev_live_without_key_ok(self):
        # dev/CI may set SMS_LIVE_ENABLED without a key to exercise the path —
        # the check is production-gated, so no boot error in dev.
        assert self._errs(SMS_LIVE_ENABLED="1") == []

    def test_empty_env_ok(self):
        assert self._errs() == []
