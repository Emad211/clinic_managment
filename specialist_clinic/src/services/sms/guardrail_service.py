"""Global operational guardrails for every outbound SMS submission."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.sms_repo import SmsRepository
from src.common.utils import iran_now


ALLOWED_START_DEFAULT = "08:00"
ALLOWED_END_DEFAULT = "21:00"
DAILY_CAP_DEFAULT = 1


class SmsGuardrailDenied(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class SmsGuardrailDecision:
    patient_link_id: int
    allowed_start: str
    allowed_end: str
    daily_cap: int
    submitted_today: int


class SmsGuardrailService:
    """Enforce Tehran allowed-hours and per-patient daily submission caps.

    ``sms_messages`` is the canonical outbound ledger. Counting it (rather than
    the engagement-only ledger) makes the cap cover approvals, campaigns and
    every future sender that uses the governed send path.
    """

    def __init__(self, settings: SmsRepository | None = None):
        self.settings = settings or SmsRepository()

    @staticmethod
    def _valid_time(value: str | None, fallback: str) -> str:
        candidate = str(value or "").strip()
        try:
            datetime.strptime(candidate, "%H:%M")
        except (TypeError, ValueError):
            return fallback
        return candidate

    def allowed_window(self) -> tuple[str, str]:
        start = self._valid_time(
            self.settings.get_setting(
                "engagement_quiet_start", ALLOWED_START_DEFAULT
            ),
            ALLOWED_START_DEFAULT,
        )
        end = self._valid_time(
            self.settings.get_setting(
                "engagement_quiet_end", ALLOWED_END_DEFAULT
            ),
            ALLOWED_END_DEFAULT,
        )
        return start, end

    def daily_cap(self) -> int:
        try:
            configured = int(
                self.settings.get_setting(
                    "engagement_daily_cap", DAILY_CAP_DEFAULT
                )
            )
        except (TypeError, ValueError):
            configured = DAILY_CAP_DEFAULT
        return min(max(configured, 1), 10)

    def is_outside_allowed_hours(self, now=None) -> bool:
        current = (now or iran_now()).strftime("%H:%M")
        start, end = self.allowed_window()
        if start == end:
            return False
        if start < end:
            return not (start <= current <= end)
        # An overnight allowed window, for example 20:00–06:00.
        return not (current >= start or current <= end)

    def submitted_today(self, patient_link_id: int) -> int:
        """Count accepted or indeterminate provider submissions in Tehran today.

        Definite provider failures do not consume the cap. SubmissionUnknown is
        counted fail-closed because retrying it may duplicate a delivered SMS.
        """
        row = get_db().execute(
            """SELECT COUNT(*) AS c
               FROM sms_messages
               WHERE patient_link_id=?
                 AND send_attempts > 0
                 AND (
                       status='accepted'
                       OR delivery_status IN ('Submitting','SubmissionUnknown')
                 )
                 AND date(COALESCE(sent_at, last_attempt_at))
                     = date('now','+3 hours','+30 minutes')""",
            (int(patient_link_id),),
        ).fetchone()
        return int(row["c"])

    def require_allowed(
        self,
        patient_link_id: int,
        *,
        override_quiet: bool = False,
    ) -> SmsGuardrailDecision:
        if self.is_outside_allowed_hours() and not override_quiet:
            raise SmsGuardrailDenied("quiet")
        count = self.submitted_today(patient_link_id)
        cap = self.daily_cap()
        if count >= cap:
            raise SmsGuardrailDenied("daily_cap")
        start, end = self.allowed_window()
        return SmsGuardrailDecision(
            patient_link_id=int(patient_link_id),
            allowed_start=start,
            allowed_end=end,
            daily_cap=cap,
            submitted_today=count,
        )


__all__ = [
    "SmsGuardrailDecision",
    "SmsGuardrailDenied",
    "SmsGuardrailService",
]
