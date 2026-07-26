"""Governed internal alert projection for fired red-flag and safety recommendations.

This service creates only an internal acknowledgement obligation. It never sends a
message, schedules care, refers a patient, or performs a clinical action.
"""
from __future__ import annotations

from datetime import datetime

from src.adapters.sqlite.clinical_alert_repo import (
    ClinicalAlertConflict,
    ClinicalAlertRepository,
    ClinicalAlertValidationError,
)
from src.adapters.sqlite.clinical_engine_fact_repo import ClinicalEngineFactRepository
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.services.clinical_engine.runtime import (
    ClinicalEngineRuntimeError,
    ClinicalEngineRuntimeService,
    ClinicalEngineRuntimeStale,
)


_ALERT_ACTIONS = {"redflag", "safety_alert"}
_ALERT_SEVERITIES = {"WARN", "URGENT", "CRITICAL"}


class ClinicalAlertService:
    def __init__(self, *, facts=None, runtime=None, repository=None):
        self.facts = facts or ClinicalEngineFactRepository()
        self.runtime = runtime or ClinicalEngineRuntimeService(facts=self.facts)
        self.repository = repository or ClinicalAlertRepository()

    def enabled_for(self, patient_link_id: int) -> bool:
        mode = self.facts.get_mode()
        return mode == "on" or (
            mode == "on_selected" and self.facts.is_selected_patient(patient_link_id)
        )

    def project_patient(self, patient_link_id: int) -> dict:
        if not self.enabled_for(patient_link_id):
            return {"enabled": False, "alerts": [], "issues": []}
        try:
            ensured = self.runtime.ensure_current_run(
                patient_link_id,
                trigger="clinical-alert",
                actor="clinical-alert",
            )
        except ClinicalEngineRuntimeStale:
            return {
                "enabled": True,
                "alerts": [],
                "issues": [{"code": "CURRENT_RUN_STALE", "rule_code": None}],
            }
        except ClinicalEngineRuntimeError:
            return {
                "enabled": True,
                "alerts": [],
                "issues": [{"code": "CURRENT_RUN_UNAVAILABLE", "rule_code": None}],
            }
        if not ensured:
            return {"enabled": False, "alerts": [], "issues": []}

        _contract, run = ensured
        if run.get("run_status") not in {"COMPLETED", "COMPLETED_WITH_ERRORS"}:
            return {
                "enabled": True,
                "alerts": [],
                "issues": [{"code": "ALERT_RUN_NOT_PROJECTABLE", "rule_code": None}],
            }

        alerts: list[dict] = []
        issues: list[dict] = []
        for evaluation in run.get("evaluations") or []:
            action = str(evaluation.get("action_type") or "").strip().lower()
            if action not in _ALERT_ACTIONS:
                continue
            outcome = evaluation.get("outcome")
            if outcome in {"NEEDS_DATA", "ERROR"}:
                issues.append(
                    {
                        "code": "ALERT_RULE_NEEDS_DATA" if outcome == "NEEDS_DATA" else "ALERT_RULE_ERROR",
                        "rule_code": evaluation.get("rule_code"),
                        "data_issues": evaluation.get("data_issues") or [],
                        "error": evaluation.get("error"),
                    }
                )
                continue
            if outcome != "FIRED":
                continue

            recommendation = evaluation.get("recommendation") or {}
            event = evaluation.get("recommendation_event")
            if not event:
                issues.append(
                    {
                        "code": "ALERT_RECOMMENDATION_AUDIT_MISSING",
                        "rule_code": evaluation.get("rule_code"),
                    }
                )
                continue
            if (
                recommendation.get("action_type") != action
                or not recommendation.get("suggestion_only")
            ):
                issues.append(
                    {
                        "code": "ALERT_POLICY_REJECTED",
                        "rule_code": evaluation.get("rule_code"),
                    }
                )
                continue
            severity = str(evaluation.get("severity") or "").strip().upper()
            if severity not in _ALERT_SEVERITIES:
                issues.append(
                    {
                        "code": "ALERT_SEVERITY_INVALID",
                        "rule_code": evaluation.get("rule_code"),
                    }
                )
                continue
            title = (
                recommendation.get("title_fa")
                or evaluation.get("rule_title")
                or evaluation.get("rule_code")
            )
            message = recommendation.get("text_fa")
            if not title or not message:
                issues.append(
                    {
                        "code": "ALERT_CONTENT_MISSING",
                        "rule_code": evaluation.get("rule_code"),
                    }
                )
                continue
            alerts.append(
                {
                    "patient_link_id": int(patient_link_id),
                    "source_run_id": str(run["run_id"]),
                    "source_recommendation_event_id": int(event["id"]),
                    "rule_code": str(evaluation.get("rule_code") or ""),
                    "action_type": action,
                    "severity": severity,
                    "title_fa": str(title),
                    "message_fa": str(message),
                    "created_by": "clinical-alert",
                    "created_at": run.get("as_of_at"),
                }
            )
        return {"enabled": True, "alerts": alerts, "issues": issues}

    def generate_patient(self, patient_link_id: int) -> dict:
        projection = self.project_patient(patient_link_id)
        created = 0
        alert_ids: list[int] = []
        for alert in projection["alerts"]:
            alert_id, was_created = self.repository.create_once(**alert)
            alert_ids.append(alert_id)
            created += int(was_created)
        return {
            "enabled": projection["enabled"],
            "created": created,
            "alert_ids": alert_ids,
            "issues": list(projection["issues"]),
        }

    def generate_all(self) -> dict:
        created = 0
        issues: list[dict] = []
        for patient_id in FollowupRepository().active_patient_ids():
            if not self.enabled_for(patient_id):
                continue
            result = self.generate_patient(patient_id)
            created += result["created"]
            issues.extend(
                {**issue, "patient_link_id": patient_id}
                for issue in result["issues"]
            )
        return {"created": created, "issues": issues}

    def list_open(self, *, patient_link_id: int | None = None) -> list[dict]:
        rows = self.repository.list_current(
            include_terminal=False,
            patient_link_id=patient_link_id,
        )
        now = datetime.now()
        for row in rows:
            try:
                due = datetime.fromisoformat(str(row["acknowledgement_due_at"]))
            except (TypeError, ValueError):
                row["is_overdue"] = True
                row["overdue_minutes"] = None
                continue
            delta = now - due
            row["is_overdue"] = delta.total_seconds() > 0
            row["overdue_minutes"] = max(int(delta.total_seconds() // 60), 0)
        return rows

    def current(self, alert_id: int) -> dict:
        return self.repository.current(alert_id)

    def acknowledge(
        self,
        alert_id: int,
        *,
        expected_current_event_id: int,
        actor_username: str,
        actor_user_id: int | None,
        assigned_to: str | None = None,
        note: str | None = None,
    ) -> dict:
        return self.repository.append_event(
            alert_id,
            event_type="ACKNOWLEDGED",
            expected_current_event_id=expected_current_event_id,
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            assigned_to=assigned_to,
            note=note,
        )

    def resolve(
        self,
        alert_id: int,
        *,
        expected_current_event_id: int,
        decision_event_id: int,
        actor_username: str,
        actor_user_id: int | None,
        note: str,
    ) -> dict:
        alert = self.repository.current(alert_id)
        latest = get_db().execute(
            """SELECT id FROM clinical_decision_events
               WHERE recommendation_event_id=?
               ORDER BY occurred_at DESC, id DESC LIMIT 1""",
            (int(alert["source_recommendation_event_id"]),),
        ).fetchone()
        if not latest or int(latest["id"]) != int(decision_event_id):
            raise ClinicalAlertValidationError(
                "resolution requires the latest clinician decision for this alert"
            )
        if not str(note or "").strip():
            raise ClinicalAlertValidationError("resolution note is required")
        return self.repository.append_event(
            alert_id,
            event_type="RESOLVED",
            expected_current_event_id=expected_current_event_id,
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            note=note,
            decision_event_id=int(decision_event_id),
        )

    def enter_in_error(
        self,
        alert_id: int,
        *,
        expected_current_event_id: int,
        actor_username: str,
        actor_user_id: int | None,
        note: str,
    ) -> dict:
        return self.repository.append_event(
            alert_id,
            event_type="ENTERED_IN_ERROR",
            expected_current_event_id=expected_current_event_id,
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            note=note,
        )

    def escalate_due(self, *, now=None) -> list[int]:
        return self.repository.escalate_due(now=now)


__all__ = [
    "ClinicalAlertConflict",
    "ClinicalAlertService",
    "ClinicalAlertValidationError",
]
