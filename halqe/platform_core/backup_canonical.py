from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
import hashlib
import ipaddress
import json
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID


class BackupVerificationError(RuntimeError):
    """Fail-closed backup-manifest or restore-verification error."""


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> Any:
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, Decimal):
        return {"decimal": str(value.normalize())}
    if isinstance(value, float):
        return {"float": repr(value)}
    if isinstance(value, datetime):
        rendered = (
            value.replace(tzinfo=UTC)
            if value.tzinfo is None
            else value.astimezone(UTC)
        )
        return {"datetime_utc": rendered.isoformat(timespec="microseconds")}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    if isinstance(value, time):
        return {"time": value.isoformat(timespec="microseconds")}
    if isinstance(value, UUID):
        return {"uuid": str(value)}
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return {
            "bytes_length": len(raw),
            "bytes_sha256": hashlib.sha256(raw).hexdigest(),
        }
    if isinstance(value, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return {"ip": str(value)}
    if isinstance(value, dict):
        return {
            str(key): canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    if isinstance(value, set):
        rendered = [canonical(item) for item in value]
        return sorted(rendered, key=lambda item: stable_json(item))
    return {"type": type(value).__name__, "text": str(value)}


def stable_json(value: Any) -> str:
    return json.dumps(
        canonical(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def digest_records(records: Iterable[Any]) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    for record in records:
        payload = stable_json(record).encode("utf-8")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
        count += 1
    return count, digest.hexdigest()


def aggregate_digest(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()
