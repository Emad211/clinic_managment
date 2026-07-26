from __future__ import annotations

from types import SimpleNamespace

from src.services.followup_engine import ClinicalV2FollowupService


class Facts:
    def get_mode(self):
        return "on"

    def is_selected_patient(self, _patient_id):
        return True


class Repo:
    def __init__(self):
        self.tasks = []

    def create_clinical_task_once(self, task):
        self.tasks.append(task)
        return 81, True


def _runtime(decision):
    recommendation_event = {"id": 501, "current_decision": decision}
    return SimpleNamespace(
        ensure_current_run=lambda *_args, **_kwargs: (
            SimpleNamespace(
                mode="on",
                engine_version="a3",
                ruleset_id=9,
                clinical_data_revision=3,
                context_hash="c" * 64,
            ),
            {
                "run_id": "run-confirmed",
                "run_status": "COMPLETED",
                "as_of_at": "2026-07-26 10:00:00",
                "evaluations": [
                    {
                        "rule_code": "CONFIRMED-TASK",
                        "rule_title": "پیگیری نیازمند تصمیم",
                        "action_type": "create_followup",
                        "outcome": "FIRED",
                        "trace": {"node_id": "n1", "fact_ids": ["lab:1"]},
                        "recommendation_event": recommendation_event,
                        "recommendation": {
                            "action_type": "create_followup",
                            "text_fa": "پس از تأیید پزشک پیگیری شود.",
                            "suggestion_only": True,
                            "requires_clinician_confirmation": True,
                            "may_create_internal_task": True,
                            "semantic_key": "test:confirmed-task",
                            "params": {
                                "due_in_days": 3,
                                "due_period": "2026-Q3",
                                "task_contract": {
                                    "urgency": "ROUTINE",
                                    "allowed_outcome_types": ["LAB_COMPLETED"],
                                    "required_fact_keys": ["lab.hba1c"],
                                    "minimum_verification": "CONFIRMED",
                                    "canonical_ingestion": "REQUIRED",
                                },
                            },
                        },
                    }
                ],
            },
        )
    )


def test_confirmation_required_task_waits_for_decision():
    repo = Repo()
    result = ClinicalV2FollowupService(
        facts=Facts(), runtime=_runtime(None), repo=repo
    ).generate_patient(7)
    assert result["created"] == 0
    assert result["issues"][0]["code"] == "CLINICIAN_DECISION_REQUIRED"
    assert repo.tasks == []


def test_dismissed_confirmation_never_creates_task():
    repo = Repo()
    decision = {"id": 41, "decision": "DISMISSED"}
    result = ClinicalV2FollowupService(
        facts=Facts(), runtime=_runtime(decision), repo=repo
    ).generate_patient(7)
    assert result["created"] == 0
    assert result["issues"][0]["code"] == "CLINICIAN_DECISION_NOT_ACCEPTED"
    assert repo.tasks == []


def test_latest_accepted_decision_is_bound_to_created_task():
    repo = Repo()
    decision = {"id": 42, "decision": "ACCEPTED"}
    result = ClinicalV2FollowupService(
        facts=Facts(), runtime=_runtime(decision), repo=repo
    ).generate_patient(7)
    assert result["created"] == 1
    assert result["task_ids"] == [81]
    assert repo.tasks[0]["source_decision_event_id"] == 42
    assert repo.tasks[0]["requires_clinician_confirmation"] is True
