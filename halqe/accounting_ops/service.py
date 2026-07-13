"""Reception/accounting application service for the Halqe migration.

The production-safe write flow is deliberately narrow and explicit:

    patient upsert -> visit invoice -> item payment -> invoice close

All commands are tenant-scoped, atomic, audited, and use the dedicated
``accounting_app`` PostgreSQL role.  The legacy Flask application remains the
money oracle while additional item families are ported.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Optional

from django.utils import timezone

from accounting_ops.payment_repository import PaymentRepository
from accounting_ops.repository import AccountingRepository
from accounting_ops.validators import (
    validate_iranian_national_id,
    validate_iranian_phone,
)
from accounting_ops.write_port import accounting_transaction


PRICING_VERSION_VISIT_V1 = "halqe_visit_v1"
PAYMENT_TYPES = frozenset({"cash", "card", "insurance", "supplementary"})
_PAYMENT_LABELS = {
    "cash": "نقد",
    "card": "کارت",
    "insurance": "بیمه",
    "supplementary": "بیمهٔ تکمیلی",
}


class AccountingCommandError(Exception):
    """Base error carrying an HTTP-friendly stable code and status."""

    status = 400
    code = "accounting_error"

    def __init__(self, detail: str, code: Optional[str] = None):
        super().__init__(detail)
        if code:
            self.code = code


class AccountingValidationError(AccountingCommandError):
    status = 422
    code = "validation_error"


class AccountingNotFound(AccountingCommandError):
    status = 404
    code = "not_found"


class AccountingConflict(AccountingCommandError):
    status = 409
    code = "conflict"


def _clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _money(value: Any) -> int:
    """Convert NUMERIC/Decimal to the integer-Toman API contract."""
    if value is None:
        return 0
    return int(Decimal(value))


def _actor_fields(actor: Any) -> tuple[Optional[int], str, str]:
    user_id = getattr(actor, "pk", None) or getattr(actor, "id", None)
    username = _clean(getattr(actor, "username", None)) or "system"
    full_name = _clean(getattr(actor, "full_name", None)) or username
    return user_id, username, full_name


def _validate_patient_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    name = _clean(payload.get("name"))
    family_name = _clean(payload.get("family_name"))
    phone = _clean(payload.get("phone_number"))
    national_id = _clean(payload.get("national_id"))
    is_foreign = bool(payload.get("is_foreign", False))

    if not name or not family_name:
        raise AccountingValidationError(
            "نام و نام خانوادگی بیمار الزامی است.",
            "patient_name_required",
        )
    if phone and not validate_iranian_phone(phone):
        raise AccountingValidationError(
            "شماره همراه باید ۱۱ رقم و با ۰۹ شروع شود.",
            "invalid_phone",
        )
    if not is_foreign:
        if not national_id:
            raise AccountingValidationError(
                "کد ملی برای بیمار ایرانی الزامی است.",
                "national_id_required",
            )
        if not validate_iranian_national_id(national_id):
            raise AccountingValidationError(
                "کد ملی واردشده معتبر نیست.",
                "invalid_national_id",
            )
    else:
        national_id = None

    return {
        "name": name,
        "family_name": family_name,
        "national_id": national_id,
        "phone_number": phone,
        "birthdate": payload.get("birthdate"),
        "gender": _clean(payload.get("gender")),
        "insurance_type": _clean(payload.get("insurance_type")),
        "insurance_expiry": payload.get("insurance_expiry"),
        "address": _clean(payload.get("address")),
        "is_foreign": is_foreign,
    }


def _patient_row_to_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "uuid": row["uuid"],
        "name": row["name"],
        "family_name": row["family_name"],
        "full_name": row["full_name"],
        "national_id": row.get("national_id"),
        "phone_number": row.get("phone_number"),
        "birthdate": row.get("birthdate"),
        "gender": row.get("gender"),
        "insurance_type": row.get("insurance_type"),
        "insurance_expiry": row.get("insurance_expiry"),
        "address": row.get("address"),
        "is_foreign": bool(row.get("is_foreign")),
    }


def _invoice_row_to_dict(
    row: Mapping[str, Any],
    financials: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    result = dict(row)
    result["id"] = int(result["id"])
    result["tenant_id"] = int(result["tenant_id"])
    result["patient_id"] = int(result["patient_id"])
    result["total_amount"] = _money(result.get("total_amount"))
    result["visit_id"] = (
        int(result["visit_id"]) if result.get("visit_id") is not None else None
    )
    result["visit_price"] = (
        _money(result["visit_price"])
        if result.get("visit_price") is not None
        else None
    )
    if financials:
        result.update(financials)
    return result


def _payment_summary(invoice_id: int, summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "invoice_id": int(invoice_id),
        "total_amount": _money(summary.get("total_amount")),
        "paid_amount": _money(summary.get("paid_amount")),
        "remaining_amount": _money(summary.get("remaining_amount")),
        "all_items_paid": bool(summary.get("all_items_paid")),
        "payment_type": summary.get("payment_type"),
    }


def _upsert_patient(
    repo: AccountingRepository,
    *,
    tenant_id: int,
    payload: Mapping[str, Any],
    actor_username: str,
) -> dict[str, Any]:
    data = _validate_patient_payload(payload)

    if data["national_id"]:
        row = repo.upsert_patient_by_national_id(
            tenant_id=tenant_id,
            data=data,
            created_by=actor_username,
        )
        return _patient_row_to_dict(row)

    existing = None
    if data["phone_number"]:
        existing = repo.find_patient_by_name_phone_for_update(
            tenant_id=tenant_id,
            name=data["name"],
            family_name=data["family_name"],
            phone_number=data["phone_number"],
        )
    if existing:
        row = repo.update_patient(
            tenant_id=tenant_id,
            patient_id=int(existing["id"]),
            data=data,
        )
    else:
        row = repo.create_patient(
            tenant_id=tenant_id,
            data=data,
            created_by=actor_username,
        )
    return _patient_row_to_dict(row)


def _resolve_visit_price(
    repo: AccountingRepository,
    *,
    tenant_id: int,
    insurance_type: str,
    supplementary_insurance: Optional[str],
) -> int:
    # Validate the primary tariff even when a supplementary tariff overrides the
    # patient share.  An unknown primary insurance must never look valid merely
    # because a supplementary row exists.
    primary = repo.get_visit_tariff(
        tenant_id=tenant_id,
        insurance_type=insurance_type,
        is_supplementary=False,
    )
    if not primary:
        raise AccountingValidationError(
            "تعرفهٔ فعال برای بیمهٔ پایهٔ انتخاب‌شده پیدا نشد.",
            "tariff_not_found",
        )
    if not supplementary_insurance:
        return _money(primary["tariff_price"])

    supplementary = repo.get_visit_tariff(
        tenant_id=tenant_id,
        insurance_type=supplementary_insurance,
        is_supplementary=True,
    )
    if not supplementary:
        raise AccountingValidationError(
            "تعرفهٔ فعال برای بیمهٔ تکمیلی انتخاب‌شده پیدا نشد.",
            "tariff_not_found",
        )
    return _money(supplementary["tariff_price"])


def _resolve_shift_context(
    repo: AccountingRepository,
    *,
    tenant_id: int,
    actor_user_id: Optional[int],
    requested_shift: Any,
    requested_work_date: Any,
) -> tuple[str, Any]:
    """Preserve the production app's manual shift/work-date contract."""
    active = None
    if actor_user_id is not None:
        active = repo.get_user_active_shift(
            tenant_id=tenant_id,
            user_id=int(actor_user_id),
        )
    shift = _clean(requested_shift) or (active or {}).get("active_shift") or "morning"
    work_date = (
        requested_work_date
        or (active or {}).get("work_date")
        or timezone.localdate()
    )
    return shift, work_date


def _resolve_doctor(
    repo: AccountingRepository,
    *,
    tenant_id: int,
    doctor_id: Optional[int],
) -> Optional[str]:
    if doctor_id is None:
        return None
    row = repo.get_active_doctor(tenant_id=tenant_id, doctor_id=doctor_id)
    if not row:
        raise AccountingValidationError(
            "پزشک انتخاب‌شده فعال یا معتبر نیست.",
            "invalid_doctor",
        )
    return row["full_name"]


def _validate_payment_type(value: Any) -> str:
    payment_type = _clean(value)
    if payment_type not in PAYMENT_TYPES:
        raise AccountingValidationError(
            "روش پرداخت باید نقد، کارت، بیمه یا بیمهٔ تکمیلی باشد.",
            "invalid_payment_type",
        )
    return payment_type


def _log_activity(
    repo: AccountingRepository,
    *,
    tenant_id: int,
    actor: Any,
    action_type: str,
    description: str,
    invoice_id: Optional[int] = None,
    patient: Optional[Mapping[str, Any]] = None,
    amount: int = 0,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    user_id, username, _full_name = _actor_fields(actor)
    repo.log_activity(
        tenant_id=tenant_id,
        user_id=user_id,
        username=username,
        action_type=action_type,
        description=description,
        invoice_id=invoice_id,
        patient_id=int(patient["id"]) if patient else None,
        patient_name=patient.get("full_name") if patient else None,
        amount=amount,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def _lock_visit_invoice(
    repo: AccountingRepository,
    *,
    tenant_id: int,
    invoice_id: int,
) -> Mapping[str, Any]:
    invoice = repo.lock_invoice(tenant_id=tenant_id, invoice_id=invoice_id)
    if not invoice:
        raise AccountingNotFound("فاکتور پیدا نشد.")
    if invoice["status"] != "open":
        raise AccountingConflict(
            "این فاکتور قبلاً بسته شده است.",
            "invoice_already_closed",
        )
    if invoice.get("pricing_version") != PRICING_VERSION_VISIT_V1:
        raise AccountingConflict(
            "این فاکتور با موتور قیمت‌گذاری قدیمی ساخته شده است و باید تا "
            "تکمیل تطبیق مالی از مسیر قبلی مدیریت شود.",
            "legacy_invoice_close_blocked",
        )
    return invoice


def list_visit_tariffs(*, tenant_id: int) -> list[dict[str, Any]]:
    with accounting_transaction(tenant_id=tenant_id) as conn:
        rows = AccountingRepository(conn).list_visit_tariffs(tenant_id=tenant_id)
        return [
            {
                **dict(row),
                "id": int(row["id"]),
                "tariff_price": _money(row["tariff_price"]),
                "nursing_tariff": _money(row["nursing_tariff"]),
            }
            for row in rows
        ]


def search_patients(
    *,
    tenant_id: int,
    query: str,
    limit: int = 30,
) -> list[dict[str, Any]]:
    q = _clean(query) or ""
    with accounting_transaction(tenant_id=tenant_id) as conn:
        rows = AccountingRepository(conn).search_patients(
            tenant_id=tenant_id,
            query=q,
            limit=limit,
        )
        return [_patient_row_to_dict(row) for row in rows]


def open_visit_invoice(
    *,
    tenant_id: int,
    payload: Mapping[str, Any],
    actor: Any,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict[str, Any]:
    """Atomically upsert the patient, open an invoice, and add its visit."""
    insurance_type = _clean(payload.get("insurance_type"))
    supplementary = _clean(payload.get("supplementary_insurance"))
    if not insurance_type:
        raise AccountingValidationError(
            "نوع بیمه الزامی است.",
            "insurance_required",
        )
    if supplementary and insurance_type == "آزاد":
        raise AccountingValidationError(
            "بیمهٔ تکمیلی فقط همراه بیمهٔ پایه قابل انتخاب است.",
            "invalid_supplementary_insurance",
        )

    doctor_id = payload.get("doctor_id")
    notes = _clean(payload.get("notes"))
    actor_user_id, username, actor_name = _actor_fields(actor)

    with accounting_transaction(tenant_id=tenant_id) as conn:
        repo = AccountingRepository(conn)
        payments = PaymentRepository(conn)
        shift, work_date = _resolve_shift_context(
            repo,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            requested_shift=payload.get("shift"),
            requested_work_date=payload.get("work_date"),
        )
        patient_payload = dict(payload["patient"])
        patient_payload["insurance_type"] = insurance_type
        patient = _upsert_patient(
            repo,
            tenant_id=tenant_id,
            payload=patient_payload,
            actor_username=username,
        )
        price = _resolve_visit_price(
            repo,
            tenant_id=tenant_id,
            insurance_type=insurance_type,
            supplementary_insurance=supplementary,
        )
        doctor_name = _resolve_doctor(
            repo,
            tenant_id=tenant_id,
            doctor_id=doctor_id,
        )

        invoice_id = repo.create_invoice(
            tenant_id=tenant_id,
            patient_id=patient["id"],
            doctor_id=doctor_id,
            insurance_type=insurance_type,
            supplementary_insurance=supplementary,
            total_amount=price,
            work_date=work_date,
            shift=shift,
            opened_by=username,
            opened_by_name=actor_name,
            pricing_version=PRICING_VERSION_VISIT_V1,
        )
        repo.create_visit(
            tenant_id=tenant_id,
            patient_id=patient["id"],
            doctor_id=doctor_id,
            doctor_name=doctor_name,
            invoice_id=invoice_id,
            insurance_type=insurance_type,
            supplementary_insurance=supplementary,
            price=price,
            work_date=work_date,
            shift=shift,
            reception_user=username,
            notes=notes,
        )
        _log_activity(
            repo,
            tenant_id=tenant_id,
            actor=actor,
            action_type="invoice_create",
            description=f"ایجاد فاکتور ویزیت برای {patient['full_name']}",
            invoice_id=invoice_id,
            patient=patient,
            amount=price,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        row = repo.invoice_projection(tenant_id=tenant_id, invoice_id=invoice_id)
        if not row:
            raise AccountingNotFound("فاکتور ایجادشده پیدا نشد.")
        summary = payments.summary_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        return _invoice_row_to_dict(row, _payment_summary(invoice_id, summary))


def list_open_invoices(
    *,
    tenant_id: int,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    with accounting_transaction(tenant_id=tenant_id) as conn:
        repo = AccountingRepository(conn)
        payments = PaymentRepository(conn)
        total = repo.count_open_invoices(tenant_id=tenant_id)
        rows = repo.list_open_invoices(
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
        )
        summaries = payments.summaries_for_invoices(
            tenant_id=tenant_id,
            invoice_ids=[int(row["id"]) for row in rows],
        )
        return {
            "items": [
                _invoice_row_to_dict(
                    row,
                    _payment_summary(int(row["id"]), summaries[int(row["id"])]),
                )
                for row in rows
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


def get_invoice_financials(*, tenant_id: int, invoice_id: int) -> dict[str, Any]:
    with accounting_transaction(tenant_id=tenant_id) as conn:
        repo = AccountingRepository(conn)
        if not repo.invoice_projection(tenant_id=tenant_id, invoice_id=invoice_id):
            raise AccountingNotFound("فاکتور پیدا نشد.")
        summary = PaymentRepository(conn).summary_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        return _payment_summary(invoice_id, summary)


def set_item_payment(
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
) -> dict[str, Any]:
    """Set one visit item's payment state and return invoice financials."""
    if item_type != "visit":
        raise AccountingValidationError(
            "در این مرحله فقط پرداخت آیتم ویزیت پشتیبانی می‌شود.",
            "payment_item_type_not_supported",
        )
    normalized_type = _validate_payment_type(payment_type) if is_paid else None

    with accounting_transaction(tenant_id=tenant_id) as conn:
        repo = AccountingRepository(conn)
        payments = PaymentRepository(conn)
        _lock_visit_invoice(repo, tenant_id=tenant_id, invoice_id=invoice_id)
        visit = payments.get_visit_item(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            visit_id=item_id,
        )
        if not visit:
            raise AccountingNotFound("آیتم ویزیت برای این فاکتور پیدا نشد.")
        payments.set_item_payment(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            item_type="visit",
            item_id=item_id,
            payment_type=normalized_type,
            is_paid=is_paid,
        )
        patient = repo.patient_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        status_label = "پرداخت‌شده" if is_paid else "پرداخت‌نشده"
        method_label = _PAYMENT_LABELS.get(normalized_type or "", "—")
        _log_activity(
            repo,
            tenant_id=tenant_id,
            actor=actor,
            action_type="item_payment_set",
            description=(
                f"تغییر وضعیت پرداخت ویزیت #{item_id} به {status_label} "
                f"({method_label})"
            ),
            invoice_id=invoice_id,
            patient=patient,
            amount=_money(visit["price"]) if is_paid else 0,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        summary = payments.summary_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        return _payment_summary(invoice_id, summary)


def settle_all_invoice(
    *,
    tenant_id: int,
    invoice_id: int,
    payment_type: str,
    actor: Any,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict[str, Any]:
    """Mark every currently supported item as paid in one transaction."""
    normalized_type = _validate_payment_type(payment_type)
    with accounting_transaction(tenant_id=tenant_id) as conn:
        repo = AccountingRepository(conn)
        payments = PaymentRepository(conn)
        _lock_visit_invoice(repo, tenant_id=tenant_id, invoice_id=invoice_id)
        unsupported = repo.unsupported_item_counts(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        if any(unsupported.values()):
            raise AccountingConflict(
                "تسویهٔ یکجای این فاکتور تا انتقال پرداخت تزریق، پروسیجر، "
                "مصرفی و خدمات افزوده مسدود است.",
                "unsupported_invoice_items",
            )
        changed = payments.settle_all_visits(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            payment_type=normalized_type,
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
        patient = repo.patient_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        _log_activity(
            repo,
            tenant_id=tenant_id,
            actor=actor,
            action_type="invoice_settle",
            description=(
                f"تسویهٔ فاکتور #{invoice_id} با روش "
                f"{_PAYMENT_LABELS[normalized_type]}"
            ),
            invoice_id=invoice_id,
            patient=patient,
            amount=_money(summary.get("paid_amount")),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return _payment_summary(invoice_id, summary)


def close_invoice(
    *,
    tenant_id: int,
    invoice_id: int,
    actor: Any,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict[str, Any]:
    """Close a fully-paid, Halqe-v1 visit-only invoice and freeze its total."""
    _user_id, username, actor_name = _actor_fields(actor)

    with accounting_transaction(tenant_id=tenant_id) as conn:
        repo = AccountingRepository(conn)
        payments = PaymentRepository(conn)
        _lock_visit_invoice(repo, tenant_id=tenant_id, invoice_id=invoice_id)

        unsupported = repo.unsupported_item_counts(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        if any(unsupported.values()):
            raise AccountingConflict(
                "بستن فاکتورهای دارای تزریق، پروسیجر، مصرفی یا خدمتِ افزودهٔ "
                "ویزیت تا انتقال کامل قواعد قیمت‌گذاری آن‌ها مسدود است.",
                "unsupported_invoice_items",
            )

        unpaid = payments.unpaid_visit_items(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
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
                "امکان بستن فاکتور وجود ندارد — وضعیت پرداخت کامل نیست.",
                "invoice_unpaid_items",
            )
        patient_total = _money(summary.get("total_amount"))
        changed = repo.mark_invoice_closed(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            total_amount=patient_total,
            closed_by=username,
            closed_by_name=actor_name,
        )
        if not changed:
            raise AccountingConflict(
                "وضعیت فاکتور هم‌زمان تغییر کرده است؛ فهرست را تازه کنید.",
                "invoice_state_changed",
            )
        patient = repo.patient_for_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        _log_activity(
            repo,
            tenant_id=tenant_id,
            actor=actor,
            action_type="invoice_close",
            description=f"بستن فاکتور #{invoice_id}",
            invoice_id=invoice_id,
            patient=patient,
            amount=patient_total,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        row = repo.invoice_projection(tenant_id=tenant_id, invoice_id=invoice_id)
        if not row:
            raise AccountingNotFound("فاکتور پیدا نشد.")
        return _invoice_row_to_dict(row, _payment_summary(invoice_id, summary))
