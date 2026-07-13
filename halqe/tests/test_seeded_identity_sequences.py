"""Regression guard for explicit-id seed rows and PostgreSQL identities."""
from __future__ import annotations

import uuid

from django.db import connection, transaction
import pytest

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
