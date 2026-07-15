from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any, Mapping

from django.db import connections, transaction

from accounting_ops.import_common import (
    AccountingImportError,
    PreflightRejectedError,
    SourceChangedError,
    TargetConflictError,
    file_sha256,
)
from accounting_ops.import_context import ImportContext
from accounting_ops.import_parents import ParentImporter
from accounting_ops.import_preflight import AccountingImportPreflight, SUPPORTED_TABLES
from accounting_ops.import_reconciliation import target_money
from accounting_ops.import_report import ImportReport
from accounting_ops.import_transactions import TransactionImporter
from accounting_ops.write_port import accounting_transaction


class _DryRunRollback(Exception):
    def __init__(self, report: ImportReport):
        super().__init__("dry-run rollback")
        self.report = report


def _assert_quiesced(path: Path) -> None:
    active: list[str] = []
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = path.with_name(path.name + suffix)
        if sidecar.exists() and sidecar.is_file() and sidecar.stat().st_size > 0:
            active.append(sidecar.name)
    if active:
        raise SourceChangedError(
            "SQLite source is no longer quiesced: " + ", ".join(active)
        )


def _load_rows(path: Path) -> dict[str, list[dict[str, Any]]]:
    db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
    db.row_factory = sqlite3.Row
    try:
        result: dict[str, list[dict[str, Any]]] = {}
        for table in SUPPORTED_TABLES:
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            order = "id" if "id" in columns else "invoice_id, item_type, item_id"
            result[table] = [
                dict(row)
                for row in db.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
            ]
        return result
    finally:
        db.close()


def _durable_ledger_count(*, tenant_id: int, source_id: str) -> int:
    with transaction.atomic(using="accounting_read"):
        with connections["accounting_read"].cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.current_tenant', %s, true)",
                [str(tenant_id)],
            )
            cursor.execute(
                """
                SELECT COUNT(*) FROM accounting.accounting_import_ledger
                WHERE tenant_id=%s AND source_id=%s
                """,
                [tenant_id, source_id],
            )
            return int(cursor.fetchone()[0])


class AccountingHistoryImporter:
    def __init__(
        self,
        *,
        sqlite_path: str | Path,
        source_id: str,
        tenant_id: int,
        imported_by: str,
        apply: bool = False,
        service_type_map: Mapping[str, str] | None = None,
    ):
        self.path = Path(sqlite_path).expanduser().absolute()
        self.source_id = source_id.strip()
        self.tenant_id = int(tenant_id)
        self.imported_by = imported_by.strip()
        self.apply = bool(apply)
        self.service_type_map = {
            str(key).strip().lower(): str(value).strip().lower()
            for key, value in (service_type_map or {}).items()
        }
        if self.tenant_id <= 0:
            raise ValueError("tenant_id must be positive")
        if not self.imported_by:
            raise ValueError("imported_by is required")

    def run(self) -> ImportReport:
        preflight = AccountingImportPreflight(
            sqlite_path=self.path,
            source_id=self.source_id,
        ).run()
        if preflight.decision != "GO":
            raise PreflightRejectedError(
                "Accounting preflight rejected the source snapshot: "
                + ", ".join(preflight.errors)
            )
        _assert_quiesced(self.path)
        if file_sha256(self.path) != preflight.source_file_sha256:
            raise SourceChangedError("SQLite source changed after preflight")

        rows = _load_rows(self.path)
        report = ImportReport(
            source_id=self.source_id,
            source_path=str(self.path),
            tenant_id=self.tenant_id,
            mode="apply" if self.apply else "dry-run",
            source_file_sha256=preflight.source_file_sha256,
            source_manifest_sha256=preflight.source_manifest_sha256,
            source_money=dict(preflight.money),
            warnings=list(preflight.warnings),
        )
        for table, table_rows in rows.items():
            report.table(table).source_rows = len(table_rows)
        report.ledger_rows_before = _durable_ledger_count(
            tenant_id=self.tenant_id,
            source_id=self.source_id,
        )

        try:
            with accounting_transaction(tenant_id=self.tenant_id) as conn:
                ctx = ImportContext(
                    conn=conn,
                    tenant_id=self.tenant_id,
                    source_id=self.source_id,
                    imported_by=self.imported_by,
                    apply=self.apply,
                    report=report,
                )
                ParentImporter(
                    ctx,
                    service_type_map=self.service_type_map,
                ).run(rows)
                TransactionImporter(ctx).run(rows)
                report.target_money = target_money(ctx)
                if report.target_money != report.source_money:
                    raise TargetConflictError(
                        "Imported target money aggregates do not match the source snapshot"
                    )
                _assert_quiesced(self.path)
                if file_sha256(self.path) != preflight.source_file_sha256:
                    raise SourceChangedError("SQLite source changed during import")
                if not self.apply:
                    report.transaction_status = "rolled_back"
                    report.ledger_rows_after = report.ledger_rows_before
                    raise _DryRunRollback(report)
                report.transaction_status = "commit_pending"

            report.transaction_status = "committed"
            report.ledger_rows_after = _durable_ledger_count(
                tenant_id=self.tenant_id,
                source_id=self.source_id,
            )
            return report
        except _DryRunRollback as signal:
            return signal.report
        except Exception as exc:
            report.transaction_status = "failed_no_commit"
            report.ledger_rows_after = _durable_ledger_count(
                tenant_id=self.tenant_id,
                source_id=self.source_id,
            )
            report.error = type(exc).__name__
            if isinstance(exc, AccountingImportError):
                raise
            raise AccountingImportError(
                f"Accounting import failed: {type(exc).__name__}"
            ) from exc
