"""Release-level clinician sign-off verification tests."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import stat

from django.core.management import call_command
from django.core.management.base import CommandError
import pytest

from clinical.secure_report_io import write_private_text
from clinical.specialist_record_clinician_signoff import (
    SpecialistRecordClinicianSignoffError,
    SpecialistRecordClinicianSignoffVerifier,
)


SOURCE_ID = "clinician-signoff-test-source"
SOURCE_HASH = "a" * 64
MANIFEST_HASH = "b" * 64
PATIENT_UUID = "00000000-0000-0000-0000-000000000101"


def _verification_payload() -> dict:
    return {
        "decision": "GO",
        "source_id": SOURCE_ID,
        "tenant_id": 1,
        "source_file_sha256": SOURCE_HASH,
        "source_manifest_sha256": MANIFEST_HASH,
        "summary": {"passed": 12, "warnings": 0, "failed": 0},
        "checks": [
            {"key": "apply_report_contract", "status": "pass", "detail": "ok"},
            {"key": "replay_idempotency", "status": "pass", "detail": "ok"},
            {"key": "source_manifest", "status": "pass", "detail": "ok"},
            {"key": "ledger_targets", "status": "pass", "detail": "ok"},
            {"key": "target_fingerprints", "status": "pass", "detail": "ok"},
            {"key": "self_reports_unverified", "status": "pass", "detail": "ok"},
            {"key": "labs_in_observations", "status": "pass", "detail": "ok"},
        ],
    }


def _write_json(path: Path, payload: dict) -> Path:
    return write_private_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _packet_payload(verification_raw: bytes) -> dict:
    return {
        "source_id": SOURCE_ID,
        "tenant_id": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "verification_report_sha256": hashlib.sha256(verification_raw).hexdigest(),
        "source_file_sha256": SOURCE_HASH,
        "source_manifest_sha256": MANIFEST_HASH,
        "per_scenario": 1,
        "max_patients": 25,
        "scenarios": [
            {
                "key": "multiple_conditions",
                "label": "چند بیماری مزمن",
                "description": "بیماری‌های فعال با مبدأ مقایسه شود.",
            },
            {
                "key": "severe_allergy",
                "label": "حساسیت شدید",
                "description": "حساسیت شدید در این snapshot وجود ندارد.",
            },
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
                "source_patient_link_id": 1001,
                "target_patient_link_id": 501,
                "patient_uuid": PATIENT_UUID,
                "cockpit_path": f"/patients/{PATIENT_UUID}",
                "scenarios": [
                    {"key": "multiple_conditions", "label": "چند بیماری مزمن"}
                ],
                "feature_counts": {"conditions": 2},
                "review_checklist": ["بیماری‌های فعال با مبدأ مقایسه شود."],
                "review_status": "approved",
                "review_notes": "نمایش با مبدأ تطبیق شد.",
            }
        ],
        "warnings": [],
        "signoff_template": {
            "reviewed_by": "doctor-reviewer",
            "reviewed_at": datetime.now(UTC).isoformat(),
            "decision": "approved",
            "acknowledged_warnings": [],
            "discrepancies": [],
        },
    }


def _artifacts(tmp_path: Path) -> tuple[Path, Path, dict]:
    verification = _write_json(
        tmp_path / "verification-go.json", _verification_payload()
    )
    packet_payload = _packet_payload(verification.read_bytes())
    packet = _write_json(tmp_path / "clinician-packet.json", packet_payload)
    return verification, packet, packet_payload


def _run(verification: Path, packet: Path):
    return SpecialistRecordClinicianSignoffVerifier(
        review_packet_path=packet,
        verification_report_path=verification,
        source_id=SOURCE_ID,
        tenant_id=1,
    ).run()


def test_completed_packet_produces_release_go(tmp_path):
    verification, packet, _payload = _artifacts(tmp_path)
    result = _run(verification, packet)

    assert result.decision == "GO"
    assert result.selected_patient_count == 1
    assert result.covered_scenario_count == 1
    assert result.discrepancy_count == 0
    assert result.summary["failed"] == 0
    assert all(item.status == "pass" for item in result.checks)


def test_pending_patient_is_no_go(tmp_path):
    verification, packet, payload = _artifacts(tmp_path)
    payload["patients"][0]["review_status"] = "pending"
    _write_json(packet, payload)

    result = _run(verification, packet)
    assert result.decision == "NO_GO"
    check = next(item for item in result.checks if item.key == "patient_reviews_complete")
    assert check.status == "fail"
    assert "review_status=pending" in check.detail


def test_packet_hash_mismatch_is_no_go(tmp_path):
    verification, packet, payload = _artifacts(tmp_path)
    payload["verification_report_sha256"] = "0" * 64
    _write_json(packet, payload)

    result = _run(verification, packet)
    assert result.decision == "NO_GO"
    assert next(
        item for item in result.checks if item.key == "verification_report_binding"
    ).status == "fail"


def test_unacknowledged_warning_is_no_go(tmp_path):
    verification, packet, payload = _artifacts(tmp_path)
    payload["warnings"] = ["One scenario required an operational waiver."]
    _write_json(packet, payload)

    result = _run(verification, packet)
    assert result.decision == "NO_GO"
    assert next(
        item for item in result.checks if item.key == "warning_acknowledgement"
    ).status == "fail"

    payload["signoff_template"]["acknowledged_warnings"] = list(payload["warnings"])
    _write_json(packet, payload)
    assert _run(verification, packet).decision == "GO"


def test_major_or_critical_discrepancy_must_be_fixed(tmp_path):
    verification, packet, payload = _artifacts(tmp_path)
    discrepancy = {
        "id": "D-001",
        "severity": "major",
        "domain": "medication",
        "description": "دوز نمایش‌داده‌شده با مبدأ متفاوت است.",
        "disposition": "accepted_risk",
        "owner": "migration-team",
        "resolution_note": "پذیرفته شد",
        "resolved_at": datetime.now(UTC).isoformat(),
    }
    payload["signoff_template"]["discrepancies"] = [discrepancy]
    _write_json(packet, payload)

    result = _run(verification, packet)
    assert result.decision == "NO_GO"
    assert "must-be-fixed" in next(
        item for item in result.checks if item.key == "discrepancy_disposition"
    ).detail

    discrepancy["disposition"] = "fixed"
    discrepancy["resolution_note"] = "داده اصلاح و دوباره بررسی شد."
    _write_json(packet, payload)
    assert _run(verification, packet).decision == "GO"


def test_direct_patient_identity_key_is_rejected(tmp_path):
    verification, packet, payload = _artifacts(tmp_path)
    payload["patients"][0]["national_id"] = "0013546759"
    _write_json(packet, payload)

    result = _run(verification, packet)
    assert result.decision == "NO_GO"
    assert next(
        item for item in result.checks if item.key == "phi_minimized_packet"
    ).status == "fail"


def test_non_owner_only_input_is_rejected_before_decision(tmp_path):
    verification, packet, _payload = _artifacts(tmp_path)
    os.chmod(packet, 0o644)

    with pytest.raises(
        SpecialistRecordClinicianSignoffError, match="owner-only"
    ):
        _run(verification, packet)


def test_underlying_verifier_failure_cannot_be_hidden_by_approved_packet(tmp_path):
    verification_payload = _verification_payload()
    verification_payload["decision"] = "NO_GO"
    verification_payload["summary"]["failed"] = 1
    verification_payload["checks"][0]["status"] = "fail"
    verification = _write_json(tmp_path / "verification-no-go.json", verification_payload)
    packet = _write_json(
        tmp_path / "approved-but-invalid.json",
        _packet_payload(verification.read_bytes()),
    )

    result = _run(verification, packet)
    assert result.decision == "NO_GO"
    assert next(
        item for item in result.checks if item.key == "verification_decision"
    ).status == "fail"
    assert next(
        item for item in result.checks if item.key == "verification_checks_nonfailing"
    ).status == "fail"


def test_management_command_writes_private_go_and_no_go_reports(tmp_path):
    verification, packet, payload = _artifacts(tmp_path)
    output = tmp_path / "decisions" / "clinician-go.json"
    stdout = StringIO()

    call_command(
        "verify_specialist_record_clinician_signoff",
        review_packet=str(packet),
        verification_report=str(verification),
        source_id=SOURCE_ID,
        tenant_id=1,
        report=str(output),
        stdout=stdout,
        verbosity=0,
    )
    assert json.loads(output.read_text(encoding="utf-8"))["decision"] == "GO"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert "Specialist clinician sign-off GO" in stdout.getvalue()
    assert PATIENT_UUID not in stdout.getvalue()

    payload["patients"][0]["review_status"] = "pending"
    _write_json(packet, payload)
    no_go_output = tmp_path / "decisions" / "clinician-no-go.json"
    with pytest.raises(CommandError, match="NO_GO"):
        call_command(
            "verify_specialist_record_clinician_signoff",
            review_packet=str(packet),
            verification_report=str(verification),
            source_id=SOURCE_ID,
            tenant_id=1,
            report=str(no_go_output),
            verbosity=0,
        )
    assert json.loads(no_go_output.read_text(encoding="utf-8"))["decision"] == "NO_GO"
