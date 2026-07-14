import os

from django.apps import AppConfig
from django.core.checks import Error, register


class ClinicalConfig(AppConfig):
    name = "clinical"
    label = "clinical"
    default_auto_field = "django.db.models.BigAutoField"

    def import_models(self):
        """Load the split structured-record model module during registry phase 2."""
        super().import_models()
        # Defining managed=False models in a focused module keeps models.py from
        # becoming another god file. Importing here is earlier/safer than ready().
        from clinical import record_models  # noqa: F401

    def ready(self):
        # Boot invariant (step 76): fail-closed SMS go-live config check.
        register(_check_sms_live_config)


# ---------------------------------------------------------------------------
# clinical.E001 — SMS go-live config check (boot invariant, step 76)
# ---------------------------------------------------------------------------
# In PRODUCTION, if SMS_LIVE_ENABLED is on but KAVENEGAR_API_KEY is empty,
# get_provider() (clinical/sms/provider.py) silently falls back to NullProvider:
# the operator THINKS real SMS is live, but every message is simulated and nobody
# notices. This surfaces that real, silent misconfiguration at boot instead.
#
# Why ONLY this check (and not "consent/sanitize active"): the consent gate and
# the clinical-content (PHI) block are UNCONDITIONAL code in the send path, so
# asserting they are "active" is tautological — a regression test covers that.
# Adding a setting to toggle them off would itself be a foot-gun. So the only
# valuable, non-tautological invariant is this env-vs-env coherence check.
#
# Production-gated: dev/CI may set SMS_LIVE_ENABLED without a key to exercise the
# path, so this errors ONLY under PRODUCTION. Reads os.environ directly (same
# contract as config/env.py resolvers).


def _sms_live_config_errors(env) -> list:
    """Pure helper (testable with a synthetic env dict): the clinical.E001 errors."""
    from config.env import is_production, resolve_sms_live_enabled

    errors = []
    if is_production(env) and resolve_sms_live_enabled(env):
        if not (env.get("KAVENEGAR_API_KEY") or "").strip():
            errors.append(Error(
                "SMS_LIVE_ENABLED is on in production but KAVENEGAR_API_KEY is empty "
                "— real SMS would silently fall back to NullProvider (simulation). "
                "Set KAVENEGAR_API_KEY, or unset SMS_LIVE_ENABLED until Kavenegar "
                "KYC is complete.",
                hint="See halqe/docs/sms_go_live.md and clinical.sms.provider.get_provider().",
                id="clinical.E001",
            ))
    return errors


def _check_sms_live_config(app_configs, **kwargs):
    return _sms_live_config_errors(os.environ)
