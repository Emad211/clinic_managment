"""
Django settings for halqe platform — vertical slice 1.

managed=False throughout: the .sql slices are the authoritative schema source.
apply_schema management command applies them.
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
    "platform_core",
    "accounting",
    "clinical",
    "accounting_port",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = []

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Databases
# 'default' → clinical/platform (read-write for clinical_app).
# 'accounting_read' → accounting read-only boundary
#   Both connect as superuser for now; OPTIONS sets the search_path so models
#   with schema-qualified db_table work without extra search_path tricks.
#   The role enforcement is at DB-level (GRANTs in slice0/slice3).
# ---------------------------------------------------------------------------
_PG_HOST = os.environ.get("PG_HOST", "localhost")
_PG_PORT = os.environ.get("PG_PORT", "55432")
_PG_USER = os.environ.get("PG_USER", "postgres")
_PG_PASSWORD = os.environ.get("PG_PASSWORD", "validate_only")
_PG_DB = os.environ.get("PG_DB", "halqe_app")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _PG_DB,
        "USER": _PG_USER,
        "PASSWORD": _PG_PASSWORD,
        "HOST": _PG_HOST,
        "PORT": _PG_PORT,
        "OPTIONS": {
            # platform_app: رولِ یکپارچهٔ اپِ پلتفرم — می‌نویسد روی platform+clinical،
            # فقط می‌خواند از accounting (مرزِ یک‌طرفهٔ DB-level).
            "options": "-c search_path=clinical,platform,accounting,public",
        },
        "TEST": {
            "NAME": os.environ.get("PG_TEST_DB", "halqe_app_test"),
        },
    },
    "accounting_read": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _PG_DB,
        "USER": _PG_USER,
        "PASSWORD": _PG_PASSWORD,
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
