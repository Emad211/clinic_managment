"""Rule-driven follow-up generation: turns fired monitoring/screening/vaccine
rules into worklist tasks — but only when actually DUE (interval elapsed or
never done). Keeps the worklist practical, not spammy.
"""
from datetime import datetime
import hashlib
import json

from src.adapters.sqlite.clinical_engine_audit_repo import ClinicalEngineAuditRepository
from src.adapters.sqlite.clinical_engine_fact_repo import ClinicalEngineFactRepository
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.common.utils import today_str, iran_now

REASON_BY_ACTION = {
    'create_followup': 'monitoring',
    'schedule_screening': 'screening',
    'vaccine': 'vaccine',
}

# Default recall interval (months) per item; None = one-time / on-demand.
ITEM_DEFAULT_MONTHS = {
    'a1c': 6, 'renal': 12, 'lipid': 12, 'eye': 12, 'foot': 12,
    'neuropathy': 12, 'masld': 12, 'renal_function': 12, 'potassium': None,
    'influenza': 12, 'tdap': 120, 'zoster': None, 'pneumococcal': None,
    'rsv': None, 'covid19': None, 'tsh': 12,
}
# Canonical observation keys whose "last done" date closes each item's recall — matched in
# BOTH vital_readings.type AND lab_results.test_key (one shared vocabulary; ADR-0005).
ITEM_VITALS = {'a1c': ['hba1c'], 'renal': ['egfr', 'uacr'], 'lipid': ['ldl'],
               'renal_function': ['egfr'], 'tsh': ['tsh']}
ITEM_FLAGS = {'eye': 'eye_exam_date', 'foot': 'foot_exam_date'}


def _last_done(pid: int, item: str, flags: dict):
    keys = ITEM_VITALS.get(item)
    if keys:
        return FollowupRepository().last_observation_at(pid, keys)
    fk = ITEM_FLAGS.get(item)
    return flags.get(fk) if fk else None


def _months_since(date_str):
    try:
        d = datetime.strptime(str(date_str)[:10], '%Y-%m-%d')
    except (ValueError, TypeError):
        return None
    now = iran_now()  # Tehran local (project convention; never naive datetime.now())
    return (now.year - d.year) * 12 + (now.month - d.month)


def due_clinical_events(pid: int) -> list[dict]:
    """Compatibility seam kept for callers; v1 clinical events are retired.

    Clinical tasks are now projected exclusively by ClinicalV2FollowupService.
    An inactive v2 engine means no rule-derived task, never a fallback to v1.
    """
    return []


def generate_for_patient(pid: int) -> int:
    """Create due monitoring/screening/vaccine follow-ups for one patient (worklist)."""
    repo = FollowupRepository()
    created = 0
    for ev in due_clinical_events(pid):
        if ev['action'] == 'redflag':
            continue  # red-flags surface in the patient panel, not the worklist
        if repo.recently_handled_source(pid, ev['rule_code'], ev['months']):
            continue
        repo.create(pid, reason=REASON_BY_ACTION[ev['action']], detail=ev['title'],
                    due_date=today_str(), source_rule=ev['rule_code'])
        created += 1
    return created


def generate_all() -> int:
    """Run rule-driven follow-up generation across all active patients."""
    return sum(generate_for_patient(pid) for pid in FollowupRepository().active_patient_ids())


_V2_TASK_REASONS = {
    "create_followup": "monitoring",
    "schedule_screening": "screening",
    "vaccine": "vaccine",
}


def _trace_fact_ids(node: dict) -> set[str]:
    values = {str(value) for value in (node.get("fact_ids") or [])}
    for child in node.get("children") or []:
        values.update(_trace_fact_ids(child))
    return values


class ClinicalV2FollowupService:
    """Project audited FIRED due rules into inert, idempotent internal tasks."""

    def __init__(self, *, facts=None, audit=None, repo=None):
        self.facts = facts or ClinicalEngineFactRepository()
        self.audit = audit or ClinicalEngineAuditRepository()
        self.repo = repo or FollowupRepository()

    def enabled_for(self, patient_link_id: int) -> bool:
        mode = self.facts.get_mode()
        return mode == "on" or (
            mode == "on_selected" and self.facts.is_selected_patient(patient_link_id)
        )

    def project_patient(self, patient_link_id: int) -> dict:
        if not self.enabled_for(patient_link_id):
            return {"enabled": False, "tasks": [], "issues": []}
        run = self.audit.latest_presentable_run(patient_link_id)
        if not run:
            return {
                "enabled": True, "tasks": [],
                "issues": [{"code": "NO_PRESENTABLE_V2_RUN", "rule_code": None}],
            }
        if run.get("run_status") == "SAFETY_FAILED":
            return {
                "enabled": True, "tasks": [],
                "issues": [{"code": "SAFETY_NOT_CLEARED", "rule_code": None}],
            }
        tasks, issues = [], []
        for evaluation in run["evaluations"]:
            action = evaluation.get("action_type")
            if action not in _V2_TASK_REASONS:
                continue
            outcome = evaluation.get("outcome")
            if outcome == "SUPPRESSED":
                continue
            if outcome in {"NEEDS_DATA", "ERROR"}:
                issues.append({
                    "code": "RULE_NEEDS_DATA" if outcome == "NEEDS_DATA" else "RULE_ERROR",
                    "rule_code": evaluation.get("rule_code"),
                    "outcome": outcome,
                    "data_issues": evaluation.get("data_issues") or [],
                    "error": evaluation.get("error"),
                })
                continue
            if outcome != "FIRED":
                continue
            recommendation = evaluation.get("recommendation") or {}
            event = evaluation.get("recommendation_event")
            if not event:
                issues.append({
                    "code": "RECOMMENDATION_AUDIT_MISSING",
                    "rule_code": evaluation.get("rule_code"),
                })
                continue
            if (
                recommendation.get("action_type") != action
                or not recommendation.get("suggestion_only")
                or not recommendation.get("may_create_internal_task")
                or recommendation.get("requires_clinician_confirmation")
            ):
                issues.append({
                    "code": "TASK_POLICY_REJECTED",
                    "rule_code": evaluation.get("rule_code"),
                })
                continue
            semantic_key = str(recommendation.get("semantic_key") or "").strip()
            if not semantic_key:
                issues.append({
                    "code": "TASK_IDENTITY_MISSING",
                    "rule_code": evaluation.get("rule_code"),
                })
                continue
            evidence_ids = sorted(_trace_fact_ids(evaluation.get("trace") or {}))
            if not evidence_ids:
                issues.append({
                    "code": "TASK_EVIDENCE_MISSING",
                    "rule_code": evaluation.get("rule_code"),
                })
                continue
            try:
                due_date = datetime.fromisoformat(str(run.get("as_of_at"))).date().isoformat()
            except (TypeError, ValueError):
                issues.append({
                    "code": "TASK_DUE_DATE_INVALID",
                    "rule_code": evaluation.get("rule_code"),
                })
                continue
            identity = json.dumps({
                "patient_link_id": int(patient_link_id),
                "semantic_key": semantic_key,
                "evidence_fact_ids": evidence_ids,
            }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            task_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            tasks.append({
                "patient_link_id": int(patient_link_id),
                "reason": _V2_TASK_REASONS[action],
                "detail": recommendation.get("text_fa") or evaluation.get("rule_title"),
                "due_date": due_date,
                "source_rule": evaluation.get("rule_code"),
                "source_run_id": run["run_id"],
                "source_recommendation_event_id": int(event["id"]),
                "clinical_semantic_key": semantic_key,
                "clinical_task_key": task_key,
            })
        return {"enabled": True, "tasks": tasks, "issues": issues}

    def generate_patient(self, patient_link_id: int) -> dict:
        projection = self.project_patient(patient_link_id)
        created = 0
        task_ids = []
        for task in projection["tasks"]:
            task_id, was_created = self.repo.create_clinical_task_once(task)
            task_ids.append(task_id)
            created += int(was_created)
        return {
            "enabled": projection["enabled"], "created": created,
            "task_ids": task_ids, "issues": projection["issues"],
        }

    def generate_all(self) -> dict:
        created = 0
        issues = []
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
