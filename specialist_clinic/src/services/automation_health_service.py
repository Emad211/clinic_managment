"""Human-readable liveness surface for the background scheduler.

This service is deliberately **independent of the clinical (analytical) engine**:
the scheduler ticks — and this snapshot reports — regardless of whether the
suggestion-only clinical engine is ON, OFF, or UNAVAILABLE. Engine mode changes
only the *content* of the clinical jobs, never scheduler liveness. Turning the
analytical engine off must not make this surface report a false problem.

Liveness is derived from the most recent *activity* timestamp, NOT from whether
the lease is currently held. The scheduler intentionally releases (expires) its
lease at the end of every tick, so between ticks the lease is always expired;
"is the lease held right now" would therefore be a misleading signal. Instead we
take the freshest of {lease.heartbeat_at, lease.acquired_at, latest job
started_at/completed_at}.

Contract (mirrors A0-A4): never report a false "healthy"; on a read error report
`unknown` (never a fabricated zero); when nothing has run yet report `idle`
(scheduler warming up), never `ok`.
"""
from __future__ import annotations

from datetime import datetime

from src.adapters.sqlite.operational_lease_repo import OperationalLeaseRepository
from src.common.utils import iran_now

# Kept in sync with Scheduler.LEASE_NAME (guarded by a test — see
# tests/test_automation_health_surface.py) to avoid importing the scheduler
# module, which pulls in the whole services graph.
LEASE_NAME = "specialist-clinic:scheduler"

# The scheduler ticks every ~120s and heartbeats every 60s. Three missed ticks
# is the boundary of "still fine"; beyond twenty minutes we call it down.
FRESH_SECONDS = 360
STALE_SECONDS = 1200

_STATUS_FA = {
    "ok": "فعال",
    "stale": "با تأخیر",
    "down": "متوقف",
    "idle": "در انتظار شروع",
    "unknown": "نامشخص",
}
_STATUS_TONE = {
    "ok": "ok",
    "stale": "warn",
    "down": "danger",
    "idle": "muted",
    "unknown": "muted",
}
_STATUS_MESSAGE_FA = {
    "ok": "زمان‌بند پس‌زمینه فعال است و کارهای خودکار به‌موقع اجرا می‌شوند.",
    "stale": "آخرین اجرای زمان‌بند با تأخیر بوده است؛ اگر ادامه یافت برنامه را بررسی کنید.",
    "down": "زمان‌بند مدتی است اجرا نشده؛ کارهای خودکار (پیگیری، پیامک، هم‌سان‌سازی مالی) متوقف‌اند. برنامه را دوباره اجرا کنید.",
    "idle": "زمان‌بند هنوز اولین اجرای خود را ثبت نکرده است (در حال آماده‌سازی).",
    "unknown": "وضعیت زمان‌بند قابل خواندن نیست؛ این مقدار به صفر یا «سالم» تبدیل نمی‌شود.",
}


def _local_naive(value: datetime | None = None) -> datetime:
    current = value or iran_now()
    if current.tzinfo is not None:
        return current.replace(tzinfo=None)
    return current


def _parse(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is not None:
        return parsed.replace(tzinfo=None)
    return parsed


class AutomationHealthService:
    def __init__(self, repo: OperationalLeaseRepository | None = None):
        self._repo = repo or OperationalLeaseRepository()

    def snapshot(self, *, now: datetime | None = None, jobs_limit: int = 8) -> dict:
        """Return a never-throwing liveness dict for the scheduler lease."""
        current = _local_naive(now)
        try:
            raw = self._repo.scheduler_health(LEASE_NAME, jobs_limit=jobs_limit)
        except Exception:
            return self._render("unknown", last_seen=None, age_seconds=None,
                                 owner_id=None, jobs=[], last_failure=None)

        lease = raw.get("lease") or {}
        jobs = list(raw.get("recent_jobs") or [])

        # Freshest activity timestamp across lease + jobs.
        candidates: list[datetime] = []
        for key in ("heartbeat_at", "acquired_at"):
            parsed = _parse(lease.get(key))
            if parsed is not None:
                candidates.append(parsed)
        for job in jobs:
            for key in ("completed_at", "started_at"):
                parsed = _parse(job.get(key))
                if parsed is not None:
                    candidates.append(parsed)

        last_seen = max(candidates) if candidates else None
        owner_id = (lease.get("owner_id") or (jobs[0].get("owner_id") if jobs else None)) or None

        last_failure = None
        for job in jobs:  # jobs already newest-first
            if str(job.get("status")) == "FAILED":
                last_failure = {
                    "job_key": job.get("job_key"),
                    "error_code": job.get("error_code"),
                    "completed_at": job.get("completed_at") or job.get("started_at"),
                }
                break

        if last_seen is None:
            return self._render("idle", last_seen=None, age_seconds=None,
                                 owner_id=owner_id, jobs=jobs, last_failure=last_failure)

        age = int((current - last_seen).total_seconds())
        if age < 0:
            age = 0
        if age <= FRESH_SECONDS:
            status = "ok"
        elif age <= STALE_SECONDS:
            status = "stale"
        else:
            status = "down"
        return self._render(status, last_seen=last_seen, age_seconds=age,
                            owner_id=owner_id, jobs=jobs, last_failure=last_failure)

    def _render(self, status, *, last_seen, age_seconds, owner_id, jobs, last_failure) -> dict:
        last_job = None
        if jobs:
            top = jobs[0]
            last_job = {
                "job_key": top.get("job_key"),
                "status": top.get("status"),
                "started_at": top.get("started_at"),
                "completed_at": top.get("completed_at"),
                "error_code": top.get("error_code"),
            }
        return {
            "status": status,
            "status_fa": _STATUS_FA.get(status, status),
            "tone": _STATUS_TONE.get(status, "muted"),
            "message_fa": _STATUS_MESSAGE_FA.get(status, ""),
            "last_seen": last_seen.isoformat(sep=" ", timespec="seconds") if last_seen else None,
            "age_seconds": age_seconds,
            "owner_id": owner_id,
            "jobs_count": len(jobs),
            "last_job": last_job,
            "last_failure": last_failure,
        }
