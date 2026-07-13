"""Public facade for the specialist-clinic historical record importer.

The implementation lives in :mod:`clinical._specialist_record_import_core`.
This facade strengthens dry-run semantics: planned rows are inserted with
explicit negative primary keys inside an outer transaction that is always
rolled back.  PostgreSQL therefore validates the real foreign keys, checks and
catalog lookups, while the dry run leaves no rows behind and never advances an
identity sequence.
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
    """Importer with a transactionally faithful, sequence-neutral dry run."""

    def run(self) -> ImportReport:
        if self.apply:
            return super().run()

        # The core importer already uses an inner atomic block.  The outer block
        # lets us materialize planned rows for genuine FK/catalog validation and
        # then discard the complete simulation in one rollback.
        with transaction.atomic():
            report = super().run()
            transaction.set_rollback(True)
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
