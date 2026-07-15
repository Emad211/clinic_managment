from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from accounting_ops.dual_run_common import (
    DualRunReport,
    build_financial_snapshot,
    compare_payload,
)
from accounting_ops.dual_run_source import load_legacy_financial_rows
from accounting_ops.dual_run_source_payroll import load_legacy_payroll
from accounting_ops.import_preflight import AccountingImportPreflight
from accounting_port.dual_run import AccountingDualRunRepository


_ALLOWED_SHIFTS = {"morning", "evening", "night"}


def _date(value: Any, *, label: str) -> date:
    try:
        return value if isinstance(value, date) else date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must use YYYY-MM-DD") from exc


def _detail(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": str(item.get("code") or ""),
        "count": int(item.get("count") or 0),
        "unit_price": float(item.get("unit_price") or 0),
        "total": float(item.get("total") or 0),
    }


def _payroll_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "staff_type": str(item.get("staff_type") or ""),
        "shift_counts": {
            "morning": int(item.get("shift_counts", {}).get("morning") or 0),
            "evening": int(item.get("shift_counts", {}).get("evening") or 0),
            "night": int(item.get("shift_counts", {}).get("night") or 0),
        },
        "details": sorted(
            (_detail(detail) for detail in item.get("details", [])),
            key=lambda detail: detail["code"],
        ),
        "gross_salary": float(item.get("gross_salary") or 0),
        "tax_amount": float(item.get("tax_amount") or 0),
        "net_salary": float(item.get("net_salary") or 0),
    }


def _normalize_payroll(
    *,
    source: dict[str, Any],
    target: dict[str, Any],
    staff_map: dict[int, int],
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_rows = {
        str(int(row["id"])): _payroll_row(row)
        for row in source.get("rows", [])
    }
    reverse = {target_id: source_id for source_id, target_id in staff_map.items()}
    target_rows: dict[str, Any] = {}
    for row in target.get("rows", []):
        target_id = int(row["id"])
        source_id = reverse.get(target_id)
        key = str(source_id) if source_id is not None else f"target-only:{target_id}"
        target_rows[key] = _payroll_row(row)
    source_payload = {
        "summary": source.get("summary", {}),
        "rows": dict(sorted(source_rows.items())),
        "mapped_staff_ids": sorted(staff_map),
    }
    target_payload = {
        "summary": target.get("summary", {}),
        "rows": dict(sorted(target_rows.items())),
        "mapped_staff_ids": sorted(staff_map),
    }
    return source_payload, target_payload


def compare_accounting_dual_run(
    *,
    sqlite_path: str | Path,
    source_id: str,
    tenant_id: int,
    date_from: Any,
    date_to: Any,
    shift: str | None = None,
) -> DualRunReport:
    start = _date(date_from, label="date_from")
    end = _date(date_to, label="date_to")
    if start > end:
        raise ValueError("date_from must not be after date_to")
    if (end - start).days + 1 > 31:
        raise ValueError("Dual-run comparison range cannot exceed 31 days")
    normalized_shift = (shift or "").strip().lower() or None
    if normalized_shift and normalized_shift not in _ALLOWED_SHIFTS:
        raise ValueError("shift must be morning, evening or night")
    if int(tenant_id) <= 0:
        raise ValueError("tenant_id must be positive")

    preflight = AccountingImportPreflight(
        sqlite_path=sqlite_path,
        source_id=source_id,
    ).run()
    if preflight.decision != "GO":
        raise ValueError("Legacy accounting snapshot failed preflight")

    source_rows = load_legacy_financial_rows(
        sqlite_path=sqlite_path,
        date_from=start,
        date_to=end,
        shift=normalized_shift,
    )
    source_financial = build_financial_snapshot(**source_rows)
    source_payroll_raw = load_legacy_payroll(
        sqlite_path=sqlite_path,
        date_from=start,
        date_to=end,
        shift=normalized_shift,
    )
    target_raw = AccountingDualRunRepository.load(
        tenant_id=int(tenant_id),
        source_id=source_id,
        date_from=start,
        date_to=end,
        shift=normalized_shift,
    )
    target_financial = build_financial_snapshot(
        invoices=target_raw["invoices"],
        events=target_raw["events"],
        payments=target_raw["payments"],
    )
    source_payroll, target_payroll = _normalize_payroll(
        source=source_payroll_raw,
        target=target_raw["payroll"],
        staff_map=target_raw["staff_map"],
    )
    differences = compare_payload(
        source_financial, target_financial, path="financial"
    ) + compare_payload(source_payroll, target_payroll, path="payroll")
    return DualRunReport(
        decision="GO" if not differences else "NO_GO",
        source_id=source_id,
        tenant_id=int(tenant_id),
        date_from=start.isoformat(),
        date_to=end.isoformat(),
        shift=normalized_shift,
        source_file_sha256=preflight.source_file_sha256,
        source_manifest_sha256=preflight.source_manifest_sha256,
        financial_source=source_financial,
        financial_target=target_financial,
        payroll_source=source_payroll,
        payroll_target=target_payroll,
        differences=differences[:500],
        errors=[] if len(differences) <= 500 else ["difference_limit_exceeded"],
    )
