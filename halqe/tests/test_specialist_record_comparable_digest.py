"""Canonical comparison digest tests used by semantic reuse warnings."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from clinical.specialist_record_import import _comparable_digest


def test_jsonb_wrapper_and_native_json_have_same_digest():
    native = {
        "items": [
            {"drug_name": "داروی تست", "dose": 5, "active": True},
        ]
    }
    assert _comparable_digest(Jsonb(native)) == _comparable_digest(native)


def test_same_instant_with_tehran_and_utc_offsets_has_same_digest():
    tehran = datetime(2025, 1, 1, 10, 0, tzinfo=ZoneInfo("Asia/Tehran"))
    utc = tehran.astimezone(UTC)
    assert _comparable_digest({"at": tehran}) == _comparable_digest({"at": utc})


def test_equivalent_numeric_types_have_same_digest():
    values = [5, 5.0, Decimal("5.000")]
    digests = {_comparable_digest({"value": value}) for value in values}
    assert len(digests) == 1
