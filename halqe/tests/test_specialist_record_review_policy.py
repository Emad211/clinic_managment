"""Cross-field clinician review packet policy tests."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from clinical.specialist_record_review_policy import (
    verify_review_packet_policy,
)


PATIENT_UUID = "00000000-0000-0000-0000-000000000303"


def _packet() -> dict:
    generated = datetime.now(UTC) - timedelta(minutes=10)
    reviewed = generated + timedelta(minutes=5)
    return {
        "generated_at": generated.isoformat(),
        "per_scenario": 1,
        "max_patients": 10,
        "scenarios": [
            {"key": "multiple_conditions", "label": "چند بیماری"},
            {"key": "severe_allergy", "label": "حساسیت شدید"},
        ],
        "coverage": {
            "multiple_conditions": {
                "eligible_patients": 1,
                "selected_patients": 1,
                "status": "covered",
            },
            "severe_allergy": {
                "eligible_patients": 0,
                "selected_patients": 0,
                "status": "not_present",
            },
        },
        "patients": [
            {
                "source_patient_link_id": 10,
                "target_patient_link_id": 20,
                "patient_uuid": PATIENT_UUID,
                "scenarios": [
                    {"key": "multiple_conditions", "label": "چند بیماری"}
                ],
                "review_status": "approved",
                "review_notes": "مقادیر بالینی با مبدأ تطبیق شد.",
            }
        ],
        "signoff_template": {
            "reviewed_by": "doctor-reviewer",
            "reviewed_at": reviewed.isoformat(),
            "decision": "approved",
            "discrepancies": [],
        },
    }


def _verification() -> dict:
    return {
        "generated_at": (datetime.now(UTC) - timedelta(minutes=20)).isoformat()
    }


def test_valid_packet_passes_temporal_scenario_and_text_policy():
    result = verify_review_packet_policy(
        packet=_packet(),
        verification=_verification(),
    )
    assert result.passed is True
    assert result.status == "pass"
    assert result.failures == []
    assert result.warnings == []


def test_review_cannot_predate_packet_or_be_in_the_future():
    packet = _packet()
    generated = datetime.fromisoformat(packet["generated_at"])
    packet["signoff_template"]["reviewed_at"] = (
        generated - timedelta(seconds=1)
    ).isoformat()
    result = verify_review_packet_policy(
        packet=packet,
        verification=_verification(),
    )
    assert "reviewed-before-packet-generation" in result.failures

    packet = _packet()
    packet["signoff_template"]["reviewed_at"] = (
        datetime.now(UTC) + timedelta(hours=1)
    ).isoformat()
    result = verify_review_packet_policy(
        packet=packet,
        verification=_verification(),
    )
    assert "reviewed-at-in-future" in result.failures


def test_packet_cannot_predate_verification_report():
    packet = _packet()
    verification = {
        "generated_at": (
            datetime.fromisoformat(packet["generated_at"]) + timedelta(minutes=1)
        ).isoformat()
    }
    result = verify_review_packet_policy(
        packet=packet,
        verification=verification,
    )
    assert "packet-generated-before-verification" in result.failures


def test_review_free_text_rejects_mobile_and_valid_iranian_national_id():
    packet = _packet()
    packet["patients"][0]["review_notes"] = (
        "برای پیگیری با 09121234567 تماس بگیرید؛ کد ملی 0013546759 است."
    )
    result = verify_review_packet_policy(
        packet=packet,
        verification=_verification(),
    )
    assert "patient-0-review-notes-contains-mobile" in result.failures
    assert "patient-0-review-notes-contains-national-id" in result.failures


def test_unknown_or_duplicate_patient_scenario_fails():
    packet = _packet()
    packet["patients"][0]["scenarios"] = [
        {"key": "multiple_conditions"},
        {"key": "multiple_conditions"},
        {"key": "not_in_catalog"},
    ]
    result = verify_review_packet_policy(
        packet=packet,
        verification=_verification(),
    )
    assert "patient-0-duplicate-scenario-multiple_conditions" in result.failures
    assert "patient-0-unknown-scenario" in result.failures


def test_coverage_claim_must_match_actual_patient_assignments():
    packet = _packet()
    packet["coverage"]["multiple_conditions"]["selected_patients"] = 2
    result = verify_review_packet_policy(
        packet=packet,
        verification=_verification(),
    )
    assert any(
        item.startswith("coverage-multiple_conditions-required-1-actual-1-reported-2")
        for item in result.failures
    )

    packet = _packet()
    packet["patients"][0]["scenarios"].append({"key": "severe_allergy"})
    result = verify_review_packet_policy(
        packet=packet,
        verification=_verification(),
    )
    assert "coverage-severe_allergy-zero-eligible-inconsistent" in result.failures


def test_discrepancy_cannot_be_resolved_after_signoff_or_before_packet():
    packet = _packet()
    reviewed = datetime.fromisoformat(packet["signoff_template"]["reviewed_at"])
    generated = datetime.fromisoformat(packet["generated_at"])
    packet["signoff_template"]["discrepancies"] = [
        {
            "id": "D-1",
            "description": "اختلاف تست",
            "resolution_note": "اصلاح شد",
            "resolved_at": (reviewed + timedelta(minutes=1)).isoformat(),
        },
        {
            "id": "D-2",
            "description": "اختلاف قدیمی",
            "resolution_note": "اصلاح شد",
            "resolved_at": (generated - timedelta(minutes=1)).isoformat(),
        },
    ]
    result = verify_review_packet_policy(
        packet=packet,
        verification=_verification(),
    )
    assert "discrepancy-0-resolved-after-signoff" in result.failures
    assert "discrepancy-1-resolved-before-packet" in result.failures


def test_missing_verification_timestamp_is_warning_not_silent_failure():
    result = verify_review_packet_policy(packet=_packet(), verification={})
    assert result.passed is True
    assert result.status == "warning"
    assert result.warnings == ["verification-report-has-no-generated-at"]
