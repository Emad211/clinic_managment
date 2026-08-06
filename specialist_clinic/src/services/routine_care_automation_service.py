"""Exception-first dispatcher for predefined, low-risk CARE messages.

The dispatcher reuses ``EngagementService.approve`` so consent, quiet hours, daily caps,
provider readiness and delivery idempotency remain authoritative. Campaigns, free text,
visit invitations and any override remain manual.
"""
from __future__ import annotations

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.engagement_repo import EngagementRepository
from src.common.utils import iran_now
from src.services.engagement_service import EngagementService


ROUTINE_CARE_EVENTS = frozenset({
    "appointment_reminder",
    "refill_due",
    "lapsed",
})
_DEFERRED_REASONS = frozenset({
    "quiet_hours",
    "daily_cap",
    "provider_unconfigured",
    "not_pending",
})


class RoutineCareAutomationService:
    def __init__(self, *, max_attempts: int = 3):
        self.db = get_db()
        self.repo = EngagementRepository()
        self.engagement = EngagementService()
        self.max_attempts = max(int(max_attempts), 1)

    def _eligible_pending(self) -> list[dict]:
        output = []
        for approval in self.repo.list_pending():
            event_key = str(approval.get("event_key") or "")
            if event_key not in ROUTINE_CARE_EVENTS:
                continue
            config = self.repo.get_event(event_key)
            if (
                not config
                or not int(config.get("is_active") or 0)
                or str(config.get("channel") or "") not in {"sms", "both"}
            ):
                continue
            output.append(approval)
        return output

    def collect(self) -> dict:
        """Collect current due events into the existing approval/worklist pipeline."""
        return self.engagement.run_all(dry_run=False, worklist_only=False)

    def process(self, *, decided_by: str = "system:routine-care") -> dict:
        result = {
            "eligible": 0,
            "sent": 0,
            "deferred": 0,
            "failed": 0,
            "skipped": 0,
            "exceptions": [],
        }
        for approval in self._eligible_pending():
            result["eligible"] += 1
            attempts = int(approval.get("send_attempts") or 0)
            if attempts >= self.max_attempts:
                self.repo.finish_approval(
                    int(approval["id"]),
                    "failed",
                    decided_by=decided_by,
                    error="routine_care_attempt_limit",
                )
                result["failed"] += 1
                result["exceptions"].append(
                    {
                        "approval_id": int(approval["id"]),
                        "event_key": approval["event_key"],
                        "patient_name": approval.get("patient_name"),
                        "reason": "attempt_limit",
                    }
                )
                continue

            response = self.engagement.approve(
                int(approval["id"]),
                decided_by=decided_by,
                message=None,
                override=False,
            )
            if response.get("ok"):
                result["sent"] += 1
                continue

            reason = str(response.get("reason") or "unknown")
            if reason in _DEFERRED_REASONS:
                result["deferred"] += 1
            elif reason in {"opt_out", "empty", "retired_clinical_event"}:
                result["skipped"] += 1
            else:
                result["failed"] += 1
                result["exceptions"].append(
                    {
                        "approval_id": int(approval["id"]),
                        "event_key": approval["event_key"],
                        "patient_name": approval.get("patient_name"),
                        "reason": reason,
                    }
                )
        return result

    def run(self, *, decided_by: str = "system:routine-care") -> dict:
        collected = self.collect()
        processed = self.process(decided_by=decided_by)
        return {
            "collected": collected,
            "processed": processed,
            "run_at": iran_now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def exception_summary(self, limit: int = 100) -> dict:
        rows = [
            dict(row)
            for row in self.db.execute(
                """SELECT approval.*, patient.full_name AS patient_name,
                          patient.phone_number,
                          COALESCE(event.label,approval.event_key) AS event_label
                   FROM engagement_approvals approval
                   JOIN patient_links patient ON patient.id=approval.patient_link_id
                   LEFT JOIN engagement_events event
                     ON event.event_key=approval.event_key
                   WHERE approval.event_key IN (
                       'appointment_reminder','refill_due','lapsed'
                   )
                     AND (
                       approval.status IN ('failed','unknown')
                       OR approval.last_error IS NOT NULL
                       OR approval.send_attempts>=?
                     )
                   ORDER BY approval.id DESC LIMIT ?""",
                (self.max_attempts, int(limit)),
            ).fetchall()
        ]
        return {
            "count": len(rows),
            "items": rows,
            "max_attempts": self.max_attempts,
        }


__all__ = ["ROUTINE_CARE_EVENTS", "RoutineCareAutomationService"]
