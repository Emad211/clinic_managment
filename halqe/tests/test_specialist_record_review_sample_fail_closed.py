"""Fail-closed edge cases for clinician review packet generation."""
from __future__ import annotations

import json

from django.core.management import call_command
from django.core.management.base import CommandError
import pytest

from clinical.secure_report_io import write_private_text
from clinical.specialist_record_review_sample import (
    ReviewCandidate,
    SpecialistRecordReviewSampler,
)


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_command_rejects_go_report_with_no_imported_patients(seed_data, tmp_path):
    source_id = "review-empty-source"
    verification = write_private_text(
        tmp_path / "empty-go.json",
        json.dumps(
            {
                "decision": "GO",
                "source_id": source_id,
                "tenant_id": 1,
                "source_file_sha256": "a" * 64,
                "source_manifest_sha256": "b" * 64,
            },
            sort_keys=True,
        )
        + "\n",
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
