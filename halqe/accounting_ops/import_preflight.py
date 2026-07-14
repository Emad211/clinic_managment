"""Fail-closed preflight for the legacy Flask accounting SQLite database.

This module performs no PostgreSQL writes. It validates source integrity,
required schemas, relational references and the exact money aggregates that
must later reconcile after import.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable

from accounting_ops.import_preflight_models import (
    AccountingImportPreflightReport,
    TablePreflight,
)


_SOURCE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{2,179}$")

SUPPORTED_TABLES: dict[str, tuple[str, ...]] = {
    "medical_staff": ("id", "full_name", "staff_type", "is_active"),
    "patients": ("id", "name", "family_name"),
    "visit_tariffs": ("id", "insurance_type", "tariff_price"),
    "services": ("id", "name", "base_price", "service_type"),
    "visit_items": ("id", "visit_id", "service_id", "quantity", "price_at_time"),
    "nursing_services": ("id", "service_name", "unit_price"),
    "injection_types": ("id", "type_name", "base_price"),
    "procedure_tariffs": ("id", "name", "unit_price"),
    "consumable_tariffs": ("id", "name", "default_price", "category"),
    "insurance_nursing_exclusions": (
        "id", "insurance_type", "nursing_service_id"
    ),
    "payroll_settings": ("id", "staff_id"),
    "invoices": ("id", "patient_id", "status", "total_amount"),
    "visits": ("id", "patient_id", "price", "invoice_id"),
    "injections": (
        "id", "patient_id", "injection_type", "total_price", "invoice_id"
    ),
    "procedures": ("id", "patient_id", "procedure_type", "price", "invoice_id"),
    "consumables_ledger": ("id", "item_name", "total_cost", "invoice_id"),
    "invoice_item_payments": (
        "invoice_id", "item_type", "item_id", "is_paid"
    ),
}

IGNORED_TABLES = frozenset({
    "users",
    "activity_logs",
    "user_active_shift",
    "settings",
    "sqlite_sequence",
})


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _rows_digest(rows: Iterable[sqlite3.Row]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        payload = {
            key: _canonical(row[key])
            for key in sorted(row.keys())
        }
        digest.update(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _scalar(db: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = db.execute(sql, params).fetchone()
    return row[0] if row else 0


def _table_names(db: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def _ordered_rows(db: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    columns = _columns(db, table)
    if "id" in columns:
        order = "id"
    elif table == "invoice_item_payments":
        order = "invoice_id, item_type, item_id"
    else:
        order = "rowid"
    return db.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()


def _orphan_count(
    db: sqlite3.Connection,
    *,
    child: str,
    child_column: str,
    parent: str,
    parent_column: str = "id",
    nullable: bool = False,
) -> int:
    null_clause = f" AND c.{child_column} IS NOT NULL" if nullable else ""
    return int(_scalar(
        db,
        f"""
        SELECT COUNT(*)
        FROM {child} c
        LEFT JOIN {parent} p ON p.{parent_column}=c.{child_column}
        WHERE p.{parent_column} IS NULL {null_clause}
        """,
    ))


def _money(db: sqlite3.Connection, table: str, column: str, where: str = "1=1") -> int:
    return int(round(float(_scalar(
        db,
        f"SELECT COALESCE(SUM({column}),0) FROM {table} WHERE {where}",
    ) or 0)))


class AccountingImportPreflight:
    def __init__(self, *, sqlite_path: str | Path, source_id: str):
        self.path = Path(sqlite_path).expanduser().absolute()
        self.source_id = source_id.strip()
        self.report = AccountingImportPreflightReport(
            source_id=self.source_id,
            source_path=str(self.path),
        )

    def _source_guard(self) -> None:
        self.report.check(
            "source_id",
            bool(_SOURCE_ID.fullmatch(self.source_id)),
            "source-id must be stable and use only letters, numbers, dot, dash or underscore",
        )
        self.report.check(
            "source_file",
            self.path.is_file() and not self.path.is_symlink(),
            "source must be an existing regular SQLite snapshot, not a symlink",
        )
        if not self.path.is_file() or self.path.is_symlink():
            return
        sidecars = {
            suffix: self.path.with_name(self.path.name + suffix).stat().st_size
            for suffix in ("-wal", "-shm", "-journal")
            if self.path.with_name(self.path.name + suffix).exists()
            and self.path.with_name(self.path.name + suffix).stat().st_size > 0
        }
        self.report.check(
            "quiesced_snapshot",
            not sidecars,
            "SQLite snapshot must have no non-empty WAL, SHM or rollback journal",
            sidecars=sidecars,
        )

    def run(self) -> AccountingImportPreflightReport:
        self._source_guard()
        if self.report.errors:
            return self.report.finalize()

        before = _sha256_file(self.path)
        self.report.source_file_sha256 = before
        uri = f"file:{self.path.as_posix()}?mode=ro&immutable=1"
        try:
            db = sqlite3.connect(uri, uri=True)
            db.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            self.report.check("sqlite_open", False, f"cannot open source: {type(exc).__name__}")
            return self.report.finalize()

        try:
            quick = db.execute("PRAGMA quick_check").fetchone()
            self.report.quick_check = str(quick[0] if quick else "missing")
            self.report.check(
                "quick_check",
                self.report.quick_check.lower() == "ok",
                "SQLite PRAGMA quick_check must return ok",
                result=self.report.quick_check,
            )
            names = _table_names(db)
            for table, required in SUPPORTED_TABLES.items():
                if table not in names:
                    self.report.tables[table] = TablePreflight(
                        source_rows=0,
                        missing_columns=list(required),
                    )
                    self.report.check(
                        f"table_{table}", False, f"required table {table} is missing"
                    )
                    continue
                columns = _columns(db, table)
                missing = sorted(set(required) - columns)
                rows = _ordered_rows(db, table)
                self.report.tables[table] = TablePreflight(
                    source_rows=len(rows),
                    manifest_sha256=_rows_digest(rows),
                    missing_columns=missing,
                )
                self.report.check(
                    f"schema_{table}",
                    not missing,
                    f"required columns for {table}",
                    missing_columns=missing,
                )

            self.report.ignored_tables = {
                table: int(_scalar(db, f"SELECT COUNT(*) FROM {table}"))
                for table in sorted(names & IGNORED_TABLES)
            }
            unknown = sorted(names - set(SUPPORTED_TABLES) - IGNORED_TABLES)
            if unknown:
                self.report.warnings.append(
                    "Source contains unclassified tables: " + ", ".join(unknown)
                )

            if not self.report.errors:
                self._relationships(db)
                self._money_snapshot(db)
                self._manifest()
        finally:
            db.close()

        after = _sha256_file(self.path)
        self.report.check(
            "source_immutable",
            after == before,
            "source file hash must stay unchanged during preflight",
            before=before,
            after=after,
        )
        return self.report.finalize()

    def _relationships(self, db: sqlite3.Connection) -> None:
        checks = [
            ("invoice_patient", "invoices", "patient_id", "patients", False),
            ("visit_patient", "visits", "patient_id", "patients", False),
            ("visit_invoice", "visits", "invoice_id", "invoices", True),
            ("injection_patient", "injections", "patient_id", "patients", False),
            ("injection_invoice", "injections", "invoice_id", "invoices", True),
            ("procedure_patient", "procedures", "patient_id", "patients", False),
            ("procedure_invoice", "procedures", "invoice_id", "invoices", True),
            ("consumable_patient", "consumables_ledger", "patient_id", "patients", True),
            ("consumable_invoice", "consumables_ledger", "invoice_id", "invoices", True),
            ("payroll_staff", "payroll_settings", "staff_id", "medical_staff", False),
            ("exclusion_service", "insurance_nursing_exclusions", "nursing_service_id", "nursing_services", False),
            ("visit_item_visit", "visit_items", "visit_id", "visits", False),
            ("visit_item_service", "visit_items", "service_id", "services", False),
        ]
        for code, child, column, parent, nullable in checks:
            count = _orphan_count(
                db,
                child=child,
                child_column=column,
                parent=parent,
                nullable=nullable,
            )
            self.report.check(
                f"fk_{code}", count == 0, f"{child}.{column} must resolve", orphan_rows=count
            )

        payment_orphans = int(_scalar(
            db,
            """
            SELECT COUNT(*)
            FROM invoice_item_payments p
            LEFT JOIN invoices i ON i.id=p.invoice_id
            WHERE i.id IS NULL
               OR (p.item_type='visit' AND NOT EXISTS (
                     SELECT 1 FROM visits v WHERE v.id=p.item_id AND v.invoice_id=p.invoice_id))
               OR (p.item_type='injection' AND NOT EXISTS (
                     SELECT 1 FROM injections n WHERE n.id=p.item_id AND n.invoice_id=p.invoice_id))
               OR (p.item_type='procedure' AND NOT EXISTS (
                     SELECT 1 FROM procedures r WHERE r.id=p.item_id AND r.invoice_id=p.invoice_id))
               OR (p.item_type='consumable' AND NOT EXISTS (
                     SELECT 1 FROM consumables_ledger c WHERE c.id=p.item_id AND c.invoice_id=p.invoice_id))
               OR p.item_type NOT IN ('visit','injection','procedure','consumable')
            """,
        ))
        self.report.check(
            "payment_item_references",
            payment_orphans == 0,
            "every payment row must resolve to an item in the same invoice",
            orphan_rows=payment_orphans,
        )

    def _money_snapshot(self, db: sqlite3.Connection) -> None:
        self.report.money = {
            "invoice_total_all": _money(db, "invoices", "total_amount"),
            "invoice_total_open": _money(db, "invoices", "total_amount", "status='open'"),
            "invoice_total_closed": _money(db, "invoices", "total_amount", "status='closed'"),
            "visit_raw": _money(db, "visits", "price"),
            "nursing_raw": _money(db, "injections", "total_price"),
            "procedure_raw": _money(db, "procedures", "price"),
            "consumables_all": _money(db, "consumables_ledger", "total_cost"),
            "consumables_center": _money(
                db,
                "consumables_ledger",
                "total_cost",
                "COALESCE(patient_provided,0)=0 AND COALESCE(is_exception,0)=0",
            ),
            "payments_total": int(_scalar(db, "SELECT COUNT(*) FROM invoice_item_payments")),
            "payments_paid": int(_scalar(db, "SELECT COUNT(*) FROM invoice_item_payments WHERE COALESCE(is_paid,0)=1")),
            "payments_unpaid": int(_scalar(db, "SELECT COUNT(*) FROM invoice_item_payments WHERE COALESCE(is_paid,0)=0")),
        }
        self.report.money["operating_revenue_raw"] = (
            self.report.money["visit_raw"]
            + self.report.money["nursing_raw"]
            + self.report.money["procedure_raw"]
        )

    def _manifest(self) -> None:
        digest = hashlib.sha256()
        for table in sorted(self.report.tables):
            item = self.report.tables[table]
            digest.update(table.encode("utf-8"))
            digest.update(b":")
            digest.update(item.manifest_sha256.encode("ascii"))
            digest.update(b"\n")
        self.report.source_manifest_sha256 = digest.hexdigest()
