"""Strict read-only accounting evidence for specialist reconciliation.

The accounting database is opened with SQLite ``mode=ro`` and ``query_only=ON``.
No schema migration, status update, payment write, or sidecar creation is allowed here.

A7 separates only payer facts explicitly present in accounting. A8 additionally captures
visit, injection, and procedure line items from the *same pinned read transaction* as the
financial snapshot. Description, performer and timing fields are populated only when the
accounting schema explicitly exposes them; absent optional fields remain null or use the
structural item-type label rather than a fabricated clinical interpretation.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from typing import Any

from src.adapters.accounting_path import accounting_db_path


class AccountingInvoiceUnavailable(RuntimeError):
    pass


class AccountingInvoiceSchemaError(RuntimeError):
    pass


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _connect() -> sqlite3.Connection:
    path = accounting_db_path()
    if not path or not os.path.isfile(path):
        raise AccountingInvoiceUnavailable("accounting database is unavailable")
    try:
        uri = f"file:{path.replace(os.sep, '/')}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection
    except sqlite3.Error as exc:
        raise AccountingInvoiceUnavailable(str(exc)) from exc


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _assert_schema(connection: sqlite3.Connection) -> None:
    required = {
        "invoices",
        "visits",
        "injections",
        "procedures",
        "invoice_item_payments",
    }
    missing = sorted(required - _tables(connection))
    if missing:
        raise AccountingInvoiceSchemaError(
            "missing accounting invoice tables: " + ",".join(missing)
        )

    required_columns = {
        "invoices": {
            "id", "patient_id", "status", "work_date", "opened_at",
            "closed_at", "total_amount",
        },
        "visits": {"id", "invoice_id", "price"},
        "injections": {"id", "invoice_id", "total_price"},
        "procedures": {"id", "invoice_id", "price"},
        "invoice_item_payments": {
            "invoice_id", "item_type", "item_id", "is_paid",
        },
    }
    for table, expected in required_columns.items():
        absent = sorted(expected - _table_columns(connection, table))
        if absent:
            raise AccountingInvoiceSchemaError(
                f"missing accounting columns in {table}: " + ",".join(absent)
            )


def is_available() -> bool:
    try:
        connection = _connect()
        try:
            _assert_schema(connection)
            return True
        finally:
            connection.close()
    except (AccountingInvoiceUnavailable, AccountingInvoiceSchemaError):
        return False


def _optional_column(columns: set[str], name: str, *, alias: str | None = None) -> str:
    output = alias or name
    return f"item.{name} AS {output}" if name in columns else f"NULL AS {output}"


def _invoice_optional(columns: set[str], name: str) -> str:
    return name if name in columns else f"NULL AS {name}"


def _invoice_row(connection: sqlite3.Connection, invoice_id: int) -> dict:
    columns = _table_columns(connection, "invoices")
    insurance = _invoice_optional(columns, "insurance_type")
    supplementary = _invoice_optional(columns, "supplementary_insurance")
    row = connection.execute(
        f"""SELECT id AS invoice_id,patient_id,status,work_date,
                   opened_at,closed_at,total_amount,{insurance},{supplementary}
            FROM invoices WHERE id=?""",
        (int(invoice_id),),
    ).fetchone()
    if not row:
        raise LookupError("accounting invoice not found")
    return dict(row)


def _category(
    connection: sqlite3.Connection,
    *,
    invoice_id: int,
    table: str,
    amount_column: str,
    item_type: str,
    payment_type_available: bool,
) -> dict[str, int]:
    payment_type = (
        "lower(trim(COALESCE(payment.payment_type,'')))"
        if payment_type_available
        else "''"
    )
    row = connection.execute(
        f"""SELECT COUNT(*) AS item_count,
                    COALESCE(SUM(item.{amount_column}),0) AS billed,
                    COALESCE(SUM(CASE WHEN payment.is_paid=1
                        THEN item.{amount_column} ELSE 0 END),0) AS collected,
                    COALESCE(SUM(CASE WHEN payment.is_paid=1
                        THEN 1 ELSE 0 END),0) AS paid_count,
                    COALESCE(SUM(CASE WHEN COALESCE(payment.is_paid,0)<>1
                        THEN item.{amount_column} ELSE 0 END),0) AS unpaid,
                    COALESCE(SUM(CASE WHEN COALESCE(payment.is_paid,0)<>1
                        THEN 1 ELSE 0 END),0) AS unpaid_count,
                    COALESCE(SUM(CASE WHEN payment.is_paid=1
                        AND {payment_type}='cash'
                        THEN item.{amount_column} ELSE 0 END),0) AS cash_collected,
                    COALESCE(SUM(CASE WHEN payment.is_paid=1
                        AND {payment_type}='card'
                        THEN item.{amount_column} ELSE 0 END),0) AS card_collected,
                    COALESCE(SUM(CASE WHEN payment.is_paid=1
                        AND {payment_type}='insurance'
                        THEN item.{amount_column} ELSE 0 END),0) AS insurance_collected,
                    COALESCE(SUM(CASE WHEN payment.is_paid=1
                        AND {payment_type} NOT IN ('cash','card','insurance')
                        THEN item.{amount_column} ELSE 0 END),0) AS unknown_collected,
                    COALESCE(SUM(CASE WHEN payment.is_paid=1
                        AND {payment_type} NOT IN ('cash','card','insurance')
                        THEN 1 ELSE 0 END),0) AS unknown_type_count
             FROM {table} item
             LEFT JOIN invoice_item_payments payment
               ON payment.invoice_id=item.invoice_id
              AND payment.item_type=?
              AND payment.item_id=item.id
             WHERE item.invoice_id=?""",
        (item_type, int(invoice_id)),
    ).fetchone()
    return {
        "item_count": int(row["item_count"] or 0),
        "billed": int(row["billed"] or 0),
        "collected": int(row["collected"] or 0),
        "paid_count": int(row["paid_count"] or 0),
        "unpaid": int(row["unpaid"] or 0),
        "unpaid_count": int(row["unpaid_count"] or 0),
        "cash_collected": int(row["cash_collected"] or 0),
        "card_collected": int(row["card_collected"] or 0),
        "insurance_collected": int(row["insurance_collected"] or 0),
        "unknown_collected": int(row["unknown_collected"] or 0),
        "unknown_type_count": int(row["unknown_type_count"] or 0),
    }


def _financial_snapshot(
    connection: sqlite3.Connection,
    *,
    invoice: dict,
) -> dict[str, Any]:
    invoice_id = int(invoice["invoice_id"])
    payment_type_available = (
        "payment_type" in _table_columns(connection, "invoice_item_payments")
    )
    visits = _category(
        connection,
        invoice_id=invoice_id,
        table="visits",
        amount_column="price",
        item_type="visit",
        payment_type_available=payment_type_available,
    )
    injections = _category(
        connection,
        invoice_id=invoice_id,
        table="injections",
        amount_column="total_price",
        item_type="injection",
        payment_type_available=payment_type_available,
    )
    procedures = _category(
        connection,
        invoice_id=invoice_id,
        table="procedures",
        amount_column="price",
        item_type="procedure",
        payment_type_available=payment_type_available,
    )
    categories = (visits, injections, procedures)
    billed = sum(category["billed"] for category in categories)
    collected = sum(category["collected"] for category in categories)
    item_count = sum(category["item_count"] for category in categories)
    paid_count = sum(category["paid_count"] for category in categories)
    unpaid_count = sum(category["unpaid_count"] for category in categories)
    cash_collected = sum(category["cash_collected"] for category in categories)
    card_collected = sum(category["card_collected"] for category in categories)
    insurance_collected = sum(
        category["insurance_collected"] for category in categories
    )
    unknown_collected = sum(category["unknown_collected"] for category in categories)
    unpaid_amount = sum(category["unpaid"] for category in categories)
    unknown_type_count = sum(
        category["unknown_type_count"] for category in categories
    )
    if cash_collected + card_collected + insurance_collected + unknown_collected != collected:
        raise AccountingInvoiceSchemaError(
            "payer breakdown does not equal collected amount"
        )

    status = str(invoice["status"] or "").strip().lower()
    if status != "closed":
        collection_state = "WAITING_FOR_INVOICE_CLOSURE"
    elif item_count == 0:
        collection_state = "CLOSED_NO_BILLABLE_ITEMS"
    elif collected <= 0:
        collection_state = "UNPAID"
    elif collected < billed:
        collection_state = "PARTIALLY_COLLECTED"
    else:
        collection_state = "COLLECTED"

    payload = {
        "accounting_invoice_id": invoice_id,
        "accounting_patient_id": int(invoice["patient_id"]),
        "invoice_status": status or "unknown",
        "work_date": invoice["work_date"],
        "opened_at": invoice["opened_at"],
        "closed_at": invoice["closed_at"],
        "insurance_type": invoice.get("insurance_type"),
        "supplementary_insurance": invoice.get("supplementary_insurance"),
        "source_total_amount": (
            int(invoice["total_amount"])
            if invoice["total_amount"] is not None
            else None
        ),
        "visits_billed": visits["billed"],
        "injections_billed": injections["billed"],
        "procedures_billed": procedures["billed"],
        "billed_amount": billed,
        "visits_collected": visits["collected"],
        "injections_collected": injections["collected"],
        "procedures_collected": procedures["collected"],
        "collected_amount": collected,
        "billable_item_count": item_count,
        "paid_item_count": paid_count,
        "unpaid_item_count": unpaid_count,
        "collection_state": collection_state,
        "payment_evidence": "ITEM_PAID_FLAGS",
        "patient_cash_collected": cash_collected,
        "patient_card_collected": card_collected,
        "insurance_collected": insurance_collected,
        "unknown_collected": unknown_collected,
        "unpaid_amount": unpaid_amount,
        "unknown_payment_type_count": unknown_type_count,
        "payer_breakdown_evidence": (
            "ACCOUNTING_ITEM_PAYMENT_TYPE_V1"
            if payment_type_available
            else "LEGACY_UNAVAILABLE"
        ),
    }
    payload["source_fingerprint"] = _canonical_hash(payload)
    return payload


def _performed_expression(columns: set[str], preferred: str) -> str:
    if preferred in columns:
        return f"item.{preferred}"
    return "COALESCE(invoice.closed_at, invoice.opened_at, invoice.work_date)"


def _service_rows(
    connection: sqlite3.Connection,
    *,
    invoice_id: int,
    table: str,
    item_type: str,
    structural_label: str,
    amount_column: str,
    preferred_date: str,
) -> list[dict[str, Any]]:
    columns = _table_columns(connection, table)
    performed = _performed_expression(columns, preferred_date)
    source_status = _optional_column(columns, "status", alias="source_status")

    if item_type == "VISIT":
        description = "'ویزیت' AS description"
        quantity = "1 AS quantity"
        unit_amount = f"item.{amount_column} AS unit_amount"
        doctor_id = "item.doctor_id" if "doctor_id" in columns else "NULL"
        doctor_name = (
            "item.doctor_name" if "doctor_name" in columns else "NULL"
        )
        performer_type = (
            f"CASE WHEN {doctor_id} IS NOT NULL OR "
            f"length(trim(COALESCE({doctor_name},'')))>0 "
            "THEN 'doctor' END AS performer_type"
        )
        performer_id = f"{doctor_id} AS performer_id"
        performer_name = f"{doctor_name} AS performer_name"
    elif item_type == "INJECTION":
        description = (
            "COALESCE(NULLIF(trim(item.injection_type),''),'تزریق') AS description"
            if "injection_type" in columns
            else "'تزریق' AS description"
        )
        quantity = (
            "COALESCE(item.count,1) AS quantity"
            if "count" in columns
            else "1 AS quantity"
        )
        unit_amount = _optional_column(columns, "unit_price", alias="unit_amount")
        if "nurse_id" in columns or "doctor_id" in columns:
            nurse = "item.nurse_id" if "nurse_id" in columns else "NULL"
            doctor = "item.doctor_id" if "doctor_id" in columns else "NULL"
            performer_type = (
                f"CASE WHEN {nurse} IS NOT NULL THEN 'nurse' "
                f"WHEN {doctor} IS NOT NULL THEN 'doctor' END AS performer_type"
            )
            performer_id = f"COALESCE({nurse},{doctor}) AS performer_id"
        else:
            performer_type = "NULL AS performer_type"
            performer_id = "NULL AS performer_id"
        performer_name = "NULL AS performer_name"
    else:
        description = (
            "COALESCE(NULLIF(trim(item.procedure_type),''),'خدمت عملی') AS description"
            if "procedure_type" in columns
            else "'خدمت عملی' AS description"
        )
        quantity = "1 AS quantity"
        unit_amount = f"item.{amount_column} AS unit_amount"
        if "performer_type" in columns:
            performer_type = "item.performer_type AS performer_type"
        elif "nurse_id" in columns or "doctor_id" in columns:
            nurse = "item.nurse_id" if "nurse_id" in columns else "NULL"
            doctor = "item.doctor_id" if "doctor_id" in columns else "NULL"
            performer_type = (
                f"CASE WHEN {nurse} IS NOT NULL THEN 'nurse' "
                f"WHEN {doctor} IS NOT NULL THEN 'doctor' END AS performer_type"
            )
        else:
            performer_type = "NULL AS performer_type"
        if "performer_id" in columns:
            performer_id = "item.performer_id AS performer_id"
        elif "nurse_id" in columns or "doctor_id" in columns:
            nurse = "item.nurse_id" if "nurse_id" in columns else "NULL"
            doctor = "item.doctor_id" if "doctor_id" in columns else "NULL"
            performer_id = f"COALESCE({nurse},{doctor}) AS performer_id"
        else:
            performer_id = "NULL AS performer_id"
        performer_name = "NULL AS performer_name"

    rows = connection.execute(
        f"""SELECT item.id AS accounting_item_id,
                   ? AS item_type,
                   {description},
                   {performed} AS performed_at,
                   invoice.work_date AS work_date,
                   {quantity},
                   {unit_amount},
                   item.{amount_column} AS total_amount,
                   {performer_type},
                   {performer_id},
                   {performer_name},
                   {source_status}
            FROM {table} item
            JOIN invoices invoice ON invoice.id=item.invoice_id
            WHERE item.invoice_id=?
            ORDER BY item.id""",
        (item_type, int(invoice_id)),
    ).fetchall()
    output: list[dict[str, Any]] = []
    for row in rows:
        line = dict(row)
        line["accounting_item_id"] = int(line["accounting_item_id"])
        line["quantity"] = (
            float(line["quantity"]) if line["quantity"] is not None else None
        )
        line["unit_amount"] = (
            int(line["unit_amount"]) if line["unit_amount"] is not None else None
        )
        line["total_amount"] = int(line["total_amount"] or 0)
        line["performer_id"] = (
            int(line["performer_id"])
            if line["performer_id"] is not None
            else None
        )
        line["description"] = str(line["description"] or structural_label).strip()
        line["source_fingerprint"] = _canonical_hash(line)
        output.append(line)
    return output


def _service_snapshot(
    connection: sqlite3.Connection,
    *,
    invoice: dict,
    financial: dict,
) -> dict[str, Any]:
    invoice_id = int(invoice["invoice_id"])
    lines = [
        *_service_rows(
            connection,
            invoice_id=invoice_id,
            table="visits",
            item_type="VISIT",
            structural_label="ویزیت",
            amount_column="price",
            preferred_date="visit_date",
        ),
        *_service_rows(
            connection,
            invoice_id=invoice_id,
            table="injections",
            item_type="INJECTION",
            structural_label="تزریق",
            amount_column="total_price",
            preferred_date="injection_date",
        ),
        *_service_rows(
            connection,
            invoice_id=invoice_id,
            table="procedures",
            item_type="PROCEDURE",
            structural_label="خدمت عملی",
            amount_column="price",
            preferred_date="procedure_date",
        ),
    ]
    order = {"VISIT": 1, "INJECTION": 2, "PROCEDURE": 3}
    lines.sort(
        key=lambda row: (
            order[str(row["item_type"])], int(row["accounting_item_id"])
        )
    )
    for sequence, line in enumerate(lines, start=1):
        line["line_sequence"] = sequence
        line["source_fingerprint"] = _canonical_hash(line)

    expected_count = int(financial["billable_item_count"])
    expected_total = int(financial["billed_amount"])
    if len(lines) != expected_count:
        raise AccountingInvoiceSchemaError(
            "service line count does not equal financial billable item count"
        )
    if sum(int(line["total_amount"]) for line in lines) != expected_total:
        raise AccountingInvoiceSchemaError(
            "service line total does not equal financial billed amount"
        )
    payload = {
        "status": "COMPLETE",
        "accounting_invoice_id": invoice_id,
        "accounting_patient_id": int(invoice["patient_id"]),
        "expected_line_count": expected_count,
        "expected_total_amount": expected_total,
        "line_fingerprints": [line["source_fingerprint"] for line in lines],
        "lines": lines,
        "evidence_code": "ACCOUNTING_SERVICE_LINES_V1",
    }
    payload["source_fingerprint"] = _canonical_hash(
        {key: value for key, value in payload.items() if key != "lines"}
    )
    return payload


def invoice_reconciliation_bundle(accounting_invoice_id: int) -> dict[str, Any]:
    """Return financial and service evidence from one pinned accounting snapshot."""
    invoice_id = int(accounting_invoice_id)
    if invoice_id <= 0:
        raise ValueError("accounting_invoice_id must be positive")
    connection = _connect()
    try:
        _assert_schema(connection)
        connection.execute("BEGIN")
        invoice = _invoice_row(connection, invoice_id)
        financial = _financial_snapshot(connection, invoice=invoice)
        services = _service_snapshot(
            connection,
            invoice=invoice,
            financial=financial,
        )
        connection.rollback()
        return {"financial": financial, "services": services}
    except sqlite3.Error as exc:
        try:
            connection.rollback()
        except sqlite3.Error:
            pass
        raise AccountingInvoiceSchemaError(str(exc)) from exc
    finally:
        connection.close()


def invoice_financial_snapshot(accounting_invoice_id: int) -> dict[str, Any]:
    """Compatibility API; financial data comes from the strict pinned bundle."""
    return invoice_reconciliation_bundle(accounting_invoice_id)["financial"]


__all__ = [
    "AccountingInvoiceSchemaError",
    "AccountingInvoiceUnavailable",
    "invoice_financial_snapshot",
    "invoice_reconciliation_bundle",
    "is_available",
]
