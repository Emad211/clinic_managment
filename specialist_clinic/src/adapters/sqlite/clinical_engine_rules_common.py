"""Shared primitives for immutable Clinical Engine v2 rule persistence."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from src.common.utils import iran_now


class ClinicalEngineStorageConflict(ValueError):
    """A version identifier was reused with different immutable content."""


def now_text() -> str:
    return iran_now().isoformat(sep=" ", timespec="seconds")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
