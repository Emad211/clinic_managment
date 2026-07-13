"""Regression guards for explicit-id seeds and sequence-neutral ETL dry-runs."""
from __future__ import annotations

import uuid

from django.db import connection, transaction
import pytest

from clinical.specialist_record_import import SpecialistRecordImporter
from platform_core.tenant_context import set_tenant_guc


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_seeded_catalog_identity_sequence_is_ahead_of_existing_rows(seed_data):
    """A normal INSERT after stable-id seeds must never reuse an existing PK."""
    set_tenant_guc(1)
    code = f"identity_guard_{uuid.uuid4().hex}"

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COALESCE(MAX(id), 0) FROM clinical.conditions WHERE tenant_id=1"
            )
            maximum_before = int(cursor.fetchone()[0])
            cursor.execute(
                """
                INSERT INTO clinical.conditions
                    (tenant_id, name, code, is_active, is_chronic, display_order)
                VALUES (1, %s, %s, TRUE, TRUE, 9999)
                RETURNING id
                """,
                [f"Identity guard {code}", code],
            )
            generated_id = int(cursor.fetchone()[0])
            assert generated_id > maximum_before

        # The assertion exercises nextval, but the catalog row is test-only.
        transaction.set_rollback(True)


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_dry_run_materialization_uses_negative_ids_without_advancing_sequence(
    seed_data,
    tmp_path,
):
    """Relational dry-run validation must not consume the production sequence."""
    set_tenant_guc(1)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT last_value::bigint, is_called FROM clinical.conditions_id_seq"
        )
        sequence_before = cursor.fetchone()

    importer = SpecialistRecordImporter(
        sqlite_path=tmp_path / "not-opened.db",
        source_id="sequence-neutral-dry-run",
        tenant_id=1,
        apply=False,
    )
    code = f"dry_run_negative_{uuid.uuid4().hex}"

    with transaction.atomic():
        set_tenant_guc(1)
        with connection.cursor() as cursor:
            importer.pg = cursor
            target_id = importer._insert(
                "clinical",
                "conditions",
                {
                    "tenant_id": 1,
                    "name": f"Dry-run condition {code}",
                    "code": code,
                    "is_active": True,
                    "is_chronic": True,
                    "display_order": 9999,
                },
            )
            assert target_id < 0
            cursor.execute(
                "SELECT COUNT(*) FROM clinical.conditions WHERE tenant_id=1 AND id=%s",
                [target_id],
            )
            assert cursor.fetchone()[0] == 1
        transaction.set_rollback(True)

    set_tenant_guc(1)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT last_value::bigint, is_called FROM clinical.conditions_id_seq"
        )
        assert cursor.fetchone() == sequence_before
        cursor.execute(
            "SELECT COUNT(*) FROM clinical.conditions WHERE tenant_id=1 AND code=%s",
            [code],
        )
        assert cursor.fetchone()[0] == 0
