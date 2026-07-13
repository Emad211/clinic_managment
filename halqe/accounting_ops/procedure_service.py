"""Procedure command service ported from the production Flask accounting app.

The raw procedure price and the patient/insurance split are frozen together.
Nurse-performed procedures are covered only when the invoice's primary tariff
explicitly enables nursing coverage; doctor-performed procedures remain full
patient liability.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from accounting_ops.constants import (
    PRICING_VERSION_VISIT_NURSING_V1,
    PRICING_VERSION_VISIT_PROCEDURE_V1,
    PRICING_VERSION_VISIT_V1,
)
from accounting_ops.nursing_repository import NursingRepository
from accounting_ops.payment_repository import PaymentRepository
from accounting_ops.procedure_repository import ProcedureRepository
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


_ALLOWED_SOURCE_VERSIONS = frozenset(
    {
        PRICING_VERSION_VISIT_V1,
        PRICING_VERSION_VISIT_NURSING_V1,
        PRICING_VERSION_VISIT_PROCEDURE_V1,
    }
)
_MAX_QUANTITY = 100


def list_procedure_tariffs(*, tenant_id: int) -> list[dict[str, Any]]:
    with accounting_transaction(tenant_id=tenant_id) as conn:
        rows = ProcedureRepository(conn).list_tariffs(tenant_id=tenant_id)
        return [
            {
                "id": int(row["id"]),
                "name": row["name"],
                "unit_price": _money(row["unit_price"]),
            }
            for row in rows
        ]


def _invoice_or_error(
    repo: NursingRepository,
    *,
    tenant_id: int,
    invoice_id: int,
) -> Mapping[str, Any]:
    invoice = repo.invoice_context(tenant_id=tenant_id, invoice_id=invoice_id)
    if not invoice:
        raise AccountingNotFound("فاکتور پیدا نشد.")
    if invoice["status"] != "open":
        raise AccountingConflict(
            "فاکتور بسته شده است و امکان افزودن پروسیجر وجود ندارد.",
            "invoice_already_closed",
        )
    if invoice.get("pricing_version") not in _ALLOWED_SOURCE_VERSIONS:
        raise AccountingConflict(
            "این فاکتور با موتور مالی قدیمی ساخته شده و باید از مسیر قبلی مدیریت شود.",
            "legacy_invoice_mutation_blocked",
        )
    return invoice


def _resolve_catalogue_or_manual(
    repo: ProcedureRepository,
    *,
    tenant_id: int,
    entry: Mapping[str, Any],
) -> tuple[str, int]:
    tariff_id = entry.get("tariff_id")
    if tariff_id is not None:
        try:
            numeric_id = int(tariff_id)
        except (TypeError, ValueError) as exc:
            raise AccountingValidationError(
                "شناسهٔ تعرفهٔ پروسیجر نامعتبر است.",
                "invalid_procedure_tariff",
            ) from exc
        tariff = repo.get_tariff(tenant_id=tenant_id, tariff_id=numeric_id)
        if not tariff:
            raise AccountingValidationError(
                "تعرفهٔ پروسیجر فعال یا معتبر نیست.",
                "invalid_procedure_tariff",
            )
        return tariff["name"], _money(tariff["unit_price"])

    name = _clean(entry.get("name"))
    if not name:
        raise AccountingValidationError(
            "نام پروسیجر الزامی است.",
            "procedure_name_required",
        )
    try:
        unit_price = int(entry.get("unit_price"))
    except (TypeError, ValueError) as exc:
        raise AccountingValidationError(
            "قیمت پروسیجر معتبر نیست.",
            "invalid_procedure_price",
        ) from exc
    if unit_price <= 0:
        raise AccountingValidationError(
            "قیمت پروسیجر باید بیشتر از صفر باشد.",
            "invalid_procedure_price",
        )
    return name, unit_price


def _resolve_performer(
    *,
    entry: Mapping[str, Any],
    staff: Mapping[str, Any],
) -> tuple[str, int, Optional[int], Optional[int]]:
    performer_type = (_clean(entry.get("performer_type")) or "").lower()
    if not performer_type:
        performer_type = "doctor" if staff.get("doctor_id") else "nurse"
    if performer_type not in {"doctor", "nurse"}:
        raise AccountingValidationError(
            "انجام‌دهندهٔ پروسیجر باید پزشک یا پرستار باشد.",
            "invalid_performer_type",
        )

    if performer_type == "doctor":
        if not staff.get("doctor_id"):
            raise AccountingValidationError(
                "برای پروسیجر پزشک، ابتدا پزشک شیفت را تعیین کنید.",
                "doctor_shift_staff_required",
            )
        performer_id = int(staff["doctor_id"])
        return "doctor", performer_id, performer_id, None

    if not staff.get("nurse_id"):
        raise AccountingValidationError(
            "برای پروسیجر پرستار، ابتدا پرستار شیفت را تعیین کنید.",
            "nurse_shift_staff_required",
        )
    performer_id = int(staff["nurse_id"])
    return "nurse", performer_id, None, performer_id


def add_procedure_items(
    *,
    tenant_id: int,
    invoice_id: int,
    payload: Mapping[str, Any],
    actor: Any,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict[str, Any]:
    procedures = list(payload.get("procedures") or [])
    notes = _clean(payload.get("notes"))
    if not procedures:
        raise AccountingValidationError(
            "حداقل یک پروسیجر انتخاب کنید.",
            "procedure_items_required",
        )

    _actor_id, username, _actor_name = _actor_fields(actor)
    with accounting_transaction(tenant_id=tenant_id) as conn:
        nursing = NursingRepository(conn)
        procedure_repo = ProcedureRepository(conn)
        accounting = AccountingRepository(conn)
        payments = PaymentRepository(conn)

        invoice = _invoice_or_error(
            nursing,
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        staff = nursing.shift_staff(
            tenant_id=tenant_id,
            work_date=invoice["work_date"],
            shift=invoice["shift"],
        )
        if not staff or (not staff.get("doctor_id") and not staff.get("nurse_id")):
            raise AccountingValidationError(
                "ابتدا کادر درمان شیفت را تعیین کنید.",
                "shift_staff_required",
            )
        coverage = nursing.nursing_coverage(
            tenant_id=tenant_id,
            insurance_type=invoice["insurance_type"],
        )
        if not coverage:
            raise AccountingValidationError(
                "تنظیم پوشش خدمات پرستاری برای بیمهٔ فاکتور پیدا نشد.",
                "nursing_coverage_not_configured",
            )
        nursing_covers = bool(coverage["nursing_covers"])

        procedure_ids: list[int] = []
        patient_liability_added = 0
        for entry in procedures:
            try:
                quantity = int(entry.get("quantity", 1))
            except (TypeError, ValueError) as exc:
                raise AccountingValidationError(
                    "تعداد پروسیجر نامعتبر است.",
                    "invalid_procedure_quantity",
                ) from exc
            if quantity < 1 or quantity > _MAX_QUANTITY:
                raise AccountingValidationError(
                    f"تعداد پروسیجر باید بین ۱ و {_MAX_QUANTITY} باشد.",
                    "invalid_procedure_quantity",
                )

            name, unit_price = _resolve_catalogue_or_manual(
                procedure_repo,
                tenant_id=tenant_id,
                entry=entry,
            )
            performer_type, performer_id, doctor_id, nurse_id = _resolve_performer(
                entry=entry,
                staff=staff,
            )
            covered = performer_type == "nurse" and nursing_covers
            patient_amount = 0 if covered else unit_price
            insurance_amount = unit_price if covered else 0

            for _ in range(quantity):
                procedure_ids.append(
                    procedure_repo.create_procedure(
                        tenant_id=tenant_id,
                        patient_id=int(invoice["patient_id"]),
                        invoice_id=invoice_id,
                        procedure_type=name,
                        price=unit_price,
                        patient_amount=patient_amount,
                        insurance_amount=insurance_amount,
                        covered_by_insurance=covered,
                        performer_type=performer_type,
                        performer_id=performer_id,
                        work_date=invoice["work_date"],
                        shift=invoice["shift"],
                        reception_user=username,
                        notes=notes,
                        doctor_id=doctor_id,
                        nurse_id=nurse_id,
                    )
                )
                patient_liability_added += patient_amount

        summary = payments.summary_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        nursing.update_invoice_total_and_version(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            total_amount=_money(summary["total_amount"]),
            pricing_version=PRICING_VERSION_VISIT_PROCEDURE_V1,
        )
        patient = accounting.patient_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        _log_activity(
            accounting,
            tenant_id=tenant_id,
            actor=actor,
            action_type="procedure_items_add",
            description=f"ثبت {len(procedure_ids)} پروسیجر",
            invoice_id=invoice_id,
            patient=patient,
            amount=patient_liability_added,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return {
            "invoice_id": invoice_id,
            "pricing_version": PRICING_VERSION_VISIT_PROCEDURE_V1,
            "procedure_ids": procedure_ids,
            "financials": _payment_summary(invoice_id, summary),
        }
