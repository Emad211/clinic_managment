from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from accounting_ops.import_common import (
    AccountingImportError,
    TargetConflictError,
    boolean,
    clean_text,
    decimal_quantity,
    integer_money,
    normalize,
)
from accounting_ops.import_context import ImportContext
from accounting_ops.import_parents import _finish_simple, _insert_id


def _optional_money(value: Any, *, field: str) -> int | None:
    if value is None or value == "":
        return None
    return integer_money(value, field=field)


def _date(value: Any) -> str | None:
    text = clean_text(value)
    return text[:10] if text else None


def _timestamp(value: Any, *, fallback_date: Any = None) -> str | None:
    text = clean_text(value)
    if text:
        return text
    fallback = _date(fallback_date)
    return f"{fallback} 00:00:00" if fallback else None


def _assert_existing(actual: Mapping[str, Any], expected: Mapping[str, Any], label: str) -> None:
    if normalize({key: actual.get(key) for key in expected}) != normalize(expected):
        raise TargetConflictError(f"Existing target differs for {label}")


class TransactionImporter:
    def __init__(self, ctx: ImportContext):
        self.ctx = ctx

    def run(self, rows: Mapping[str, list[dict[str, Any]]]) -> None:
        self._invoices(rows["invoices"])
        self._visits(rows["visits"])
        self._visit_items(rows["visit_items"])
        self._injections(rows["injections"])
        self._procedures(rows["procedures"])
        self._consumables(rows["consumables_ledger"])
        self._payments(rows["invoice_item_payments"])

    def _invoices(self, rows: list[dict[str, Any]]) -> None:
        fields = (
            "patient_id", "doctor_id", "nurse_id", "status", "insurance_type",
            "supplementary_insurance", "total_amount", "work_date", "shift",
            "opened_at", "closed_at", "opened_by", "opened_by_name", "closed_by",
            "closed_by_name", "pricing_version",
        )
        for row in rows:
            start = self.ctx.start("invoices", row, "accounting.invoices")
            if start.replayed:
                continue
            status = (clean_text(row.get("status")) or "open").lower()
            if status not in {"open", "closed"}:
                raise AccountingImportError(f"Unsupported invoice status: {status}")
            opened_at = _timestamp(row.get("opened_at"), fallback_date=row.get("work_date"))
            if opened_at is None:
                raise AccountingImportError("Invoice has neither opened_at nor work_date")
            expected = {
                "patient_id": self.ctx.mapped_id("patients", row.get("patient_id")),
                "doctor_id": self.ctx.mapped_id(
                    "medical_staff", row.get("doctor_id"), nullable=True
                ),
                "nurse_id": self.ctx.mapped_id(
                    "medical_staff", row.get("nurse_id"), nullable=True
                ),
                "status": status,
                "insurance_type": clean_text(row.get("insurance_type")),
                "supplementary_insurance": clean_text(row.get("supplementary_insurance")),
                "total_amount": integer_money(row.get("total_amount"), field="invoice.total_amount"),
                "work_date": _date(row.get("work_date")),
                "shift": clean_text(row.get("shift")),
                "opened_at": opened_at,
                "closed_at": _timestamp(row.get("closed_at")),
                "opened_by": clean_text(row.get("opened_by")),
                "opened_by_name": clean_text(row.get("opened_by_name")),
                "closed_by": clean_text(row.get("closed_by")),
                "closed_by_name": clean_text(row.get("closed_by_name")),
                "pricing_version": "legacy",
            }
            target_id = _insert_id(
                self.ctx,
                table="accounting.invoices",
                columns=("tenant_id", *fields),
                values=(self.ctx.tenant_id, *(expected[field] for field in fields)),
            )
            _finish_simple(
                self.ctx, source_table="invoices", start=start,
                target_table="accounting.invoices", target_id=target_id, reused=False,
            )

    def _visits(self, rows: list[dict[str, Any]]) -> None:
        fields = (
            "patient_id", "doctor_name", "visit_date", "shift", "work_date",
            "insurance_type", "supplementary_insurance", "status", "price",
            "payment_status", "reception_user", "notes", "invoice_id", "doctor_id",
            "nurse_id",
        )
        for row in rows:
            start = self.ctx.start("visits", row, "accounting.visits")
            if start.replayed:
                continue
            payment_status = (clean_text(row.get("payment_status")) or "unpaid").lower()
            if payment_status not in {"paid", "unpaid"}:
                raise AccountingImportError("Unsupported visit payment_status")
            expected = {
                "patient_id": self.ctx.mapped_id("patients", row.get("patient_id")),
                "doctor_name": clean_text(row.get("doctor_name")),
                "visit_date": _timestamp(row.get("visit_date"), fallback_date=row.get("work_date")),
                "shift": clean_text(row.get("shift")),
                "work_date": _date(row.get("work_date")),
                "insurance_type": clean_text(row.get("insurance_type")),
                "supplementary_insurance": clean_text(row.get("supplementary_insurance")),
                "status": clean_text(row.get("status")) or "pending",
                "price": integer_money(row.get("price"), field="visit.price"),
                "payment_status": payment_status,
                "reception_user": clean_text(row.get("reception_user")),
                "notes": clean_text(row.get("notes")),
                "invoice_id": self.ctx.mapped_id("invoices", row.get("invoice_id"), nullable=True),
                "doctor_id": self.ctx.mapped_id(
                    "medical_staff", row.get("doctor_id"), nullable=True
                ),
                "nurse_id": self.ctx.mapped_id(
                    "medical_staff", row.get("nurse_id"), nullable=True
                ),
            }
            if expected["visit_date"] is None:
                raise AccountingImportError("Visit has neither visit_date nor work_date")
            target_id = _insert_id(
                self.ctx,
                table="accounting.visits",
                columns=("tenant_id", *fields),
                values=(self.ctx.tenant_id, *(expected[field] for field in fields)),
            )
            _finish_simple(
                self.ctx, source_table="visits", start=start,
                target_table="accounting.visits", target_id=target_id, reused=False,
            )

    def _visit_items(self, rows: list[dict[str, Any]]) -> None:
        fields = ("visit_id", "service_id", "quantity", "price_at_time")
        for row in rows:
            start = self.ctx.start("visit_items", row, "accounting.visit_items")
            if start.replayed:
                continue
            expected = {
                "visit_id": self.ctx.mapped_id("visits", row.get("visit_id")),
                "service_id": self.ctx.mapped_id("services", row.get("service_id")),
                "quantity": int(row.get("quantity") or 1),
                "price_at_time": integer_money(
                    row.get("price_at_time"), field="visit_item.price_at_time"
                ),
            }
            if expected["quantity"] <= 0:
                raise AccountingImportError("Visit item quantity must be positive")
            target_id = _insert_id(
                self.ctx,
                table="accounting.visit_items",
                columns=("tenant_id", *fields),
                values=(self.ctx.tenant_id, *(expected[field] for field in fields)),
            )
            _finish_simple(
                self.ctx, source_table="visit_items", start=start,
                target_table="accounting.visit_items", target_id=target_id, reused=False,
            )

    def _injections(self, rows: list[dict[str, Any]]) -> None:
        fields = (
            "patient_id", "injection_type", "service_id", "injection_date", "shift",
            "work_date", "count", "unit_price", "total_price", "patient_amount",
            "insurance_amount", "covered_by_insurance", "reception_user", "notes",
            "invoice_id", "doctor_id", "nurse_id",
        )
        for row in rows:
            start = self.ctx.start("injections", row, "accounting.injections")
            if start.replayed:
                continue
            count = int(row.get("count") or 1)
            if count <= 0:
                raise AccountingImportError("Injection count must be positive")
            expected = {
                "patient_id": self.ctx.mapped_id("patients", row.get("patient_id")),
                "injection_type": clean_text(row.get("injection_type")) or "",
                "service_id": self.ctx.mapped_id(
                    "nursing_services", row.get("service_id"), nullable=True
                ),
                "injection_date": _timestamp(
                    row.get("injection_date"), fallback_date=row.get("work_date")
                ),
                "shift": clean_text(row.get("shift")),
                "work_date": _date(row.get("work_date")),
                "count": count,
                "unit_price": integer_money(row.get("unit_price"), field="injection.unit_price"),
                "total_price": integer_money(row.get("total_price"), field="injection.total_price"),
                "patient_amount": _optional_money(
                    row.get("patient_amount"), field="injection.patient_amount"
                ),
                "insurance_amount": _optional_money(
                    row.get("insurance_amount"), field="injection.insurance_amount"
                ),
                "covered_by_insurance": boolean(row.get("covered_by_insurance", 0)),
                "reception_user": clean_text(row.get("reception_user")),
                "notes": clean_text(row.get("notes")),
                "invoice_id": self.ctx.mapped_id("invoices", row.get("invoice_id"), nullable=True),
                "doctor_id": self.ctx.mapped_id(
                    "medical_staff", row.get("doctor_id"), nullable=True
                ),
                "nurse_id": self.ctx.mapped_id(
                    "medical_staff", row.get("nurse_id"), nullable=True
                ),
            }
            if expected["injection_date"] is None:
                raise AccountingImportError("Injection has no date")
            target_id = _insert_id(
                self.ctx,
                table="accounting.injections",
                columns=("tenant_id", *fields),
                values=(self.ctx.tenant_id, *(expected[field] for field in fields)),
            )
            _finish_simple(
                self.ctx, source_table="injections", start=start,
                target_table="accounting.injections", target_id=target_id, reused=False,
            )

    def _procedures(self, rows: list[dict[str, Any]]) -> None:
        fields = (
            "patient_id", "procedure_type", "procedure_date", "shift", "work_date",
            "price", "patient_amount", "insurance_amount", "covered_by_insurance",
            "reception_user", "notes", "invoice_id", "performer_type", "performer_id",
            "doctor_id", "nurse_id",
        )
        for row in rows:
            start = self.ctx.start("procedures", row, "accounting.procedures")
            if start.replayed:
                continue
            performer_type = clean_text(row.get("performer_type"))
            if performer_type not in {None, "doctor", "nurse"}:
                raise AccountingImportError("Unsupported procedure performer_type")
            performer_id = None
            if row.get("performer_id") is not None:
                performer_id = self.ctx.mapped_id(
                    "medical_staff", row.get("performer_id"), nullable=True
                )
            expected = {
                "patient_id": self.ctx.mapped_id("patients", row.get("patient_id")),
                "procedure_type": clean_text(row.get("procedure_type")) or "",
                "procedure_date": _timestamp(
                    row.get("procedure_date"), fallback_date=row.get("work_date")
                ),
                "shift": clean_text(row.get("shift")),
                "work_date": _date(row.get("work_date")),
                "price": integer_money(row.get("price"), field="procedure.price"),
                "patient_amount": _optional_money(
                    row.get("patient_amount"), field="procedure.patient_amount"
                ),
                "insurance_amount": _optional_money(
                    row.get("insurance_amount"), field="procedure.insurance_amount"
                ),
                "covered_by_insurance": boolean(row.get("covered_by_insurance", 0)),
                "reception_user": clean_text(row.get("reception_user")),
                "notes": clean_text(row.get("notes")),
                "invoice_id": self.ctx.mapped_id("invoices", row.get("invoice_id"), nullable=True),
                "performer_type": performer_type,
                "performer_id": performer_id,
                "doctor_id": self.ctx.mapped_id(
                    "medical_staff", row.get("doctor_id"), nullable=True
                ),
                "nurse_id": self.ctx.mapped_id(
                    "medical_staff", row.get("nurse_id"), nullable=True
                ),
            }
            if expected["procedure_date"] is None:
                raise AccountingImportError("Procedure has no date")
            target_id = _insert_id(
                self.ctx,
                table="accounting.procedures",
                columns=("tenant_id", *fields),
                values=(self.ctx.tenant_id, *(expected[field] for field in fields)),
            )
            _finish_simple(
                self.ctx, source_table="procedures", start=start,
                target_table="accounting.procedures", target_id=target_id, reused=False,
            )

    def _consumables(self, rows: list[dict[str, Any]]) -> None:
        fields = (
            "patient_id", "item_name", "category", "quantity", "unit_price",
            "total_cost", "patient_provided", "is_exception", "usage_date", "shift",
            "work_date", "reception_user", "notes", "invoice_id", "doctor_id", "nurse_id",
        )
        for row in rows:
            start = self.ctx.start(
                "consumables_ledger", row, "accounting.consumables_ledger"
            )
            if start.replayed:
                continue
            category = clean_text(row.get("category"))
            if category not in {None, "drug", "supply"}:
                raise AccountingImportError("Unsupported consumable category")
            expected = {
                "patient_id": self.ctx.mapped_id(
                    "patients", row.get("patient_id"), nullable=True
                ),
                "item_name": clean_text(row.get("item_name")) or "",
                "category": category,
                "quantity": decimal_quantity(
                    row.get("quantity"), field="consumable.quantity"
                ),
                "unit_price": integer_money(
                    row.get("unit_price"), field="consumable.unit_price"
                ),
                "total_cost": integer_money(
                    row.get("total_cost"), field="consumable.total_cost"
                ),
                "patient_provided": boolean(row.get("patient_provided", 0)),
                "is_exception": boolean(row.get("is_exception", 0)),
                "usage_date": _timestamp(
                    row.get("usage_date"), fallback_date=row.get("work_date")
                ),
                "shift": clean_text(row.get("shift")),
                "work_date": _date(row.get("work_date")),
                "reception_user": clean_text(row.get("reception_user")),
                "notes": clean_text(row.get("notes")),
                "invoice_id": self.ctx.mapped_id("invoices", row.get("invoice_id"), nullable=True),
                "doctor_id": self.ctx.mapped_id(
                    "medical_staff", row.get("doctor_id"), nullable=True
                ),
                "nurse_id": self.ctx.mapped_id(
                    "medical_staff", row.get("nurse_id"), nullable=True
                ),
            }
            if expected["usage_date"] is None:
                raise AccountingImportError("Consumable row has no usage date")
            target_id = _insert_id(
                self.ctx,
                table="accounting.consumables_ledger",
                columns=("tenant_id", *fields),
                values=(self.ctx.tenant_id, *(expected[field] for field in fields)),
            )
            _finish_simple(
                self.ctx, source_table="consumables_ledger", start=start,
                target_table="accounting.consumables_ledger", target_id=target_id,
                reused=False,
            )

    def _payments(self, rows: list[dict[str, Any]]) -> None:
        item_tables = {
            "visit": "visits",
            "injection": "injections",
            "procedure": "procedures",
            "consumable": "consumables_ledger",
        }
        for row in rows:
            start = self.ctx.start(
                "invoice_item_payments", row, "accounting.invoice_item_payments"
            )
            if start.replayed:
                continue
            item_type = clean_text(row.get("item_type")) or ""
            source_item_table = item_tables.get(item_type)
            if source_item_table is None:
                raise AccountingImportError("Unsupported payment item_type")
            expected = {
                "invoice_id": self.ctx.mapped_id("invoices", row.get("invoice_id")),
                "item_type": item_type,
                "item_id": self.ctx.mapped_id(source_item_table, row.get("item_id")),
                "payment_type": clean_text(row.get("payment_type")),
                "is_paid": boolean(row.get("is_paid", 0)),
            }
            target_key = (
                f"{expected['invoice_id']}:{expected['item_type']}:{expected['item_id']}"
            )
            existing = self.ctx.read_target(
                "accounting.invoice_item_payments", target_key
            )
            if existing:
                _assert_existing(existing, {"tenant_id": self.ctx.tenant_id, **expected}, "payment")
                reused = True
            else:
                columns = ("tenant_id", *expected)
                values = (self.ctx.tenant_id, *(expected[column] for column in expected))
                if self.ctx.apply:
                    self.ctx.conn.execute(
                        f"INSERT INTO accounting.invoice_item_payments ({', '.join(columns)}) "
                        f"VALUES ({', '.join(['%s'] * len(values))})",
                        values,
                    )
                else:
                    self.ctx.conn.execute(
                        f"INSERT INTO accounting.invoice_item_payments "
                        f"(id, {', '.join(columns)}) VALUES "
                        f"(%s, {', '.join(['%s'] * len(values))})",
                        (self.ctx.temp_id(), *values),
                    )
                existing = self.ctx.read_target(
                    "accounting.invoice_item_payments", target_key
                )
                reused = False
            if existing is None:
                raise TargetConflictError("Payment target disappeared")
            self.ctx.finish(
                source_table="invoice_item_payments",
                start=start,
                target_table="accounting.invoice_item_payments",
                target_key=target_key,
                target_payload=existing,
                reused=reused,
            )
