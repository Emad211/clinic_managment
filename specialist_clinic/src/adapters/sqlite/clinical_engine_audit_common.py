"""Shared deterministic serialization for Clinical Engine v2 audit rows."""
from __future__ import annotations

import json
from typing import Any

from src.common.utils import iran_now


def now_text() -> str:
    return iran_now().isoformat(sep=" ", timespec="seconds")


def json_text(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def optional_json(value: Any | None) -> str | None:
    return None if value is None else json_text(value)
