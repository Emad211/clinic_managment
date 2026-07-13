"""Public facade for the specialist-clinic historical record importer.

The implementation lives in :mod:`clinical._specialist_record_import_core`.
This facade strengthens two operational boundaries:

* dry-run rows use explicit negative primary keys inside a transaction that is
  always rolled back, validating real PostgreSQL relationships without leaving
  data behind or advancing identities;
* reports and command errors redact raw patient identifiers by default so
  national IDs and names cannot leak into shell, CI or generic job logs.
"""
from __future__ import annotations

from typing import Any, Mapping

from django.db import transaction
from psycopg import sql

from clinical import _specialist_record_import_core as _core
from clinical._specialist_record_import_core import (
    FinancialDataOutOfScopeError,
    ImportConflictError,
    ImportReport,
    SourceDatabaseError,
    SourceRowChangedError,
    SpecialistRecordImportError,
    SQLiteSnapshot,
    TableStats,
    UnresolvedPatientError,
)


class SpecialistRecordImporter(_core.SpecialistRecordImporter):
    """Importer with sequence-neutral dry-run and PHI-safe default reporting."""

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

    def run(self) -> ImportReport:
        try:
            if self.apply:
                report = super().run()
            else:
                # The core importer already uses an inner atomic block. The outer
                # block materializes planned rows for genuine FK/catalog validation
                # and discards the complete simulation in one rollback.
                with transaction.atomic():
                    report = super().run()
                    transaction.set_rollback(True)
        except _core.UnresolvedPatientError:
            source_ids = [
                item.get("source_patient_link_id")
                for item in self.report.unresolved_patients
            ]
            self._redact_sensitive_report()
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
