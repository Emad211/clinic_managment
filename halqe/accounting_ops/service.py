"""Reception/accounting application service — first Halqe migration slice.

This module moves the production flow

    register/update patient -> open invoice -> add visit -> close invoice

from ``webapp`` into the unified PostgreSQL platform. Commands are tenant-
scoped, atomic, audited, and persist only through the dedicated accounting
repository/role.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Optional

from django.utils import timezone
from psycopg.errors import UniqueViolation

from accounting_ops.repository import AccountingRepository
from accounting_ops.validators import (
    validate_iranian_national_id,
    validate_iranian_phone,
)
from accounting_ops.write_port import accounting_transaction


PRICING_VERSION_VISIT_V1 = "halqe_visit_v1"


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
    """Convert NUMERIC/Decimal to the platform's integer-Toman contract."""
    if value is None:
        return 0
    return int(Decimal(value))


def _current_shift() -> str:
    """Legacy-compatible default shift derived from Tehran local clock."""
    hour = timezone.localtime().hour
    if 7 <= hour <= 13:
        return "morning"
    if 14 <= hour <= 19:
        return "evening"
    return "night"


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


def _invoice_row_to_dict(row: Mapping[str, Any]) -> dict[str, Any]:
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
    return result


def _upsert_patient(
    repo: AccountingRepository,
    *,
    tenant_id: int,
    payload: Mapping[str, Any],
    actor_username: str,
) -> dict[str, Any]:
    data = _validate_patient_payload(payload)

    existing = None
    if data["national_id"]:
        existing = repo.find_patient_by_national_id_for_update(
            tenant_id=tenant_id,
            national_id=data["national_id"],
        )
    elif data["phone_number"]:
        existing = repo.find_patient_by_name_phone_for_update(
            tenant_id=tenant_id,
            name=data["name"],
            family_name=data["family_name"],
            phone_number=data["phone_number"],
        )

    try:
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
    except UniqueViolation as exc:
        raise AccountingConflict(
            "بیماری با این کد ملی قبلاً ثبت شده است.",
            "duplicate_patient",
        ) from exc

    return _patient_row_to_dict(row)


def _resolve_visit_price(
    repo: AccountingRepository,
    *,
    tenant_id: int,
    insurance_type: str,
    supplementary_insurance: Optional[str],
) -> int:
    selected = supplementary_insurance or insurance_type
    row = repo.get_visit_tariff(
        tenant_id=tenant_id,
        insurance_type=selected,
        is_supplementary=bool(supplementary_insurance),
    )
    if not row:
        label = "بیمهٔ تکمیلی" if supplementary_insurance else "بیمه"
        raise AccountingValidationError(
            f"تعرفهٔ فعال برای {label} انتخاب‌شده پیدا نشد.",
            "tariff_not_found",
        )
    return _money(row["tariff_price"])


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

    work_date = payload.get("work_date") or timezone.localdate()
    shift = _clean(payload.get("shift")) or _current_shift()
    doctor_id = payload.get("doctor_id")
    notes = _clean(payload.get("notes"))
    _user_id, username, actor_name = _actor_fields(actor)

    with accounting_transaction(tenant_id=tenant_id) as conn:
        repo = AccountingRepository(conn)
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
        return _invoice_row_to_dict(row)


def list_open_invoices(
    *,
    tenant_id: int,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    with accounting_transaction(tenant_id=tenant_id) as conn:
        repo = AccountingRepository(conn)
        total = repo.count_open_invoices(tenant_id=tenant_id)
        rows = repo.list_open_invoices(
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
        )
        return {
            "items": [_invoice_row_to_dict(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


def close_invoice(
    *,
    tenant_id: int,
    invoice_id: int,
    actor: Any,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict[str, Any]:
    """Close a visit-only invoice and freeze its patient-facing total.

    Injection/procedure/consumable pricing is deliberately blocked in this first
    slice. Closing such an invoice before those pricing rules are ported could
    corrupt money. Following slices remove this guard one item family at a time
    under golden-master tests.
    """
    _user_id, username, actor_name = _actor_fields(actor)

    with accounting_transaction(tenant_id=tenant_id) as conn:
        repo = AccountingRepository(conn)
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
                "تکمیل تطبیق مالی از مسیر قبلی بسته شود.",
                "legacy_invoice_close_blocked",
            )

        unsupported = repo.unsupported_item_counts(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        if any(unsupported.values()):
            raise AccountingConflict(
                "بستن فاکتورهای دارای تزریق، پروسیجر یا مصرفی تا انتقال کامل "
                "قواعد قیمت‌گذاری آن‌ها مسدود است.",
                "unsupported_invoice_items",
            )

        patient_total = repo.visit_patient_total(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
        )
        repo.mark_invoice_closed(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            total_amount=patient_total,
            closed_by=username,
            closed_by_name=actor_name,
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
        return _invoice_row_to_dict(row)
