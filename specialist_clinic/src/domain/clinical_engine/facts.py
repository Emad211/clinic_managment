"""Immutable canonical fact contracts; population is deferred to PR-04."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from .enums import (
    ConflictStatus,
    FactKind,
    FactStatus,
    FreshnessStatus,
    VerificationStatus,
)


@dataclass(frozen=True, slots=True)
class FactSource:
    system: str
    record_id: str
    actor: str | None = None


@dataclass(frozen=True, slots=True)
class ClinicalFact:
    schema_version: str
    fact_id: str
    patient_link_id: int
    kind: FactKind
    key: str
    status: FactStatus
    effective_at: datetime
    recorded_at: datetime
    source: FactSource
    verification: VerificationStatus
    freshness: FreshnessStatus
    conflict: ConflictStatus
    value: Any = None
    unit: str | None = None
    encounter_key: str | None = None
    reference_range: Mapping[str, Any] | None = None
    derived_from: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FactSnapshot:
    schema_version: str
    patient_link_id: int
    as_of_at: datetime
    facts: tuple[ClinicalFact, ...]
    content_hash: str
    encounter_key: str | None = None
    # Monotonic revision captured from the same SQLite read snapshot as the facts.
    # It is the runtime contract that prevents an older audited run from being
    # presented after the patient record has changed.
    clinical_data_revision: int = 0
