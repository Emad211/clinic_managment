"""Shared vocabulary and time helpers for clinical flag persistence."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from src.common.utils import IRAN_TZ, iran_now, parse_datetime
from src.domain.clinical_engine.flag_history import parse_legacy_options


CATEGORY_LABELS = {
    "cardiac": "قلبی-عروقی",
    "renal": "کلیه",
    "risk": "ریسک",
    "hepatic": "کبد",
    "repro": "باروری",
    "lifestyle": "سبک زندگی",
    "functional": "وضعیت عملکردی",
    "history": "سابقه",
    "exam": "معاینات",
    "other": "سایر",
}
CATEGORY_ORDER = (
    "cardiac",
    "renal",
    "risk",
    "hepatic",
    "repro",
    "lifestyle",
    "functional",
    "history",
    "exam",
    "other",
)


class ClinicalFlagConflict(RuntimeError):
    """The submitted form was based on a superseded event or definition."""


class ClinicalFlagValidationError(ValueError):
    """A submitted flag state, value or source is invalid."""


def parsed_time(value: datetime | str | None = None) -> datetime:
    parsed = parse_datetime(value) if value is not None else iran_now()
    if parsed is None:
        raise ClinicalFlagValidationError("clinical flag timestamp is invalid")
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(IRAN_TZ).replace(tzinfo=None)
    return parsed.replace(microsecond=0)


def text_time(value: datetime | str | None = None) -> str:
    return parsed_time(value).strftime("%Y-%m-%d %H:%M:%S")


def option_list(row: Mapping[str, Any]) -> list[dict[str, str]]:
    source = row.get("options_json") or row.get("options")
    return [dict(item) for item in parse_legacy_options(source)]
