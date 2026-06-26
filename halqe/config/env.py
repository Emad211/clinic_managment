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

GUC / pooling guard (ADR-0008):
  resolve_conn_max_age() — enforces the session-level GUC contract.
  CONN_MAX_AGE must remain 0 (one fresh connection per request) until
  the operator explicitly acknowledges session-mode-only pooling via
  TENANT_GUC_POOLING_ACK=session-mode-only.

  If PRODUCTION=1 and CONN_MAX_AGE > 0 without the ACK env var,
  the server refuses to start with ImproperlyConfigured pointing to ADR-0008.
  This turns a silent foot-gun (persistent connection carrying a stale GUC
  into the next request) into a deliberate, documented decision.
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


# ---------------------------------------------------------------------------
# GUC / pooling invariant (ADR-0008)
# ---------------------------------------------------------------------------

#: The acknowledgement token an operator must set to allow CONN_MAX_AGE > 0.
#: Must equal exactly this string (case-sensitive) to be accepted.
TENANT_GUC_POOLING_ACK_VALUE = "session-mode-only"


def resolve_conn_max_age(environ: dict, production: bool) -> int:
    """
    Return the CONN_MAX_AGE value for Django DATABASES.

    Invariant (ADR-0008):
      halqe uses session-scoped GUC set_config('app.current_tenant', id, false)
      for RLS.  With CONN_MAX_AGE=0 (Django default) each request gets a brand-
      new connection; the GUC dies when the connection closes, so no cross-request
      leak is possible.

      With CONN_MAX_AGE > 0 (persistent / pooled connection), the GUC survives
      across requests on the same thread.  TenantGucMiddleware clears it at
      request start, but:
        - transaction-mode poolers (PgBouncer transaction mode) reset the
          connection mid-flight, so clear() in middleware has no effect.
        - Even session-mode poolers require careful validation.

      Therefore:
        Dev / CI (PRODUCTION unset): always 0.  Tests run clean.
        Production + CONN_MAX_AGE=0 (default): always allowed.
        Production + CONN_MAX_AGE > 0 + ACK present: allowed (operator
          has acknowledged the session-mode-only contract from ADR-0008).
        Production + CONN_MAX_AGE > 0 + NO ACK: fail-fast with a message
          that points to ADR-0008 and the required acknowledgement.

    Usage in settings.py:
        CONN_MAX_AGE = resolve_conn_max_age(os.environ, _production)
        # Then set it on both DATABASES entries via the helper below.

    Changing this value requires reading ADR-0008 and understanding the
    transaction-pooler constraint.
    """
    if not production:
        # Dev/CI: always fresh connection — no risk, no config.
        return 0

    raw = environ.get("CONN_MAX_AGE", "0").strip()
    try:
        value = int(raw)
    except ValueError:
        raise ImproperlyConfigured(
            f"CONN_MAX_AGE must be an integer, got '{raw}'."
        )

    if value == 0:
        # The invariant: zero is always safe, no ACK required.
        return 0

    # value > 0: persistent connection requested — require explicit ACK.
    ack = environ.get("TENANT_GUC_POOLING_ACK", "").strip()
    if ack != TENANT_GUC_POOLING_ACK_VALUE:
        raise ImproperlyConfigured(
            f"PRODUCTION is enabled and CONN_MAX_AGE={value} (persistent "
            f"connection), but TENANT_GUC_POOLING_ACK is not set to "
            f"'{TENANT_GUC_POOLING_ACK_VALUE}'. "
            f"halqe uses session-scoped GUC set_config('app.current_tenant', "
            f"id, false) for RLS tenant isolation. With a persistent connection "
            f"(CONN_MAX_AGE > 0), a stale tenant GUC can leak into the next "
            f"request on the same thread if the middleware clear() is bypassed "
            f"(e.g. transaction-mode pooler). "
            f"Before enabling persistent connections you MUST: "
            f"(1) confirm the pooler operates in SESSION mode (not transaction "
            f"mode) — see ADR-0008 (halqe/docs/adr/0008-...); "
            f"(2) set TENANT_GUC_POOLING_ACK=session-mode-only in the "
            f"environment to acknowledge this contract. "
            f"If you need transaction-mode pooling (PgBouncer transaction mode "
            f"or Supavisor), you must first migrate to SET LOCAL + "
            f"ATOMIC_REQUESTS=True — see ADR-0008 §seam for the migration path."
        )

    # ACK is present and valid: operator has acknowledged session-mode-only.
    return value
