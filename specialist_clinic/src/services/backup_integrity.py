"""Verification and atomic restore for attested SQLite backups."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any


class BackupVerificationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class VerifiedBackup:
    database_path: Path
    manifest_path: Path
    sha256: str
    size_bytes: int
    created_at: str


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sqlite_integrity(path: Path) -> str:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
        return str(row[0] if row else "missing")
    finally:
        connection.close()


class BackupIntegrityService:
    """Accept only a manifest-matched, internally consistent SQLite snapshot."""

    def verify(
        self,
        database_path: str | os.PathLike,
        *,
        manifest_path: str | os.PathLike | None = None,
    ) -> VerifiedBackup:
        database = Path(database_path).resolve()
        manifest = (
            Path(manifest_path).resolve()
            if manifest_path is not None
            else database.with_suffix(".manifest.json")
        )
        if not database.is_file() or not manifest.is_file():
            raise BackupVerificationError("backup database or manifest is missing")
        try:
            payload: dict[str, Any] = json.loads(
                manifest.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, TypeError) as exc:
            raise BackupVerificationError("backup manifest is not valid JSON") from exc
        required = {
            "schema_version",
            "backup_file",
            "sha256",
            "size_bytes",
            "integrity_check",
            "created_at",
        }
        if not required <= set(payload):
            raise BackupVerificationError("backup manifest is incomplete")
        if payload["schema_version"] != "1.0":
            raise BackupVerificationError("unsupported backup manifest version")
        if str(payload["backup_file"]) != database.name:
            raise BackupVerificationError("manifest refers to another backup file")
        if str(payload["integrity_check"]).lower() != "ok":
            raise BackupVerificationError("manifest does not attest SQLite integrity")
        actual_size = database.stat().st_size
        if int(payload["size_bytes"]) != actual_size:
            raise BackupVerificationError("backup size does not match manifest")
        actual_hash = file_sha256(database)
        if not hashlib.compare_digest(
            actual_hash,
            str(payload["sha256"]).strip().lower(),
        ):
            raise BackupVerificationError("backup SHA-256 does not match manifest")
        integrity = sqlite_integrity(database)
        if integrity.lower() != "ok":
            raise BackupVerificationError(
                f"backup SQLite integrity check failed: {integrity[:80]}"
            )
        return VerifiedBackup(
            database_path=database,
            manifest_path=manifest,
            sha256=actual_hash,
            size_bytes=actual_size,
            created_at=str(payload["created_at"]),
        )

    def restore(
        self,
        database_path: str | os.PathLike,
        destination_path: str | os.PathLike,
        *,
        manifest_path: str | os.PathLike | None = None,
    ) -> VerifiedBackup:
        """Verify source and staging copy before one atomic destination replace."""
        verified = self.verify(
            database_path,
            manifest_path=manifest_path,
        )
        destination = Path(destination_path).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.with_suffix(destination.suffix + ".restore.tmp")
        try:
            shutil.copy2(verified.database_path, staging)
            if file_sha256(staging) != verified.sha256:
                raise BackupVerificationError("restore staging hash mismatch")
            integrity = sqlite_integrity(staging)
            if integrity.lower() != "ok":
                raise BackupVerificationError(
                    f"restore staging integrity failed: {integrity[:80]}"
                )
            os.replace(staging, destination)
        finally:
            staging.unlink(missing_ok=True)
        return verified
