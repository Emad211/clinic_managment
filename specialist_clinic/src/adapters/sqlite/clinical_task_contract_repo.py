"""Repository for immutable task contracts and canonical outcome ingestion."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
from typing import Any

from src.adapters.sqlite.core import get_db

_IRAN_TZ = timezone(timedelta(hours=3, minutes=30))
_VERIFICATION_RANK = {"UNVERIFIED": 1, "PROVISIONAL": 2, "CONFIRMED": 3}
_ALLOWED_TYPES = {
    "OBSERVATION",
    "PATIENT_REPORTED",
    "ENCOUNTER_COMPLETED",
    "PROCEDURE_COMPLETED",
    "LAB_COMPLETED",
    "OTHER",
}


class ClinicalTaskContractError(RuntimeError):
    pass


def _text(value: datetime | str | None = None) -> str:
    if value is None:
        parsed = datetime.now(_IRAN_TZ)
    elif isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_IRAN_TZ).replace(tzinfo=None)
    return parsed.isoformat(sep=" ", timespec="seconds")


def _hash(payload: dict[str, Any]) -> str:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def normalize_contract(raw: dict, *, due_at: str) -> dict:
    allowed = sorted(
        {
            str(value).strip().upper()
            for value in raw.get("allowed_outcome_types") or []
            if str(value).strip()
        }
    )
    if not allowed or any(value not in _ALLOWED_TYPES for value in allowed):
        raise ClinicalTaskContractError("invalid allowed_outcome_types")
    required = sorted(
        {
            str(value).strip()
            for value in raw.get("required_fact_keys") or []
            if str(value).strip()
        }
    )
    verification = str(
        raw.get("minimum_verification") or "CONFIRMED"
    ).strip().upper()
    if verification not in _VERIFICATION_RANK:
        raise ClinicalTaskContractError("invalid minimum_verification")
    ingestion = str(raw.get("canonical_ingestion") or "NONE").strip().upper()
    if ingestion not in {"NONE", "OPTIONAL", "REQUIRED"}:
        raise ClinicalTaskContractError("invalid canonical_ingestion")
    urgency = str(raw.get("urgency") or "ROUTINE").strip().upper()
    if urgency not in {"ROUTINE", "PRIORITY", "URGENT", "CRITICAL"}:
        raise ClinicalTaskContractError("invalid task urgency")
    if ingestion == "REQUIRED" and not required:
        raise ClinicalTaskContractError(
            "canonical_ingestion=REQUIRED needs required_fact_keys"
        )
    return {
        "contract_version": "1.0",
        "due_at": _text(due_at),
        "urgency": urgency,
        "allowed_outcome_types": allowed,
        "required_fact_keys": required,
        "minimum_verification": verification,
        "canonical_ingestion": ingestion,
        "requires_acknowledgement": bool(
            raw.get("requires_acknowledgement", False)
        ),
    }


class ClinicalTaskContractRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    @staticmethod
    def _decode(row) -> dict | None:
        if not row:
            return None
        item = dict(row)
        item["allowed_outcome_types"] = json.loads(
            item.pop("allowed_outcome_types_json")
        )
        item["required_fact_keys"] = json.loads(
            item.pop("required_fact_keys_json")
        )
        item["requires_acknowledgement"] = bool(
            item["requires_acknowledgement"]
        )
        return item

    def get(self, task_id: int) -> dict | None:
        row = self._db().execute(
            "SELECT * FROM clinical_task_contracts WHERE task_id=?",
            (int(task_id),),
        ).fetchone()
        return self._decode(row)

    def create_once(
        self,
        *,
        task_id: int,
        source_recommendation_event_id: int,
        contract: dict,
        created_by: str,
        created_at: datetime | str | None = None,
        commit: bool = True,
    ) -> dict:
        existing = self.get(task_id)
        normalized = normalize_contract(contract, due_at=contract["due_at"])
        if existing:
            comparable = {
                key: existing[key]
                for key in (
                    "contract_version",
                    "due_at",
                    "urgency",
                    "allowed_outcome_types",
                    "required_fact_keys",
                    "minimum_verification",
                    "canonical_ingestion",
                    "requires_acknowledgement",
                )
            }
            if comparable != normalized:
                raise ClinicalTaskContractError(
                    "clinical task already has another immutable contract"
                )
            return existing
        actor = str(created_by or "").strip()
        if not actor:
            raise ClinicalTaskContractError("created_by is required")
        timestamp = _text(created_at)
        payload = {
            "task_id": int(task_id),
            **normalized,
            "contract_origin": "RULE_RECOMMENDATION",
            "source_recommendation_event_id": int(
                source_recommendation_event_id
            ),
            "created_by": actor,
            "created_at": timestamp,
        }
        db = self._db()
        db.execute(
            """INSERT INTO clinical_task_contracts
               (task_id, contract_version, contract_origin, due_at, urgency,
                allowed_outcome_types_json, required_fact_keys_json,
                minimum_verification, canonical_ingestion,
                requires_acknowledgement, source_recommendation_event_id,
                created_by, created_at, content_hash)
               VALUES (?, '1.0', 'RULE_RECOMMENDATION', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                int(task_id),
                normalized["due_at"],
                normalized["urgency"],
                json.dumps(
                    normalized["allowed_outcome_types"], separators=(",", ":")
                ),
                json.dumps(
                    normalized["required_fact_keys"], separators=(",", ":")
                ),
                normalized["minimum_verification"],
                normalized["canonical_ingestion"],
                int(normalized["requires_acknowledgement"]),
                int(source_recommendation_event_id),
                actor,
                timestamp,
                _hash(payload),
            ),
        )
        if commit:
            db.commit()
        return self.get(task_id)

    def validate_outcome(
        self,
        *,
        task_id: int,
        outcome_type: str,
        fact_key: str | None,
        verification: str,
        value: Any,
    ) -> dict:
        contract = self.get(task_id)
        if not contract:
            raise ClinicalTaskContractError("clinical task contract is missing")
        kind = str(outcome_type or "").strip().upper()
        if kind not in contract["allowed_outcome_types"]:
            raise ClinicalTaskContractError(
                "outcome type is not allowed by task contract"
            )
        level = str(verification or "").strip().upper()
        if _VERIFICATION_RANK.get(level, 0) < _VERIFICATION_RANK[
            contract["minimum_verification"]
        ]:
            raise ClinicalTaskContractError(
                "outcome verification is below task contract"
            )
        key = str(fact_key or "").strip() or None
        required = contract["required_fact_keys"]
        if required and key not in required:
            raise ClinicalTaskContractError(
                "outcome fact_key does not satisfy task contract"
            )
        if contract["canonical_ingestion"] == "REQUIRED":
            if key is None or value in {None, ""}:
                raise ClinicalTaskContractError(
                    "canonical task outcome requires fact_key and value"
                )
            if not (key.startswith("observation.") or key.startswith("lab.")):
                raise ClinicalTaskContractError(
                    "required canonical outcome has unsupported fact_key"
                )
        return contract

    def canonical_link(self, outcome_event_id: int) -> dict | None:
        row = self._db().execute(
            """SELECT * FROM clinical_outcome_canonical_links
               WHERE outcome_event_id=?""",
            (int(outcome_event_id),),
        ).fetchone()
        return dict(row) if row else None

    def ingest_if_applicable(
        self,
        *,
        task_id: int,
        outcome_event_id: int,
        patient_link_id: int,
        fact_key: str | None,
        value: Any,
        unit: str | None,
        observed_at: str,
        actor_username: str,
        note: str | None,
        contract: dict,
    ) -> dict | None:
        ingestion = contract["canonical_ingestion"]
        key = str(fact_key or "").strip()
        if ingestion == "NONE" or not key or value in {None, ""}:
            if ingestion == "REQUIRED":
                raise ClinicalTaskContractError(
                    "required canonical outcome was not ingestible"
                )
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            if ingestion == "REQUIRED":
                raise ClinicalTaskContractError(
                    "canonical observation value must be numeric"
                ) from exc
            return None

        db = self._db()
        source_note = (
            f"clinical task #{int(task_id)} outcome #{int(outcome_event_id)}"
            + (f" — {note}" if note else "")
        )
        if key.startswith("observation."):
            concept = key.split(".", 1)[1]
            cursor = db.execute(
                """INSERT INTO vital_readings
                   (patient_link_id, type, value, unit, measured_at,
                    source, notes, recorded_by)
                   VALUES (?, ?, ?, ?, ?, 'clinical_task_outcome', ?, ?)""",
                (
                    int(patient_link_id),
                    concept,
                    numeric,
                    unit,
                    observed_at,
                    source_note,
                    actor_username,
                ),
            )
            record_type = "VITAL"
        elif key.startswith("lab."):
            concept = key.split(".", 1)[1]
            cursor = db.execute(
                """INSERT INTO lab_results
                   (patient_link_id, test_name, test_key, value, unit,
                    taken_at, notes, recorded_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(patient_link_id),
                    concept,
                    concept,
                    numeric,
                    unit,
                    observed_at,
                    source_note,
                    actor_username,
                ),
            )
            record_type = "LAB"
        else:
            if ingestion == "REQUIRED":
                raise ClinicalTaskContractError(
                    "unsupported canonical fact namespace"
                )
            return None
        payload = {
            "outcome_event_id": int(outcome_event_id),
            "task_id": int(task_id),
            "record_type": record_type,
            "record_id": int(cursor.lastrowid),
            "fact_key": key,
            "created_at": _text(),
        }
        db.execute(
            """INSERT INTO clinical_outcome_canonical_links
               (outcome_event_id, task_id, record_type, record_id,
                fact_key, created_at, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                payload["outcome_event_id"],
                payload["task_id"],
                payload["record_type"],
                payload["record_id"],
                payload["fact_key"],
                payload["created_at"],
                _hash(payload),
            ),
        )
        return self.canonical_link(outcome_event_id)
