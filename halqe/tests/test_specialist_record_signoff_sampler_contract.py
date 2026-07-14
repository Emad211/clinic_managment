"""Contract test between deterministic sampler output and sign-off verifier."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json

from clinical.secure_report_io import write_private_text
from clinical.specialist_record_clinician_signoff import (
    SpecialistRecordClinicianSignoffVerifier,
)
from clinical.specialist_record_review_database import ReviewPatientBindingResult


def test_sampler_selected_samples_and_not_present_in_source_are_normalized(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "clinical.specialist_record_clinician_signoff.verify_review_patient_bindings",
        lambda **_kwargs: ReviewPatientBindingResult(
            passed=True,
            checked_patients=1,
            failures=[],
        ),
    )
    source_id = "sampler-contract-source"
    verified_at = datetime.now(UTC) - timedelta(minutes=2)
    reviewed_at = datetime.now(UTC) - timedelta(minutes=1)
    verification_payload = {
        "decision": "GO",
        "source_id": source_id,
        "tenant_id": 1,
        "generated_at": verified_at.isoformat(),
        "source_file_sha256": "a" * 64,
        "source_manifest_sha256": "b" * 64,
        "summary": {"passed": 1, "warnings": 0, "failed": 0},
        "checks": [{"key": "mechanical", "status": "pass", "detail": "ok"}],
    }
    verification = write_private_text(
        tmp_path / "verification.json",
        json.dumps(verification_payload, sort_keys=True) + "\n",
    )
    patient_uuid = "00000000-0000-0000-0000-000000000321"
    packet = {
        "source_id": source_id,
        "tenant_id": 1,
        "generated_at": reviewed_at.isoformat(),
        "verification_report_sha256": hashlib.sha256(
            verification.read_bytes()
        ).hexdigest(),
        "source_file_sha256": "a" * 64,
        "source_manifest_sha256": "b" * 64,
        "per_scenario": 1,
        "max_patients": 25,
        "scenarios": [
            {"key": "laboratory_result", "label": "آزمایش"},
            {"key": "severe_allergy", "label": "حساسیت شدید"},
        ],
        "coverage": {
            "laboratory_result": {
                "eligible_patients": 1,
                "desired_samples": 1,
                "selected_samples": 1,
                "selected_source_patient_link_ids": [77],
                "status": "covered",
            },
            "severe_allergy": {
                "eligible_patients": 0,
                "desired_samples": 0,
                "selected_samples": 0,
                "selected_source_patient_link_ids": [],
                "status": "not_present_in_source",
            },
        },
        "patients": [
            {
                "source_patient_link_id": 77,
                "target_patient_link_id": 88,
                "patient_uuid": patient_uuid,
                "cockpit_path": f"/patients/{patient_uuid}",
                "scenarios": [
                    {"key": "laboratory_result", "label": "آزمایش"}
                ],
                "feature_counts": {"lab_count": 1},
                "review_checklist": ["نتیجه آزمایش تطبیق شد."],
                "review_status": "approved",
                "review_notes": "تطبیق انجام شد.",
            }
        ],
        "warnings": [],
        "signoff_template": {
            "reviewed_by": "doctor-sampler-contract",
            "reviewed_at": reviewed_at.isoformat(),
            "decision": "approved",
            "acknowledged_warnings": [],
            "discrepancies": [],
        },
    }
    packet_path = write_private_text(
        tmp_path / "packet.json",
        json.dumps(packet, ensure_ascii=False, sort_keys=True) + "\n",
    )

    result = SpecialistRecordClinicianSignoffVerifier(
        review_packet_path=packet_path,
        verification_report_path=verification,
        source_id=source_id,
        tenant_id=1,
    ).run()

    assert result.decision == "GO"
    assert next(
        item for item in result.checks if item.key == "scenario_coverage"
    ).status == "pass"
    assert next(
        item for item in result.checks if item.key == "review_packet_policy"
    ).status == "pass"
