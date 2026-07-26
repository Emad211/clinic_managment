"""Clinical follow-up projection from exact current Clinical Engine v2 runs.

Administrative reminders remain separate. Rule-derived tasks require an explicit,
versioned due/completion contract; an inactive/stale rollout or incomplete contract emits
no mutation. Human confirmation is verified from the latest append-only decision event.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json

from src.adapters.sqlite.clinical_engine_fact_repo import (
    ClinicalEngineFactRepository,
)
from src.adapters.sqlite.clinical_followup_repo import ClinicalFollowupRepository
from src.adapters.sqlite.clinical_task_contract_repo import (
    ClinicalTaskContractError,
    normalize_contract,
)
from src.services.clinical_engine.runtime import (
    ClinicalEngineRuntimeError,
    ClinicalEngineRuntimeService,
    ClinicalEngineRuntimeStale,
)


_TASK_REASONS = {
    "create_followup": "monitoring",
    "schedule_screening": "screening",
    "vaccine": "vaccine",
}


def _trace_fact_ids(node: dict) -> set[str]:
    values = {str(value) for value in (node.get("fact_ids") or [])}
    for child in node.get("children") or []:
        values.update(_trace_fact_ids(child))
    return values


def _due_at(as_of_at: str, params: dict) -> datetime:
    base = datetime.fromisoformat(str(as_of_at))
    has_hours = params.get("due_in_hours") is not None
    has_days = params.get("due_in_days") is not None
    if has_hours == has_days:
        raise ClinicalTaskContractError(
            "exactly one of due_in_hours or due_in_days is required"
        )
    if has_hours:
        raw = params.get("due_in_hours")
        if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= 8760:
            raise ClinicalTaskContractError("invalid due_in_hours")
        return base + timedelta(hours=raw)
    raw = params.get("due_in_days")
    if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= 3650:
        raise ClinicalTaskContractError("invalid due_in_days")
    return base + timedelta(days=raw)


class ClinicalV2FollowupService:
    """Project current audited FIRED due rules into idempotent internal tasks."""

    def __init__(self, *, facts=None, repo=None, runtime=None):
        self.facts = facts or ClinicalEngineFactRepository()
        self.repo = repo or ClinicalFollowupRepository()
        self.runtime = runtime or ClinicalEngineRuntimeService(facts=self.facts)

    def enabled_for(self, patient_link_id: int) -> bool:
        mode = self.facts.get_mode()
        return mode == "on" or (
            mode == "on_selected"
            and self.facts.is_selected_patient(patient_link_id)
        )

    def project_patient(self, patient_link_id: int) -> dict:
        if not self.enabled_for(patient_link_id):
            return {"enabled": False, "tasks": [], "issues": []}
        try:
            ensured = self.runtime.ensure_current_run(
                patient_link_id,
                trigger="clinical-followup",
                actor="clinical-followup",
            )
        except ClinicalEngineRuntimeStale:
            return {
                "enabled": True,
                "tasks": [],
                "issues": [{"code": "CURRENT_RUN_STALE", "rule_code": None}],
            }
        except ClinicalEngineRuntimeError:
            return {
                "enabled": True,
                "tasks": [],
                "issues": [
                    {"code": "CURRENT_RUN_UNAVAILABLE", "rule_code": None}
                ],
            }
        if not ensured:
            return {"enabled": False, "tasks": [], "issues": []}
        contract, run = ensured
        if run.get("run_status") == "SAFETY_FAILED":
            return {
                "enabled": True,
                "tasks": [],
                "issues": [{"code": "SAFETY_NOT_CLEARED", "rule_code": None}],
            }

        tasks: list[dict] = []
        issues: list[dict] = []
        for evaluation in run["evaluations"]:
            action = evaluation.get("action_type")
            if action not in _TASK_REASONS:
                continue
            outcome = evaluation.get("outcome")
            if outcome == "SUPPRESSED":
                continue
            if outcome in {"NEEDS_DATA", "ERROR"}:
                issues.append(
                    {
                        "code": (
                            "RULE_NEEDS_DATA"
                            if outcome == "NEEDS_DATA"
                            else "RULE_ERROR"
                        ),
                        "rule_code": evaluation.get("rule_code"),
                        "outcome": outcome,
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
                        "code": "RECOMMENDATION_AUDIT_MISSING",
                        "rule_code": evaluation.get("rule_code"),
                    }
                )
                continue
            if (
                recommendation.get("action_type") != action
                or not recommendation.get("suggestion_only")
                or not recommendation.get("may_create_internal_task")
            ):
                issues.append(
                    {
                        "code": "TASK_POLICY_REJECTED",
                        "rule_code": evaluation.get("rule_code"),
                    }
                )
                continue

            requires_confirmation = bool(
                recommendation.get("requires_clinician_confirmation")
            )
            current_decision = event.get("current_decision")
            decision_event_id: int | None = None
            if requires_confirmation:
                if not current_decision:
                    issues.append(
                        {
                            "code": "CLINICIAN_DECISION_REQUIRED",
                            "rule_code": evaluation.get("rule_code"),
                            "recommendation_event_id": int(event["id"]),
                        }
                    )
                    continue
                if current_decision.get("decision") != "ACCEPTED":
                    issues.append(
                        {
                            "code": "CLINICIAN_DECISION_NOT_ACCEPTED",
                            "rule_code": evaluation.get("rule_code"),
                            "recommendation_event_id": int(event["id"]),
                            "decision": current_decision.get("decision"),
                            "decision_event_id": int(current_decision["id"]),
                        }
                    )
                    continue
                decision_event_id = int(current_decision["id"])
            elif current_decision:
                if current_decision.get("decision") != "ACCEPTED":
                    issues.append(
                        {
                            "code": "TASK_BLOCKED_BY_CLINICIAN_DECISION",
                            "rule_code": evaluation.get("rule_code"),
                            "recommendation_event_id": int(event["id"]),
                            "decision": current_decision.get("decision"),
                            "decision_event_id": int(current_decision["id"]),
                        }
                    )
                    continue
                decision_event_id = int(current_decision["id"])

            semantic_key = str(
                recommendation.get("semantic_key") or ""
            ).strip()
            if not semantic_key:
                issues.append(
                    {
                        "code": "TASK_IDENTITY_MISSING",
                        "rule_code": evaluation.get("rule_code"),
                    }
                )
                continue
            evidence_ids = sorted(
                _trace_fact_ids(evaluation.get("trace") or {})
            )
            if not evidence_ids:
                issues.append(
                    {
                        "code": "TASK_EVIDENCE_MISSING",
                        "rule_code": evaluation.get("rule_code"),
                    }
                )
                continue

            params = recommendation.get("params") or {}
            raw_task_contract = params.get("task_contract")
            if not isinstance(raw_task_contract, dict):
                issues.append(
                    {
                        "code": "TASK_CONTRACT_MISSING",
                        "rule_code": evaluation.get("rule_code"),
                    }
                )
                continue
            try:
                due = _due_at(str(run.get("as_of_at")), params)
                task_contract = normalize_contract(
                    raw_task_contract,
                    due_at=due.isoformat(sep=" ", timespec="seconds"),
                )
            except (TypeError, ValueError, ClinicalTaskContractError) as exc:
                issues.append(
                    {
                        "code": "TASK_CONTRACT_INVALID",
                        "rule_code": evaluation.get("rule_code"),
                        "error": str(exc),
                    }
                )
                continue

            due_date = due.date().isoformat()
            due_period = str(
                params.get("due_period") or due_date
            ).strip()
            identity = json.dumps(
                {
                    "patient_link_id": int(patient_link_id),
                    "semantic_key": semantic_key,
                    "due_period": due_period,
                    "evidence_fact_ids": evidence_ids,
                    "context_hash": contract.context_hash,
                    "task_contract": task_contract,
                    "source_decision_event_id": decision_event_id,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            task_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            tasks.append(
                {
                    "patient_link_id": int(patient_link_id),
                    "reason": _TASK_REASONS[action],
                    "detail": (
                        recommendation.get("text_fa")
                        or evaluation.get("rule_title")
                    ),
                    "due_date": due_date,
                    "due_period": due_period,
                    "task_contract": task_contract,
                    "source_rule": evaluation.get("rule_code"),
                    "source_run_id": run["run_id"],
                    "source_recommendation_event_id": int(event["id"]),
                    "source_decision_event_id": decision_event_id,
                    "requires_clinician_confirmation": requires_confirmation,
                    "clinical_semantic_key": semantic_key,
                    "clinical_task_key": task_key,
                    "source_mode": contract.mode,
                    "source_engine_version": contract.engine_version,
                    "source_ruleset_id": contract.ruleset_id,
                    "source_clinical_data_revision": (
                        contract.clinical_data_revision
                    ),
                    "clinical_context_hash": contract.context_hash,
                }
            )
        return {"enabled": True, "tasks": tasks, "issues": issues}

    def generate_patient(self, patient_link_id: int) -> dict:
        projection = self.project_patient(patient_link_id)
        created = 0
        task_ids: list[int] = []
        issues = list(projection["issues"])
        for task in projection["tasks"]:
            try:
                task_id, was_created = self.repo.create_clinical_task_once(task)
            except RuntimeError as exc:
                code = str(exc)
                if code == "STALE_CLINICAL_TASK_SOURCE":
                    issues.append(
                        {
                            "code": "CURRENT_RUN_STALE",
                            "rule_code": task.get("source_rule"),
                        }
                    )
                    continue
                if code in {
                    "CLINICIAN_DECISION_STALE",
                    "CLINICIAN_DECISION_NOT_ACCEPTED",
                }:
                    issues.append(
                        {
                            "code": code,
                            "rule_code": task.get("source_rule"),
                            "recommendation_event_id": task.get(
                                "source_recommendation_event_id"
                            ),
                        }
                    )
                    continue
                raise
            task_ids.append(task_id)
            created += int(was_created)
        return {
            "enabled": projection["enabled"],
            "created": created,
            "task_ids": task_ids,
            "issues": issues,
        }

    def generate_all(self) -> dict:
        created = 0
        issues: list[dict] = []
        for patient_id in self.repo.active_patient_ids():
            if not self.enabled_for(patient_id):
                continue
            result = self.generate_patient(patient_id)
            created += result["created"]
            issues.extend(
                {**issue, "patient_link_id": patient_id}
                for issue in result["issues"]
            )
        return {"created": created, "issues": issues}
