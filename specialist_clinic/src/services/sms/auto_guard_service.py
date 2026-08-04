"""Hardened public service facade for FOUX-V1 FO-6 governed CARE SMS.

The implementation is kept in ``auto_guard_service_impl``.  This facade adds a
strict disabled-state fast path: executing against a database without FO-6
storage returns ``FEATURE_DISABLED`` without creating any table or trigger.
"""
from __future__ import annotations

from datetime import datetime

from src.adapters.sqlite.sms_auto_guard_repo import SmsAutoGuardRepository
from src.services.sms import auto_guard_service_impl as _impl


ALLOWLIST = _impl.ALLOWLIST
DEFAULT_TTL_HOURS = _impl.DEFAULT_TTL_HOURS
MAX_TTL_HOURS = _impl.MAX_TTL_HOURS
MIN_TTL_HOURS = _impl.MIN_TTL_HOURS
POLICY_KEY = _impl.POLICY_KEY
POLICY_LEVELS = _impl.POLICY_LEVELS
REASON_LABELS = _impl.REASON_LABELS
SmsAutoGuardDenied = _impl.SmsAutoGuardDenied
SmsAutoGuardError = _impl.SmsAutoGuardError

# Compatibility hook for existing tests and provider adapters that patch this
# canonical module path.
get_provider = _impl.get_provider


class SmsAutoGuardService(_impl.SmsAutoGuardService):
    """Public FO-6 service with a zero-mutation disabled execution path."""

    def revalidate(
        self,
        candidate_id: int,
        *,
        now: datetime | None = None,
    ) -> _impl.RevalidatedCandidate:
        _impl.get_provider = get_provider
        return super().revalidate(candidate_id, now=now)

    def execute_candidate(
        self,
        candidate_id: int,
        *,
        actor_username: str,
        now: datetime | None = None,
    ) -> dict:
        if not _impl._flag_enabled():
            repo = SmsAutoGuardRepository(self.db)
            if not repo.ready():
                return {
                    "ok": False,
                    "candidate_id": int(candidate_id),
                    "reason": "FEATURE_DISABLED",
                }
        return super().execute_candidate(
            candidate_id,
            actor_username=actor_username,
            now=now,
        )


__all__ = [
    "ALLOWLIST",
    "DEFAULT_TTL_HOURS",
    "MAX_TTL_HOURS",
    "MIN_TTL_HOURS",
    "POLICY_KEY",
    "POLICY_LEVELS",
    "REASON_LABELS",
    "SmsAutoGuardDenied",
    "SmsAutoGuardError",
    "SmsAutoGuardService",
]
