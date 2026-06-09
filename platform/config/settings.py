"""Django settings for the cloud SaaS platform (docs/TECH_STACK.md).

Target stack: Django + django-ninja + PostgreSQL (pgvector later) + RLS
multi-tenancy. This is the Evolve-not-Rewrite destination for the two Flask
apps; it does NOT touch them — they keep running on 8080/8090.
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(key, default=False):
    return os.getenv(key, str(default)).lower() in {"1", "true", "yes", "on"}


DEBUG = _env_bool("DJANGO_DEBUG", True)

# SECRET_KEY: no usable insecure default in production. With DEBUG off, a missing
# or known/weak key is a HARD error — a public key lets an attacker forge signed
# session cookies, and on this RLS app a forged session carries a forged clinic_id
# that TenantMiddleware would trust, crossing tenant isolation. (security audit)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
_WEAK_SECRETS = {"", "build-time", "change-me-in-production", "ci-only-secret"}
if not DEBUG and (SECRET_KEY in _WEAK_SECRETS or SECRET_KEY.startswith("dev-")):
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set to a strong value when DEBUG=False."
    )
if not SECRET_KEY:
    SECRET_KEY = "dev-only-insecure-change-me"  # dev/test convenience only

ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # platform modules (modular monolith)
    "apps.common",
    "apps.identity",
    "apps.billing",
    "apps.patients",
    "apps.chronic",
    "apps.rx",
    "apps.accounting",
    "apps.messaging",
    "apps.web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # serve static in the container
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Tenant isolation (RLS): MUST run after auth so the user/clinic is known.
    "apps.common.middleware.TenantMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.web.context_processors.current_app_user",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# PostgreSQL by default (the locked target). dj-database-url lets a single
# DATABASE_URL env var drive it; falls back to a local postgres DSN.
#
# CRITICAL (proven by manage.py verify_rls): the RUNTIME DATABASE_URL must use a
# NON-superuser, NOBYPASSRLS role, or RLS is silently bypassed and tenants leak.
# Migrations + global seeding need a privileged role instead — the entrypoint
# runs those with the admin URL, then starts the app with the unprivileged one.
DATABASES = {
    "default": dj_database_url.config(
        default=os.getenv(
            "DATABASE_URL",
            "postgres://postgres:postgres@127.0.0.1:5432/clinic_platform",
        ),
        conn_max_age=600,
    )
}

# Atomic requests so SET LOCAL app.current_clinic (TenantMiddleware) holds for
# the whole request transaction.
DATABASES["default"]["ATOMIC_REQUESTS"] = True

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

# RTL / Jalali product: store UTC, render Tehran + Jalali in the app layer.
LANGUAGE_CODE = "fa-ir"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── production hardening (active when DEBUG is off) ──
CSRF_TRUSTED_ORIGINS = [
    o for o in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o
]
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # behind TLS proxy
    # secure transport ON by default in prod (proxy header set below avoids loops)
    SECURE_SSL_REDIRECT = _env_bool("DJANGO_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_HSTS_SECONDS", "31536000") or 0)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
