"""Normalization regressions for clinician-review identity protection."""
from __future__ import annotations

from clinical.specialist_record_clinician_signoff import (
    _review_identity_key_failures,
    _review_text_phi_failures,
)


def test_recursive_key_guard_rejects_punctuation_and_camel_case_variants():
    packet = {
        "patients": [
            {
                "patient_uuid": "00000000-0000-0000-0000-000000000001",
                "source_patient_link_id": 1,
                "nested": {
                    "national-id": "redacted",
                    "patientFullName": "redacted",
                },
            }
        ],
        "signoff_template": {
            "discrepancies": [
                {"کد-ملی": "redacted"},
                {"شماره‌موبایل": "redacted"},
            ]
        },
    }

    failures = _review_identity_key_failures(packet)
    assert any("national-id" in item for item in failures)
    assert any("patientFullName" in item for item in failures)
    assert any("کد-ملی" in item for item in failures)
    assert any("شماره‌موبایل" in item for item in failures)
    assert not any(item.endswith("patient_uuid") for item in failures)
    assert not any(item.endswith("source_patient_link_id") for item in failures)


def test_formatted_plus98_mobile_with_persian_digits_is_rejected():
    packet = {
        "patients": [
            {
                "review_notes": "تماس با +۹۸ (۹۱۲) ۱۲۳-۴۵۶۷ انجام شد.",
            }
        ]
    }
    failures = _review_text_phi_failures(packet)
    assert failures == ["patient-0-review-notes-contains-mobile"]


def test_separated_persian_national_id_is_rejected():
    packet = {
        "signoff_template": {
            "discrepancies": [
                {
                    "description": "شناسه در مبدأ ۰۰۱-۳۵۴-۶۷۵۹ بود.",
                    "resolution_note": "حذف شد.",
                }
            ]
        }
    }
    failures = _review_text_phi_failures(packet)
    assert failures == ["discrepancy-0-description-contains-national-id"]
