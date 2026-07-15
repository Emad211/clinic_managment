from __future__ import annotations

from io import StringIO
import json
import os
from pathlib import Path

from django.core.management import call_command
import psycopg
import pytest

from platform_core.backup_restore import verify_restored_backup


PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = os.environ.get("PG_PORT", "55432")
TEST_DB = os.environ.get("PG_TEST_DB", "halqe_app_test")
PG_USER = os.environ.get("PG_USER", "postgres")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "validate_only")


def _conninfo() -> str:
    return (
        f"host='{PG_HOST}' port='{PG_PORT}' user='{PG_USER}' "
        f"password='{PG_PASSWORD}' dbname='{TEST_DB}'"
    )


def _dump(path: Path) -> Path:
    path.write_bytes(b"PGDMP" + b"synthetic-restore-rehearsal")
    os.chmod(path, 0o600)
    return path


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_manifest_contains_only_hashes_and_detects_restored_drift(tmp_path, django_db_setup):
    marker = "raw-backup-marker-must-not-leak"
    tenant_id = 860001
    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        conn.execute(
            "DELETE FROM platform.tenants WHERE id=%s",
            (tenant_id,),
        )
        conn.execute(
            "INSERT INTO platform.tenants(id,name,is_active) VALUES(%s,%s,TRUE)",
            (tenant_id, marker),
        )

    backup = _dump(tmp_path / "halqe.dump")
    manifest_path = tmp_path / "private" / "backup-manifest.json"
    stdout = StringIO()
    try:
        call_command(
            "capture_halqe_backup_manifest",
            backup_file=str(backup),
            output=str(manifest_path),
            database_name=TEST_DB,
            confirm_quiesced=True,
            stdout=stdout,
        )
        rendered = manifest_path.read_text(encoding="utf-8")
        payload = json.loads(rendered)
        assert marker not in rendered
        assert payload["database"]["database_name"] == TEST_DB
        assert payload["database"]["tables"]
        assert payload["database"]["catalogs"]
        assert payload["database"]["sequences"]
        assert len(payload["manifest_sha256"]) == 64
        assert "Backup manifest captured" in stdout.getvalue()

        clean = verify_restored_backup(
            manifest_file=str(manifest_path),
            backup_file=str(backup),
            restored_database=TEST_DB,
            confirmed_restored_database=TEST_DB,
            allow_same_database=True,
        )
        assert clean.decision == "VERIFIED", clean.errors
        assert {check.status for check in clean.checks} == {"PASS"}

        with psycopg.connect(_conninfo(), autocommit=True) as conn:
            conn.execute(
                "UPDATE platform.tenants SET name='changed-after-backup' WHERE id=%s",
                (tenant_id,),
            )
        drift = verify_restored_backup(
            manifest_file=str(manifest_path),
            backup_file=str(backup),
            restored_database=TEST_DB,
            confirmed_restored_database=TEST_DB,
            allow_same_database=True,
        )
        assert drift.decision == "FAILED"
        assert "table_data_fingerprints" in drift.errors
        assert "content_digest" in drift.errors
        changed = next(
            check for check in drift.checks if check.code == "table_data_fingerprints"
        )
        assert any(
            item["table"] == "platform.tenants"
            for item in changed.evidence["changed_tables"]
        )
    finally:
        with psycopg.connect(_conninfo(), autocommit=True) as conn:
            conn.execute("DELETE FROM platform.tenants WHERE id=%s", (tenant_id,))
