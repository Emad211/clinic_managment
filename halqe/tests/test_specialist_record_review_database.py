"""PostgreSQL binding tests for clinician review packet patient identities."""
from __future__ import annotations

import uuid

from django.db import connection
import pytest

from clinical.specialist_record_review_database import (
    verify_review_patient_bindings,
)
from platform_core.tenant_context import set_tenant_guc



def _insert_ledger(
    *,
    source_id: str,
    source_row_id: int,
    target_row_id: int,
    target_table: str = "clinical.patient_links",
) -> None:
    set_tenant_guc(1)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO clinical.record_import_ledger
                (tenant_id, source_id, source_table, source_row_id,
                 target_table, target_row_id, target_key,
                 payload_sha256, imported_by)
            VALUES (1, %s, 'patient_links', %s, %s, %s, NULL, %s,
                    'review-binding-test')
            """,
            [
                source_id,
                source_row_id,
                target_table,
                target_row_id,
                "a" * 64,
            ],
        )



def _packet(seed_data, *, source_row_id: int, target_id: int, patient_uuid: str):
    return {
        "patients": [
            {
                "source_patient_link_id": source_row_id,
                "target_patient_link_id": target_id,
                "patient_uuid": patient_uuid,
                "cockpit_path": f"/patients/{patient_uuid}",
            }
        ]
    }


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_packet_patient_matches_ledger_link_and_accounting_uuid(seed_data):
    source_id = f"review-binding-{uuid.uuid4().hex}"
    source_row_id = 701
    _insert_ledger(
        source_id=source_id,
        source_row_id=source_row_id,
        target_row_id=seed_data["link_id"],
    )

    result = verify_review_patient_bindings(
        packet=_packet(
            seed_data,
            source_row_id=source_row_id,
            target_id=seed_data["link_id"],
            patient_uuid=str(seed_data["patient_uuid"]),
        ),
        source_id=source_id,
        tenant_id=1,
    )
    assert result.passed is True
    assert result.checked_patients == 1
    assert result.failures == []


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_packet_target_id_cannot_differ_from_import_ledger(seed_data):
    source_id = f"review-binding-{uuid.uuid4().hex}"
    source_row_id = 702
    _insert_ledger(
        source_id=source_id,
        source_row_id=source_row_id,
        target_row_id=seed_data["link_id"],
    )

    result = verify_review_patient_bindings(
        packet=_packet(
            seed_data,
            source_row_id=source_row_id,
            target_id=seed_data["link_id"] + 999999,
            patient_uuid=str(seed_data["patient_uuid"]),
        ),
        source_id=source_id,
        tenant_id=1,
    )
    assert result.passed is False
    assert result.failures == [f"source-{source_row_id}:ledger-target-id"]


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_packet_uuid_cannot_be_replaced_before_clinician_signoff(seed_data):
    source_id = f"review-binding-{uuid.uuid4().hex}"
    source_row_id = 703
    _insert_ledger(
        source_id=source_id,
        source_row_id=source_row_id,
        target_row_id=seed_data["link_id"],
    )

    result = verify_review_patient_bindings(
        packet=_packet(
            seed_data,
            source_row_id=source_row_id,
            target_id=seed_data["link_id"],
            patient_uuid="00000000-0000-0000-0000-000000000999",
        ),
        source_id=source_id,
        tenant_id=1,
    )
    assert result.passed is False
    assert result.failures == [
        f"source-{source_row_id}:accounting-uuid-mismatch"
    ]


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_missing_or_wrong_target_table_ledger_rows_fail_closed(seed_data):
    source_id = f"review-binding-{uuid.uuid4().hex}"
    missing = verify_review_patient_bindings(
        packet=_packet(
            seed_data,
            source_row_id=704,
            target_id=seed_data["link_id"],
            patient_uuid=str(seed_data["patient_uuid"]),
        ),
        source_id=source_id,
        tenant_id=1,
    )
    assert missing.passed is False
    assert missing.failures == ["source-704:ledger-missing"]

    _insert_ledger(
        source_id=source_id,
        source_row_id=705,
        target_row_id=seed_data["link_id"],
        target_table="clinical.medical_history",
    )
    wrong = verify_review_patient_bindings(
        packet=_packet(
            seed_data,
            source_row_id=705,
            target_id=seed_data["link_id"],
            patient_uuid=str(seed_data["patient_uuid"]),
        ),
        source_id=source_id,
        tenant_id=1,
    )
    assert wrong.passed is False
    assert wrong.failures == ["source-705:ledger-target-table"]
