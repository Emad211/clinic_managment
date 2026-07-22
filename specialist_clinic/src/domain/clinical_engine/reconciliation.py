"""Canonical, immutable reconciliation semantics for longitudinal collections.

A current row set is not the same thing as a reviewed row set.  This module keeps
those concepts separate for conditions, medications and allergies, and provides one
content-hash contract shared by the write repository and the Clinical Engine adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any, Iterable, Mapping

from src.common.utils import IRAN_TZ, parse_datetime

from .enums import FactStatus, FreshnessStatus, VerificationStatus


COLLECTION_KEYS = ("conditions", "medications", "allergies")
COLLECTION_FACT_KEYS = {
    "conditions": "condition.codes",
    "medications": "medication.classes",
    "allergies": "allergy.substances",
}
COLLECTION_LABELS_FA = {
    "conditions": "فهرست تشخیص‌ها",
    "medications": "فهرست داروها",
    "allergies": "فهرست حساسیت‌ها",
}


def _local_naive(value: Any) -> datetime | None:
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(IRAN_TZ).replace(tzinfo=None)
    return parsed


def _text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).strip().split())
    return normalized or None


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _not_future(value: Any, as_of_at: datetime) -> bool:
    parsed = _local_naive(value)
    return parsed is None or parsed <= as_of_at


def _not_resolved(value: Any, as_of_at: datetime) -> bool:
    parsed = _local_naive(value)
    return parsed is None or as_of_at < parsed


def _event_sort_key(row: Mapping[str, Any]) -> tuple[datetime, int]:
    return (_local_naive(row.get("event_date") or row.get("created_at")) or datetime.min,
            _integer(row.get("id")) or 0)


def _reconciliation_sort_key(row: Mapping[str, Any]) -> tuple[datetime, int]:
    return (_local_naive(row.get("reconciled_at")) or datetime.min,
            _integer(row.get("id")) or 0)


def _dose_at(
    medication: Mapping[str, Any],
    events: Iterable[Mapping[str, Any]],
    as_of_at: datetime,
) -> tuple[str | None, tuple[str, ...]]:
    applicable = [
        event for event in events
        if _integer(event.get("medication_id")) == _integer(medication.get("id"))
        and _not_future(event.get("event_date") or event.get("created_at"), as_of_at)
        and str(event.get("event_type") or "") in {"start", "dose_change"}
    ]
    if applicable:
        latest = max(applicable, key=_event_sort_key)
        return _text(latest.get("dose")), ()
    return _text(medication.get("dose")), ("HISTORICAL_DOSE_APPROXIMATION",)


def active_collection_rows(
    collection_key: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of_at: datetime,
    medication_events: Iterable[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], ...]:
    """Project source rows that were active at ``as_of_at``.

    New stop/removal operations persist an effective end date.  Older inactive rows
    without one cannot be placed honestly on a historical timeline and are excluded
    rather than being copied into the past.
    """
    if collection_key not in COLLECTION_KEYS:
        raise ValueError(f"unsupported reconciliation collection: {collection_key}")
    as_of_at = _local_naive(as_of_at) or as_of_at
    projected: list[dict[str, Any]] = []

    for raw in rows:
        row = dict(raw)
        warnings: list[str] = []
        if collection_key == "conditions":
            start = row.get("onset_date") or row.get("diagnosed_at")
            end = row.get("resolved_at")
            if not _not_future(start, as_of_at):
                continue
            if end is not None:
                if not _not_resolved(end, as_of_at):
                    continue
            elif not int(row.get("is_active", 1) or 0):
                continue
            row["_effective_at"] = start or row.get("diagnosed_at") or as_of_at

        elif collection_key == "medications":
            start = row.get("start_date") or row.get("created_at")
            end = row.get("end_date")
            if not _not_future(start, as_of_at):
                continue
            if end is not None:
                if not _not_resolved(end, as_of_at):
                    continue
            elif not int(row.get("is_active", 1) or 0):
                continue
            dose, dose_warnings = _dose_at(row, medication_events, as_of_at)
            row["_dose_as_of"] = dose
            warnings.extend(dose_warnings)
            row["_effective_at"] = start or row.get("created_at") or as_of_at

        else:  # allergies
            start = row.get("created_at")
            end = row.get("resolved_at")
            if not _not_future(start, as_of_at):
                continue
            if end is not None:
                if not _not_resolved(end, as_of_at):
                    continue
            elif not int(row.get("is_active", 1) or 0):
                continue
            row["_effective_at"] = start or as_of_at

        row["_history_warnings"] = tuple(sorted(set(warnings)))
        projected.append(row)

    return tuple(sorted(projected, key=lambda row: (_integer(row.get("id")) or 0)))


def canonical_collection_items(
    collection_key: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of_at: datetime,
    medication_events: Iterable[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], ...]:
    active = active_collection_rows(
        collection_key,
        rows,
        as_of_at=as_of_at,
        medication_events=medication_events,
    )
    items: list[dict[str, Any]] = []
    for row in active:
        if collection_key == "conditions":
            items.append({
                "record_id": _integer(row.get("id")),
                "condition_id": _integer(row.get("condition_id")),
                "code": _text(row.get("condition_code")),
                "stage": _text(row.get("stage")),
                "onset_date": _text(row.get("onset_date")),
            })
        elif collection_key == "medications":
            items.append({
                "record_id": _integer(row.get("id")),
                "drug_catalog_id": _integer(row.get("drug_catalog_id")),
                "name": _text(row.get("drug_name")),
                "drug_class": _text(row.get("drug_class")),
                "dose": _text(row.get("_dose_as_of")),
                "schedule": _text(row.get("schedule")),
                "start_date": _text(row.get("start_date")),
            })
        else:
            items.append({
                "record_id": _integer(row.get("id")),
                "substance": _text(row.get("substance")),
                "reaction": _text(row.get("reaction")),
                "severity": _text(row.get("severity")),
            })
    return tuple(items)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def collection_content_hash(
    collection_key: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of_at: datetime,
    medication_events: Iterable[Mapping[str, Any]] = (),
) -> str:
    items = canonical_collection_items(
        collection_key,
        rows,
        as_of_at=as_of_at,
        medication_events=medication_events,
    )
    payload = {
        "schema_version": "1.0",
        "collection_key": collection_key,
        "items": items,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _values(collection_key: str, items: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    field = {
        "conditions": "code",
        "medications": "drug_class",
        "allergies": "substance",
    }[collection_key]
    return tuple(sorted({str(item[field]) for item in items if item.get(field)}))


def _mapping_complete(collection_key: str, items: Iterable[Mapping[str, Any]]) -> bool:
    required = {
        "conditions": ("code",),
        "medications": ("name", "drug_class"),
        "allergies": ("substance",),
    }[collection_key]
    return all(all(item.get(field) for field in required) for item in items)


@dataclass(frozen=True, slots=True)
class CollectionProjection:
    collection_key: str
    rows: tuple[dict[str, Any], ...]
    items: tuple[dict[str, Any], ...]
    values: tuple[str, ...]
    content_hash: str
    item_count: int
    mapping_complete: bool
    state: str
    status: FactStatus
    verification: VerificationStatus
    freshness: FreshnessStatus
    effective_at: datetime
    source_system: str
    source_record_id: str
    actor: str | None
    warnings: tuple[str, ...]
    reconciliation_event: dict[str, Any] | None


def project_collection(
    collection_key: str,
    rows: Iterable[Mapping[str, Any]],
    reconciliation_events: Iterable[Mapping[str, Any]],
    *,
    as_of_at: datetime,
    medication_events: Iterable[Mapping[str, Any]] = (),
) -> CollectionProjection:
    """Combine effective rows with the latest applicable reconciliation event."""
    if collection_key not in COLLECTION_KEYS:
        raise ValueError(f"unsupported reconciliation collection: {collection_key}")
    as_of_at = _local_naive(as_of_at) or as_of_at
    active_rows = active_collection_rows(
        collection_key,
        rows,
        as_of_at=as_of_at,
        medication_events=medication_events,
    )
    items = canonical_collection_items(
        collection_key,
        active_rows,
        as_of_at=as_of_at,
        medication_events=medication_events,
    )
    values = _values(collection_key, items)
    content_hash = collection_content_hash(
        collection_key,
        active_rows,
        as_of_at=as_of_at,
        medication_events=medication_events,
    )
    mapping_complete = _mapping_complete(collection_key, items)

    candidates = [
        dict(event)
        for event in reconciliation_events
        if str(event.get("collection_key") or "") == collection_key
        and _not_future(event.get("reconciled_at"), as_of_at)
    ]
    event = max(candidates, key=_reconciliation_sort_key) if candidates else None
    warnings: list[str] = []
    if collection_key == "medications" and any(
        item.get("drug_catalog_id") is None for item in items
    ):
        warnings.append("UNMAPPED_MEDICATION_CONCEPT")
    if not mapping_complete:
        warnings.append("CANONICAL_MAPPING_INCOMPLETE")
    for row in active_rows:
        warnings.extend(row.get("_history_warnings") or ())

    if event is None:
        state = "unreconciled"
        status = FactStatus.PRESENT if values and mapping_complete else FactStatus.UNKNOWN
        verification = VerificationStatus.UNVERIFIED
        freshness = FreshnessStatus.UNKNOWN
        effective_at = as_of_at
        source_system = "legacy_collection"
        source_record_id = collection_key
        actor = None
        warnings.append("UNRECONCILED_COLLECTION")
    else:
        effective_at = _local_naive(event.get("reconciled_at")) or as_of_at
        source_system = "clinical_reconciliation"
        source_record_id = str(event.get("id"))
        actor = _text(event.get("actor_username"))
        exact = (
            str(event.get("content_hash") or "") == content_hash
            and _integer(event.get("item_count")) == len(items)
        )
        if not exact:
            state = "stale"
            status = FactStatus.PRESENT if values and mapping_complete else FactStatus.UNKNOWN
            verification = VerificationStatus.UNVERIFIED
            freshness = FreshnessStatus.STALE
            warnings.append("COLLECTION_CHANGED_AFTER_RECONCILIATION")
        elif str(event.get("completeness") or "") == "partial":
            state = "partial"
            status = FactStatus.PRESENT if values and mapping_complete else FactStatus.UNKNOWN
            verification = VerificationStatus.PROVISIONAL
            freshness = FreshnessStatus.FRESH
            warnings.append("PARTIAL_RECONCILIATION")
        elif not mapping_complete:
            state = "mapping_incomplete"
            status = FactStatus.UNKNOWN
            verification = VerificationStatus.UNVERIFIED
            freshness = FreshnessStatus.FRESH
        else:
            state = "confirmed_absent" if not values else "confirmed_present"
            status = FactStatus.ABSENT if not values else FactStatus.PRESENT
            verification = VerificationStatus.CONFIRMED
            freshness = FreshnessStatus.FRESH

    return CollectionProjection(
        collection_key=collection_key,
        rows=active_rows,
        items=items,
        values=values,
        content_hash=content_hash,
        item_count=len(items),
        mapping_complete=mapping_complete,
        state=state,
        status=status,
        verification=verification,
        freshness=freshness,
        effective_at=effective_at,
        source_system=source_system,
        source_record_id=source_record_id,
        actor=actor,
        warnings=tuple(sorted(set(warnings))),
        reconciliation_event=event,
    )
