"""Canonical Clinical Engine v2 snapshot construction and shadow capture."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any

from src.adapters.sqlite.clinical_engine_audit_repo import ClinicalEngineAuditRepository
from src.adapters.sqlite.clinical_engine_fact_repo import ClinicalEngineFactRepository
from src.domain.clinical_engine import FactSnapshot, RunStatus
from src.common.utils import IRAN_TZ
from src.services.clinical_engine.legacy_adapter import LegacyFactBundleAdapter


ENGINE_VERSION = "2.0.0-fact-shadow"


def _json_default(value: Any):
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, default=_json_default, ensure_ascii=False,
                      sort_keys=True, separators=(",", ":"), allow_nan=False)


def _iso(value: datetime) -> str:
    aware = value if value.tzinfo else value.replace(tzinfo=IRAN_TZ)
    return aware.isoformat(timespec="seconds")


def _fact_payload(fact, *, assessed_at: datetime) -> dict:
    source_types = {
        "laboratory": "laboratory", "clinician": "clinician", "derived": "derived",
        "patient": "patient", "caregiver": "caregiver", "device": "device",
        "accounting_bridge": "accounting_bridge",
    }
    source_type = source_types.get(fact.source.system, "system")
    conflict_state = {
        "NONE": "NONE", "PRESENT": "CONFIRMED", "UNKNOWN": "POSSIBLE",
        "POSSIBLE": "POSSIBLE", "CONFIRMED": "CONFIRMED", "RESOLVED": "RESOLVED",
    }.get(fact.conflict.value, "POSSIBLE")
    return {
        "schema_version": fact.schema_version,
        "fact_id": fact.fact_id,
        "patient_link_id": fact.patient_link_id,
        "encounter_key": fact.encounter_key,
        "kind": fact.kind.value,
        "key": fact.key,
        "status": fact.status.value,
        "value": fact.value,
        "unit": fact.unit,
        "reference_range": dict(fact.reference_range) if fact.reference_range else None,
        "effective_at": _iso(fact.effective_at),
        "recorded_at": _iso(fact.recorded_at),
        "source": {
            "type": source_type,
            "table": None if fact.source.system in source_types else fact.source.system,
            "record_id": fact.source.record_id,
            "recorded_by": fact.source.actor,
        },
        "verification": fact.verification.value,
        "freshness": {
            "state": fact.freshness.value,
            "max_age_days": None,
            "assessed_at": _iso(assessed_at),
        },
        "conflict": {
            "state": conflict_state,
            "group_key": None,
            "related_fact_ids": [],
            "resolution_note": None,
        },
        "derived_from": list(fact.derived_from),
        "warnings": list(fact.warnings),
    }


def snapshot_payload(snapshot: FactSnapshot, *, include_hash: bool = True) -> dict:
    payload = {
        "schema_version": snapshot.schema_version,
        "patient_link_id": snapshot.patient_link_id,
        "as_of_at": _iso(snapshot.as_of_at),
        "encounter_key": snapshot.encounter_key,
        "facts": [_fact_payload(fact, assessed_at=snapshot.as_of_at) for fact in snapshot.facts],
    }
    if include_hash:
        payload["content_hash"] = snapshot.content_hash
    return payload


class FactBuilder:
    def __init__(self, repository=None, adapter=None):
        self.repository = repository or ClinicalEngineFactRepository()
        self.adapter = adapter or LegacyFactBundleAdapter()

    def build(self, patient_link_id: int, *, as_of_at: datetime,
              encounter_key: str | None = None) -> FactSnapshot:
        if not isinstance(as_of_at, datetime):
            raise TypeError("as_of_at must be a datetime")
        bundle = self.repository.load_bundle(patient_link_id)
        facts = self.adapter.adapt(bundle, as_of_at=as_of_at)
        provisional = FactSnapshot(
            schema_version="2.0", patient_link_id=patient_link_id,
            as_of_at=as_of_at, facts=facts, content_hash="", encounter_key=encounter_key,
        )
        body = snapshot_payload(provisional, include_hash=False)
        content_hash = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
        return FactSnapshot(
            schema_version="2.0", patient_link_id=patient_link_id,
            as_of_at=as_of_at, facts=facts, content_hash=content_hash,
            encounter_key=encounter_key,
        )


class ShadowFactCapture:
    """Persist facts only in shadow mode; never evaluates or returns recommendations."""

    def __init__(self, repository=None, builder=None, audit=None):
        self.repository = repository or ClinicalEngineFactRepository()
        self.builder = builder or FactBuilder(repository=self.repository)
        self.audit = audit or ClinicalEngineAuditRepository()

    def capture(self, patient_link_id: int, *, as_of_at: datetime,
                encounter_key: str | None = None, created_by: str | None = None) -> str | None:
        if self.repository.get_mode() != "shadow":
            return None
        snapshot = self.builder.build(patient_link_id, as_of_at=as_of_at,
                                      encounter_key=encounter_key)
        payload = snapshot_payload(snapshot)
        run_id = self.audit.start_run(
            patient_link_id=patient_link_id, encounter_key=encounter_key,
            as_of_at=as_of_at.isoformat(sep=" ", timespec="seconds"),
            engine_version=ENGINE_VERSION, fact_snapshot=payload, created_by=created_by,
        )
        self.audit.complete_run(run_id, status=RunStatus.COMPLETED,
                                summary={"mode": "shadow", "evaluated_rules": 0,
                                         "recommendations": 0})
        return run_id
