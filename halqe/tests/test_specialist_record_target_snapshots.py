"""Target-content fingerprint tests for the specialist import ledger."""
from __future__ import annotations

from io import StringIO
import json
import uuid

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
import pytest

from clinical.secure_report_io import write_private_text
from clinical.specialist_record_import import SpecialistRecordImporter
from clinical.specialist_record_target_snapshots import verify_target_snapshots
from platform_core.tenant_context import set_tenant_guc
from tests.test_specialist_record_import import _build_source


def _apply_and_report(source, source_id: str, tmp_path):
    first = SpecialistRecordImporter(
        sqlite_path=source,
        source_id=source_id,
        tenant_id=1,
        apply=True,
    ).run()
    replay = SpecialistRecordImporter(
        sqlite_path=source,
        source_id=source_id,
        tenant_id=1,
        apply=True,
    ).run()
    apply_path = write_private_text(
        tmp_path / "snapshot-apply.json",
        json.dumps(first.to_dict(), ensure_ascii=False, sort_keys=True) + "\n",
    )
    replay_path = write_private_text(
        tmp_path / "snapshot-replay.json",
        json.dumps(replay.to_dict(), ensure_ascii=False, sort_keys=True) + "\n",
    )
    return apply_path, replay_path


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_every_new_ledger_row_has_a_verifiable_target_snapshot(seed_data, tmp_path):
    suffix = uuid.uuid4().hex
    source_id = f"target-snapshot-complete-{suffix}"
    source = _build_source(
        tmp_path / "target-snapshot-complete.db",
        accounting_patient_id=seed_data["patient_id"],
        suffix=suffix,
    )
    _apply_and_report(source, source_id, tmp_path)

    result = verify_target_snapshots(tenant_id=1, source_id=source_id)
    assert result.status == "pass"
    assert result.metrics["ledger_rows"] == result.metrics["checked"]

    set_tenant_guc(1)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*),
                   COUNT(*) FILTER (
                       WHERE target_payload_sha256 IS NULL
                          OR cardinality(target_payload_columns)=0
                   ),
                   COUNT(*) FILTER (
                       WHERE target_table='clinical.condition_lab_tests'
                         AND target_row_id IS NULL
                   )
            FROM clinical.record_import_ledger
            WHERE tenant_id=1 AND source_id=%s
            """,
            [source_id],
        )
        total, missing_fingerprint, natural_targets = cursor.fetchone()
    assert total > 10
    assert missing_fingerprint == 0
    assert natural_targets == 1


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_natural_key_target_mutation_forces_verifier_no_go(seed_data, tmp_path):
    suffix = uuid.uuid4().hex
    source_id = f"target-snapshot-drift-{suffix}"
    source = _build_source(
        tmp_path / "target-snapshot-drift.db",
        accounting_patient_id=seed_data["patient_id"],
        suffix=suffix,
    )
    apply_report, replay_report = _apply_and_report(source, source_id, tmp_path)

    set_tenant_guc(1)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE clinical.condition_lab_tests
            SET display_order=display_order + 1
            WHERE tenant_id=1
              AND condition_code=%s
              AND lab_test_key=%s
            """,
            [f"etl_condition_{suffix}", f"etl_lab_{suffix}"],
        )
        assert cursor.rowcount == 1

    snapshot = verify_target_snapshots(tenant_id=1, source_id=source_id)
    assert snapshot.status == "fail"
    assert snapshot.metrics["drifted_count"] >= 1
    assert "condition_lab_tests" in " ".join(snapshot.metrics["drifted_sample"])

    output = tmp_path / "snapshot-no-go.json"
    with pytest.raises(CommandError, match="NO_GO"):
        call_command(
            "verify_specialist_record_import",
            sqlite=str(source),
            apply_report=str(apply_report),
            replay_report=str(replay_report),
            source_id=source_id,
            tenant_id=1,
            report=str(output),
            stdout=StringIO(),
            verbosity=0,
        )

    payload = json.loads(output.read_text(encoding="utf-8"))
    check = next(
        item
        for item in payload["checks"]
        if item["name"] == "target_payload_fingerprints"
    )
    assert payload["decision"] == "NO_GO"
    assert check["status"] == "fail"
    assert check["metrics"]["drifted_count"] >= 1
