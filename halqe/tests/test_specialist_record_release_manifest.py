"""Final artifact-chain release manifest tests."""
from __future__ import annotations

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
    SpecialistRecordClinicianSignoffVerifier,
)
from clinical.specialist_record_release_manifest import (
    SpecialistRecordReleaseManifestBuilder,
    SpecialistRecordReleaseManifestError,
)
from clinical.specialist_record_review_database import ReviewPatientBindingResult


SOURCE_ID = "release-manifest-test-source"
MANIFEST_HASH = "d" * 64
COMMIT_SHA = "e" * 40
IMAGE_DIGEST = "sha256:" + "f" * 64
PATIENT_UUID = "00000000-0000-0000-0000-000000000202"


@pytest.fixture(autouse=True)
def _artifact_chain_uses_controlled_database_binding(monkeypatch):
    """Release hash-chain tests mock only the already integration-tested DB hop."""

    def verified_binding(*, packet, source_id, tenant_id):
        patients = packet.get("patients") if isinstance(packet, dict) else []
        count = len(patients) if isinstance(patients, list) else 0
        return ReviewPatientBindingResult(
            passed=count > 0,
            checked_patients=count,
            failures=[] if count > 0 else ["patient-sample-empty"],
        )

    monkeypatch.setattr(
        "clinical.specialist_record_clinician_signoff.verify_review_patient_bindings",
        verified_binding,
    )


def _write_json(path: Path, payload: dict) -> Path:
    return write_private_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _verification(source_hash: str) -> dict:
    return {
        "decision": "GO",
        "source_id": SOURCE_ID,
        "tenant_id": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_file_sha256": source_hash,
        "source_manifest_sha256": MANIFEST_HASH,
        "summary": {"passed": 10, "warnings": 0, "failed": 0},
        "checks": [
            {"key": "apply", "status": "pass", "detail": "ok"},
            {"key": "replay", "status": "pass", "detail": "ok"},
            {"key": "ledger", "status": "pass", "detail": "ok"},
        ],
    }


def _import_report(source_hash: str, *, replay: bool) -> dict:
    return {
        "mode": "apply",
        "transaction_status": "committed",
        "source_id": SOURCE_ID,
        "tenant_id": 1,
        "source_file_sha256": source_hash,
        "source_manifest_sha256": MANIFEST_HASH,
        "error": None,
        "tables": {
            "patient_links": {
                "source_rows": 1,
                "inserted": 0 if replay else 1,
                "reused": 0,
                "replayed": 1 if replay else 0,
                "skipped": 0,
            },
            "medical_history": {
                "source_rows": 1,
                "inserted": 0 if replay else 1,
                "reused": 0,
                "replayed": 1 if replay else 0,
                "skipped": 0,
            },
        },
    }


def _packet(source_hash: str, verification_raw: bytes) -> dict:
    generated_at = datetime.now(UTC).isoformat()
    return {
        "source_id": SOURCE_ID,
        "tenant_id": 1,
        "generated_at": generated_at,
        "verification_report_sha256": hashlib.sha256(verification_raw).hexdigest(),
        "source_file_sha256": source_hash,
        "source_manifest_sha256": MANIFEST_HASH,
        "per_scenario": 1,
        "max_patients": 25,
        "scenarios": [
            {"key": "multiple_conditions", "label": "چند بیماری"},
            {"key": "medication_timeline", "label": "چرخه دارویی"},
        ],
        "coverage": {
            "multiple_conditions": {
                "eligible_patients": 1,
                "selected_patients": 1,
                "status": "covered",
            },
            "medication_timeline": {
                "eligible_patients": 1,
                "selected_patients": 1,
                "status": "covered",
            },
        },
        "patients": [
            {
                "source_patient_link_id": 10,
                "target_patient_link_id": 20,
                "patient_uuid": PATIENT_UUID,
                "cockpit_path": f"/patients/{PATIENT_UUID}",
                "scenarios": [
                    {"key": "multiple_conditions", "label": "چند بیماری"},
                    {"key": "medication_timeline", "label": "چرخه دارویی"},
                ],
                "feature_counts": {"conditions": 2, "medication_events": 3},
                "review_checklist": ["بیماری‌ها", "چرخه دارویی"],
                "review_status": "approved",
                "review_notes": "تطبیق شد.",
            }
        ],
        "warnings": [],
        "signoff_template": {
            "reviewed_by": "doctor-release-reviewer",
            "reviewed_at": generated_at,
            "decision": "approved",
            "acknowledged_warnings": [],
            "discrepancies": [],
        },
    }


def _chain(tmp_path: Path) -> dict[str, Path]:
    source = tmp_path / "specialist-snapshot.db"
    source.write_bytes(b"SQLite format 3\x00release-manifest-test")
    os.chmod(source, 0o600)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    apply = _write_json(tmp_path / "apply.json", _import_report(source_hash, replay=False))
    replay = _write_json(tmp_path / "replay.json", _import_report(source_hash, replay=True))
    verification = _write_json(tmp_path / "verification.json", _verification(source_hash))
    packet = _write_json(
        tmp_path / "review-packet.json",
        _packet(source_hash, verification.read_bytes()),
    )
    signoff_result = SpecialistRecordClinicianSignoffVerifier(
        review_packet_path=packet,
        verification_report_path=verification,
        source_id=SOURCE_ID,
        tenant_id=1,
    ).run()
    assert signoff_result.decision == "GO"
    signoff = _write_json(tmp_path / "clinician-signoff.json", signoff_result.to_dict())
    return {
        "source": source,
        "apply": apply,
        "replay": replay,
        "verification": verification,
        "packet": packet,
        "signoff": signoff,
    }


def _builder(paths: dict[str, Path]) -> SpecialistRecordReleaseManifestBuilder:
    return SpecialistRecordReleaseManifestBuilder(
        source_snapshot_path=paths["source"],
        apply_report_path=paths["apply"],
        replay_report_path=paths["replay"],
        verification_report_path=paths["verification"],
        review_packet_path=paths["packet"],
        clinician_signoff_report_path=paths["signoff"],
        source_id=SOURCE_ID,
        tenant_id=1,
        git_commit=COMMIT_SHA,
        image_digest=IMAGE_DIGEST,
    )


def test_complete_hash_chain_produces_go_manifest(tmp_path):
    paths = _chain(tmp_path)
    result = _builder(paths).run()

    assert result.decision == "GO"
    assert result.git_commit == COMMIT_SHA
    assert result.image_digest == IMAGE_DIGEST
    assert result.selected_patient_count == 1
    assert result.summary["failed"] == 0
    assert len(result.release_id) == 64
    assert set(result.artifact_sha256) == {
        "apply_report",
        "replay_report",
        "verification_report",
        "review_packet",
        "clinician_signoff_report",
    }


def test_source_snapshot_mutation_after_reports_is_no_go(tmp_path):
    paths = _chain(tmp_path)
    paths["source"].write_bytes(paths["source"].read_bytes() + b"changed")
    os.chmod(paths["source"], 0o600)

    result = _builder(paths).run()
    assert result.decision == "NO_GO"
    assert next(
        item for item in result.checks if item.key == "source_snapshot_hash_chain"
    ).status == "fail"


def test_packet_mutation_after_saved_signoff_is_no_go(tmp_path):
    paths = _chain(tmp_path)
    packet = json.loads(paths["packet"].read_text(encoding="utf-8"))
    packet["patients"][0]["review_notes"] = "تغییر پس از sign-off"
    _write_json(paths["packet"], packet)

    result = _builder(paths).run()
    assert result.decision == "NO_GO"
    assert next(
        item
        for item in result.checks
        if item.key == "clinician_signoff_artifact_binding"
    ).status == "fail"


def test_replay_with_new_insert_is_no_go(tmp_path):
    paths = _chain(tmp_path)
    replay = json.loads(paths["replay"].read_text(encoding="utf-8"))
    replay["tables"]["medical_history"]["inserted"] = 1
    _write_json(paths["replay"], replay)

    result = _builder(paths).run()
    assert result.decision == "NO_GO"
    assert next(
        item for item in result.checks if item.key == "replay_zero_inserts"
    ).status == "fail"


def test_claimed_coverage_without_patient_assignment_is_no_go(tmp_path):
    paths = _chain(tmp_path)
    packet = json.loads(paths["packet"].read_text(encoding="utf-8"))
    packet["patients"][0]["scenarios"] = [
        {"key": "multiple_conditions", "label": "چند بیماری"}
    ]
    _write_json(paths["packet"], packet)

    fresh_signoff = SpecialistRecordClinicianSignoffVerifier(
        review_packet_path=paths["packet"],
        verification_report_path=paths["verification"],
        source_id=SOURCE_ID,
        tenant_id=1,
    ).run()
    assert fresh_signoff.decision == "NO_GO"
    assert next(
        item for item in fresh_signoff.checks if item.key == "review_packet_policy"
    ).status == "fail"
    _write_json(paths["signoff"], fresh_signoff.to_dict())

    result = _builder(paths).run()
    assert result.decision == "NO_GO"
    assert next(
        item for item in result.checks if item.key == "fresh_clinician_verification"
    ).status == "fail"
    detail = next(
        item for item in result.checks if item.key == "actual_scenario_coverage"
    )
    assert detail.status == "fail"
    assert "medication_timeline" in detail.detail


def test_invalid_commit_or_public_source_is_rejected_before_manifest(tmp_path):
    paths = _chain(tmp_path)
    builder = SpecialistRecordReleaseManifestBuilder(
        source_snapshot_path=paths["source"],
        apply_report_path=paths["apply"],
        replay_report_path=paths["replay"],
        verification_report_path=paths["verification"],
        review_packet_path=paths["packet"],
        clinician_signoff_report_path=paths["signoff"],
        source_id=SOURCE_ID,
        tenant_id=1,
        git_commit="short",
    )
    with pytest.raises(SpecialistRecordReleaseManifestError, match="40-character"):
        builder.run()

    os.chmod(paths["source"], 0o644)
    with pytest.raises(SpecialistRecordReleaseManifestError, match="owner-only"):
        _builder(paths).run()


def test_manifest_command_writes_private_go_and_no_go_outputs(tmp_path):
    paths = _chain(tmp_path)
    output = tmp_path / "release" / "manifest-go.json"
    stdout = StringIO()
    call_command(
        "build_specialist_record_release_manifest",
        sqlite=str(paths["source"]),
        apply_report=str(paths["apply"]),
        replay_report=str(paths["replay"]),
        verification_report=str(paths["verification"]),
        review_packet=str(paths["packet"]),
        clinician_signoff_report=str(paths["signoff"]),
        source_id=SOURCE_ID,
        tenant_id=1,
        git_commit=COMMIT_SHA,
        image_digest=IMAGE_DIGEST,
        report=str(output),
        stdout=stdout,
        verbosity=0,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["decision"] == "GO"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert "release manifest GO" in stdout.getvalue()
    assert PATIENT_UUID not in stdout.getvalue()

    replay = json.loads(paths["replay"].read_text(encoding="utf-8"))
    replay["tables"]["patient_links"]["inserted"] = 1
    _write_json(paths["replay"], replay)
    no_go = tmp_path / "release" / "manifest-no-go.json"
    with pytest.raises(CommandError, match="NO_GO"):
        call_command(
            "build_specialist_record_release_manifest",
            sqlite=str(paths["source"]),
            apply_report=str(paths["apply"]),
            replay_report=str(paths["replay"]),
            verification_report=str(paths["verification"]),
            review_packet=str(paths["packet"]),
            clinician_signoff_report=str(paths["signoff"]),
            source_id=SOURCE_ID,
            tenant_id=1,
            git_commit=COMMIT_SHA,
            report=str(no_go),
            verbosity=0,
        )
    assert json.loads(no_go.read_text(encoding="utf-8"))["decision"] == "NO_GO"
