from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any

import psycopg
from django.conf import settings

from platform_core.backup_canonical import BackupVerificationError
from platform_core.backup_database import capture_database_fingerprint
from platform_core.backup_manifest import (
    _connection_kwargs,
    load_backup_manifest,
    validate_backup_artifact,
)


@dataclass
class RestoreCheck:
    code: str
    status: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class RestoreVerificationReport:
    decision: str
    manifest_sha256: str
    source_database: str
    restored_database: str
    backup_sha256: str
    expected_database_sha256: str
    actual_database_sha256: str
    checks: list[RestoreCheck] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add(
        self,
        code: str,
        ok: bool,
        message: str,
        **evidence: Any,
    ) -> None:
        self.checks.append(
            RestoreCheck(
                code=code,
                status="PASS" if ok else "FAIL",
                message=message,
                evidence=evidence,
            )
        )
        if not ok:
            self.errors.append(code)
            self.decision = "FAILED"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _json_shape(value: Any) -> Any:
    """Normalize tuples/dataclasses to the exact shape persisted in JSON."""
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def _named(items: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    return {
        ".".join(str(item[key]) for key in keys): item
        for item in items
    }


def _table_diff(expected: list[dict[str, Any]], actual: list[dict[str, Any]]):
    left = _named(expected, ("schema", "table"))
    right = _named(actual, ("schema", "table"))
    missing = sorted(set(left) - set(right))
    extra = sorted(set(right) - set(left))
    changed: list[dict[str, Any]] = []
    for name in sorted(set(left) & set(right)):
        expected_item = left[name]
        actual_item = right[name]
        metadata_match = (
            expected_item.get("columns") == actual_item.get("columns")
            and expected_item.get("primary_key") == actual_item.get("primary_key")
        )
        count_match = expected_item.get("row_count") == actual_item.get("row_count")
        digest_match = expected_item.get("row_sha256") == actual_item.get("row_sha256")
        if not (metadata_match and count_match and digest_match):
            changed.append(
                {
                    "table": name,
                    "metadata_match": metadata_match,
                    "expected_rows": expected_item.get("row_count"),
                    "actual_rows": actual_item.get("row_count"),
                    "row_sha256_match": digest_match,
                }
            )
    return missing, extra, changed


def _sequence_diff(expected: list[dict[str, Any]], actual: list[dict[str, Any]]):
    left = _named(expected, ("schema", "sequence"))
    right = _named(actual, ("schema", "sequence"))
    missing = sorted(set(left) - set(right))
    extra = sorted(set(right) - set(left))
    changed = [
        name
        for name in sorted(set(left) & set(right))
        if left[name].get("last_value") != right[name].get("last_value")
        or left[name].get("is_called") != right[name].get("is_called")
    ]
    return missing, extra, changed


def verify_restored_backup(
    *,
    manifest_file: str,
    backup_file: str,
    restored_database: str,
    confirmed_restored_database: str,
    allow_same_database: bool = False,
) -> RestoreVerificationReport:
    payload = load_backup_manifest(manifest_file)
    expected_backup = payload["backup"]
    actual_backup = validate_backup_artifact(backup_file)
    source_database = str(payload["database"]["database_name"])
    restored_database = restored_database.strip()
    if not restored_database:
        raise BackupVerificationError("Restored database name is required")
    if confirmed_restored_database.strip() != restored_database:
        raise BackupVerificationError(
            "--confirm-restored-database must exactly match --restored-database"
        )
    if restored_database == source_database:
        if settings.PRODUCTION or not allow_same_database:
            raise BackupVerificationError(
                "Restore verification must target a database different from the source"
            )

    kwargs = _connection_kwargs(database_name=restored_database, restored=True)
    with psycopg.connect(**kwargs) as conn:
        actual_database = _json_shape(capture_database_fingerprint(conn).to_dict())
        conn.rollback()

    expected_database = _json_shape(payload["database"])
    report = RestoreVerificationReport(
        decision="VERIFIED",
        manifest_sha256=payload["manifest_sha256"],
        source_database=source_database,
        restored_database=actual_database["database_name"],
        backup_sha256=actual_backup.sha256,
        expected_database_sha256=expected_database["database_sha256"],
        actual_database_sha256=actual_database["database_sha256"],
    )
    report.add(
        "backup_artifact_continuity",
        actual_backup.sha256 == expected_backup["sha256"]
        and actual_backup.size_bytes == expected_backup["size_bytes"]
        and actual_backup.format == expected_backup["format"],
        "Backup bytes, size and format must match the captured manifest",
        sha256_match=actual_backup.sha256 == expected_backup["sha256"],
        size_match=actual_backup.size_bytes == expected_backup["size_bytes"],
        format_match=actual_backup.format == expected_backup["format"],
    )
    report.add(
        "restored_database_identity",
        actual_database["database_name"] == restored_database,
        "The connected database must be the explicitly confirmed restore target",
        connected_database=actual_database["database_name"],
    )
    report.add(
        "postgres_compatibility",
        actual_database["server_major"] == expected_database["server_major"],
        "Source and restore PostgreSQL major versions must match",
        expected_major=expected_database["server_major"],
        actual_major=actual_database["server_major"],
    )
    metadata_fields = ("encoding", "collate", "ctype", "timezone")
    metadata_mismatch = [
        field
        for field in metadata_fields
        if actual_database.get(field) != expected_database.get(field)
    ]
    report.add(
        "database_settings",
        not metadata_mismatch,
        "Encoding, collation, ctype and timezone must match",
        mismatched_fields=metadata_mismatch,
    )
    for code, key, message in (
        ("extensions", "extensions", "Extension inventory and versions must match"),
        ("required_roles", "required_roles", "Required Halqe role capabilities must match"),
        ("schema_ledger", "schema_ledger", "Applied schema-slice ledger must match"),
        ("schema_catalog", "catalogs", "Constraints, indexes, RLS, triggers and functions must match"),
    ):
        report.add(
            code,
            actual_database.get(key) == expected_database.get(key),
            message,
            expected_count=len(expected_database.get(key, [])),
            actual_count=len(actual_database.get(key, [])),
        )

    missing_tables, extra_tables, changed_tables = _table_diff(
        expected_database["tables"], actual_database["tables"]
    )
    report.add(
        "table_data_fingerprints",
        not missing_tables and not extra_tables and not changed_tables,
        "Every protected table must have identical metadata, row count and row digest",
        missing_tables=missing_tables,
        extra_tables=extra_tables,
        changed_tables=changed_tables,
    )
    missing_sequences, extra_sequences, changed_sequences = _sequence_diff(
        expected_database["sequences"], actual_database["sequences"]
    )
    report.add(
        "sequence_state",
        not missing_sequences and not extra_sequences and not changed_sequences,
        "All sequence positions and is_called states must match",
        missing_sequences=missing_sequences,
        extra_sequences=extra_sequences,
        changed_sequences=changed_sequences,
    )
    report.add(
        "schema_digest",
        actual_database["schema_sha256"] == expected_database["schema_sha256"],
        "Complete protected-schema digest must match",
    )
    report.add(
        "content_digest",
        actual_database["content_sha256"] == expected_database["content_sha256"],
        "Complete table and sequence content digest must match",
    )
    report.add(
        "database_digest",
        actual_database["database_sha256"] == expected_database["database_sha256"],
        "Combined database restore digest must match",
    )
    return report
