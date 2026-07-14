"""Permission, RLS and idempotency contracts for accounting import evidence."""
from __future__ import annotations

import os

import psycopg
import pytest
from django.core.management import call_command


PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = os.environ.get("PG_PORT", "55432")
TEST_DB = os.environ.get("PG_TEST_DB", "halqe_app_test")
PG_SU_USER = os.environ.get("PG_USER", "postgres")
PG_SU_PASSWORD = os.environ.get("PG_PASSWORD", "validate_only")
PG_APP_USER = os.environ.get("PG_APP_USER", "platform_login_test")
PG_APP_PASSWORD = os.environ.get("PG_APP_PASSWORD", "test_pw")
ACCOUNTING_USER = os.environ.get("PG_ACCOUNTING_USER", "accounting_login_test")
ACCOUNTING_PASSWORD = os.environ.get(
    "PG_ACCOUNTING_PASSWORD", "accounting_test_pw"
)


def _conninfo(user: str, password: str) -> str:
    return (
        f"host='{PG_HOST}' port='{PG_PORT}' user='{user}' "
        f"password='{password}' dbname='{TEST_DB}'"
    )


@pytest.fixture(scope="session")
def accounting_import_ledger_ready(django_db_setup):
    call_command(
        "ensure_accounting_role",
        login_role=ACCOUNTING_USER,
        login_password=ACCOUNTING_PASSWORD,
        verbosity=0,
    )
    with psycopg.connect(
        _conninfo(PG_SU_USER, PG_SU_PASSWORD), autocommit=True
    ) as conn:
        conn.execute(
            """
            INSERT INTO platform.tenants (id, name, is_active)
            VALUES (2, 'Accounting import tenant 2', TRUE)
            ON CONFLICT (id) DO NOTHING
            """
        )
    return None


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_writer_can_insert_and_replay_key_is_unique(accounting_import_ledger_ready):
    source_digest = "a" * 64
    target_digest = "b" * 64
    with psycopg.connect(
        _conninfo(ACCOUNTING_USER, ACCOUNTING_PASSWORD), autocommit=True
    ) as conn:
        conn.execute("SELECT set_config('app.current_tenant', '1', false)")
        row_id = conn.execute(
            """
            INSERT INTO accounting.accounting_import_ledger
                (tenant_id, source_id, source_table, source_key,
                 target_table, target_key, source_sha256, target_sha256,
                 imported_by)
            VALUES (1, 'ledger-contract-source', 'patients', '10',
                    'accounting.patients', 'patient:500', %s, %s,
                    'pytest')
            RETURNING id
            """,
            (source_digest, target_digest),
        ).fetchone()[0]
        assert row_id > 0
        assert conn.execute(
            """
            SELECT target_key FROM accounting.accounting_import_ledger
            WHERE tenant_id=1 AND source_id='ledger-contract-source'
              AND source_table='patients' AND source_key='10'
            """
        ).fetchone()[0] == "patient:500"

        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                """
                INSERT INTO accounting.accounting_import_ledger
                    (tenant_id, source_id, source_table, source_key,
                     target_table, target_key, source_sha256, imported_by)
                VALUES (1, 'ledger-contract-source', 'patients', '10',
                        'accounting.patients', 'patient:501', %s, 'pytest')
                """,
                (source_digest,),
            )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_ledger_is_tenant_scoped_and_append_only(accounting_import_ledger_ready):
    with psycopg.connect(
        _conninfo(ACCOUNTING_USER, ACCOUNTING_PASSWORD), autocommit=True
    ) as writer:
        writer.execute("SELECT set_config('app.current_tenant', '2', false)")
        assert writer.execute(
            """
            SELECT COUNT(*) FROM accounting.accounting_import_ledger
            WHERE source_id='ledger-contract-source'
            """
        ).fetchone()[0] == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            writer.execute(
                "UPDATE accounting.accounting_import_ledger SET imported_by='changed'"
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            writer.execute("DELETE FROM accounting.accounting_import_ledger")

    with psycopg.connect(
        _conninfo(PG_APP_USER, PG_APP_PASSWORD), autocommit=True
    ) as reader:
        reader.execute("SELECT set_config('app.current_tenant', '1', false)")
        assert reader.execute(
            """
            SELECT COUNT(*) FROM accounting.accounting_import_ledger
            WHERE source_id='ledger-contract-source'
            """
        ).fetchone()[0] == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.execute(
                """
                INSERT INTO accounting.accounting_import_ledger
                    (tenant_id, source_id, source_table, source_key,
                     target_table, target_key, source_sha256, imported_by)
                VALUES (1, 'forbidden', 'patients', '1',
                        'accounting.patients', 'patient:1', %s, 'platform')
                """,
                ("c" * 64,),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.execute(
                "UPDATE accounting.accounting_import_ledger SET imported_by='changed'"
            )
