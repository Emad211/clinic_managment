"""Test settings: in-memory SQLite (fast, CI-independent). Real RLS enforcement
is covered separately by `manage.py verify_rls` against Postgres in CI."""

from .settings import *  # noqa: F401,F403

DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
}
# speed: cheap password hashing in tests
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
