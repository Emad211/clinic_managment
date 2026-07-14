"""Public specialist-record importer with production source-snapshot guards.

The complete transactional, redaction, continuity and target-fingerprint logic
lives in :mod:`clinical._specialist_record_import_target_core`. This final
facade adds two release-facing guarantees:

* apply is permitted only from a fully quiesced SQLite snapshot;
* when a natural-key match reuses a canonical target whose actual values differ
  from the transformed source payload, the discrepancy is reported using only
  source table/row identity. Strict reconciliation can therefore block silent
  semantic divergence without copying clinical values into operator logs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

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
                self._digest(comparable)
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
        if self._digest(actual) == source_digest:
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
