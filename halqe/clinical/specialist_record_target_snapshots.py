"""Batch verification of target-content fingerprints stored in the ETL ledger."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Iterable

from django.db import connection
from psycopg import sql

from clinical import _specialist_record_import_core as _core
from platform_core.tenant_context import set_tenant_guc


_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_SCHEMAS = frozenset({"clinical", "accounting", "platform"})


@dataclass
class TargetSnapshotVerification:
    status: str
    detail: str
    metrics: dict[str, Any] = field(default_factory=dict)


def _digest(payload: dict[str, Any]) -> str:
    rendered = json.dumps(
        _core.SpecialistRecordImporter._jsonable(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def _chunks(values: list[int], size: int = 5000) -> Iterable[list[int]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def verify_target_snapshots(
    *,
    tenant_id: int,
    source_id: str,
) -> TargetSnapshotVerification:
    """Compare every durable target against its post-import content fingerprint.

    The returned details never contain target values or patient identifiers;
    samples are limited to source table names and source row IDs.
    """
    set_tenant_guc(tenant_id)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT source_table, source_row_id, target_table, target_row_id,
                   target_key, target_payload_columns, target_payload_sha256
            FROM clinical.record_import_ledger
            WHERE tenant_id=%s AND source_id=%s
            ORDER BY source_table, source_row_id
            """,
            [tenant_id, source_id],
        )
        rows = [
            {
                "source_table": str(row[0]),
                "source_row_id": int(row[1]),
                "target_table": str(row[2]),
                "target_row_id": int(row[3]) if row[3] is not None else None,
                "target_key": str(row[4]),
                "columns": tuple(str(item) for item in (row[5] or [])),
                "digest": str(row[6]) if row[6] is not None else None,
            }
            for row in cursor.fetchall()
        ]

    malformed: list[str] = []
    groups: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        table_parts = row["target_table"].split(".")
        columns = row["columns"]
        if (
            len(table_parts) != 2
            or table_parts[0] not in _ALLOWED_SCHEMAS
            or not all(_IDENTIFIER_RE.fullmatch(part) for part in table_parts)
            or not columns
            or len(set(columns)) != len(columns)
            or not all(_IDENTIFIER_RE.fullmatch(column) for column in columns)
            or not row["digest"]
            or not _HASH_RE.fullmatch(row["digest"])
        ):
            malformed.append(
                f"{row['source_table']}#{row['source_row_id']}"
            )
            continue
        groups[(row["target_table"], columns)].append(row)

    missing: list[str] = []
    drifted: list[str] = []
    invalid_groups: list[str] = []
    checked = 0

    set_tenant_guc(tenant_id)
    with connection.cursor() as cursor:
        for (target_table, columns), group_rows in groups.items():
            schema_name, table_name = target_table.split(".", 1)
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema=%s AND table_name=%s
                """,
                [schema_name, table_name],
            )
            available = {str(row[0]) for row in cursor.fetchall()}
            if not set(columns).issubset(available):
                invalid_groups.append(target_table)
                continue

            id_rows = [row for row in group_rows if row["target_row_id"] is not None]
            natural_rows = [row for row in group_rows if row["target_row_id"] is None]

            if id_rows:
                actual_by_id: dict[int, dict[str, Any]] = {}
                identifiers = sql.SQL(", ").join(
                    sql.Identifier(column) for column in columns
                )
                target_ids = sorted({row["target_row_id"] for row in id_rows})
                for chunk in _chunks(target_ids):
                    query = sql.SQL(
                        "SELECT id, {} FROM {}.{} "
                        "WHERE tenant_id=%s AND id=ANY(%s)"
                    ).format(
                        identifiers,
                        sql.Identifier(schema_name),
                        sql.Identifier(table_name),
                    )
                    cursor.execute(query, [tenant_id, chunk])
                    for result in cursor.fetchall():
                        actual_by_id[int(result[0])] = dict(
                            zip(columns, result[1:])
                        )

                for row in id_rows:
                    target_id = row["target_row_id"]
                    actual = actual_by_id.get(target_id)
                    rendered = f"{row['source_table']}#{row['source_row_id']}"
                    if actual is None:
                        missing.append(rendered)
                    elif _digest(actual) != row["digest"]:
                        drifted.append(rendered)
                    else:
                        checked += 1

            if natural_rows:
                if target_table != "clinical.condition_lab_tests":
                    invalid_groups.append(target_table)
                    continue
                identifiers = sql.SQL(", ").join(
                    sql.Identifier(column) for column in columns
                )
                query = sql.SQL(
                    "SELECT condition_code, lab_test_key, {} "
                    "FROM clinical.condition_lab_tests WHERE tenant_id=%s"
                ).format(identifiers)
                cursor.execute(query, [tenant_id])
                actual_by_key = {
                    f"{result[0]}|{result[1]}": dict(
                        zip(columns, result[2:])
                    )
                    for result in cursor.fetchall()
                }
                for row in natural_rows:
                    actual = actual_by_key.get(row["target_key"])
                    rendered = f"{row['source_table']}#{row['source_row_id']}"
                    if actual is None:
                        missing.append(rendered)
                    elif _digest(actual) != row["digest"]:
                        drifted.append(rendered)
                    else:
                        checked += 1

    if malformed or missing or drifted or invalid_groups:
        return TargetSnapshotVerification(
            status="fail",
            detail=(
                "One or more target-content fingerprints are missing, invalid or "
                "different from the actual post-import target values."
            ),
            metrics={
                "ledger_rows": len(rows),
                "checked": checked,
                "malformed_count": len(malformed),
                "malformed_sample": malformed[:10],
                "missing_count": len(missing),
                "missing_sample": missing[:10],
                "drifted_count": len(drifted),
                "drifted_sample": drifted[:10],
                "invalid_target_groups": sorted(set(invalid_groups))[:10],
            },
        )

    return TargetSnapshotVerification(
        status="pass",
        detail=(
            "Every ledger row has a target fingerprint and every current target "
            "still matches its post-import snapshot."
        ),
        metrics={
            "ledger_rows": len(rows),
            "checked": checked,
            "drifted_count": 0,
        },
    )
