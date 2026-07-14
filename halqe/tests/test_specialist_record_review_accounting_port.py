"""Boundary tests for clinician sample accounting identity access."""
from __future__ import annotations

import uuid

from django.db import connection
import pytest

from accounting_port.review import get_accounting_patient_uuids_for_review
from clinical.specialist_record_review_sample import SpecialistRecordReviewSampler
from platform_core.tenant_context import set_tenant_guc


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_batch_accounting_review_port_is_tenant_scoped(seed_data):
    found = get_accounting_patient_uuids_for_review(
        accounting_patient_ids=[seed_data["patient_id"], -1, "bad"],
        tenant_id=1,
    )
    assert found == {
        seed_data["patient_id"]: str(seed_data["patient_uuid"]),
    }
    assert get_accounting_patient_uuids_for_review(
        accounting_patient_ids=[seed_data["patient_id"]],
        tenant_id=2,
    ) == {}


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_sampler_uses_accounting_port_result_not_direct_accounting_join(
    seed_data,
    tmp_path,
    monkeypatch,
):
    source_id = f"review-port-{uuid.uuid4().hex}"
    source_row_id = 8101
    set_tenant_guc(1)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO clinical.record_import_ledger
                (tenant_id, source_id, source_table, source_row_id,
                 target_table, target_row_id, target_key, payload_sha256,
                 target_payload_columns, target_payload_sha256, imported_by)
            VALUES (1, %s, 'patient_links', %s,
                    'clinical.patient_links', %s, %s, %s,
                    ARRAY['tenant_id','patient_id','is_active']::text[], %s,
                    'review-port-test')
            """,
            [
                source_id,
                source_row_id,
                seed_data["link_id"],
                f"id:{seed_data['link_id']}",
                "a" * 64,
                "b" * 64,
            ],
        )

    fake_uuid = "00000000-0000-0000-0000-000000008101"
    calls = []

    def fake_batch(*, accounting_patient_ids, tenant_id):
        ids = list(accounting_patient_ids)
        calls.append((ids, tenant_id))
        return {seed_data["patient_id"]: fake_uuid}

    monkeypatch.setattr(
        "clinical.specialist_record_review_sample.get_accounting_patient_uuids_for_review",
        fake_batch,
    )
    sampler = SpecialistRecordReviewSampler(
        verification_report_path=tmp_path / "not-needed-for-candidate-load.json",
        source_id=source_id,
        tenant_id=1,
    )
    candidates = sampler._load_candidates()

    assert calls == [([seed_data["patient_id"]], 1)]
    assert len(candidates) == 1
    assert candidates[0].source_patient_link_id == source_row_id
    assert candidates[0].target_patient_link_id == seed_data["link_id"]
    assert candidates[0].patient_uuid == fake_uuid
