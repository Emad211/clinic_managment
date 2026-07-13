"""Public facade for the specialist-clinic historical record importer.

The implementation lives in :mod:`clinical._specialist_record_import_core`.
This facade strengthens four operational boundaries:

* dry-run rows use explicit negative primary keys inside a transaction that is
  always rolled back, validating real PostgreSQL relationships without leaving
  data behind or advancing identities;
* reports and command errors redact raw patient identifiers by default so
  national IDs and names cannot leak into shell, CI or generic job logs;
* a reused ``source_id`` must contain every source row already present in its
  append-only ledger; truncated or unrelated sources fail before commit;
* every report states whether changes were committed, intentionally rolled back
  after validation, or failed with no durable import changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from django.db import connection, transaction
from psycopg import sql

from clinical import _specialist_record_import_core as _core
from clinical._specialist_record_import_core import (
    FinancialDataOutOfScopeError,
    ImportConflictError,
    SourceDatabaseError,
    SourceRowChangedError,
    SpecialistRecordImportError,
    SQLiteSnapshot,
    TableStats,
    UnresolvedPatientError,
)


@dataclass
class ImportReport(_core.ImportReport):
    """Operator-facing report with an explicit durability state."""

    transaction_status: str = "not_started"


class SpecialistRecordImporter(_core.SpecialistRecordImporter):
    """Importer with monotonic source identity and PHI-safe reporting."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base = self.report
        self.report = ImportReport(
            source_id=base.source_id,
            source_path=base.source_path,
            tenant_id=base.tenant_id,
            mode=base.mode,
        )

    def _redact_sensitive_report(self) -> None:
        """Remove direct patient identifiers from operator-facing report data."""
        redacted_unresolved = []
        for item in self.report.unresolved_patients:
            redacted_unresolved.append(
                {
                    "source_patient_link_id": item.get("source_patient_link_id"),
                    "has_national_id": bool(item.get("national_id")),
                    "has_accounting_patient_id": item.get("accounting_patient_id")
                    not in (None, ""),
                }
            )
        self.report.unresolved_patients = redacted_unresolved

        financial = self.report.financial_data_out_of_scope
        if isinstance(financial, dict):
            wallets = financial.get("nonzero_patient_wallets") or []
            financial["nonzero_patient_wallets"] = [
                {
                    "source_patient_link_id": item.get("source_patient_link_id"),
                    "wallet_balance": item.get("wallet_balance"),
                }
                for item in wallets
            ]

    def _durable_ledger_count(self) -> int | None:
        """Read the post-transaction ledger count; failure here must not mask root cause."""
        try:
            _core.set_tenant_guc(self.tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM clinical.record_import_ledger
                    WHERE tenant_id=%s AND source_id=%s
                    """,
                    [self.tenant_id, self.source_id],
                )
                return int(cursor.fetchone()[0])
        except Exception:
            return None

    def _mark_failed_no_commit(self) -> None:
        self.report.transaction_status = "failed_no_commit"
        self.report.ledger_rows_after = self._durable_ledger_count()
        message = (
            "No import changes were committed. Per-table inserted/reused counters "
            "in this failed report describe attempted work before rollback."
        )
        if message not in self.report.warnings:
            self.report.warnings.append(message)

    def _assert_source_continuity(self) -> None:
        """Reject a source snapshot that omits rows imported under this source-id."""
        manifest_rows = {
            (str(table), int(source_row_id))
            for table, source_row_id, _digest in self._manifest
        }
        _core.set_tenant_guc(self.tenant_id)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT source_table, source_row_id
                FROM clinical.record_import_ledger
                WHERE tenant_id=%s AND source_id=%s
                ORDER BY source_table, source_row_id
                """,
                [self.tenant_id, self.source_id],
            )
            ledger_rows = {
                (str(table), int(source_row_id))
                for table, source_row_id in cursor.fetchall()
            }

        missing = sorted(ledger_rows - manifest_rows)
        if missing:
            preview = ", ".join(
                f"{table}#{source_row_id}" for table, source_row_id in missing[:10]
            )
            suffix = "" if len(missing) <= 10 else f" (+{len(missing) - 10} more)"
            raise _core.ImportConflictError(
                "The current SQLite snapshot is missing source rows previously "
                f"recorded for source_id={self.source_id!r}: {preview}{suffix}. "
                "Do not reuse a source-id for another database or a truncated snapshot."
            )

    def run(self) -> ImportReport:
        self.report.transaction_status = "running"
        try:
            # An outer transaction surrounds BOTH apply and dry-run. The core uses
            # an inner savepoint. This lets source-continuity validation roll back
            # newly imported target and ledger rows before the outer commit.
            with transaction.atomic():
                report = super().run()
                self._assert_source_continuity()
                if not self.apply:
                    transaction.set_rollback(True)

            if self.apply:
                self.report.transaction_status = "committed"
            else:
                self.report.transaction_status = "validated_no_commit"
            self.report.ledger_rows_after = self._durable_ledger_count()
        except _core.UnresolvedPatientError:
            source_ids = [
                item.get("source_patient_link_id")
                for item in self.report.unresolved_patients
            ]
            self._redact_sensitive_report()
            self._mark_failed_no_commit()
            rendered_ids = ",".join(
                str(item) for item in source_ids if item is not None
            ) or "unknown"
            # Suppress the original exception context: it contains the legacy
            # full_name/national_id detail and a generic traceback sink could log it.
            raise _core.UnresolvedPatientError(
                "Cannot resolve specialist patient row(s) to accounting.patients; "
                f"source patient_link id(s): {rendered_ids}. "
                "See the redacted reconciliation report and inspect the secured "
                "SQLite snapshot directly."
            ) from None
        except Exception:
            self._redact_sensitive_report()
            self._mark_failed_no_commit()
            raise

        self._redact_sensitive_report()
        return report

    def _insert(
        self,
        schema: str,
        table: str,
        payload: Mapping[str, Any],
    ) -> int:
        if self.apply:
            return super()._insert(schema, table, payload)

        assert self.pg is not None
        columns_available = self._columns(schema, table)
        if "id" not in columns_available:
            # Composite-key tables are handled explicitly by the core importer;
            # retain its no-write behaviour if one ever reaches this method.
            return super()._insert(schema, table, payload)

        target_id = self._pseudo()
        values = self._filtered_payload(schema, table, payload)
        values = {"id": target_id, **values}
        columns = list(values)
        query = sql.SQL("INSERT INTO {}.{} ({}) VALUES ({}) RETURNING id").format(
            sql.Identifier(schema),
            sql.Identifier(table),
            sql.SQL(", ").join(sql.Identifier(column) for column in columns),
            sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        )
        self.pg.execute(query, [values[column] for column in columns])
        return int(self.pg.fetchone()[0])


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
