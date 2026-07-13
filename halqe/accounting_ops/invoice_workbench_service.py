"""Accounting invoice detail, add-visit and correction commands.

The workbench is deliberately narrow: it can inspect every invoice, but it may
mutate only open invoices created by a migrated pricing engine. Corrections are
atomic, audited and always recompute patient liability from frozen item amounts.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Optional

from accounting_ops.constants import (
    PRICING_VERSION_VISIT_NURSING_V1,
    PRICING_VERSION_VISIT_PROCEDURE_V1,
    PRICING_VERSION_VISIT_V1,
)
from accounting_ops.invoice_workbench_repository import InvoiceWorkbenchRepository
from accounting_ops.nursing_repository import NursingRepository
from accounting_ops.payment_repository import PaymentRepository
from accounting_ops.repository import AccountingRepository
from accounting_ops.service import (
    AccountingConflict,
    AccountingNotFound,
    AccountingValidationError,
    _actor_fields,
    _clean,
    _log_activity,
    _money,
    _payment_summary,
)
from accounting_ops.write_port import accounting_transaction


_MUTABLE_VERSIONS = frozenset(
    {
        PRICING_VERSION_VISIT_V1,
        PRICING_VERSION_VISIT_NURSING_V1,
        PRICING_VERSION_VISIT_PROCEDURE_V1,
    }
)
_ITEM_TYPES = frozenset({"visit", "injection", "procedure", "consumable"})


def _header_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for key in ("id", "tenant_id", "patient_id"):
        out[key] = int(out[key])
    out["total_amount"] = _money(out.get("total_amount"))
    return out


def _item_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "item_type": row["item_type"],
        "item_id": int(row["item_id"]),
        "description": row["description"],
        "quantity": float(Decimal(row["quantity"] or 0)),
        "recorded_amount": _money(row["recorded_amount"]),
        "patient_amount": _money(row["patient_amount"]),
        "insurance_amount": _money(row["insurance_amount"]),
        "covered_by_insurance": bool(row["covered_by_insurance"]),
        "performer_type": row.get("performer_type"),
        "performer_id": (
            int(row["performer_id"]) if row.get("performer_id") is not None else None
        ),
        "performer_name": row.get("performer_name"),
        "occurred_at": row["occurred_at"],
        "notes": row.get("notes"),
        "payment_type": row.get("payment_type"),
        "is_paid": bool(row.get("is_paid")),
        "payment_updated_at": row.get("payment_updated_at"),
    }


def _build_detail(
    *,
    tenant_id: int,
    invoice_id: int,
    workbench: InvoiceWorkbenchRepository,
    payments: PaymentRepository,
) -> dict[str, Any]:
    header = workbench.invoice_header(tenant_id=tenant_id, invoice_id=invoice_id)
    if not header:
        raise AccountingNotFound("فاکتور پیدا نشد.")
    items = workbench.invoice_items(tenant_id=tenant_id, invoice_id=invoice_id)
    summary = payments.summary_for_invoice(
        tenant_id=tenant_id,
        invoice_id=invoice_id,
    )
    return {
        "invoice": _header_dict(header),
        "items": [_item_dict(row) for row in items],
        "financials": _payment_summary(invoice_id, summary),
    }


def get_invoice_detail(*, tenant_id: int, invoice_id: int) -> dict[str, Any]:
    with accounting_transaction(tenant_id=tenant_id) as conn:
        return _build_detail(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            workbench=InvoiceWorkbenchRepository(conn),
            payments=PaymentRepository(conn),
        )


def _lock_mutable_invoice(
    accounting: AccountingRepository,
    workbench: InvoiceWorkbenchRepository,
    *,
    tenant_id: int,
    invoice_id: int,
) -> Mapping[str, Any]:
    locked = accounting.lock_invoice(tenant_id=tenant_id, invoice_id=invoice_id)
    if not locked:
        raise AccountingNotFound("فاکتور پیدا نشد.")
    if locked["status"] != "open":
        raise AccountingConflict(
            "فاکتور بسته شده است و امکان اصلاح ندارد.",
            "invoice_already_closed",
        )
    if locked.get("pricing_version") not in _MUTABLE_VERSIONS:
        raise AccountingConflict(
            "فاکتور legacy از مسیر جدید قابل اصلاح نیست.",
            "legacy_invoice_mutation_blocked",
        )
    header = workbench.invoice_header(tenant_id=tenant_id, invoice_id=invoice_id)
    if not header:
        raise AccountingNotFound("فاکتور پیدا نشد.")
    return header


def _primary_and_effective_visit_price(
    accounting: AccountingRepository,
    *,
    tenant_id: int,
    insurance_type: str,
    supplementary_insurance: Optional[str],
) -> int:
    primary = accounting.get_visit_tariff(
        tenant_id=tenant_id,
        insurance_type=insurance_type,
        is_supplementary=False,
    )
    if not primary:
        raise AccountingValidationError(
            "تعرفهٔ فعال بیمهٔ پایه پیدا نشد.",
            "tariff_not_found",
        )
    if supplementary_insurance:
        supplementary = accounting.get_visit_tariff(
            tenant_id=tenant_id,
            insurance_type=supplementary_insurance,
            is_supplementary=True,
        )
        if not supplementary:
            raise AccountingValidationError(
                "تعرفهٔ فعال بیمهٔ تکمیلی پیدا نشد.",
                "tariff_not_found",
            )
        return _money(supplementary["tariff_price"])
    return _money(primary["tariff_price"])


def add_visit_to_invoice(
    *,
    tenant_id: int,
    invoice_id: int,
    notes: Optional[str],
    actor: Any,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict[str, Any]:
    _user_id, username, _actor_name = _actor_fields(actor)
    with accounting_transaction(tenant_id=tenant_id) as conn:
        accounting = AccountingRepository(conn)
        nursing = NursingRepository(conn)
        payments = PaymentRepository(conn)
        workbench = InvoiceWorkbenchRepository(conn)
        invoice = _lock_mutable_invoice(
            accounting,
            workbench,
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        staff = nursing.shift_staff(
            tenant_id=tenant_id,
            work_date=invoice["work_date"],
            shift=invoice["shift"],
        )
        if not staff or staff.get("doctor_id") is None:
            raise AccountingValidationError(
                "برای ثبت ویزیت، ابتدا پزشک شیفت را تعیین کنید.",
                "doctor_shift_staff_required",
            )
        doctor_id = int(staff["doctor_id"])
        doctor = nursing.get_active_staff(
            tenant_id=tenant_id,
            staff_id=doctor_id,
            staff_type="doctor",
        )
        if not doctor:
            raise AccountingValidationError(
                "پزشک شیفت فعال یا معتبر نیست.",
                "invalid_doctor",
            )
        price = _primary_and_effective_visit_price(
            accounting,
            tenant_id=tenant_id,
            insurance_type=invoice["insurance_type"],
            supplementary_insurance=invoice.get("supplementary_insurance"),
        )
        visit_id = accounting.create_visit(
            tenant_id=tenant_id,
            patient_id=int(invoice["patient_id"]),
            doctor_id=doctor_id,
            doctor_name=doctor["full_name"],
            invoice_id=invoice_id,
            insurance_type=invoice["insurance_type"],
            supplementary_insurance=invoice.get("supplementary_insurance"),
            price=price,
            work_date=invoice["work_date"],
            shift=invoice["shift"],
            reception_user=username,
            notes=_clean(notes),
        )
        summary = payments.summary_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        nursing.update_invoice_total_and_version(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            total_amount=_money(summary["total_amount"]),
            pricing_version=invoice["pricing_version"],
        )
        patient = accounting.patient_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        _log_activity(
            accounting,
            tenant_id=tenant_id,
            actor=actor,
            action_type="visit_add",
            description=f"افزودن ویزیت #{visit_id} به فاکتور #{invoice_id}",
            invoice_id=invoice_id,
            patient=patient,
            amount=price,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return _build_detail(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            workbench=workbench,
            payments=payments,
        )


def delete_invoice_item(
    *,
    tenant_id: int,
    invoice_id: int,
    item_type: str,
    item_id: int,
    actor: Any,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict[str, Any]:
    normalized_type = (_clean(item_type) or "").lower()
    if normalized_type not in _ITEM_TYPES:
        raise AccountingValidationError(
            "نوع آیتم نامعتبر است.",
            "invalid_item_type",
        )
    with accounting_transaction(tenant_id=tenant_id) as conn:
        accounting = AccountingRepository(conn)
        nursing = NursingRepository(conn)
        payments = PaymentRepository(conn)
        workbench = InvoiceWorkbenchRepository(conn)
        invoice = _lock_mutable_invoice(
            accounting,
            workbench,
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        item = workbench.item_for_update(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            item_type=normalized_type,
            item_id=item_id,
        )
        if not item:
            raise AccountingNotFound("آیتم برای این فاکتور پیدا نشد.")
        if normalized_type == "visit" and workbench.visit_has_children(
            tenant_id=tenant_id,
            visit_id=item_id,
        ):
            raise AccountingConflict(
                "این ویزیت دارای خدمت وابسته است و تا انتقال قواعد آن قابل حذف نیست.",
                "visit_has_dependent_items",
            )
        workbench.delete_payment(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            item_type=normalized_type,
            item_id=item_id,
        )
        if not workbench.delete_item(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            item_type=normalized_type,
            item_id=item_id,
        ):
            raise AccountingConflict(
                "آیتم هم‌زمان تغییر کرده است؛ صفحه را تازه کنید.",
                "item_state_changed",
            )
        summary = payments.summary_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        nursing.update_invoice_total_and_version(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            total_amount=_money(summary["total_amount"]),
            pricing_version=invoice["pricing_version"],
        )
        patient = accounting.patient_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        _log_activity(
            accounting,
            tenant_id=tenant_id,
            actor=actor,
            action_type=f"{normalized_type}_delete",
            description=(
                f"حذف {normalized_type} #{item_id} از فاکتور #{invoice_id}"
            ),
            invoice_id=invoice_id,
            patient=patient,
            amount=_money(item["patient_amount"]),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return {
            "deleted": True,
            "item_type": normalized_type,
            "item_id": item_id,
            "detail": _build_detail(
                tenant_id=tenant_id,
                invoice_id=invoice_id,
                workbench=workbench,
                payments=payments,
            ),
        }
