"""Canonical, immutable reconciliation semantics for longitudinal collections.

A current row set is not the same thing as a reviewed row set. This module keeps
those concepts separate for conditions, medications and allergies, and provides one
content-hash contract shared by the write repository and Clinical Engine adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any, Iterable, Mapping

from src.common.utils import IRAN_TZ, parse_datetime

from .enums import (
    ConflictStatus,
    FactStatus,
    FreshnessStatus,
    VerificationStatus,
)
from .data_conflicts import (
    detect_conflict_groups,
    project_conflict_overlay,
)


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


def _has_raw_value(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _event_sort_key(row: Mapping[str, Any]) -> tuple[datetime, int]:
    return (
        _local_naive(row.get("event_date") or row.get("created_at"))
        or datetime.min,
        _integer(row.get("id")) or 0,
    )


def _reconciliation_sort_key(
    row: Mapping[str, Any],
) -> tuple[datetime, int]:
    return (
        _local_naive(row.get("reconciled_at")) or datetime.min,
        _integer(row.get("id")) or 0,
    )


def _dose_at(
    medication: Mapping[str, Any],
    events: Iterable[Mapping[str, Any]],
    as_of_at: datetime,
) -> tuple[str | None, tuple[str, ...]]:
    applicable = [
        event
        for event in events
        if _integer(event.get("medication_id"))
        == _integer(medication.get("id"))
        and (
            (_local_naive(event.get("event_date") or event.get("created_at")))
            or datetime.max
        )
        <= as_of_at
        and str(event.get("event_type") or "")
        in {"start", "dose_change"}
    ]
    if applicable:
        latest = max(applicable, key=_event_sort_key)
        return _text(latest.get("dose")), ()
    return (
        _text(medication.get("dose")),
        ("HISTORICAL_DOSE_APPROXIMATION",),
    )


@dataclass(frozen=True, slots=True)
class _ActiveRows:
    rows: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]


def _project_active_rows(
    collection_key: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of_at: datetime,
    medication_events: Iterable[Mapping[str, Any]] = (),
) -> _ActiveRows:
    """Project source rows active at ``as_of_at`` exactly once.

    Missing/invalid legacy interval timestamps do not silently become exact history:
    the row is retained as current knowledge at the requested snapshot and receives
    an explicit approximation warning. Inactive legacy rows without an end date are
    excluded because their historical interval cannot be reconstructed honestly.
    """
    if collection_key not in COLLECTION_KEYS:
        raise ValueError(
            f"unsupported reconciliation collection: {collection_key}"
        )
    as_of_at = _local_naive(as_of_at) or as_of_at
    projected: list[dict[str, Any]] = []
    projection_warnings: list[str] = []

    for raw in rows:
        row = dict(raw)
        if str(row.get("source_assertion") or "PRESENT").upper() != "PRESENT":
            continue
        warnings: list[str] = []
        if collection_key == "conditions":
            start_raw = row.get("onset_date") or row.get("diagnosed_at")
            end_raw = row.get("resolved_at")
        elif collection_key == "medications":
            start_raw = row.get("start_date") or row.get("created_at")
            end_raw = row.get("end_date")
        else:
            start_raw = row.get("created_at")
            end_raw = row.get("resolved_at")

        start = _local_naive(start_raw)
        if start is None:
            warnings.append("HISTORICAL_INTERVAL_APPROXIMATION")
            start = as_of_at
        if start > as_of_at:
            continue

        end = _local_naive(end_raw)
        if _has_raw_value(end_raw) and end is None:
            warnings.append("HISTORICAL_INTERVAL_APPROXIMATION")
        if end is not None and as_of_at >= end:
            continue
        if end is None and not int(row.get("is_active", 1) or 0):
            # Current absence is known, but without an effective end date this row
            # cannot be copied into an arbitrary historical snapshot.
            continue

        if collection_key == "medications":
            dose, dose_warnings = _dose_at(
                row, medication_events, as_of_at
            )
            row["_dose_as_of"] = dose
            warnings.extend(dose_warnings)

        row["_effective_at"] = start
        row["_history_warnings"] = tuple(sorted(set(warnings)))
        projection_warnings.extend(warnings)
        projected.append(row)

    return _ActiveRows(
        rows=tuple(
            sorted(
                projected,
                key=lambda row: _integer(row.get("id")) or 0,
            )
        ),
        warnings=tuple(sorted(set(projection_warnings))),
    )


def active_collection_rows(
    collection_key: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of_at: datetime,
    medication_events: Iterable[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], ...]:
    """Public effective-row projection retained for repository/test callers."""
    return _project_active_rows(
        collection_key,
        rows,
        as_of_at=as_of_at,
        medication_events=medication_events,
    ).rows


def _canonical_items_from_active_rows(
    collection_key: str,
    active_rows: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    items: list[dict[str, Any]] = []
    for row in active_rows:
        if collection_key == "conditions":
            items.append(
                {
                    "record_id": _integer(row.get("id")),
                    "condition_id": _integer(row.get("condition_id")),
                    "code": _text(row.get("condition_code")),
                    "stage": _text(row.get("stage")),
                    "onset_date": _text(row.get("onset_date")),
                }
            )
        elif collection_key == "medications":
            items.append(
                {
                    "record_id": _integer(row.get("id")),
                    "drug_catalog_id": _integer(
                        row.get("drug_catalog_id")
                    ),
                    "name": _text(row.get("drug_name")),
                    "drug_class": _text(row.get("drug_class")),
                    "dose": _text(row.get("_dose_as_of")),
                    "schedule": _text(row.get("schedule")),
                    "start_date": _text(row.get("start_date")),
                }
            )
        else:
            items.append(
                {
                    "record_id": _integer(row.get("id")),
                    "allergy_concept_id": _integer(row.get("allergy_concept_id")),
                    "concept_key": _text(row.get("allergy_concept_key")),
                    "substance": _text(row.get("substance")),
                    "reaction": _text(row.get("reaction")),
                    "severity": _text(row.get("severity")),
                }
            )
    return tuple(items)


def canonical_collection_items(
    collection_key: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of_at: datetime,
    medication_events: Iterable[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], ...]:
    active = _project_active_rows(
        collection_key,
        rows,
        as_of_at=as_of_at,
        medication_events=medication_events,
    )
    return _canonical_items_from_active_rows(collection_key, active.rows)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _content_hash_from_items(
    collection_key: str,
    items: tuple[dict[str, Any], ...],
) -> str:
    payload = {
        "schema_version": "1.0",
        "collection_key": collection_key,
        "items": items,
    }
    return hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()


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
    return _content_hash_from_items(collection_key, items)


def _values(
    collection_key: str,
    items: Iterable[Mapping[str, Any]],
) -> tuple[str, ...]:
    if collection_key == "allergies":
        return tuple(
            sorted(
                {
                    str(item.get("concept_key") or item.get("substance"))
                    for item in items
                    if item.get("concept_key") or item.get("substance")
                }
            )
        )
    field = {
        "conditions": "code",
        "medications": "drug_class",
    }[collection_key]
    return tuple(
        sorted({str(item[field]) for item in items if item.get(field)})
    )


def _mapping_complete(
    collection_key: str,
    items: Iterable[Mapping[str, Any]],
) -> bool:
    required = {
        "conditions": ("code",),
        # A manually typed class is useful provisional evidence but is not a
        # complete medication identity. Confirmed medication aggregates require
        # an active catalog concept as well as the canonical class.
        "medications": ("name", "drug_class", "drug_catalog_id"),
        "allergies": ("substance", "allergy_concept_id", "concept_key"),
    }[collection_key]
    return all(
        all(item.get(field) is not None for field in required)
        for item in items
    )


def _status_for_values(values: tuple[str, ...]) -> FactStatus:
    return FactStatus.PRESENT if values else FactStatus.UNKNOWN


@dataclass(frozen=True, slots=True)
class CollectionProjection:
    collection_key: str
    rows: tuple[dict[str, Any], ...]
    items: tuple[dict[str, Any], ...]
    values: tuple[str, ...]
    content_hash: str
    item_count: int
    mapping_complete: bool
    conflict_snapshot_hash: str
    conflict_count: int
    unresolved_conflict_count: int
    resolved_unknown_count: int
    conflicts: tuple[dict[str, Any], ...]
    conflict: ConflictStatus
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
    conflict_events: Iterable[Mapping[str, Any]] = (),
) -> CollectionProjection:
    """Combine one effective-row projection with its latest review event."""
    if collection_key not in COLLECTION_KEYS:
        raise ValueError(
            f"unsupported reconciliation collection: {collection_key}"
        )
    as_of_at = _local_naive(as_of_at) or as_of_at
    source_rows = tuple(dict(row) for row in rows)
    active = _project_active_rows(
        collection_key,
        source_rows,
        as_of_at=as_of_at,
        medication_events=medication_events,
    )
    groups = detect_conflict_groups(
        collection_key,
        source_rows,
        as_of_at=as_of_at,
        medication_events=medication_events,
    )
    conflict_overlay = project_conflict_overlay(
        collection_key,
        groups,
        conflict_events,
        as_of_at=as_of_at,
    )
    usable_rows = tuple(
        {
            **row,
            "_resolution_confirmed": (
                _integer(row.get("id"))
                in conflict_overlay.resolution_confirmed_record_ids
            ),
        }
        for row in active.rows
        if _integer(row.get("id")) in conflict_overlay.usable_record_ids
    )
    items_list = list(_canonical_items_from_active_rows(collection_key, usable_rows))
    synthetic_rows: list[dict[str, Any]] = []
    for synthetic in conflict_overlay.synthetic_items:
        item = {key: value for key, value in synthetic.items() if not key.startswith("_")}
        items_list.append(item)
        resolution_id = synthetic.get("_resolution_event_id")
        if collection_key == "conditions":
            synthetic_rows.append({
                "id": f"resolution-{resolution_id}",
                "condition_code": item.get("code"),
                "stage": item.get("stage"),
                "onset_date": item.get("onset_date"),
                "_effective_at": synthetic.get("_effective_at"),
                "_history_warnings": (),
                "recorded_by": "clinical-conflict-resolution",
            })
        elif collection_key == "medications":
            synthetic_rows.append({
                "id": f"resolution-{resolution_id}",
                "drug_catalog_id": item.get("drug_catalog_id"),
                "drug_name": item.get("name"),
                "drug_class": item.get("drug_class"),
                "_dose_as_of": item.get("dose"),
                "schedule": item.get("schedule"),
                "start_date": item.get("start_date"),
                "_effective_at": synthetic.get("_effective_at"),
                "_history_warnings": (),
                "recorded_by": "clinical-conflict-resolution",
            })
        else:
            synthetic_rows.append({
                "id": f"resolution-{resolution_id}",
                "allergy_concept_id": item.get("allergy_concept_id"),
                "allergy_concept_key": item.get("concept_key"),
                "substance": item.get("substance"),
                "reaction": item.get("reaction"),
                "severity": item.get("severity"),
                "_effective_at": synthetic.get("_effective_at"),
                "_history_warnings": (),
                "recorded_by": "clinical-conflict-resolution",
            })
    items = tuple(sorted(items_list, key=lambda item: canonical_json(item)))
    values = _values(collection_key, items)
    content_hash = _content_hash_from_items(collection_key, items)
    mapping_complete = _mapping_complete(collection_key, items)
    projected_rows = tuple((*usable_rows, *synthetic_rows))

    candidates = [
        dict(event)
        for event in reconciliation_events
        if str(event.get("collection_key") or "") == collection_key
        and (
            _local_naive(event.get("reconciled_at")) or datetime.max
        )
        <= as_of_at
    ]
    event = (
        max(candidates, key=_reconciliation_sort_key)
        if candidates
        else None
    )
    warnings = [*active.warnings, *conflict_overlay.warnings]
    if collection_key == "medications" and any(
        item.get("drug_catalog_id") is None for item in items
    ):
        warnings.append("UNMAPPED_MEDICATION_CONCEPT")
    if collection_key == "allergies" and any(
        item.get("allergy_concept_id") is None for item in items
    ):
        warnings.append("UNMAPPED_ALLERGY_CONCEPT")
    if not mapping_complete:
        warnings.append("CANONICAL_MAPPING_INCOMPLETE")

    if conflict_overlay.unresolved_count:
        state = "conflict_unresolved"
        status = FactStatus.UNKNOWN
        verification = VerificationStatus.UNVERIFIED
        freshness = FreshnessStatus.FRESH
        effective_at = as_of_at
        source_system = "clinical_data_conflict"
        source_record_id = conflict_overlay.snapshot_hash
        actor = None
        warnings.append("UNRESOLVED_CLINICAL_CONFLICT")
    elif conflict_overlay.resolved_unknown_count:
        state = "conflict_unknown"
        status = FactStatus.UNKNOWN
        verification = VerificationStatus.UNVERIFIED
        freshness = FreshnessStatus.FRESH
        effective_at = as_of_at
        source_system = "clinical_data_conflict"
        source_record_id = conflict_overlay.snapshot_hash
        actor = None
        warnings.append("CLINICAL_CONFLICT_RESOLVED_UNKNOWN")
    elif event is None:
        state = "unreconciled"
        status = _status_for_values(values)
        verification = VerificationStatus.UNVERIFIED
        freshness = FreshnessStatus.UNKNOWN
        effective_at = as_of_at
        source_system = "legacy_collection"
        source_record_id = collection_key
        actor = None
        warnings.append("UNRECONCILED_COLLECTION")
    else:
        effective_at = (
            _local_naive(event.get("reconciled_at")) or as_of_at
        )
        source_system = "clinical_reconciliation"
        source_record_id = str(event.get("id"))
        actor = _text(event.get("actor_username"))
        exact = (
            str(event.get("content_hash") or "") == content_hash
            and _integer(event.get("item_count")) == len(items)
            and str(event.get("conflict_snapshot_hash") or "")
                == conflict_overlay.snapshot_hash
            and _integer(event.get("unresolved_conflict_count"))
                == conflict_overlay.unresolved_count
        )
        if not exact:
            state = "stale"
            status = _status_for_values(values)
            verification = VerificationStatus.UNVERIFIED
            freshness = FreshnessStatus.STALE
            warnings.append(
                "COLLECTION_CHANGED_AFTER_RECONCILIATION"
            )
        elif str(event.get("completeness") or "") == "partial":
            state = "partial"
            status = _status_for_values(values)
            verification = VerificationStatus.PROVISIONAL
            freshness = FreshnessStatus.FRESH
            warnings.append("PARTIAL_RECONCILIATION")
        elif not mapping_complete:
            state = "mapping_incomplete"
            status = _status_for_values(values)
            verification = (
                VerificationStatus.PROVISIONAL
                if values
                else VerificationStatus.UNVERIFIED
            )
            freshness = FreshnessStatus.FRESH
        else:
            state = (
                "confirmed_absent"
                if not values
                else "confirmed_present"
            )
            status = (
                FactStatus.ABSENT
                if not values
                else FactStatus.PRESENT
            )
            verification = VerificationStatus.CONFIRMED
            freshness = FreshnessStatus.FRESH

    return CollectionProjection(
        collection_key=collection_key,
        rows=projected_rows,
        items=items,
        values=values,
        content_hash=content_hash,
        item_count=len(items),
        mapping_complete=mapping_complete,
        conflict_snapshot_hash=conflict_overlay.snapshot_hash,
        conflict_count=conflict_overlay.conflict_count,
        unresolved_conflict_count=conflict_overlay.unresolved_count,
        resolved_unknown_count=conflict_overlay.resolved_unknown_count,
        conflicts=conflict_overlay.groups,
        conflict=(
            ConflictStatus.PRESENT
            if conflict_overlay.unresolved_count
            else ConflictStatus.UNKNOWN
            if conflict_overlay.resolved_unknown_count
            else ConflictStatus.NONE
        ),
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
