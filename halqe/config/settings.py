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
# ---------------------------------------------------------------------------
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "halqe-dev-secret-not-for-production")

DEBUG = os.environ.get("DEBUG", "true").lower() == "true"

ALLOWED_HOSTS = ["*"]

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
    # TenantGucMiddleware MUST come first: clears app.current_tenant GUC to ''
    # at the start of every request.  JWTBearer.authenticate() re-sets it to
    # the real tenant_id for authenticated requests.  Order matters: clearing
    # before CommonMiddleware ensures even CORS/security middleware runs with
    # a clean GUC state.  (Step 2 — RLS hook; RLS policy is Step 19.)
    "platform_core.middleware.TenantGucMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

# ---------------------------------------------------------------------------
# CORS — dev only: allow Next.js dev server on localhost:3000
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
CORS_ALLOW_CREDENTIALS = False

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
