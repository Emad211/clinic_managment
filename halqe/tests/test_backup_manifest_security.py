from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from platform_core.backup_canonical import (
    BackupVerificationError,
    canonical,
    stable_json,
)
from platform_core.backup_manifest import (
    load_backup_manifest,
    manifest_digest,
    validate_backup_artifact,
)


def _dump(path: Path, *, private: bool = True) -> Path:
    path.write_bytes(b"PGDMP" + b"synthetic-custom-dump")
    os.chmod(path, 0o600 if private else 0o644)
    return path


def test_private_custom_dump_is_accepted_without_exposing_bytes(tmp_path):
    backup = validate_backup_artifact(_dump(tmp_path / "halqe.dump"))
    assert backup.format == "postgres-custom"
    assert backup.mode_octal == "0o600"
    assert backup.size_bytes > 5
    assert len(backup.sha256) == 64
    rendered = stable_json(canonical(b"raw-secret-marker"))
    assert "raw-secret-marker" not in rendered
    assert "bytes_sha256" in rendered


def test_dump_rejects_wrong_format_permissions_and_symlink(tmp_path):
    wrong = tmp_path / "wrong.dump"
    wrong.write_bytes(b"not-a-postgres-dump")
    os.chmod(wrong, 0o600)
    with pytest.raises(BackupVerificationError, match="custom-format"):
        validate_backup_artifact(wrong)

    readable = _dump(tmp_path / "readable.dump", private=False)
    with pytest.raises(BackupVerificationError, match="owner-only"):
        validate_backup_artifact(readable)

    target = _dump(tmp_path / "target.dump")
    link = tmp_path / "link.dump"
    link.symlink_to(target)
    with pytest.raises(BackupVerificationError, match="symlink"):
        validate_backup_artifact(link)


def test_manifest_integrity_rejects_tampering(tmp_path):
    payload = {
        "manifest_version": 1,
        "created_at": "2099-01-01T00:00:00+00:00",
        "confirmed_quiesced": True,
        "backup": {"sha256": "a" * 64},
        "database": {"database_name": "source", "database_sha256": "b" * 64},
    }
    payload["manifest_sha256"] = manifest_digest(payload)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_backup_manifest(path)["database"]["database_name"] == "source"

    payload["database"]["database_name"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BackupVerificationError, match="integrity"):
        load_backup_manifest(path)
