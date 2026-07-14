"""End-to-end database binding for the public clinician sign-off verifier."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import uuid

from django.db import connection
import pytest

from clinical.secure_report_io import write_private_text
from clinical.specialist_record_clinician_signoff import (
    SpecialistRecordClinicianSignoffVerifier,
)
from platform_core.tenant_context import set_tenant_guc


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_signoff_is_no_go_until_packet_patient_is_bound_to_durable_ledger(
    seed_data,
    tmp_path,
):
    source_id = f"signoff-live-binding-{uuid.uuid4().hex}"
    source_hash = "a" * 64
    manifest_hash = "b" * 64
    verified_at = datetime.now(UTC) - timedelta(minutes=2)
    reviewed_at = datetime.now(UTC) - timedelta(minutes=1)

    verification_payload = {
        "decision": "GO",
        "source_id": source_id,
        "tenant_id": 1,
        "generated_at": verified_at.isoformat(),
        "source_file_sha256": source_hash,
        "source_manifest_sha256": manifest_hash,
        "summary": {"passed": 2, "warnings": 0, "failed": 0},
        "checks": [
            {"key": "mechanical", "status": "pass", "detail": "ok"},
            {"key": "clinical", "status": "pass", "detail": "ok"},
        ],
    }
    verification = write_private_text(
        tmp_path / "verification.json",
        json.dumps(verification_payload, sort_keys=True) + "\n",
    )
    packet_payload = {
        "source_id": source_id,
        "tenant_id": 1,
        "generated_at": reviewed_at.isoformat(),
        "verification_report_sha256": hashlib.sha256(
            verification.read_bytes()
        ).hexdigest(),
        "source_file_sha256": source_hash,
        "source_manifest_sha256": manifest_hash,
        "per_scenario": 1,
        "max_patients": 5,
        "scenarios": [
            {"key": "laboratory_result", "label": "نتیجه آزمایش"}
        ],
        "coverage": {
            "laboratory_result": {
                "eligible_patients": 1,
                "selected_patients": 1,
                "status": "covered",
            }
        },
        "patients": [
            {
                "source_patient_link_id": 7001,
                "target_patient_link_id": seed_data["link_id"],
                "patient_uuid": str(seed_data["patient_uuid"]),
                "cockpit_path": f"/patients/{seed_data['patient_uuid']}",
                "scenarios": [
                    {"key": "laboratory_result", "label": "نتیجه آزمایش"}
                ],
                "feature_counts": {"lab_count": 1},
                "review_checklist": ["نتیجه و محدوده مرجع تطبیق شد."],
                "review_status": "approved",
                "review_notes": "تطبیق کامل بود.",
            }
        ],
        "warnings": [],
        "signoff_template": {
            "reviewed_by": "doctor-integration-reviewer",
            "reviewed_at": reviewed_at.isoformat(),
            "decision": "approved",
            "acknowledged_warnings": [],
            "discrepancies": [],
        },
    }
    packet = write_private_text(
        tmp_path / "packet.json",
        json.dumps(packet_payload, ensure_ascii=False, sort_keys=True) + "\n",
    )

    verifier = lambda: SpecialistRecordClinicianSignoffVerifier(
        review_packet_path=packet,
        verification_report_path=verification,
        source_id=source_id,
        tenant_id=1,
    ).run()

    missing = verifier()
    assert missing.decision == "NO_GO"
    binding = next(
        item for item in missing.checks if item.key == "patient_database_binding"
    )
    assert binding.status == "fail"
    assert "ledger-missing" in binding.detail

    set_tenant_guc(1)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO clinical.record_import_ledger
                (tenant_id, source_id, source_table, source_row_id,
                 target_table, target_row_id, target_key,
                 payload_sha256, imported_by)
            VALUES (1, %s, 'patient_links', 7001,
                    'clinical.patient_links', %s, %s, %s,
                    'signoff-integration-test')
            """,
            [
                source_id,
                seed_data["link_id"],
                f"id:{seed_data['link_id']}",
                "c" * 64,
            ],
        )

    bound = verifier()
    assert bound.decision == "GO"
    assert bound.summary["failed"] == 0
    assert next(
        item for item in bound.checks if item.key == "patient_database_binding"
    ).status == "pass"
    assert next(
        item for item in bound.checks if item.key == "review_packet_policy"
    ).status == "pass"
