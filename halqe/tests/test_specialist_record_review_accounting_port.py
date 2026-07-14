"""Boundary tests for record migration/review accounting identity access."""
from __future__ import annotations

import uuid

from django.db import connection
import pytest

from accounting_port.review import (
    AccountingPatientResolution,
    get_accounting_patient_uuids_for_review,
    resolve_accounting_patient_for_record_import,
)
from clinical.specialist_record_import import (
    ImportConflictError,
    SpecialistRecordImporter,
)
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
def test_import_resolution_uses_exact_accounting_id_and_national_id(seed_data):
    by_id = resolve_accounting_patient_for_record_import(
        tenant_id=1,
        accounting_patient_id=seed_data["patient_id"],
    )
    assert by_id.patient_id == seed_data["patient_id"]
    assert by_id.conflict is False

    by_national = resolve_accounting_patient_for_record_import(
        tenant_id=1,
        national_id="1234567890",
    )
    assert by_national.patient_id == seed_data["patient_id"]

    both = resolve_accounting_patient_for_record_import(
        tenant_id=1,
        accounting_patient_id=seed_data["patient_id"],
        national_id="1234567890",
    )
    assert both.patient_id == seed_data["patient_id"]


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


def test_importer_uses_redacted_accounting_port_conflict(monkeypatch, tmp_path):
    secret_national_id = "0013546759"
    monkeypatch.setattr(
        "clinical.specialist_record_import.resolve_accounting_patient_for_record_import",
        lambda **_kwargs: AccountingPatientResolution(
            by_accounting_id=10,
            by_national_id=20,
        ),
    )
    importer = SpecialistRecordImporter(
        sqlite_path=tmp_path / "not-opened.db",
        source_id="redacted-accounting-resolution",
        tenant_id=1,
        apply=False,
    )

    with pytest.raises(ImportConflictError) as captured:
        importer._resolve_accounting_patient(
            {
                "id": 77,
                "accounting_patient_id": 10,
                "national_id": secret_national_id,
            }
        )
    message = str(captured.value)
    assert "patient_links#77" in message
    assert secret_national_id not in message
    assert "10" not in message
    assert "20" not in message
