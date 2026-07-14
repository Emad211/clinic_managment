"""Persian/Arabic digit PHI guards for retained clinician sign-off artifacts."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json

import pytest

from clinical.secure_report_io import write_private_text
from clinical.specialist_record_clinician_signoff import (
    SpecialistRecordClinicianSignoffVerifier,
)
from clinical.specialist_record_review_database import ReviewPatientBindingResult


@pytest.fixture
def artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "clinical.specialist_record_clinician_signoff.verify_review_patient_bindings",
        lambda **_kwargs: ReviewPatientBindingResult(
            passed=True,
            checked_patients=1,
            failures=[],
        ),
    )
    source_id = "persian-phi-signoff"
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
        "checks": [{"key": "all", "status": "pass", "detail": "ok"}],
    }
    verification = write_private_text(
        tmp_path / "verification.json",
        json.dumps(verification_payload, sort_keys=True) + "\n",
    )
    patient_uuid = "00000000-0000-0000-0000-000000000456"
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
        "max_patients": 5,
        "scenarios": [{"key": "laboratory_result", "label": "آزمایش"}],
        "coverage": {
            "laboratory_result": {
                "eligible_patients": 1,
                "selected_patients": 1,
                "status": "covered",
            }
        },
        "patients": [
            {
                "source_patient_link_id": 1,
                "target_patient_link_id": 2,
                "patient_uuid": patient_uuid,
                "cockpit_path": f"/patients/{patient_uuid}",
                "scenarios": [{"key": "laboratory_result", "label": "آزمایش"}],
                "feature_counts": {"lab_count": 1},
                "review_checklist": ["تطبیق آزمایش"],
                "review_status": "approved",
                "review_notes": "تطبیق شد.",
            }
        ],
        "warnings": [],
        "signoff_template": {
            "reviewed_by": "doctor-reviewer",
            "reviewed_at": reviewed_at.isoformat(),
            "decision": "approved",
            "acknowledged_warnings": [],
            "discrepancies": [],
        },
    }
    packet_path = tmp_path / "packet.json"

    def run(payload):
        write_private_text(
            packet_path,
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        )
        return SpecialistRecordClinicianSignoffVerifier(
            review_packet_path=packet_path,
            verification_report_path=verification,
            source_id=source_id,
            tenant_id=1,
        ).run()

    return packet, run


def test_persian_digit_mobile_in_review_note_is_no_go(artifacts):
    packet, run = artifacts
    packet["patients"][0]["review_notes"] = "تماس با ۰۹۱۲۱۲۳۴۵۶۷ انجام شد"

    result = run(packet)
    assert result.decision == "NO_GO"
    check = next(item for item in result.checks if item.key == "review_text_phi_guard")
    assert check.status == "fail"
    assert "contains-mobile" in check.detail


def test_persian_digit_valid_national_id_in_discrepancy_is_no_go(artifacts):
    packet, run = artifacts
    packet["signoff_template"]["discrepancies"] = [
        {
            "id": "D-phi",
            "severity": "minor",
            "domain": "identity",
            "description": "کد ثبت‌شده ۰۰۱۳۵۴۶۷۵۹ بود",
            "disposition": "fixed",
            "owner": "reviewer",
            "resolution_note": "از گزارش حذف شد",
            "resolved_at": packet["signoff_template"]["reviewed_at"],
        }
    ]

    result = run(packet)
    assert result.decision == "NO_GO"
    check = next(item for item in result.checks if item.key == "review_text_phi_guard")
    assert check.status == "fail"
    assert "contains-national-id" in check.detail
