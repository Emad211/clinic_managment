from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3
from typing import Any

from accounting_ops.import_common import SourceDatabaseError


_REQUIRED = {
    "invoices": {"id", "work_date", "shift", "insurance_type", "status", "total_amount"},
    "visits": {"id", "invoice_id", "work_date", "shift", "price"},
    "injections": {"id", "invoice_id", "work_date", "shift", "total_price"},
    "procedures": {"id", "invoice_id", "work_date", "shift", "price"},
    "consumables_ledger": {
        "id", "invoice_id", "work_date", "shift", "total_cost",
        "patient_provided", "is_exception",
    },
    "invoice_item_payments": {"invoice_id", "item_type", "item_id", "is_paid"},
}


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in db.execute(f"PRAGMA table_info({table})")}


def _rows(db: sqlite3.Connection, query: str, params: list[Any]) -> list[dict[str, Any]]:
    cursor = db.execute(query, params)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _shift_filter(alias: str, shift: str | None) -> tuple[str, list[Any]]:
    return (f" AND {alias}.shift=?", [shift]) if shift else ("", [])


def load_legacy_financial_rows(
    *,
    sqlite_path: str | Path,
    date_from: date,
    date_to: date,
    shift: str | None,
) -> dict[str, list[dict[str, Any]]]:
    path = Path(sqlite_path).expanduser().absolute()
    if not path.is_file() or path.is_symlink():
        raise SourceDatabaseError("Dual-run source must be a regular SQLite snapshot")
    uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
    try:
        db = sqlite3.connect(uri, uri=True)
        db.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        raise SourceDatabaseError(f"Cannot open dual-run SQLite snapshot: {type(exc).__name__}") from exc
    try:
        quick = db.execute("PRAGMA quick_check").fetchone()
        if not quick or str(quick[0]).lower() != "ok":
            raise SourceDatabaseError("Dual-run SQLite quick_check did not return ok")
        names = {
            str(row[0])
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for table, required in _REQUIRED.items():
            if table not in names:
                raise SourceDatabaseError(f"Dual-run source table is missing: {table}")
            missing = sorted(required - _columns(db, table))
            if missing:
                raise SourceDatabaseError(
                    f"Dual-run source {table} is missing columns: {', '.join(missing)}"
                )

        start, end = date_from.isoformat(), date_to.isoformat()
        clause, shift_params = _shift_filter("i", shift)
        invoices = _rows(
            db,
            f"""
            SELECT i.work_date,COALESCE(i.shift,'unknown') AS shift,
                   COALESCE(i.insurance_type,'unknown') AS insurance_type,
                   COALESCE(i.status,'open') AS status,
                   COALESCE(i.total_amount,0) AS amount
            FROM invoices i
            WHERE i.work_date BETWEEN ? AND ? {clause}
            ORDER BY i.work_date,i.id
            """,
            [start, end, *shift_params],
        )

        events: list[dict[str, Any]] = []
        event_specs = (
            ("visit", "visits", "price", "0"),
            ("nursing", "injections", "total_price", "0"),
            ("procedure", "procedures", "price", "0"),
            (
                "consumable",
                "consumables_ledger",
                "total_cost",
                "CASE WHEN COALESCE(e.patient_provided,0)=0 "
                "AND COALESCE(e.is_exception,0)=0 THEN 1 ELSE 0 END",
            ),
        )
        for kind, table, amount_column, center_expression in event_specs:
            clause, shift_params = _shift_filter("e", shift)
            events.extend(
                _rows(
                    db,
                    f"""
                    SELECT '{kind}' AS kind,e.work_date,
                           COALESCE(e.shift,'unknown') AS shift,
                           COALESCE(i.insurance_type,'unknown') AS insurance_type,
                           COALESCE(i.status,'open') AS invoice_status,
                           COALESCE(e.{amount_column},0) AS amount,
                           {center_expression} AS center_supplied
                    FROM {table} e
                    JOIN invoices i ON i.id=e.invoice_id
                    WHERE e.work_date BETWEEN ? AND ? {clause}
                    ORDER BY e.work_date,e.id
                    """,
                    [start, end, *shift_params],
                )
            )

        clause, shift_params = _shift_filter("i", shift)
        payments = _rows(
            db,
            f"""
            SELECT i.work_date,COALESCE(i.shift,'unknown') AS shift,
                   COALESCE(i.insurance_type,'unknown') AS insurance_type,
                   COALESCE(p.is_paid,0) AS is_paid
            FROM invoice_item_payments p
            JOIN invoices i ON i.id=p.invoice_id
            WHERE i.work_date BETWEEN ? AND ? {clause}
            ORDER BY i.work_date,p.invoice_id,p.item_type,p.item_id
            """,
            [start, end, *shift_params],
        )
        return {"invoices": invoices, "events": events, "payments": payments}
    finally:
        db.close()
