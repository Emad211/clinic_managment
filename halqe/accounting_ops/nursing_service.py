"""Nursing/consumable command service ported from the production Flask app."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping, Optional

from accounting_ops.constants import (
    PRICING_VERSION_VISIT_NURSING_V1,
    PRICING_VERSION_VISIT_V1,
)
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


_ALLOWED_SOURCE_VERSIONS = frozenset(
    {PRICING_VERSION_VISIT_V1, PRICING_VERSION_VISIT_NURSING_V1}
)
_VALID_CATEGORIES = frozenset({"drug", "supply"})
_MAX_SERVICE_QUANTITY = 100


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
            "فاکتور بسته شده است و امکان افزودن خدمت وجود ندارد.",
            "invoice_already_closed",
        )
    if invoice.get("pricing_version") not in _ALLOWED_SOURCE_VERSIONS:
        raise AccountingConflict(
            "این فاکتور با موتور مالی قدیمی ساخته شده و باید از مسیر قبلی مدیریت شود.",
            "legacy_invoice_mutation_blocked",
        )
    return invoice


def _staff_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "work_date": row["work_date"],
        "shift": row["shift"],
        "doctor_id": int(row["doctor_id"]) if row.get("doctor_id") else None,
        "nurse_id": int(row["nurse_id"]) if row.get("nurse_id") else None,
        "doctor_name": row.get("doctor_name"),
        "nurse_name": row.get("nurse_name"),
        "updated_at": row["updated_at"],
    }


def list_nursing_services(*, tenant_id: int) -> list[dict[str, Any]]:
    with accounting_transaction(tenant_id=tenant_id) as conn:
        rows = NursingRepository(conn).list_nursing_services(tenant_id=tenant_id)
        return [
            {
                "id": int(row["id"]),
                "service_name": row["service_name"],
                "unit_price": _money(row["unit_price"]),
            }
            for row in rows
        ]


def list_consumable_tariffs(
    *, tenant_id: int, category: Optional[str] = None
) -> list[dict[str, Any]]:
    if category and category not in _VALID_CATEGORIES:
        raise AccountingValidationError(
            "دستهٔ مصرفی باید دارو یا لوازم باشد.",
            "invalid_consumable_category",
        )
    with accounting_transaction(tenant_id=tenant_id) as conn:
        rows = NursingRepository(conn).list_consumable_tariffs(
            tenant_id=tenant_id,
            category=category,
        )
        return [
            {
                "id": int(row["id"]),
                "name": row["name"],
                "default_price": _money(row["default_price"]),
                "category": row["category"],
            }
            for row in rows
        ]


def list_active_staff(
    *, tenant_id: int, staff_type: Optional[str] = None
) -> list[dict[str, Any]]:
    if staff_type and staff_type not in {"doctor", "nurse"}:
        raise AccountingValidationError(
            "نوع کادر درمان نامعتبر است.",
            "invalid_staff_type",
        )
    with accounting_transaction(tenant_id=tenant_id) as conn:
        rows = NursingRepository(conn).list_active_staff(
            tenant_id=tenant_id,
            staff_type=staff_type,
        )
        return [
            {
                "id": int(row["id"]),
                "full_name": row["full_name"],
                "staff_type": row["staff_type"],
            }
            for row in rows
        ]


def get_shift_staff_for_invoice(
    *, tenant_id: int, invoice_id: int
) -> Optional[dict[str, Any]]:
    with accounting_transaction(tenant_id=tenant_id) as conn:
        repo = NursingRepository(conn)
        invoice = _invoice_or_error(repo, tenant_id=tenant_id, invoice_id=invoice_id)
        row = repo.shift_staff(
            tenant_id=tenant_id,
            work_date=invoice["work_date"],
            shift=invoice["shift"],
        )
        return _staff_projection(row) if row else None


def set_shift_staff_for_invoice(
    *,
    tenant_id: int,
    invoice_id: int,
    doctor_id: Optional[int],
    nurse_id: Optional[int],
    actor: Any,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict[str, Any]:
    if doctor_id is None and nurse_id is None:
        raise AccountingValidationError(
            "حداقل یک پزشک یا پرستار باید انتخاب شود.",
            "shift_staff_required",
        )

    with accounting_transaction(tenant_id=tenant_id) as conn:
        nursing = NursingRepository(conn)
        accounting = AccountingRepository(conn)
        invoice = _invoice_or_error(
            nursing,
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        if doctor_id is not None and not nursing.get_active_staff_member(
            tenant_id=tenant_id,
            staff_id=int(doctor_id),
            staff_type="doctor",
        ):
            raise AccountingValidationError(
                "پزشک انتخاب‌شده فعال یا معتبر نیست.",
                "invalid_doctor",
            )
        if nurse_id is not None and not nursing.get_active_staff_member(
            tenant_id=tenant_id,
            staff_id=int(nurse_id),
            staff_type="nurse",
        ):
            raise AccountingValidationError(
                "پرستار انتخاب‌شده فعال یا معتبر نیست.",
                "invalid_nurse",
            )
        row = nursing.set_shift_staff(
            tenant_id=tenant_id,
            work_date=invoice["work_date"],
            shift=invoice["shift"],
            doctor_id=int(doctor_id) if doctor_id is not None else None,
            nurse_id=int(nurse_id) if nurse_id is not None else None,
        )
        patient = accounting.patient_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        parts = []
        if row.get("doctor_name"):
            parts.append(f"پزشک: {row['doctor_name']}")
        if row.get("nurse_name"):
            parts.append(f"پرستار: {row['nurse_name']}")
        _log_activity(
            accounting,
            tenant_id=tenant_id,
            actor=actor,
            action_type="shift_staff_set",
            description="تنظیم کادر شیفت — " + "، ".join(parts),
            invoice_id=invoice_id,
            patient=patient,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return _staff_projection(row)


def _decimal_quantity(value: Any) -> Decimal:
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AccountingValidationError(
            "تعداد مصرفی معتبر نیست.",
            "invalid_consumable_quantity",
        ) from exc
    if quantity <= 0 or quantity.as_tuple().exponent < -3:
        raise AccountingValidationError(
            "تعداد مصرفی باید مثبت و حداکثر دارای سه رقم اعشار باشد.",
            "invalid_consumable_quantity",
        )
    return quantity


def add_nursing_items(
    *,
    tenant_id: int,
    invoice_id: int,
    payload: Mapping[str, Any],
    actor: Any,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict[str, Any]:
    services = list(payload.get("services") or [])
    consumables = list(payload.get("consumables") or [])
    notes = _clean(payload.get("notes"))
    if not services and not consumables:
        raise AccountingValidationError(
            "حداقل یک خدمت پرستاری یا مصرفی انتخاب کنید.",
            "nursing_items_required",
        )

    _actor_id, username, _actor_name = _actor_fields(actor)
    with accounting_transaction(tenant_id=tenant_id) as conn:
        nursing = NursingRepository(conn)
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
        # Exact characterization of the production code: the PostgreSQL column is
        # NOT NULL, so only explicit nursing_covers=TRUE enables coverage.  A
        # nursing_tariff=0 with nursing_covers=FALSE does not activate the dead
        # legacy fallback path.
        nursing_covers = bool(coverage["nursing_covers"])
        excluded = nursing.excluded_nursing_service_ids(
            tenant_id=tenant_id,
            insurance_type=invoice["insurance_type"],
        )

        injection_ids: list[int] = []
        consumable_ids: list[int] = []
        for entry in services:
            try:
                service_id = int(entry.get("service_id"))
                quantity = int(entry.get("quantity", 0))
            except (TypeError, ValueError) as exc:
                raise AccountingValidationError(
                    "شناسه یا تعداد خدمت پرستاری نامعتبر است.",
                    "invalid_nursing_service",
                ) from exc
            if quantity < 1 or quantity > _MAX_SERVICE_QUANTITY:
                raise AccountingValidationError(
                    f"تعداد هر خدمت باید بین ۱ و {_MAX_SERVICE_QUANTITY} باشد.",
                    "invalid_nursing_quantity",
                )
            service = nursing.get_nursing_service(
                tenant_id=tenant_id,
                service_id=service_id,
            )
            if not service:
                raise AccountingValidationError(
                    f"خدمت پرستاری شمارهٔ {service_id} فعال یا معتبر نیست.",
                    "invalid_nursing_service",
                )
            unit_price = _money(service["unit_price"])
            covered = nursing_covers and service_id not in excluded
            patient_amount = 0 if covered else unit_price
            insurance_amount = unit_price if covered else 0
            for _ in range(quantity):
                injection_ids.append(
                    nursing.create_injection(
                        tenant_id=tenant_id,
                        patient_id=int(invoice["patient_id"]),
                        invoice_id=invoice_id,
                        service_id=service_id,
                        service_name=service["service_name"],
                        unit_price=unit_price,
                        patient_amount=patient_amount,
                        insurance_amount=insurance_amount,
                        covered_by_insurance=covered,
                        work_date=invoice["work_date"],
                        shift=invoice["shift"],
                        reception_user=username,
                        notes=notes,
                        doctor_id=(
                            int(staff["doctor_id"]) if staff.get("doctor_id") else None
                        ),
                        nurse_id=(
                            int(staff["nurse_id"]) if staff.get("nurse_id") else None
                        ),
                    )
                )

        for entry in consumables:
            name = _clean(entry.get("name"))
            category = _clean(entry.get("category")) or "supply"
            if not name:
                raise AccountingValidationError(
                    "نام مصرفی الزامی است.",
                    "consumable_name_required",
                )
            if category not in _VALID_CATEGORIES:
                raise AccountingValidationError(
                    "دستهٔ مصرفی باید دارو یا لوازم باشد.",
                    "invalid_consumable_category",
                )
            quantity = _decimal_quantity(entry.get("quantity"))
            try:
                unit_price = int(entry.get("unit_price", 0))
            except (TypeError, ValueError) as exc:
                raise AccountingValidationError(
                    "قیمت مصرفی معتبر نیست.",
                    "invalid_consumable_price",
                ) from exc
            if unit_price < 0:
                raise AccountingValidationError(
                    "قیمت مصرفی نمی‌تواند منفی باشد.",
                    "invalid_consumable_price",
                )
            total_cost = int(
                (quantity * Decimal(unit_price)).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
            consumable_ids.append(
                nursing.create_consumable(
                    tenant_id=tenant_id,
                    patient_id=int(invoice["patient_id"]),
                    invoice_id=invoice_id,
                    item_name=name,
                    category=category,
                    quantity=quantity,
                    unit_price=unit_price,
                    total_cost=total_cost,
                    patient_provided=bool(entry.get("patient_provided", False)),
                    is_exception=bool(entry.get("is_exception", False)),
                    work_date=invoice["work_date"],
                    shift=invoice["shift"],
                    reception_user=username,
                    notes=notes,
                    doctor_id=(
                        int(staff["doctor_id"]) if staff.get("doctor_id") else None
                    ),
                    nurse_id=(
                        int(staff["nurse_id"]) if staff.get("nurse_id") else None
                    ),
                )
            )

        summary = payments.summary_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        nursing.update_invoice_total_and_version(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            total_amount=_money(summary["total_amount"]),
            pricing_version=PRICING_VERSION_VISIT_NURSING_V1,
        )
        patient = accounting.patient_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        parts = []
        if injection_ids:
            parts.append(f"{len(injection_ids)} خدمت پرستاری")
        if consumable_ids:
            parts.append(f"{len(consumable_ids)} مصرفی")
        _log_activity(
            accounting,
            tenant_id=tenant_id,
            actor=actor,
            action_type="nursing_items_add",
            description="ثبت " + " و ".join(parts),
            invoice_id=invoice_id,
            patient=patient,
            amount=_money(summary["total_amount"]),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return {
            "invoice_id": invoice_id,
            "pricing_version": PRICING_VERSION_VISIT_NURSING_V1,
            "injection_ids": injection_ids,
            "consumable_ids": consumable_ids,
            "financials": _payment_summary(invoice_id, summary),
        }
