from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping


_METRIC_TEMPLATE = {
    "invoice_count": 0,
    "invoice_open_count": 0,
    "invoice_closed_count": 0,
    "invoice_amount": 0,
    "invoice_open_amount": 0,
    "invoice_closed_amount": 0,
    "visit_count": 0,
    "visit_amount": 0,
    "visit_closed_count": 0,
    "visit_closed_amount": 0,
    "nursing_count": 0,
    "nursing_amount": 0,
    "nursing_closed_count": 0,
    "nursing_closed_amount": 0,
    "procedure_count": 0,
    "procedure_amount": 0,
    "procedure_closed_count": 0,
    "procedure_closed_amount": 0,
    "consumable_count": 0,
    "consumable_amount": 0,
    "consumable_center_count": 0,
    "consumable_center_amount": 0,
    "payment_count": 0,
    "payment_paid_count": 0,
    "payment_unpaid_count": 0,
    "operating_revenue": 0,
}


def _money(value: Any) -> int:
    try:
        number = Decimal(str(value or 0))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Dual-run money values must be numeric") from exc
    if number != number.to_integral_value():
        raise ValueError("Dual-run money values must use integral toman amounts")
    return int(number)


def _bucket(container: dict[str, dict[str, int]], key: Any) -> dict[str, int]:
    normalized = str(key or "unknown")
    return container.setdefault(normalized, deepcopy(_METRIC_TEMPLATE))


def _apply_invoice(bucket: dict[str, int], row: Mapping[str, Any]) -> None:
    amount = _money(row.get("amount"))
    status = str(row.get("status") or "")
    bucket["invoice_count"] += 1
    bucket["invoice_amount"] += amount
    if status == "closed":
        bucket["invoice_closed_count"] += 1
        bucket["invoice_closed_amount"] += amount
    else:
        bucket["invoice_open_count"] += 1
        bucket["invoice_open_amount"] += amount


def _apply_event(bucket: dict[str, int], row: Mapping[str, Any]) -> None:
    kind = str(row.get("kind") or "")
    if kind not in {"visit", "nursing", "procedure", "consumable"}:
        raise ValueError(f"Unsupported dual-run service kind: {kind}")
    amount = _money(row.get("amount"))
    bucket[f"{kind}_count"] += 1
    bucket[f"{kind}_amount"] += amount
    if kind == "consumable":
        if bool(row.get("center_supplied")):
            bucket["consumable_center_count"] += 1
            bucket["consumable_center_amount"] += amount
        return
    if str(row.get("invoice_status") or "") == "closed":
        bucket[f"{kind}_closed_count"] += 1
        bucket[f"{kind}_closed_amount"] += amount
        bucket["operating_revenue"] += amount


def _apply_payment(bucket: dict[str, int], row: Mapping[str, Any]) -> None:
    bucket["payment_count"] += 1
    if bool(row.get("is_paid")):
        bucket["payment_paid_count"] += 1
    else:
        bucket["payment_unpaid_count"] += 1


def build_financial_snapshot(
    *,
    invoices: Iterable[Mapping[str, Any]],
    events: Iterable[Mapping[str, Any]],
    payments: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    totals = deepcopy(_METRIC_TEMPLATE)
    by_day: dict[str, dict[str, int]] = {}
    by_shift: dict[str, dict[str, int]] = {}
    by_insurance: dict[str, dict[str, int]] = {}

    for row in invoices:
        for bucket in (
            totals,
            _bucket(by_day, row.get("work_date")),
            _bucket(by_shift, row.get("shift")),
            _bucket(by_insurance, row.get("insurance_type")),
        ):
            _apply_invoice(bucket, row)

    for row in events:
        for bucket in (
            totals,
            _bucket(by_day, row.get("work_date")),
            _bucket(by_shift, row.get("shift")),
            _bucket(by_insurance, row.get("insurance_type")),
        ):
            _apply_event(bucket, row)

    for row in payments:
        for bucket in (
            totals,
            _bucket(by_day, row.get("work_date")),
            _bucket(by_shift, row.get("shift")),
            _bucket(by_insurance, row.get("insurance_type")),
        ):
            _apply_payment(bucket, row)

    return {
        "totals": totals,
        "by_day": dict(sorted(by_day.items())),
        "by_shift": dict(sorted(by_shift.items())),
        "by_insurance": dict(sorted(by_insurance.items())),
    }


@dataclass(frozen=True)
class Difference:
    path: str
    source: Any
    target: Any
    delta: Any = None


@dataclass
class DualRunReport:
    decision: str
    source_id: str
    tenant_id: int
    date_from: str
    date_to: str
    shift: str | None
    source_file_sha256: str
    source_manifest_sha256: str
    financial_source: dict[str, Any]
    financial_target: dict[str, Any]
    payroll_source: dict[str, Any]
    payroll_target: dict[str, Any]
    differences: list[Difference] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["differences"] = [asdict(item) for item in self.differences]
        return payload


def compare_payload(source: Any, target: Any, *, path: str = "") -> list[Difference]:
    if isinstance(source, Mapping) and isinstance(target, Mapping):
        result: list[Difference] = []
        for key in sorted(set(source) | set(target), key=str):
            child = f"{path}.{key}" if path else str(key)
            if key not in source:
                result.append(Difference(child, None, target[key]))
            elif key not in target:
                result.append(Difference(child, source[key], None))
            else:
                result.extend(compare_payload(source[key], target[key], path=child))
        return result
    if isinstance(source, list) and isinstance(target, list):
        if source == target:
            return []
        return [Difference(path, source, target)]
    if source == target:
        return []
    delta = None
    if isinstance(source, (int, float)) and isinstance(target, (int, float)):
        delta = target - source
    return [Difference(path, source, target, delta)]
