"""Pure contracts for typed, longitudinal clinical flags.

A flag is not a nullable string.  The engine must distinguish an explicit negative
answer from unknown information and from a question that was never asked.  This
module contains only deterministic parsing/validation helpers; it has no Flask or
SQLite dependency.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
import hashlib
import json
from typing import Any, Iterable, Mapping


class ClinicalFlagState(StrEnum):
    PRESENT = "PRESENT"
    UNKNOWN = "UNKNOWN"
    NOT_ASKED = "NOT_ASKED"


class ClinicalFlagValueError(ValueError):
    """A flag value cannot be represented by its catalog definition."""


_FLAG_TYPES = frozenset({"bool", "enum", "date", "text"})
_TRUE_TEXT = frozenset({"1", "true", "yes", "on"})
_FALSE_TEXT = frozenset({"0", "false", "no", "off"})


def normalize_flag_type(value: Any) -> str:
    normalized = str(value or "bool").strip().lower()
    aliases = {"boolean": "bool", "str": "text", "string": "text"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in _FLAG_TYPES:
        raise ClinicalFlagValueError(f"unsupported flag_type: {value!r}")
    return normalized


def _normalized_option(item: Any) -> dict[str, str]:
    if isinstance(item, Mapping):
        value = str(item.get("value", "")).strip()
        label = str(item.get("label", value)).strip()
    elif isinstance(item, (list, tuple)) and len(item) == 2:
        value, label = (str(part).strip() for part in item)
    else:
        text = str(item or "").strip()
        if "|" in text:
            value, label = (part.strip() for part in text.split("|", 1))
        else:
            value = label = text
    if not value:
        raise ClinicalFlagValueError("enum option value cannot be blank")
    if not label:
        label = value
    return {"value": value, "label": label}


def parse_legacy_options(source: Any) -> tuple[dict[str, str], ...]:
    """Parse canonical JSON or the historical ``value|label,...`` format."""
    if source is None or source == "":
        return ()
    raw: Any = source
    if isinstance(source, str):
        text = source.strip()
        if not text:
            return ()
        if text.startswith("["):
            try:
                raw = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ClinicalFlagValueError("invalid enum options JSON") from exc
        else:
            raw = [part for part in text.split(",") if part.strip()]
    if not isinstance(raw, (list, tuple)):
        raise ClinicalFlagValueError("enum options must be an array")

    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        option = _normalized_option(item)
        if option["value"] in seen:
            raise ClinicalFlagValueError(
                f"duplicate enum option value: {option['value']!r}"
            )
        seen.add(option["value"])
        result.append(option)
    return tuple(result)


def canonical_options_json(source: Any, *, flag_type: str = "enum") -> str:
    normalized_type = normalize_flag_type(flag_type)
    options = parse_legacy_options(source) if normalized_type == "enum" else ()
    if normalized_type == "enum" and not options:
        raise ClinicalFlagValueError("enum flags require at least one option")
    return json.dumps(
        list(options),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def flag_definition_hash(
    flag_key: Any,
    flag_type: Any,
    options_json: Any,
    is_active: Any,
    definition_version: Any = 1,
) -> str:
    key = str(flag_key or "").strip().lower()
    if not key:
        raise ClinicalFlagValueError("flag_key cannot be blank")
    normalized_type = normalize_flag_type(flag_type)
    try:
        normalized_version = int(definition_version)
    except (TypeError, ValueError) as exc:
        raise ClinicalFlagValueError(
            "definition_version must be a positive integer"
        ) from exc
    if normalized_version < 1:
        raise ClinicalFlagValueError(
            "definition_version must be a positive integer"
        )
    canonical_options = canonical_options_json(
        options_json,
        flag_type=normalized_type,
    )
    body = {
        "schema_version": "1.0",
        "flag_key": key,
        "flag_type": normalized_type,
        "options": json.loads(canonical_options),
        "is_active": bool(is_active),
        "definition_version": normalized_version,
    }
    canonical = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    text = str(value or "").strip().lower()
    if text in _TRUE_TEXT:
        return True
    if text in _FALSE_TEXT:
        return False
    raise ClinicalFlagValueError("boolean flag value must be true or false")


def normalize_present_value(
    value: Any,
    *,
    flag_type: str,
    options_json: Any = None,
) -> Any:
    normalized_type = normalize_flag_type(flag_type)
    if normalized_type == "bool":
        return _bool_value(value)
    if normalized_type == "enum":
        text = str(value or "").strip()
        allowed = {
            option["value"]
            for option in parse_legacy_options(options_json)
        }
        if text not in allowed:
            raise ClinicalFlagValueError(
                f"enum value {text!r} is not in the active catalog"
            )
        return text
    if normalized_type == "date":
        text = str(value or "").strip()
        try:
            parsed = date.fromisoformat(text)
        except ValueError as exc:
            raise ClinicalFlagValueError(
                "date flag value must be ISO YYYY-MM-DD"
            ) from exc
        return parsed.isoformat()
    text = " ".join(str(value or "").split())
    if not text:
        raise ClinicalFlagValueError("text flag value cannot be blank")
    if len(text) > 2000:
        raise ClinicalFlagValueError("text flag value exceeds 2000 characters")
    return text


def encode_flag_value(
    state: ClinicalFlagState | str,
    value: Any,
    *,
    flag_type: str,
    options_json: Any = None,
) -> str | None:
    normalized_state = ClinicalFlagState(state)
    if normalized_state is not ClinicalFlagState.PRESENT:
        if value is not None and value != "":
            raise ClinicalFlagValueError(
                f"{normalized_state.value} must not carry a value"
            )
        return None
    normalized = normalize_present_value(
        value,
        flag_type=flag_type,
        options_json=options_json,
    )
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def decode_flag_value(
    state: ClinicalFlagState | str,
    value_json: str | None,
    *,
    flag_type: str,
    options_json: Any = None,
) -> Any:
    normalized_state = ClinicalFlagState(state)
    if normalized_state is not ClinicalFlagState.PRESENT:
        if value_json is not None:
            raise ClinicalFlagValueError(
                f"{normalized_state.value} must not carry value_json"
            )
        return None
    if value_json is None:
        raise ClinicalFlagValueError("PRESENT requires value_json")
    try:
        raw = json.loads(value_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ClinicalFlagValueError("invalid flag value JSON") from exc
    return normalize_present_value(
        raw,
        flag_type=flag_type,
        options_json=options_json,
    )


__all__ = [
    "ClinicalFlagState",
    "ClinicalFlagValueError",
    "canonical_options_json",
    "decode_flag_value",
    "encode_flag_value",
    "flag_definition_hash",
    "normalize_flag_type",
    "normalize_present_value",
    "parse_legacy_options",
]


_IRAN_TZ = timezone(timedelta(hours=3, minutes=30))


def _event_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value is None:
        return None
    else:
        try:
            parsed = datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_IRAN_TZ).replace(tzinfo=None)
    return parsed.replace(microsecond=0)


def project_flag_events(
    events: Iterable[Mapping[str, Any]],
    catalog_rows: Iterable[Mapping[str, Any]],
    *,
    as_of_at: Any,
    knowledge_at: Any | None = None,
) -> dict[str, dict[str, Any]]:
    """Project bitemporal flag state for every catalog definition.

    ``effective_at`` answers when a state is clinically true; ``recorded_at``
    answers when the system learned it.  A correction recorded later never
    rewrites a historical snapshot whose knowledge cutoff predates it.
    """
    effective_cutoff = _event_time(as_of_at)
    knowledge_cutoff = _event_time(
        knowledge_at if knowledge_at is not None else as_of_at
    )
    if effective_cutoff is None or knowledge_cutoff is None:
        raise ClinicalFlagValueError("flag projection cutoff is invalid")

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for event in events:
        effective = _event_time(event.get("effective_at"))
        recorded = _event_time(event.get("recorded_at"))
        if (
            effective is None
            or recorded is None
            or effective > effective_cutoff
            or recorded > knowledge_cutoff
        ):
            continue
        grouped.setdefault(str(event.get("flag_key") or ""), []).append(event)

    projected: dict[str, dict[str, Any]] = {}
    for raw_catalog in catalog_rows:
        catalog = dict(raw_catalog)
        key = str(catalog.get("flag_key") or "")
        candidates = grouped.get(key, [])
        event = max(
            candidates,
            key=lambda row: (
                _event_time(row.get("recorded_at")),
                int(row.get("id") or 0),
            ),
        ) if candidates else None
        warnings: list[str] = []
        if event is None:
            state = ClinicalFlagState.NOT_ASKED
            value = None
            verification = "UNVERIFIED"
        else:
            try:
                event_type = normalize_flag_type(event.get("flag_type"))
                catalog_type = normalize_flag_type(catalog.get("flag_type"))
            except ClinicalFlagValueError:
                state = ClinicalFlagState.UNKNOWN
                value = None
                verification = "UNVERIFIED"
                warnings.append("FLAG_EVENT_VALUE_INVALID")
            else:
                if (
                    str(event.get("definition_hash") or "")
                    != str(catalog.get("definition_hash") or "")
                    or event_type != catalog_type
                ):
                    state = ClinicalFlagState.UNKNOWN
                    value = None
                    verification = "UNVERIFIED"
                    warnings.append(
                        "FLAG_DEFINITION_CHANGED_REVIEW_REQUIRED"
                    )
                else:
                    try:
                        state = ClinicalFlagState(event.get("status"))
                        value = decode_flag_value(
                            state,
                            event.get("value_json"),
                            flag_type=catalog_type,
                            options_json=catalog.get("options_json"),
                        )
                        verification = str(
                            event.get("verification") or "UNVERIFIED"
                        )
                    except (ValueError, ClinicalFlagValueError):
                        state = ClinicalFlagState.UNKNOWN
                        value = None
                        verification = "UNVERIFIED"
                        warnings.append("FLAG_EVENT_VALUE_INVALID")
        projected[key] = {
            "catalog": catalog,
            "event": dict(event) if event is not None else None,
            "event_id": int(event["id"]) if event is not None else None,
            "state": state.value,
            "value": value,
            "verification": verification,
            "warnings": tuple(sorted(set(warnings))),
            "effective_at": event.get("effective_at") if event else as_of_at,
            "recorded_at": event.get("recorded_at") if event else as_of_at,
        }
    return projected


__all__.append("project_flag_events")
