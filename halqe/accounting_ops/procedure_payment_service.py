"""Settlement and close commands for the procedure pricing engine."""
from __future__ import annotations

from typing import Any, Optional

from accounting_ops.constants import (
    PAYMENT_LABELS,
    PROCEDURE_ITEM_TYPES,
    PRICING_VERSION_VISIT_PROCEDURE_V1,
)
from accounting_ops.payment_repository import PaymentRepository
from accounting_ops.repository import AccountingRepository
from accounting_ops.service import (
    AccountingConflict,
    AccountingNotFound,
    AccountingValidationError,
    _actor_fields,
    _log_activity,
    _money,
    _payment_summary,
    _validate_payment_type,
)
from accounting_ops.write_port import accounting_transaction


def _lock_procedure_invoice(
    repo: AccountingRepository,
    *,
    tenant_id: int,
    invoice_id: int,
):
    invoice = repo.lock_invoice(tenant_id=tenant_id, invoice_id=invoice_id)
    if not invoice:
        raise AccountingNotFound("فاکتور پیدا نشد.")
    if invoice["status"] != "open":
        raise AccountingConflict(
            "این فاکتور قبلاً بسته شده است.",
            "invoice_already_closed",
        )
    if invoice.get("pricing_version") != PRICING_VERSION_VISIT_PROCEDURE_V1:
        raise AccountingConflict(
            "این مسیر فقط برای فاکتورهای موتور پروسیجر فعال است.",
            "procedure_pricing_version_required",
        )
    unsupported = repo.unsupported_item_counts(
        tenant_id=tenant_id,
        invoice_id=invoice_id,
    )
    if unsupported.get("visit_items"):
        raise AccountingConflict(
            "فاکتور دارای خدمت افزودهٔ ویزیت است و قواعد آن هنوز منتقل نشده است.",
            "unsupported_invoice_items",
        )
    return invoice


def set_procedure_item_payment(
    *,
    tenant_id: int,
    invoice_id: int,
    item_type: str,
    item_id: int,
    payment_type: Optional[str],
    is_paid: bool,
    actor: Any,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict:
    if item_type not in PROCEDURE_ITEM_TYPES:
        raise AccountingValidationError(
            "نوع آیتم برای موتور پروسیجر پشتیبانی نمی‌شود.",
            "payment_item_type_not_supported",
        )
    normalized = _validate_payment_type(payment_type) if is_paid else None

    with accounting_transaction(tenant_id=tenant_id) as conn:
        accounting = AccountingRepository(conn)
        payments = PaymentRepository(conn)
        _lock_procedure_invoice(
            accounting,
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        item = payments.get_item(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            item_type=item_type,
            item_id=item_id,
        )
        if not item:
            raise AccountingNotFound("آیتم برای این فاکتور پیدا نشد.")
        payments.set_item_payment(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            item_type=item_type,
            item_id=item_id,
            payment_type=normalized,
            is_paid=is_paid,
        )
        patient = accounting.patient_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        _log_activity(
            accounting,
            tenant_id=tenant_id,
            actor=actor,
            action_type="item_payment_set",
            description=(
                f"تغییر پرداخت {item_type} #{item_id} به "
                f"{'پرداخت‌شده' if is_paid else 'پرداخت‌نشده'}"
            ),
            invoice_id=invoice_id,
            patient=patient,
            amount=_money(item["amount"]) if is_paid else 0,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        summary = payments.summary_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        return _payment_summary(invoice_id, summary)


def settle_procedure_invoice(
    *,
    tenant_id: int,
    invoice_id: int,
    payment_type: str,
    actor: Any,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict:
    normalized = _validate_payment_type(payment_type)
    with accounting_transaction(tenant_id=tenant_id) as conn:
        accounting = AccountingRepository(conn)
        payments = PaymentRepository(conn)
        _lock_procedure_invoice(
            accounting,
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        changed = payments.settle_item_types(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            payment_type=normalized,
            item_types=PROCEDURE_ITEM_TYPES,
        )
        if changed == 0:
            raise AccountingConflict(
                "این فاکتور آیتم قابل تسویه ندارد.",
                "invoice_has_no_payable_items",
            )
        summary = payments.summary_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        patient = accounting.patient_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        _log_activity(
            accounting,
            tenant_id=tenant_id,
            actor=actor,
            action_type="invoice_settle",
            description=(
                f"تسویهٔ فاکتور #{invoice_id} با روش {PAYMENT_LABELS[normalized]}"
            ),
            invoice_id=invoice_id,
            patient=patient,
            amount=_money(summary["paid_amount"]),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return _payment_summary(invoice_id, summary)


def close_procedure_invoice(
    *,
    tenant_id: int,
    invoice_id: int,
    actor: Any,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict:
    _user_id, username, actor_name = _actor_fields(actor)
    with accounting_transaction(tenant_id=tenant_id) as conn:
        accounting = AccountingRepository(conn)
        payments = PaymentRepository(conn)
        _lock_procedure_invoice(
            accounting,
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        unpaid = payments.unpaid_items(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            item_types=PROCEDURE_ITEM_TYPES,
        )
        if unpaid:
            raise AccountingConflict(
                f"امکان بستن فاکتور وجود ندارد — {len(unpaid)} آیتم تسویه نشده است.",
                "invoice_unpaid_items",
            )
        summary = payments.summary_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        if not summary.get("all_items_paid"):
            raise AccountingConflict(
                "وضعیت پرداخت فاکتور کامل نیست.",
                "invoice_unpaid_items",
            )
        total = _money(summary["total_amount"])
        if not accounting.mark_invoice_closed(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            total_amount=total,
            closed_by=username,
            closed_by_name=actor_name,
        ):
            raise AccountingConflict(
                "وضعیت فاکتور هم‌زمان تغییر کرده است؛ فهرست را تازه کنید.",
                "invoice_state_changed",
            )
        patient = accounting.patient_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        _log_activity(
            accounting,
            tenant_id=tenant_id,
            actor=actor,
            action_type="invoice_close",
            description=f"بستن فاکتور #{invoice_id}",
            invoice_id=invoice_id,
            patient=patient,
            amount=total,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        row = accounting.invoice_projection(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        if not row:
            raise AccountingNotFound("فاکتور پیدا نشد.")
        result = dict(row)
        result["id"] = int(result["id"])
        result["tenant_id"] = int(result["tenant_id"])
        result["patient_id"] = int(result["patient_id"])
        result["total_amount"] = total
        result["visit_id"] = int(result["visit_id"]) if result.get("visit_id") else None
        result["visit_price"] = (
            _money(result["visit_price"])
            if result.get("visit_price") is not None
            else None
        )
        return result
