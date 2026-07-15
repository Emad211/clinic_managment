from __future__ import annotations

from dataclasses import asdict

import psycopg

from platform_core import _backup_database_core as _core
from platform_core.backup_canonical import aggregate_digest
from platform_core.backup_security_catalog import capture_security_catalogs


BackupVerificationError = _core.BackupVerificationError
CatalogFingerprint = _core.CatalogFingerprint
ColumnFingerprint = _core.ColumnFingerprint
DatabaseFingerprint = _core.DatabaseFingerprint
PROTECTED_SCHEMAS = _core.PROTECTED_SCHEMAS
REQUIRED_ROLES = _core.REQUIRED_ROLES
SequenceFingerprint = _core.SequenceFingerprint
TableFingerprint = _core.TableFingerprint


def capture_database_fingerprint(conn: psycopg.Connection) -> DatabaseFingerprint:
    """Capture data plus security-sensitive PostgreSQL catalog state.

    The verified core owns table streaming, sequence state, constraints, indexes,
    RLS, triggers, functions, extensions, required roles and schema ledger.
    This facade additionally binds object/database ownership, sorted ACL/default
    ACL state, view definitions, type metadata and all supported comments into
    the schema digest. Only catalog counts and SHA-256 values reach the manifest.
    """
    base = _core.capture_database_fingerprint(conn)
    catalogs = tuple((*base.catalogs, *capture_security_catalogs(conn)))
    schema_payload = {
        "catalogs": [asdict(item) for item in catalogs],
        "extensions": base.extensions,
        "required_roles": base.required_roles,
        "schema_ledger": base.schema_ledger,
        "encoding": base.encoding,
        "collate": base.collate,
        "ctype": base.ctype,
    }
    schema_sha256 = aggregate_digest(schema_payload)
    database_sha256 = aggregate_digest(
        {
            "server_major": base.server_major,
            "timezone": base.timezone,
            "schema_sha256": schema_sha256,
            "content_sha256": base.content_sha256,
        }
    )
    return DatabaseFingerprint(
        database_name=base.database_name,
        server_version_num=base.server_version_num,
        server_major=base.server_major,
        encoding=base.encoding,
        collate=base.collate,
        ctype=base.ctype,
        timezone=base.timezone,
        extensions=base.extensions,
        required_roles=base.required_roles,
        schema_ledger=base.schema_ledger,
        catalogs=catalogs,
        tables=base.tables,
        sequences=base.sequences,
        schema_sha256=schema_sha256,
        content_sha256=base.content_sha256,
        database_sha256=database_sha256,
    )


__all__ = [
    "BackupVerificationError",
    "CatalogFingerprint",
    "ColumnFingerprint",
    "DatabaseFingerprint",
    "PROTECTED_SCHEMAS",
    "REQUIRED_ROLES",
    "SequenceFingerprint",
    "TableFingerprint",
    "capture_database_fingerprint",
]
