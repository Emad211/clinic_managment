"""Manager command service for accounting catalogs and payroll settings."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
from typing import Any, Mapping, Optional

from psycopg.errors import UniqueViolation

from accounting_ops.admin_repository import AccountingAdminRepository
from accounting_ops.service import (
    AccountingConflict,
    AccountingNotFound,
    AccountingValidationError,
    _actor_fields,
    _clean,
)
from accounting_ops.write_port import accounting_transaction


_CATALOG_TYPES = frozenset({"nursing", "procedure", "consumable"})
_CONSUMABLE_CATEGORIES = frozenset({"drug", "supply"})


def _money(value: Any, *, label: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise AccountingValidationError(
            f"{label} باید عدد صحیح تومان باشد.", "invalid_money"
        ) from exc
    if number < 0:
        raise AccountingValidationError(
            f"{label} نمی‌تواند منفی باشد.", "invalid_money"
        )
    return number


def _percent(value: Any, *, label: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AccountingValidationError(
            f"{label} باید عدد باشد.", "invalid_percent"
        ) from exc
    if not number.is_finite() or number < 0 or number > 100:
        raise AccountingValidationError(
            f"{label} باید بین صفر و صد باشد.", "invalid_percent"
        )
    if number.as_tuple().exponent < -3:
        raise AccountingValidationError(
            f"{label} حداکثر سه رقم اعشار می‌پذیرد.", "invalid_percent"
        )
    return number


def _required(value: Any, *, label: str, max_length: int = 180) -> str:
    text = _clean(value)
    if not text:
        raise AccountingValidationError(f"{label} الزامی است.", "required_field")
    if len(text) > max_length:
        raise AccountingValidationError(
            f"{label} بیش از حد طولانی است.", "field_too_long"
        )
    return text


def _row(row: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    if not row:
        raise AccountingNotFound("رکورد تنظیمات پیدا نشد.")
    result = dict(row)
    for key, value in list(result.items()):
        if isinstance(value, Decimal):
            result[key] = float(value) if value.as_tuple().exponent < 0 else int(value)
    return result


def _configuration(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "staff": [_row(item) for item in raw["staff"]],
        "insurance_schemes": [_row(item) for item in raw["insurance_schemes"]],
        "visit_tariffs": [_row(item) for item in raw["visit_tariffs"]],
        "catalogs": {
            key: [_row(item) for item in values]
            for key, values in raw["catalogs"].items()
        },
        "exclusions": [_row(item) for item in raw["exclusions"]],
        "payroll_settings": [_row(item) for item in raw["payroll_settings"]],
    }


def get_accounting_admin_configuration(*, tenant_id: int) -> dict[str, Any]:
    with accounting_transaction(tenant_id=tenant_id) as conn:
        return _configuration(
            AccountingAdminRepository(conn).configuration(tenant_id=tenant_id)
        )


def _audit(
    repo: AccountingAdminRepository,
    *,
    tenant_id: int,
    actor: Any,
    action_type: str,
    target_type: str,
    target: Mapping[str, Any],
    description: str,
    ip_address: Optional[str],
    user_agent: Optional[str],
) -> None:
    user_id, username, _full_name = _actor_fields(actor)
    repo.log_configuration_change(
        tenant_id=tenant_id,
        user_id=user_id,
        username=username,
        action_type=action_type,
        target_type=target_type,
        target_id=int(target["id"]) if target.get("id") is not None else None,
        target_name=(
            target.get("full_name")
            or target.get("name")
            or target.get("insurance_type")
            or target.get("code")
        ),
        description=description,
        old_value=None,
        new_value=json.dumps(
            _row(target), ensure_ascii=False, sort_keys=True, default=str
        ),
        ip_address=ip_address,
        user_agent=user_agent,
    )


def upsert_staff(
    *,
    tenant_id: int,
    payload: Mapping[str, Any],
    actor: Any,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict[str, Any]:
    staff_id = int(payload["id"]) if payload.get("id") is not None else None
    full_name = _required(payload.get("full_name"), label="نام کادر درمان")
    staff_type = (_clean(payload.get("staff_type")) or "").lower()
    if staff_type not in {"doctor", "nurse"}:
        raise AccountingValidationError(
            "نوع کادر باید doctor یا nurse باشد.", "invalid_staff_type"
        )
    with accounting_transaction(tenant_id=tenant_id) as conn:
        repo = AccountingAdminRepository(conn)
        try:
            row = repo.upsert_staff(
                tenant_id=tenant_id,
                staff_id=staff_id,
                full_name=full_name,
                staff_type=staff_type,
                is_active=bool(payload.get("is_active", True)),
            )
        except UniqueViolation as exc:
            raise AccountingConflict(
                "کادر درمانی با همین مشخصات وجود دارد.", "duplicate_configuration"
            ) from exc
        result = _row(row)
        _audit(
            repo,
            tenant_id=tenant_id,
            actor=actor,
            action_type="staff_upsert",
            target_type="medical_staff",
            target=result,
            description="ثبت یا ویرایش کادر درمان",
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return result


def upsert_insurance_scheme(
    *, tenant_id: int, payload: Mapping[str, Any], actor: Any,
    ip_address: Optional[str] = None, user_agent: Optional[str] = None,
) -> dict[str, Any]:
    scheme_id = int(payload["id"]) if payload.get("id") is not None else None
    code = _required(payload.get("code"), label="کد بیمه", max_length=80).lower()
    name = _required(payload.get("name"), label="نام بیمه")
    supplementary = bool(payload.get("is_supplementary", False))
    base = bool(payload.get("is_base", False))
    if supplementary and base:
        raise AccountingValidationError(
            "یک بیمه نمی‌تواند هم پایه و هم تکمیلی باشد.",
            "invalid_insurance_flags",
        )
    with accounting_transaction(tenant_id=tenant_id) as conn:
        repo = AccountingAdminRepository(conn)
        try:
            result = _row(repo.upsert_insurance_scheme(
                tenant_id=tenant_id, scheme_id=scheme_id, code=code, name=name,
                is_supplementary=supplementary, is_base=base,
                is_active=bool(payload.get("is_active", True)),
            ))
        except UniqueViolation as exc:
            raise AccountingConflict("کد بیمه تکراری است.", "duplicate_configuration") from exc
        _audit(repo, tenant_id=tenant_id, actor=actor,
               action_type="insurance_scheme_upsert", target_type="insurance_scheme",
               target=result, description="ثبت یا ویرایش بیمه",
               ip_address=ip_address, user_agent=user_agent)
        return result


def upsert_visit_tariff(
    *, tenant_id: int, payload: Mapping[str, Any], actor: Any,
    ip_address: Optional[str] = None, user_agent: Optional[str] = None,
) -> dict[str, Any]:
    tariff_id = int(payload["id"]) if payload.get("id") is not None else None
    insurance_type = _required(payload.get("insurance_type"), label="نام تعرفه بیمه")
    supplementary = bool(payload.get("is_supplementary", False))
    base = bool(payload.get("is_base_tariff", False))
    if supplementary and base:
        raise AccountingValidationError(
            "تعرفه نمی‌تواند هم پایه و هم تکمیلی باشد.", "invalid_tariff_flags"
        )
    scheme_id = (
        int(payload["insurance_scheme_id"])
        if payload.get("insurance_scheme_id") is not None else None
    )
    with accounting_transaction(tenant_id=tenant_id) as conn:
        repo = AccountingAdminRepository(conn)
        try:
            result = _row(repo.upsert_visit_tariff(
                tenant_id=tenant_id, tariff_id=tariff_id,
                insurance_type=insurance_type,
                insurance_scheme_id=scheme_id,
                tariff_price=_money(payload.get("tariff_price", 0), label="تعرفه ویزیت"),
                nursing_tariff=_money(payload.get("nursing_tariff", 0), label="تعرفه پرستاری"),
                nursing_covers=bool(payload.get("nursing_covers", False)),
                is_active=bool(payload.get("is_active", True)),
                is_supplementary=supplementary, is_base_tariff=base,
            ))
        except UniqueViolation as exc:
            raise AccountingConflict("نام تعرفه بیمه تکراری است.", "duplicate_configuration") from exc
        _audit(repo, tenant_id=tenant_id, actor=actor,
               action_type="visit_tariff_upsert", target_type="visit_tariff",
               target=result, description="ثبت یا ویرایش تعرفه ویزیت",
               ip_address=ip_address, user_agent=user_agent)
        return result


def upsert_catalog_item(
    *, tenant_id: int, catalog_type: str, payload: Mapping[str, Any], actor: Any,
    ip_address: Optional[str] = None, user_agent: Optional[str] = None,
) -> dict[str, Any]:
    normalized = (_clean(catalog_type) or "").lower()
    if normalized not in _CATALOG_TYPES:
        raise AccountingValidationError("نوع کاتالوگ نامعتبر است.", "invalid_catalog_type")
    category = (_clean(payload.get("category")) or "").lower() or None
    if normalized == "consumable" and category not in _CONSUMABLE_CATEGORIES:
        raise AccountingValidationError(
            "دسته مصرفی باید drug یا supply باشد.", "invalid_consumable_category"
        )
    item_id = int(payload["id"]) if payload.get("id") is not None else None
    with accounting_transaction(tenant_id=tenant_id) as conn:
        repo = AccountingAdminRepository(conn)
        try:
            result = _row(repo.upsert_catalog_item(
                tenant_id=tenant_id, catalog_type=normalized, item_id=item_id,
                name=_required(payload.get("name"), label="نام خدمت"),
                price=_money(payload.get("price", 0), label="قیمت"),
                is_active=bool(payload.get("is_active", True)), category=category,
            ))
        except UniqueViolation as exc:
            raise AccountingConflict("نام کاتالوگ تکراری است.", "duplicate_configuration") from exc
        _audit(repo, tenant_id=tenant_id, actor=actor,
               action_type=f"{normalized}_catalog_upsert",
               target_type=f"{normalized}_catalog", target=result,
               description="ثبت یا ویرایش کاتالوگ حسابداری",
               ip_address=ip_address, user_agent=user_agent)
        return result


def upsert_exclusion(
    *, tenant_id: int, payload: Mapping[str, Any], actor: Any,
    ip_address: Optional[str] = None, user_agent: Optional[str] = None,
) -> dict[str, Any]:
    exclusion_id = int(payload["id"]) if payload.get("id") is not None else None
    insurance_type = _required(payload.get("insurance_type"), label="نام بیمه")
    service_id = int(payload.get("nursing_service_id") or 0)
    if service_id <= 0:
        raise AccountingValidationError("خدمت پرستاری معتبر نیست.", "invalid_nursing_service")
    with accounting_transaction(tenant_id=tenant_id) as conn:
        repo = AccountingAdminRepository(conn)
        service = repo.nursing_service(tenant_id=tenant_id, service_id=service_id)
        tariff = repo.visit_tariff_by_name(tenant_id=tenant_id, insurance_type=insurance_type)
        if not service or not service["is_active"]:
            raise AccountingValidationError("خدمت پرستاری فعال نیست.", "invalid_nursing_service")
        if not tariff or not tariff["is_active"]:
            raise AccountingValidationError("تعرفه بیمه فعال نیست.", "invalid_insurance")
        try:
            result = _row(repo.upsert_exclusion(
                tenant_id=tenant_id, exclusion_id=exclusion_id,
                insurance_type=insurance_type, nursing_service_id=service_id,
                note=_clean(payload.get("note")),
            ))
        except UniqueViolation as exc:
            raise AccountingConflict("این استثنای بیمه قبلاً ثبت شده است.", "duplicate_configuration") from exc
        result["service_name"] = service["service_name"]
        _audit(repo, tenant_id=tenant_id, actor=actor,
               action_type="insurance_exclusion_upsert", target_type="insurance_exclusion",
               target=result, description="ثبت یا ویرایش استثنای پوشش پرستاری",
               ip_address=ip_address, user_agent=user_agent)
        return result


def delete_exclusion(
    *, tenant_id: int, exclusion_id: int, actor: Any,
    ip_address: Optional[str] = None, user_agent: Optional[str] = None,
) -> dict[str, Any]:
    with accounting_transaction(tenant_id=tenant_id) as conn:
        repo = AccountingAdminRepository(conn)
        if not repo.delete_exclusion(tenant_id=tenant_id, exclusion_id=exclusion_id):
            raise AccountingNotFound("استثنای بیمه پیدا نشد.")
        target = {"id": exclusion_id, "name": "insurance exclusion"}
        _audit(repo, tenant_id=tenant_id, actor=actor,
               action_type="insurance_exclusion_delete", target_type="insurance_exclusion",
               target=target, description="حذف استثنای پوشش پرستاری",
               ip_address=ip_address, user_agent=user_agent)
        return {"deleted": True, "id": exclusion_id}


def upsert_payroll_settings(
    *, tenant_id: int, payload: Mapping[str, Any], actor: Any,
    ip_address: Optional[str] = None, user_agent: Optional[str] = None,
) -> dict[str, Any]:
    staff_id = int(payload.get("staff_id") or 0)
    if staff_id <= 0:
        raise AccountingValidationError("کادر درمان معتبر نیست.", "invalid_staff")
    with accounting_transaction(tenant_id=tenant_id) as conn:
        repo = AccountingAdminRepository(conn)
        staff = repo.active_staff(tenant_id=tenant_id, staff_id=staff_id)
        if not staff:
            raise AccountingValidationError("کادر درمان پیدا نشد.", "invalid_staff")
        result = _row(repo.upsert_payroll(
            tenant_id=tenant_id, staff_id=staff_id,
            base_morning=_money(payload.get("base_morning", 0), label="پایه صبح"),
            base_evening=_money(payload.get("base_evening", 0), label="پایه عصر"),
            base_night=_money(payload.get("base_night", 0), label="پایه شب"),
            visit_fee=_money(payload.get("visit_fee", 0), label="حق ویزیت"),
            injection_percent=_percent(payload.get("injection_percent", 0), label="درصد تزریق"),
            procedure_percent=_percent(payload.get("procedure_percent", 0), label="درصد پروسیجر"),
            tax_percent=_percent(payload.get("tax_percent", 0), label="درصد مالیات"),
            nursing_percent=_percent(payload.get("nursing_percent", 0), label="درصد پرستاری"),
            nurse_procedure_percent=_percent(payload.get("nurse_procedure_percent", 0), label="درصد پروسیجر پرستار"),
        ))
        result["staff_name"] = staff["full_name"]
        result["staff_type"] = staff["staff_type"]
        _audit(repo, tenant_id=tenant_id, actor=actor,
               action_type="payroll_settings_upsert", target_type="payroll_settings",
               target=result, description="ثبت یا ویرایش تنظیمات حقوق",
               ip_address=ip_address, user_agent=user_agent)
        return result
