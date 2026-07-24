"""Pure, fail-closed clinical source conflict and completeness semantics.

No source is implicitly more trustworthy than another.  A source bundle is converted
into immutable candidates grouped by canonical concept.  Conflicting or unknown groups
are unusable until an append-only resolution event matches the exact candidate-set hash.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Iterable, Mapping

from src.common.utils import IRAN_TZ, parse_datetime


class CandidateAssertion(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"


class ConflictEventType(StrEnum):
    OPENED = "OPENED"
    REOPENED = "REOPENED"
    RESOLVED = "RESOLVED"
    ENTERED_IN_ERROR = "ENTERED_IN_ERROR"


class ConflictEventStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    ENTERED_IN_ERROR = "ENTERED_IN_ERROR"


class ConflictResolutionMethod(StrEnum):
    SELECT_CANDIDATE = "SELECT_CANDIDATE"
    CONFIRMED_ABSENT = "CONFIRMED_ABSENT"
    MARK_UNKNOWN = "MARK_UNKNOWN"
    MERGE_CANDIDATES = "MERGE_CANDIDATES"


class ClinicalDataConflictError(ValueError):
    pass


_COLLECTIONS = frozenset({"conditions", "medications", "allergies"})
_VERIFICATIONS = frozenset({"CONFIRMED", "PROVISIONAL", "UNVERIFIED", "REFUTED"})
_KEY_SAFE = re.compile(r"[^a-z0-9._-]+")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _dt(value: Any) -> datetime | None:
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(IRAN_TZ).replace(tzinfo=None)
    return parsed


def _text(value: Any) -> str | None:
    if value is None:
        return None
    clean = " ".join(str(value).strip().split())
    return clean or None


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _slug(value: Any) -> str:
    clean = _text(value)
    if not clean:
        return "unknown"
    normalized = _KEY_SAFE.sub("-", clean.lower()).strip("-")
    return normalized[:160] or "unknown"


def _row_is_effective(collection_key: str, row: Mapping[str, Any], as_of: datetime) -> bool:
    if collection_key == "conditions":
        start_raw = row.get("onset_date") or row.get("diagnosed_at")
        end_raw = row.get("resolved_at")
    elif collection_key == "medications":
        start_raw = row.get("start_date") or row.get("created_at")
        end_raw = row.get("end_date")
    else:
        start_raw = row.get("created_at")
        end_raw = row.get("resolved_at")
    start = _dt(start_raw)
    if start is not None and start > as_of:
        return False
    end = _dt(end_raw)
    if end is not None and as_of >= end:
        return False
    if end is None and not int(row.get("is_active", 1) or 0):
        return False
    return True


def _dose_at(
    row: Mapping[str, Any],
    medication_events: Iterable[Mapping[str, Any]],
    as_of: datetime,
) -> str | None:
    events = []
    for event in medication_events:
        if _integer(event.get("medication_id")) != _integer(row.get("id")):
            continue
        when = _dt(event.get("event_date") or event.get("created_at"))
        if when is None or when > as_of:
            continue
        if str(event.get("event_type") or "") not in {"start", "dose_change"}:
            continue
        events.append((when, _integer(event.get("id")) or 0, event))
    if not events:
        return _text(row.get("dose"))
    return _text(max(events, key=lambda item: (item[0], item[1]))[2].get("dose"))


def _concept_key(collection_key: str, row: Mapping[str, Any]) -> str:
    if collection_key == "conditions":
        code = _text(row.get("condition_code"))
        return f"condition:{code}" if code else f"condition:unmapped-{_integer(row.get('condition_id')) or _slug(row.get('condition_name'))}"
    if collection_key == "medications":
        catalog_id = _integer(row.get("drug_catalog_id"))
        if catalog_id is not None:
            return f"medication:catalog-{catalog_id}"
        return f"medication:unmapped-{_slug(row.get('drug_name'))}-{_slug(row.get('drug_class'))}"
    concept = _text(row.get("allergy_concept_key"))
    if concept:
        return f"allergy:{concept}"
    return f"allergy:unmapped-{_slug(row.get('substance'))}"


def _item(collection_key: str, row: Mapping[str, Any], *, dose: str | None = None) -> dict[str, Any]:
    if collection_key == "conditions":
        return {
            "record_id": _integer(row.get("id")),
            "condition_id": _integer(row.get("condition_id")),
            "code": _text(row.get("condition_code")),
            "stage": _text(row.get("stage")),
            "onset_date": _text(row.get("onset_date")),
        }
    if collection_key == "medications":
        return {
            "record_id": _integer(row.get("id")),
            "drug_catalog_id": _integer(row.get("drug_catalog_id")),
            "name": _text(row.get("drug_name")),
            "drug_class": _text(row.get("drug_class")),
            "dose": dose if dose is not None else _text(row.get("dose")),
            "schedule": _text(row.get("schedule")),
            "start_date": _text(row.get("start_date")),
        }
    return {
        "record_id": _integer(row.get("id")),
        "allergy_concept_id": _integer(row.get("allergy_concept_id")),
        "concept_key": _text(row.get("allergy_concept_key")),
        "substance": _text(row.get("substance")),
        "reaction": _text(row.get("reaction")),
        "severity": _text(row.get("severity")),
    }


def _semantic_item(item: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key != "record_id"}


@dataclass(frozen=True, slots=True)
class ConflictCandidate:
    candidate_key: str
    collection_key: str
    group_key: str
    concept_key: str
    record_id: int
    source_system: str
    source_record_id: str
    assertion: CandidateAssertion
    verification: str
    effective_at: datetime
    recorded_at: datetime
    item: Mapping[str, Any]

    def payload(self) -> dict[str, Any]:
        return {
            "candidate_key": self.candidate_key,
            "collection_key": self.collection_key,
            "group_key": self.group_key,
            "concept_key": self.concept_key,
            "record_id": self.record_id,
            "source_system": self.source_system,
            "source_record_id": self.source_record_id,
            "assertion": self.assertion.value,
            "verification": self.verification,
            "effective_at": self.effective_at.isoformat(sep=" ", timespec="seconds"),
            "recorded_at": self.recorded_at.isoformat(sep=" ", timespec="seconds"),
            "item": dict(self.item),
        }


@dataclass(frozen=True, slots=True)
class ConflictGroup:
    collection_key: str
    group_key: str
    concept_key: str
    candidates: tuple[ConflictCandidate, ...]
    candidate_set_hash: str
    reasons: tuple[str, ...]
    requires_resolution: bool

    def payload(self) -> dict[str, Any]:
        return {
            "collection_key": self.collection_key,
            "group_key": self.group_key,
            "concept_key": self.concept_key,
            "candidate_set_hash": self.candidate_set_hash,
            "reasons": list(self.reasons),
            "requires_resolution": self.requires_resolution,
            "candidates": [candidate.payload() for candidate in self.candidates],
        }


@dataclass(frozen=True, slots=True)
class ConflictOverlay:
    collection_key: str
    snapshot_hash: str
    groups: tuple[dict[str, Any], ...]
    usable_record_ids: frozenset[int]
    resolution_confirmed_record_ids: frozenset[int]
    synthetic_items: tuple[dict[str, Any], ...]
    unresolved_count: int
    conflict_count: int
    resolved_unknown_count: int
    warnings: tuple[str, ...]


def detect_conflict_groups(
    collection_key: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of_at: datetime,
    medication_events: Iterable[Mapping[str, Any]] = (),
) -> tuple[ConflictGroup, ...]:
    if collection_key not in _COLLECTIONS:
        raise ClinicalDataConflictError(f"unsupported collection: {collection_key}")
    as_of = _dt(as_of_at) or as_of_at
    candidates: list[ConflictCandidate] = []
    for raw in rows:
        row = dict(raw)
        if not _row_is_effective(collection_key, row, as_of):
            continue
        record_id = _integer(row.get("id"))
        if record_id is None:
            raise ClinicalDataConflictError("source row is missing a stable record id")
        try:
            assertion = CandidateAssertion(str(row.get("source_assertion") or "PRESENT").upper())
        except ValueError as exc:
            raise ClinicalDataConflictError("invalid source assertion") from exc
        verification = str(row.get("verification") or "CONFIRMED").upper()
        if verification not in _VERIFICATIONS:
            raise ClinicalDataConflictError("invalid source verification")
        concept_key = _concept_key(collection_key, row)
        group_key = f"{collection_key}:{concept_key}"
        source_system = _text(row.get("source_system")) or "clinic"
        source_record_id = _text(row.get("source_record_id")) or f"{collection_key}:{record_id}"
        effective = _dt(
            row.get("onset_date")
            or row.get("start_date")
            or row.get("diagnosed_at")
            or row.get("created_at")
        ) or as_of
        recorded = _dt(row.get("diagnosed_at") or row.get("created_at")) or effective
        item = _item(
            collection_key,
            row,
            dose=(
                _dose_at(row, medication_events, as_of)
                if collection_key == "medications"
                else None
            ),
        )
        candidate_key = digest(
            {
                "collection_key": collection_key,
                "group_key": group_key,
                "source_system": source_system,
                "source_record_id": source_record_id,
                "record_id": record_id,
            }
        )
        candidates.append(
            ConflictCandidate(
                candidate_key=candidate_key,
                collection_key=collection_key,
                group_key=group_key,
                concept_key=concept_key,
                record_id=record_id,
                source_system=source_system,
                source_record_id=source_record_id,
                assertion=assertion,
                verification=verification,
                effective_at=effective,
                recorded_at=recorded,
                item=item,
            )
        )

    grouped: dict[str, list[ConflictCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.group_key, []).append(candidate)

    result: list[ConflictGroup] = []
    for group_key, group_candidates in sorted(grouped.items()):
        ordered = tuple(
            sorted(
                group_candidates,
                key=lambda candidate: (
                    candidate.source_system,
                    candidate.source_record_id,
                    candidate.record_id,
                    candidate.candidate_key,
                ),
            )
        )
        assertions = {candidate.assertion for candidate in ordered}
        present_payloads = {
            canonical_json(_semantic_item(candidate.item))
            for candidate in ordered
            if candidate.assertion is CandidateAssertion.PRESENT
        }
        reasons: list[str] = []
        if CandidateAssertion.UNKNOWN in assertions:
            reasons.append("SOURCE_ASSERTION_UNKNOWN")
        if len(assertions) > 1:
            reasons.append("ASSERTION_DISAGREEMENT")
        if len(present_payloads) > 1:
            reasons.append("CLINICAL_DETAIL_DISAGREEMENT")
        requires_resolution = bool(reasons)
        candidate_hash = digest([candidate.payload() for candidate in ordered])
        result.append(
            ConflictGroup(
                collection_key=collection_key,
                group_key=group_key,
                concept_key=ordered[0].concept_key,
                candidates=ordered,
                candidate_set_hash=candidate_hash,
                reasons=tuple(sorted(set(reasons))),
                requires_resolution=requires_resolution,
            )
        )
    return tuple(result)


def _latest_events(
    events: Iterable[Mapping[str, Any]],
    *,
    collection_key: str,
    as_of_at: datetime,
) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for raw in events:
        event = dict(raw)
        if str(event.get("collection_key") or "") != collection_key:
            continue
        when = _dt(event.get("recorded_at"))
        if when is None or when > as_of_at:
            continue
        group_key = str(event.get("conflict_group_key") or "")
        previous = latest.get(group_key)
        if previous is None or (
            when,
            _integer(event.get("id")) or 0,
        ) > (
            _dt(previous.get("recorded_at")) or datetime.min,
            _integer(previous.get("id")) or 0,
        ):
            latest[group_key] = event
    return latest


def _selected_keys(event: Mapping[str, Any]) -> tuple[str, ...]:
    try:
        values = json.loads(str(event.get("selected_candidate_keys_json") or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()
    return tuple(sorted(str(value) for value in values if str(value).strip()))


def _resolved_item(event: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = event.get("resolved_value_json")
    if not raw:
        return None
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return dict(value) if isinstance(value, dict) else None


def project_conflict_overlay(
    collection_key: str,
    groups: Iterable[ConflictGroup],
    events: Iterable[Mapping[str, Any]],
    *,
    as_of_at: datetime,
) -> ConflictOverlay:
    as_of = _dt(as_of_at) or as_of_at
    groups = tuple(groups)
    latest = _latest_events(events, collection_key=collection_key, as_of_at=as_of)
    usable: set[int] = set()
    resolution_confirmed: set[int] = set()
    synthetic: list[dict[str, Any]] = []
    views: list[dict[str, Any]] = []
    unresolved = 0
    conflict_count = 0
    resolved_unknown = 0
    warnings: set[str] = set()
    snapshot_components: list[dict[str, Any]] = []

    for group in groups:
        event = latest.get(group.group_key)
        valid_resolution = bool(
            event
            and str(event.get("status") or "") == ConflictEventStatus.RESOLVED.value
            and str(event.get("candidate_set_hash") or "") == group.candidate_set_hash
        )
        stale_resolution = bool(
            event
            and str(event.get("status") or "") == ConflictEventStatus.RESOLVED.value
            and str(event.get("candidate_set_hash") or "") != group.candidate_set_hash
        )
        if group.requires_resolution:
            conflict_count += 1
        state = "clear"
        method = None
        selected: tuple[str, ...] = ()
        if group.requires_resolution and not valid_resolution:
            unresolved += 1
            state = "stale" if stale_resolution else "open"
            warnings.add(
                "STALE_CONFLICT_RESOLUTION" if stale_resolution else "UNRESOLVED_CLINICAL_CONFLICT"
            )
        elif valid_resolution:
            method = str(event.get("resolution_method") or "")
            selected = _selected_keys(event)
            if method == ConflictResolutionMethod.MARK_UNKNOWN.value:
                resolved_unknown += 1
                state = "resolved_unknown"
                warnings.add("CLINICAL_CONFLICT_RESOLVED_UNKNOWN")
            elif method == ConflictResolutionMethod.CONFIRMED_ABSENT.value:
                state = "resolved_absent"
            elif method == ConflictResolutionMethod.SELECT_CANDIDATE.value:
                state = "resolved_selected"
                chosen = {
                    candidate.candidate_key: candidate
                    for candidate in group.candidates
                }
                for key in selected:
                    candidate = chosen.get(key)
                    if candidate and candidate.assertion is CandidateAssertion.PRESENT:
                        usable.add(candidate.record_id)
                        resolution_confirmed.add(candidate.record_id)
            elif method == ConflictResolutionMethod.MERGE_CANDIDATES.value:
                state = "resolved_merged"
                item = _resolved_item(event)
                if item:
                    item = dict(item)
                    item["_resolution_event_id"] = _integer(event.get("id"))
                    item["_effective_at"] = _dt(event.get("effective_at")) or as_of
                    item["_source_system"] = "clinical_data_conflict_resolution"
                    synthetic.append(item)
                else:
                    unresolved += 1
                    state = "open"
                    warnings.add("INVALID_CONFLICT_RESOLUTION_PAYLOAD")
            else:
                unresolved += 1
                state = "open"
                warnings.add("INVALID_CONFLICT_RESOLUTION_METHOD")
        else:
            for candidate in group.candidates:
                if candidate.assertion is CandidateAssertion.PRESENT:
                    usable.add(candidate.record_id)
                elif candidate.assertion is CandidateAssertion.UNKNOWN:
                    unresolved += 1
                    state = "open"
                    warnings.add("SOURCE_ASSERTION_UNKNOWN")

        event_id = _integer(event.get("id")) if event else None
        snapshot_components.append(
            {
                "group_key": group.group_key,
                "candidate_set_hash": group.candidate_set_hash,
                "event_id": event_id,
                "event_status": event.get("status") if event else None,
                "resolution_method": method,
                "state": state,
            }
        )
        views.append(
            {
                **group.payload(),
                "state": state,
                "current_event_id": event_id,
                "resolution_method": method,
                "selected_candidate_keys": list(selected),
                "stale_resolution": stale_resolution,
            }
        )

    return ConflictOverlay(
        collection_key=collection_key,
        snapshot_hash=digest(snapshot_components),
        groups=tuple(views),
        usable_record_ids=frozenset(usable),
        resolution_confirmed_record_ids=frozenset(resolution_confirmed),
        synthetic_items=tuple(synthetic),
        unresolved_count=unresolved,
        conflict_count=conflict_count,
        resolved_unknown_count=resolved_unknown,
        warnings=tuple(sorted(warnings)),
    )


def merge_candidate_items(candidates: Iterable[ConflictCandidate]) -> dict[str, Any]:
    candidates = tuple(candidates)
    if len(candidates) < 2:
        raise ClinicalDataConflictError("merge requires at least two candidates")
    if any(candidate.assertion is not CandidateAssertion.PRESENT for candidate in candidates):
        raise ClinicalDataConflictError("only PRESENT candidates can be merged")
    merged: dict[str, Any] = {}
    for candidate in candidates:
        for key, value in _semantic_item(candidate.item).items():
            if value in (None, "", [], {}):
                continue
            if key in merged and merged[key] != value:
                raise ClinicalDataConflictError(
                    f"candidate values conflict for field {key}"
                )
            merged[key] = value
    merged["record_id"] = None
    return merged
