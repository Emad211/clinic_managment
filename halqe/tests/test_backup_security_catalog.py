from __future__ import annotations

import os

import psycopg
import pytest

from platform_core.backup_database import capture_database_fingerprint


PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = os.environ.get("PG_PORT", "55432")
TEST_DB = os.environ.get("PG_TEST_DB", "halqe_app_test")
PG_USER = os.environ.get("PG_USER", "postgres")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "validate_only")
_ROLE = "backup_security_probe_role"
_VIEW = "backup_security_probe_view"


def _conninfo() -> str:
    return (
        f"host='{PG_HOST}' port='{PG_PORT}' user='{PG_USER}' "
        f"password='{PG_PASSWORD}' dbname='{TEST_DB}'"
    )


def _capture():
    with psycopg.connect(_conninfo()) as conn:
        result = capture_database_fingerprint(conn)
        conn.rollback()
        return result


def _catalogs(fingerprint) -> dict[str, tuple[int, str]]:
    return {
        item.category: (item.object_count, item.sha256)
        for item in fingerprint.catalogs
    }


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_security_catalogs_bind_owner_default_acl_view_definition_and_comments(
    django_db_setup,
):
    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        conn.execute(f"DROP VIEW IF EXISTS platform.{_VIEW}")
        conn.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA platform "
            f"REVOKE SELECT ON TABLES FROM {_ROLE}"
        ) if conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname=%s", (_ROLE,)
        ).fetchone() else None
        conn.execute(f"DROP ROLE IF EXISTS {_ROLE}")
        conn.execute(f"CREATE ROLE {_ROLE} NOLOGIN")
        conn.execute(f"CREATE VIEW platform.{_VIEW} AS SELECT 1::integer AS marker")
        conn.execute(
            f"COMMENT ON VIEW platform.{_VIEW} IS "
            "'initial backup security probe comment'"
        )

    try:
        before = _capture()
        before_catalogs = _catalogs(before)
        expected_categories = {
            "database_security",
            "schema_security",
            "relation_security",
            "default_acl",
            "views",
            "function_security",
            "types",
            "comments",
        }
        assert expected_categories <= set(before_catalogs)

        with psycopg.connect(_conninfo(), autocommit=True) as conn:
            conn.execute(
                f"CREATE OR REPLACE VIEW platform.{_VIEW} "
                "AS SELECT 2::integer AS marker"
            )
            conn.execute(f"ALTER VIEW platform.{_VIEW} OWNER TO {_ROLE}")
            conn.execute(
                f"COMMENT ON VIEW platform.{_VIEW} IS "
                "'changed backup security probe comment'"
            )
            conn.execute(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA platform "
                f"GRANT SELECT ON TABLES TO {_ROLE}"
            )

        after = _capture()
        after_catalogs = _catalogs(after)
        for category in ("relation_security", "default_acl", "views", "comments"):
            assert after_catalogs[category] != before_catalogs[category]
        assert after.schema_sha256 != before.schema_sha256
        assert after.content_sha256 == before.content_sha256
        assert after.database_sha256 != before.database_sha256
    finally:
        with psycopg.connect(_conninfo(), autocommit=True) as conn:
            conn.execute(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA platform "
                f"REVOKE SELECT ON TABLES FROM {_ROLE}"
            )
            conn.execute(f"DROP VIEW IF EXISTS platform.{_VIEW}")
            conn.execute(f"DROP ROLE IF EXISTS {_ROLE}")
