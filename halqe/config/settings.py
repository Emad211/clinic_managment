"""
Django settings for halqe platform — vertical slice 1.

managed=False throughout: the .sql slices are the authoritative schema source.
apply_schema management command applies them.

# ---------------------------------------------------------------------------
# Role separation — two sets of credentials:
#
#   SUPERUSER (PG_USER / PG_PASSWORD):
#     Default: postgres / validate_only (Docker dev)
#     Used ONLY by:
#       - apply_schema management command (DDL, GRANT, CREATE/DROP DATABASE)
#       - conftest.py DDL/seed fixtures (psycopg raw, not Django ORM)
#       - seed_demo management command for the accounting.patients seed path
#         (dev tooling; the app role cannot write accounting)
#     NOT used by the Django app connections.
#
#   APP ROLE (PG_APP_USER / PG_APP_PASSWORD):
#     Default: platform_login_test / test_pw  (matches the role conftest creates)
#     A LOGIN role that is a MEMBER of platform_app (inherits all its grants):
#       - WRITE on platform.* + clinical.*
#       - SELECT-only on accounting.*  (the hard DB-level boundary)
#     Used by Django's 'default' and 'accounting_read' connections.
#     Create this role idempotently with:
#       python manage.py ensure_app_role
#     or via apply_schema --create-login-role <name> --role-password <pw>
#
# ---------------------------------------------------------------------------
# Production hardening — gated by PRODUCTION=1 env var:
#
#   When PRODUCTION=1 is set the server refuses to start unless:
#     - SECRET_KEY is non-empty and not the dev placeholder  → fail-fast
#     - DEBUG is forced to False regardless of the DEBUG env var
#     - ALLOWED_HOSTS is explicit (no wildcard allowed)       → fail-fast
#     - CORS_ALLOWED_ORIGINS comes from env, not localhost defaults
#
#   Dev / CI / tests: PRODUCTION is unset → permissive defaults unchanged.
#   Resolution logic lives in config/env.py (pure functions, unit-testable).
# ---------------------------------------------------------------------------
"""
import os
from pathlib import Path

# env.py must be imported AFTER Django internals are importable. It is imported
# here at module load time because settings.py is only loaded once per process.
from config.env import is_production, resolve_secret_key, resolve_debug, \
    resolve_allowed_hosts, resolve_cors_origins, resolve_conn_max_age

BASE_DIR = Path(__file__).resolve().parent.parent

# Resolve all environment-gated settings via pure functions from config/env.py
_env = os.environ
_production = is_production(_env)

SECRET_KEY = resolve_secret_key(_env, _production)

DEBUG = resolve_debug(_env, _production)

ALLOWED_HOSTS = resolve_allowed_hosts(_env, _production)

# Expose the flag so middleware/views can inspect it if needed (read-only).
PRODUCTION = _production

INSTALLED_APPS = [
    # No django.contrib.admin — minimal vertical slice
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "corsheaders",
    "platform_core",
    "accounting",
    "clinical",
    "accounting_port",
]

MIDDLEWARE = [
    # RequestIdMiddleware MUST come first (before TenantGucMiddleware) so that
    # every log line — including those from TenantGucMiddleware itself — carries
    # a request_id tag.  It sets the contextvar consumed by RequestIdFilter.
    "platform_core.request_id.RequestIdMiddleware",
    # TenantGucMiddleware clears app.current_tenant GUC to '' at the start of
    # every request.  JWTBearer.authenticate() re-sets it to the real tenant_id
    # for authenticated requests.  Order matters: clearing before CommonMiddleware
    # ensures even CORS/security middleware runs with a clean GUC state.
    # (Step 2 — RLS hook; RLS policy is Step 19.)
    "platform_core.middleware.TenantGucMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

# ---------------------------------------------------------------------------
# CORS — dev: localhost:3000; production: from CORS_ALLOWED_ORIGINS env var
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = resolve_cors_origins(_env, _production)
CORS_ALLOW_CREDENTIALS = False

# ---------------------------------------------------------------------------
# GUC / pooling invariant (ADR-0008)
# ---------------------------------------------------------------------------
# CONN_MAX_AGE must stay 0: each request opens a fresh connection, the GUC
# (app.current_tenant) dies with it, and no cross-request tenant leak is
# possible.  Changing this requires an explicit ACK (TENANT_GUC_POOLING_ACK
# =session-mode-only) and understanding the session-mode-only contract.
# See specialist_clinic/docs/adr/0008-tenant-guc-lifecycle-and-pooling.md
# ---------------------------------------------------------------------------
_CONN_MAX_AGE = resolve_conn_max_age(_env, _production)
# Expose as a module-level constant so tests can assert on it.
CONN_MAX_AGE = _CONN_MAX_AGE

ROOT_URLCONF = "config.urls"

TEMPLATES = []

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Postgres coordinates
# ---------------------------------------------------------------------------
_PG_HOST = os.environ.get("PG_HOST", "localhost")
_PG_PORT = os.environ.get("PG_PORT", "55432")
_PG_DB   = os.environ.get("PG_DB", "halqe_app")

# Superuser credentials — only for apply_schema, conftest DDL, seed_demo's
# accounting write path.  Never used by the Django app connections below.
PG_SUPERUSER      = os.environ.get("PG_USER", "postgres")
PG_SUPERPASSWORD  = os.environ.get("PG_PASSWORD", "validate_only")

# App-role credentials — least-privilege LOGIN role, member of platform_app.
# The role has WRITE on platform+clinical and SELECT-only on accounting.
# Create idempotently with: python manage.py ensure_app_role
# Default matches the role conftest creates for Docker validation.
_PG_APP_USER     = os.environ.get("PG_APP_USER", "platform_login_test")
_PG_APP_PASSWORD = os.environ.get("PG_APP_PASSWORD", "test_pw")

# ---------------------------------------------------------------------------
# Databases
# 'default'         → clinical/platform read-write  (app role, platform_app)
# 'accounting_read' → accounting SELECT-only        (app role, platform_app)
#
# Both use the LEAST-PRIVILEGE app role.  The role physically cannot write to
# accounting.* — enforced by Postgres GRANTs, not only by ClinicalRouter.
# search_path is set in OPTIONS so schema-qualified db_table names resolve
# without extra tricks.
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _PG_DB,
        "USER": _PG_APP_USER,
        "PASSWORD": _PG_APP_PASSWORD,
        "HOST": _PG_HOST,
        "PORT": _PG_PORT,
        # CONN_MAX_AGE invariant (ADR-0008):
        # 0 → each request opens a fresh connection; GUC dies with it.
        # Changing requires resolve_conn_max_age() ACK + reading ADR-0008.
        "CONN_MAX_AGE": _CONN_MAX_AGE,
        "OPTIONS": {
            # platform_app: می‌نویسد روی platform+clinical، فقط می‌خواند از accounting
            "options": "-c search_path=clinical,platform,accounting,public",
        },
        "TEST": {
            "NAME": os.environ.get("PG_TEST_DB", "halqe_app_test"),
        },
    },
    "accounting_read": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _PG_DB,
        "USER": _PG_APP_USER,
        "PASSWORD": _PG_APP_PASSWORD,
        "HOST": _PG_HOST,
        "PORT": _PG_PORT,
        # Same CONN_MAX_AGE invariant — accounting_read is also session-GUC-scoped.
        "CONN_MAX_AGE": _CONN_MAX_AGE,
        "OPTIONS": {
            "options": "-c search_path=accounting,platform,public",
        },
        "TEST": {
            "NAME": os.environ.get("PG_TEST_DB", "halqe_app_test"),
        },
    },
}

DATABASE_ROUTERS = ["config.routers.ClinicalRouter"]

# ---------------------------------------------------------------------------
# Internationalization — Iran/Jalali context
# ---------------------------------------------------------------------------
USE_TZ = True
TIME_ZONE = "Asia/Tehran"
LANGUAGE_CODE = "fa"
USE_I18N = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Schema slice directory — used by apply_schema management command.
# Points to specialist_clinic/docs/migration_tools/ relative to BASE_DIR.
# Override with env var SCHEMA_SLICE_DIR for different layouts.
# ---------------------------------------------------------------------------
SCHEMA_SLICE_DIR = os.environ.get(
    "SCHEMA_SLICE_DIR",
    str(BASE_DIR.parent / "specialist_clinic" / "docs" / "migration_tools"),
)

# ---------------------------------------------------------------------------
# Structured logging (Step 28 — observability)
# ---------------------------------------------------------------------------
# Two modes gated by PRODUCTION:
#
#   Dev  (PRODUCTION unset): human-readable format with timestamp + level +
#        logger name + request_id + message.  Coloured if colorlog is installed,
#        plain text otherwise.  DEBUG level so nothing is hidden in dev.
#
#   Production (PRODUCTION=1): JSON-like key=value format on a single line,
#        machine-parseable by log aggregators (Loki, ELK, CloudWatch).
#        Level INFO+ (DEBUG suppressed in production).
#
# RequestIdFilter reads the contextvar set by RequestIdMiddleware and injects
# request_id into every LogRecord.  If the contextvar is empty (management
# commands, background threads) request_id defaults to '-'.
#
# PII-free contract (enforced at caller level — logging must never receive):
#   - request/response bodies
#   - national_id, password, token values
#   - Any field whose name ends in _hash or _token
# ---------------------------------------------------------------------------

_LOG_LEVEL = "DEBUG" if not _production else "INFO"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,

    # ── Filters ──────────────────────────────────────────────────────────────
    "filters": {
        "request_id": {
            "()": "platform_core.request_id.RequestIdFilter",
        },
    },

    # ── Formatters ───────────────────────────────────────────────────────────
    "formatters": {
        # Human-readable for dev: timestamp | level | logger | [req-id] message
        "dev": {
            "format": (
                "%(asctime)s | %(levelname)-8s | %(name)s | "
                "[%(request_id)s] %(message)s"
            ),
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        # Structured key=value for production — one line per record,
        # machine-parseable, no embedded newlines in the message itself.
        "structured": {
            "format": (
                "time=%(asctime)s level=%(levelname)s logger=%(name)s "
                "request_id=%(request_id)s message=%(message)s"
            ),
            "datefmt": "%Y-%m-%dT%H:%M:%S%z",
        },
    },

    # ── Handlers ─────────────────────────────────────────────────────────────
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["request_id"],
            "formatter": "structured" if _production else "dev",
        },
    },

    # ── Loggers ──────────────────────────────────────────────────────────────
    "loggers": {
        # Halqe platform loggers — full verbosity in dev, INFO+ in production
        "platform_core": {
            "handlers": ["console"],
            "level": _LOG_LEVEL,
            "propagate": False,
        },
        "clinical": {
            "handlers": ["console"],
            "level": _LOG_LEVEL,
            "propagate": False,
        },
        "accounting_port": {
            "handlers": ["console"],
            "level": _LOG_LEVEL,
            "propagate": False,
        },
        "config": {
            "handlers": ["console"],
            "level": _LOG_LEVEL,
            "propagate": False,
        },
    },

    # Root logger: WARNING+ for third-party noise, handled by console
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
}
