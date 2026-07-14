"""Public specialist-record importer with production source-snapshot guards.

The complete transactional, redaction, continuity and target-fingerprint logic
lives in :mod:`clinical._specialist_record_import_target_core`. This final
facade adds two release-facing guarantees:

* apply is permitted only from a fully quiesced SQLite snapshot;
* when a natural-key match reuses a canonical target whose actual values differ
  from the transformed source payload, the discrepancy is reported using only
  source table/row identity.

Comparable digests normalize aware datetimes to UTC, finite numerics to a stable
decimal string and psycopg ``Jsonb`` wrappers to their underlying JSON value.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Optional

from psycopg.types.json import Jsonb

from clinical import _specialist_record_import_target_core as _target


FinancialDataOutOfScopeError = _target.FinancialDataOutOfScopeError
ImportConflictError = _target.ImportConflictError
ImportReport = _target.ImportReport
SourceDatabaseError = _target.SourceDatabaseError
SourceRowChangedError = _target.SourceRowChangedError
SpecialistRecordImportError = _target.SpecialistRecordImportError
SQLiteSnapshot = _target.SQLiteSnapshot
TableStats = _target.TableStats
UnresolvedPatientError = _target.UnresolvedPatientError


class SpecialistRecordImporter(_target.SpecialistRecordImporter):
    """Quiesced-source importer with visible canonical-reuse divergence."""

    _LIVE_SIDECARS = ("-wal", "-shm", "-journal")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._source_target_payload_sha256: dict[tuple[str, int], str] = {}
        self._reported_target_divergence: set[tuple[str, int]] = set()

    def _assert_apply_source_is_quiesced(self) -> None:
        if not self.apply:
            return
        if self.allow_live_source:
            raise SourceDatabaseError(
                "--allow-live-source is never permitted with --apply. Create a "
                "quiesced copy, checkpoint SQLite, and rerun without the flag."
            )
        active = []
        for suffix in self._LIVE_SIDECARS:
            sidecar = Path(str(self.path) + suffix)
            try:
                nonempty = (
                    sidecar.exists()
                    and sidecar.is_file()
                    and sidecar.stat().st_size > 0
                )
            except OSError as exc:
                raise SourceDatabaseError(
                    f"Cannot inspect SQLite sidecar {sidecar.name}: {exc}"
                ) from exc
            if nonempty:
                active.append(sidecar.name)
        if active:
            raise SourceDatabaseError(
                "Committed import requires a quiesced SQLite snapshot; non-empty "
                "sidecar files are present: "
                + ", ".join(active)
            )

    def run(self) -> ImportReport:
        try:
            self._assert_apply_source_is_quiesced()
        except SourceDatabaseError:
            self.report.transaction_status = "failed_no_commit"
            self.report.ledger_rows_after = self._durable_ledger_count()
            raise
        return super().run()

    def _begin(
        self,
        *,
        source_table: str,
        row: Mapping[str, Any],
        payload: Mapping[str, Any],
        expected_target_table: str,
    ):
        result = super()._begin(
            source_table=source_table,
            row=row,
            payload=payload,
            expected_target_table=expected_target_table,
        )
        source_row_id = int(result[0])
        schema_name, table_name = expected_target_table.split(".", 1)
        columns = self._target_snapshot_columns.get((source_table, source_row_id))
        if columns:
            filtered = self._filtered_payload(schema_name, table_name, payload)
            comparable = {column: filtered.get(column) for column in columns}
            self._source_target_payload_sha256[(source_table, source_row_id)] = (
                _comparable_digest(comparable)
            )
        return result

    def _warn_if_target_differs(
        self,
        *,
        source_table: str,
        source_row_id: int,
        target_table: str,
        target_row_id: Optional[int],
        target_key: str,
    ) -> None:
        if source_table == "patient_links":
            return
        identity = (source_table, int(source_row_id))
        if identity in self._reported_target_divergence:
            return
        columns = self._target_snapshot_columns.get(identity)
        source_digest = self._source_target_payload_sha256.get(identity)
        if not columns or not source_digest:
            return
        actual = self._read_actual_target_payload(
            target_table=target_table,
            target_row_id=target_row_id,
            target_key=target_key,
            columns=columns,
        )
        if _comparable_digest(actual) == source_digest:
            return
        self._reported_target_divergence.add(identity)
        self.report.warnings.append(
            "Canonical target differs from transformed source payload for "
            f"{source_table}#{source_row_id}; no target values were copied to this "
            "report. Review and document the canonicalization before release."
        )

    def _ledger_add(
        self,
        *,
        source_table: str,
        source_row_id: int,
        target_table: str,
        target_row_id: Optional[int],
        target_key: str,
        payload_sha256: str,
    ) -> None:
        if self.apply:
            self._warn_if_target_differs(
                source_table=source_table,
                source_row_id=source_row_id,
                target_table=target_table,
                target_row_id=target_row_id,
                target_key=target_key,
            )
        super()._ledger_add(
            source_table=source_table,
            source_row_id=source_row_id,
            target_table=target_table,
            target_row_id=target_row_id,
            target_key=target_key,
            payload_sha256=payload_sha256,
        )

    def _finish(
        self,
        *,
        source_table: str,
        source_row_id: int,
        target_table: str,
        target_row_id: Optional[int],
        target_key: str,
        digest: str,
        reused: bool,
    ) -> None:
        if not self.apply and reused:
            self._warn_if_target_differs(
                source_table=source_table,
                source_row_id=source_row_id,
                target_table=target_table,
                target_row_id=target_row_id,
                target_key=target_key,
            )
        super()._finish(
            source_table=source_table,
            source_row_id=source_row_id,
            target_table=target_table,
            target_row_id=target_row_id,
            target_key=target_key,
            digest=digest,
            reused=reused,
        )


def _comparable_digest(value: Any) -> str:
    normalized = _normalize_comparable(value)
    rendered = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def _normalize_comparable(value: Any) -> Any:
    if isinstance(value, Jsonb):
        return _normalize_comparable(value.obj)
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_comparable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_comparable(item) for item in value]
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.isoformat()
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float, Decimal)):
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        try:
            numeric = Decimal(str(value)).normalize()
        except (InvalidOperation, ValueError):
            return str(value)
        rendered = format(numeric, "f")
        return "0" if rendered in {"-0", "-0.0"} else rendered
    return str(value)


__all__ = [
    "FinancialDataOutOfScopeError",
    "ImportConflictError",
    "ImportReport",
    "SourceDatabaseError",
    "SourceRowChangedError",
    "SpecialistRecordImportError",
    "SpecialistRecordImporter",
    "SQLiteSnapshot",
    "TableStats",
    "UnresolvedPatientError",
]
