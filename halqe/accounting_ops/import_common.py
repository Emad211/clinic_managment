from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping


class AccountingImportError(RuntimeError):
    """Base class for fail-closed accounting migration failures."""


class PreflightRejectedError(AccountingImportError):
    pass


class SourceChangedError(AccountingImportError):
    pass


class ReplayConflictError(AccountingImportError):
    pass


class TargetConflictError(AccountingImportError):
    pass


class UnsupportedServiceTypeError(AccountingImportError):
    pass


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.isoformat(timespec="microseconds")
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, Decimal)):
        return str(Decimal(value).normalize())
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AccountingImportError("Non-finite numeric value in import payload")
        return str(Decimal(str(value)).normalize())
    return str(value)


def payload_sha256(payload: Mapping[str, Any]) -> str:
    rendered = json.dumps(
        normalize(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def source_key(table: str, row: Mapping[str, Any]) -> str:
    if table == "invoice_item_payments":
        return f"{int(row['invoice_id'])}:{row['item_type']}:{int(row['item_id'])}"
    if "id" not in row or row["id"] is None:
        raise AccountingImportError(f"Source table {table} has no stable primary key")
    return str(int(row["id"]))


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def integer_money(value: Any, *, field: str) -> int:
    if value is None or value == "":
        return 0
    try:
        amount = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise AccountingImportError(f"Invalid money value for {field}") from exc
    if amount < 0:
        raise AccountingImportError(f"Negative money value for {field}")
    return int(amount)


def decimal_quantity(value: Any, *, field: str) -> Decimal:
    try:
        amount = Decimal(str(1 if value is None else value)).quantize(Decimal("0.001"))
    except (InvalidOperation, ValueError) as exc:
        raise AccountingImportError(f"Invalid quantity for {field}") from exc
    if amount < 0:
        raise AccountingImportError(f"Negative quantity for {field}")
    return amount


def boolean(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def mapped_service_type(value: Any, mapping: Mapping[str, str]) -> tuple[str, str | None]:
    source = (clean_text(value) or "").lower()
    allowed = {"visit", "injection", "procedure", "consumable"}
    if source in allowed:
        return source, None
    target = (mapping.get(source) or "").strip().lower()
    if target not in allowed:
        raise UnsupportedServiceTypeError(
            f"Legacy service type {source!r} requires an explicit mapping to one of "
            + ", ".join(sorted(allowed))
        )
    return target, source
