from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import stat
from typing import Any

import psycopg
from django.conf import settings

from platform_core.backup_canonical import (
    BackupVerificationError,
    aggregate_digest,
    file_sha256,
)
from platform_core.backup_database import capture_database_fingerprint


_MANIFEST_VERSION = 1
_CUSTOM_MAGIC = b"PGDMP"


@dataclass(frozen=True)
class BackupArtifactFingerprint:
    path: str
    filename: str
    format: str
    size_bytes: int
    mode_octal: str
    sha256: str


@dataclass(frozen=True)
class BackupManifest:
    manifest_version: int
    created_at: str
    confirmed_quiesced: bool
    backup: BackupArtifactFingerprint
    database: dict[str, Any]
    manifest_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _connection_kwargs(
    *,
    database_name: str | None = None,
    restored: bool = False,
) -> dict[str, Any]:
    db = settings.DATABASES["default"]
    prefix = "RESTORE_PG_" if restored else "PG_"
    user_default = getattr(settings, "PG_SUPERUSER", "postgres")
    password_default = getattr(settings, "PG_SUPERPASSWORD", "")
    return {
        "host": os.environ.get(f"{prefix}HOST", db.get("HOST") or "localhost"),
        "port": int(os.environ.get(f"{prefix}PORT", db.get("PORT") or 5432)),
        "dbname": database_name or db.get("NAME"),
        "user": os.environ.get(f"{prefix}USER", user_default),
        "password": os.environ.get(f"{prefix}PASSWORD", password_default),
        "connect_timeout": 10,
        "application_name": (
            "halqe-restore-verifier" if restored else "halqe-backup-manifest"
        ),
        "options": "-c search_path=platform,accounting,clinical,public",
    }


def validate_backup_artifact(path: str | Path) -> BackupArtifactFingerprint:
    backup = Path(path).expanduser().absolute()
    if backup.is_symlink():
        raise BackupVerificationError(f"Backup file must not be a symlink: {backup}")
    if not backup.exists() or not backup.is_file():
        raise BackupVerificationError(f"Backup file is not a regular file: {backup}")
    info = backup.stat()
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o077:
        raise BackupVerificationError(
            "Backup file must be owner-only (chmod 600 or stricter)"
        )
    if info.st_size <= len(_CUSTOM_MAGIC):
        raise BackupVerificationError("Backup file is empty or truncated")
    with backup.open("rb") as handle:
        magic = handle.read(len(_CUSTOM_MAGIC))
    if magic != _CUSTOM_MAGIC:
        raise BackupVerificationError(
            "Only PostgreSQL custom-format dumps created with pg_dump -Fc are accepted"
        )
    return BackupArtifactFingerprint(
        path=str(backup),
        filename=backup.name,
        format="postgres-custom",
        size_bytes=int(info.st_size),
        mode_octal=oct(mode),
        sha256=file_sha256(backup),
    )


def _manifest_integrity_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key != "manifest_sha256"
    }


def manifest_digest(payload: dict[str, Any]) -> str:
    return aggregate_digest(_manifest_integrity_payload(payload))


def capture_backup_manifest(
    *,
    backup_file: str | Path,
    confirmed_quiesced: bool,
    database_name: str | None = None,
) -> BackupManifest:
    if not confirmed_quiesced:
        raise BackupVerificationError(
            "A backup manifest requires explicit confirmation that application writers "
            "were quiesced for the dump"
        )
    backup = validate_backup_artifact(backup_file)
    kwargs = _connection_kwargs(database_name=database_name, restored=False)
    with psycopg.connect(**kwargs) as conn:
        database = capture_database_fingerprint(conn).to_dict()
        conn.rollback()
    payload: dict[str, Any] = {
        "manifest_version": _MANIFEST_VERSION,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "confirmed_quiesced": True,
        "backup": asdict(backup),
        "database": database,
    }
    digest = manifest_digest(payload)
    return BackupManifest(
        manifest_version=_MANIFEST_VERSION,
        created_at=payload["created_at"],
        confirmed_quiesced=True,
        backup=backup,
        database=database,
        manifest_sha256=digest,
    )


def load_backup_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).expanduser().absolute()
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise BackupVerificationError("Manifest must be a regular non-symlink file")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupVerificationError(f"Backup manifest is unreadable: {exc}") from exc
    if payload.get("manifest_version") != _MANIFEST_VERSION:
        raise BackupVerificationError("Unsupported backup manifest version")
    expected = payload.get("manifest_sha256")
    actual = manifest_digest(payload)
    if not isinstance(expected, str) or expected != actual:
        raise BackupVerificationError("Backup manifest integrity hash is invalid")
    return payload
