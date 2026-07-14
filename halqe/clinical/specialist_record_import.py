"""Public specialist-record importer with production source-snapshot guards.

The complete transactional, redaction, continuity and target-fingerprint logic
lives in :mod:`clinical._specialist_record_import_target_core`.  This final
facade forbids committed imports from live SQLite state: ``--allow-live-source``
is a diagnostic dry-run exception only, and non-empty WAL/SHM/rollback-journal
sidecars block apply before any PostgreSQL write is attempted.
"""
from __future__ import annotations

from pathlib import Path

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
    """Importer that permits apply only from a fully quiesced SQLite snapshot."""

    _LIVE_SIDECARS = ("-wal", "-shm", "-journal")

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
                nonempty = sidecar.exists() and sidecar.is_file() and sidecar.stat().st_size > 0
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
