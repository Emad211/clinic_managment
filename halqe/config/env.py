"""
config/env.py — Pure environment resolution functions for halqe settings.

Design: each function takes an explicit `environ` dict and a `production` bool.
This makes them trivially unit-testable without monkeypatching os.environ or
reloading Django settings (which is only loaded once per process).

Pattern mirrors specialist_clinic/src/config/settings.py:
  - _env_flag('PRODUCTION') gates all hardening
  - DEFAULT_SECRET_KEY constant for comparison
  - fail-fast via Django's ImproperlyConfigured (not a plain RuntimeError)

Only production=True activates the guards; dev/CI/test runs (PRODUCTION unset)
keep exactly the old permissive defaults so no existing test breaks.
"""
from django.core.exceptions import ImproperlyConfigured

# The dev placeholder — any production deploy that still has this value is
# a misconfigured deploy. Mirrors the specialist_clinic DEFAULT_SECRET_KEY pattern.
DEV_SECRET_KEY = "halqe-dev-secret-not-for-production"


def _env_flag(environ: dict, name: str) -> bool:
    """Return True when the env var is one of the truthy string values."""
    return environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def is_production(environ: dict) -> bool:
    """
    True when PRODUCTION=1/true/yes/on is set in the environment.

    This is the single gate for all production hardening. CI and dev never
    set PRODUCTION so all guards remain inactive in those environments.
    Mirrors specialist_clinic Config.PRODUCTION = _env_flag('PRODUCTION').
    """
    return _env_flag(environ, "PRODUCTION")


def resolve_secret_key(environ: dict, production: bool) -> str:
    """
    Return the SECRET_KEY to use.

    Dev: fall back to DEV_SECRET_KEY if SECRET_KEY is absent — preserves
         existing behavior.
    Production: SECRET_KEY MUST be present and MUST NOT equal the dev default.
                Raises ImproperlyConfigured (fail-fast) on either violation.
    """
    key = environ.get("SECRET_KEY", "").strip()
    if production:
        if not key:
            raise ImproperlyConfigured(
                "PRODUCTION is enabled but SECRET_KEY is not set. "
                "Set a strong, unique SECRET_KEY before starting the server."
            )
        if key == DEV_SECRET_KEY:
            raise ImproperlyConfigured(
                "PRODUCTION is enabled but SECRET_KEY is still the dev default. "
                "Generate a unique secret key and set it in SECRET_KEY."
            )
        return key
    # Dev/CI: use env value if provided, fall back to the dev placeholder
    return key or DEV_SECRET_KEY


def resolve_debug(environ: dict, production: bool) -> bool:
    """
    Return the DEBUG flag.

    Dev: honour the DEBUG env var (default 'true' — preserves existing behaviour).
    Production: always False regardless of what DEBUG env var says.
                A misconfigured deploy cannot accidentally enable DEBUG.
    """
    if production:
        return False
    return environ.get("DEBUG", "true").lower() == "true"


def resolve_allowed_hosts(environ: dict, production: bool) -> list:
    """
    Return the ALLOWED_HOSTS list.

    Dev: ["*"] — preserves existing behaviour.
    Production: parse ALLOWED_HOSTS env var as CSV. Wildcards ("*") are rejected
                with ImproperlyConfigured.  Empty value → fail-fast so the deploy
                doesn't silently serve with a broken host check.

    Example production value: "api.halqe.ir,clinic.halqe.ir"
    """
    if not production:
        return ["*"]

    raw = environ.get("ALLOWED_HOSTS", "").strip()
    if not raw:
        raise ImproperlyConfigured(
            "PRODUCTION is enabled but ALLOWED_HOSTS is not set. "
            "Provide a comma-separated list of allowed host names "
            "(e.g. ALLOWED_HOSTS=api.halqe.ir,clinic.halqe.ir)."
        )
    hosts = [h.strip() for h in raw.split(",") if h.strip()]
    if "*" in hosts:
        raise ImproperlyConfigured(
            "PRODUCTION is enabled but ALLOWED_HOSTS contains '*' (wildcard). "
            "Specify exact host names instead."
        )
    return hosts


def resolve_cors_origins(environ: dict, production: bool) -> list:
    """
    Return CORS_ALLOWED_ORIGINS.

    Dev: localhost:3000 — preserves existing behaviour.
    Production: parse CORS_ALLOWED_ORIGINS env var as CSV.
                If unset in production, returns [] (no CORS origins allowed)
                rather than leaking the localhost dev origins into production.
    """
    if not production:
        return [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    raw = environ.get("CORS_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return []
    return [o.strip() for o in raw.split(",") if o.strip()]
