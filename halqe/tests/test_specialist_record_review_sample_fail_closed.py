"""Fail-closed edge cases for clinician review packet generation."""
from __future__ import annotations

import json
import os

from django.core.management import call_command
from django.core.management.base import CommandError
import pytest

from clinical.secure_report_io import write_private_text
from clinical.specialist_record_review_sample import (
    ReviewCandidate,
    SpecialistRecordReviewSampler,
)


REQUIRED_CHECKS = {
    "apply_report_contract",
    "apply_table_accounting",
    "unresolved_patient_policy",
    "apply_report_ledger_count",
    "idempotent_replay_report",
    "relational_dry_run_reproduction",
    "durable_ledger_count",
    "ledger_source_table_counts",
    "ledger_row_shape",
    "ledger_manifest",
    "ledger_target_existence",
    "target_payload_fingerprints",
    "medication_event_orphans",
    "verified_patient_self_reports",
    "lab_observation_visibility",
    "appointment_parent_orphans",
    "followup_appointment_orphans",
    "prescription_followup_orphans",
}


def _go_report(source_id: str, *, omit: str | None = None) -> dict:
    names = sorted(REQUIRED_CHECKS - ({omit} if omit else set()))
    return {
        "decision": "GO",
        "source_id": source_id,
        "tenant_id": 1,
        "source_file_sha256": "a" * 64,
        "source_manifest_sha256": "b" * 64,
        "summary": {"passed": len(names), "warnings": 0, "failed": 0},
        "checks": [
            {"name": name, "status": "pass", "detail": "ok", "metrics": {}}
            for name in names
        ],
    }


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_command_rejects_go_report_with_no_imported_patients(seed_data, tmp_path):
    source_id = "review-empty-source"
    verification = write_private_text(
        tmp_path / "empty-go.json",
        json.dumps(_go_report(source_id), sort_keys=True) + "\n",
    )
    output = tmp_path / "empty-review.json"

    with pytest.raises(CommandError, match="no imported patient"):
        call_command(
            "generate_specialist_record_review_sample",
            verification_report=str(verification),
            source_id=source_id,
            tenant_id=1,
            report=str(output),
            verbosity=0,
        )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["patients"] == []
    assert any(
        "No imported patient_links" in warning
        for warning in payload["warnings"]
    )


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_command_rejects_go_label_when_a_required_check_is_missing(seed_data, tmp_path):
    source_id = "review-incomplete-go"
    verification = write_private_text(
        tmp_path / "incomplete-go.json",
        json.dumps(
            _go_report(source_id, omit="target_payload_fingerprints"),
            sort_keys=True,
        )
        + "\n",
    )

    with pytest.raises(CommandError, match="missing=target_payload_fingerprints"):
        call_command(
            "generate_specialist_record_review_sample",
            verification_report=str(verification),
            source_id=source_id,
            tenant_id=1,
            report=str(tmp_path / "incomplete-review.json"),
            verbosity=0,
        )
    assert not (tmp_path / "incomplete-review.json").exists()


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_command_rejects_group_readable_verification_report(seed_data, tmp_path):
    source_id = "review-permission-go"
    verification = write_private_text(
        tmp_path / "permission-go.json",
        json.dumps(_go_report(source_id), sort_keys=True) + "\n",
    )
    os.chmod(verification, 0o640)

    with pytest.raises(CommandError, match="owner-only"):
        call_command(
            "generate_specialist_record_review_sample",
            verification_report=str(verification),
            source_id=source_id,
            tenant_id=1,
            report=str(tmp_path / "permission-review.json"),
            verbosity=0,
        )


def test_selection_reports_present_scenarios_uncovered_by_limit(tmp_path):
    sampler = SpecialistRecordReviewSampler(
        verification_report_path=tmp_path / "unused.json",
        source_id="review-limit-test",
        tenant_id=1,
        per_scenario=1,
        max_patients=1,
    )
    candidates = [
        ReviewCandidate(
            source_patient_link_id=1,
            target_patient_link_id=101,
            patient_uuid="00000000-0000-0000-0000-000000000001",
            scenarios=["multiple_conditions"],
            feature_counts={},
        ),
        ReviewCandidate(
            source_patient_link_id=2,
            target_patient_link_id=102,
            patient_uuid="00000000-0000-0000-0000-000000000002",
            scenarios=["severe_allergy"],
            feature_counts={},
        ),
    ]

    selected, coverage, warnings = sampler._select(candidates)
    assert len(selected) == 1
    statuses = {
        coverage["multiple_conditions"]["status"],
        coverage["severe_allergy"]["status"],
    }
    assert statuses == {"covered", "uncovered_due_to_limit"}
    assert any("max_patients=1" in warning for warning in warnings)
