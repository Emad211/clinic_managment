"""Immutable context contract for every Clinical Engine evaluation.

An appointment is an administrative plan, not proof that a clinical encounter happened.
Every run therefore declares either an exact encounter event or an explicit longitudinal
review context.  The canonical context hash is part of current-run identity.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Mapping

from src.common.utils import IRAN_TZ


_CONTEXT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{2,199}$")
_REASON_CODE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,79}$")


class EvaluationMode(StrEnum):
    ENCOUNTER = "ENCOUNTER"
    LONGITUDINAL = "LONGITUDINAL"


class CareSetting(StrEnum):
    PRIMARY_CARE = "primary_care"
    SPECIALTY_CLINIC = "specialty_clinic"
    URGENT_CARE = "urgent_care"
    TELEHEALTH = "telehealth"


class EncounterType(StrEnum):
    OFFICE_VISIT = "office_visit"
    FOLLOWUP = "followup"
    URGENT_VISIT = "urgent_visit"
    TELEVISIT = "televisit"
    MEDICATION_REVIEW = "medication_review"
    PREVENTIVE_VISIT = "preventive_visit"
    CHRONIC_CARE_REVIEW = "chronic_care_review"
    LONGITUDINAL_REVIEW = "longitudinal_review"


class EncounterStatus(StrEnum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"
    ENTERED_IN_ERROR = "ENTERED_IN_ERROR"


class EncounterEventType(StrEnum):
    OPENED = "OPENED"
    UPDATED = "UPDATED"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"
    ENTERED_IN_ERROR = "ENTERED_IN_ERROR"


class ClinicalContextError(ValueError):
    """The supplied evaluation context is incomplete or internally inconsistent."""


def local_naive(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("context timestamps must be datetime values")
    if value.tzinfo is not None:
        return value.astimezone(IRAN_TZ).replace(tzinfo=None)
    return value


def iso_local(value: datetime) -> str:
    return local_naive(value).isoformat(sep=" ", timespec="seconds")


def canonical_context_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def context_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_context_json(value).encode("utf-8")).hexdigest()


def normalize_reason_codes(values) -> tuple[str, ...]:
    result = []
    for value in values or ():
        code = str(value or "").strip().upper()
        if not code or not _REASON_CODE.fullmatch(code):
            raise ClinicalContextError(f"invalid clinical reason code: {value!r}")
        result.append(code)
    if len(result) > 20:
        raise ClinicalContextError("at most 20 reason codes are allowed")
    if len(result) != len(set(result)):
        raise ClinicalContextError("clinical reason codes must be unique")
    return tuple(sorted(result))


@dataclass(frozen=True, slots=True)
class ClinicalEvaluationContext:
    schema_version: str
    patient_link_id: int
    context_key: str
    evaluation_mode: EvaluationMode
    care_setting: CareSetting
    encounter_type: EncounterType
    assessment_date: str
    effective_at: datetime
    recorded_at: datetime
    source: str
    content_hash: str
    encounter_key: str | None = None
    encounter_event_id: int | None = None
    encounter_status: EncounterStatus | None = None
    appointment_id: int | None = None
    reason_codes: tuple[str, ...] = ()
    chief_complaint: str | None = None
    responsible_actor: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ClinicalContextError("unsupported clinical context schema version")
        if int(self.patient_link_id) <= 0:
            raise ClinicalContextError("patient_link_id must be positive")
        if not _CONTEXT_KEY.fullmatch(str(self.context_key or "")):
            raise ClinicalContextError("invalid context_key")
        effective = local_naive(self.effective_at)
        recorded = local_naive(self.recorded_at)
        if effective > recorded:
            raise ClinicalContextError("context effective_at cannot exceed recorded_at")
        try:
            assessment = datetime.fromisoformat(self.assessment_date).date()
        except (TypeError, ValueError) as exc:
            raise ClinicalContextError("assessment_date must be an ISO date") from exc
        if assessment != recorded.date():
            raise ClinicalContextError(
                "assessment_date must equal the Tehran-local recorded date"
            )
        if not str(self.source or "").strip():
            raise ClinicalContextError("context source is required")
        if self.chief_complaint and len(self.chief_complaint.strip()) > 1000:
            raise ClinicalContextError("chief complaint is too long")
        if self.responsible_actor and len(self.responsible_actor.strip()) > 200:
            raise ClinicalContextError("responsible actor is too long")
        normalize_reason_codes(self.reason_codes)
        if self.evaluation_mode is EvaluationMode.LONGITUDINAL:
            if self.encounter_key is not None or self.encounter_event_id is not None:
                raise ClinicalContextError(
                    "longitudinal context cannot reference an encounter event"
                )
            if self.encounter_status is not None or self.appointment_id is not None:
                raise ClinicalContextError(
                    "longitudinal context cannot carry encounter lifecycle fields"
                )
            if self.encounter_type is not EncounterType.LONGITUDINAL_REVIEW:
                raise ClinicalContextError(
                    "longitudinal context requires longitudinal_review"
                )
        else:
            if not self.encounter_key or self.encounter_event_id is None:
                raise ClinicalContextError(
                    "encounter context requires encounter_key and encounter_event_id"
                )
            if self.encounter_status not in {
                EncounterStatus.OPEN,
                EncounterStatus.FINALIZED,
            }:
                raise ClinicalContextError(
                    "only OPEN or FINALIZED encounters are executable"
                )
            if self.encounter_type is EncounterType.LONGITUDINAL_REVIEW:
                raise ClinicalContextError(
                    "encounter context cannot use longitudinal_review"
                )
        expected = context_digest(self.identity_payload())
        if self.content_hash != expected:
            raise ClinicalContextError("clinical context hash does not match content")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "patient_link_id": int(self.patient_link_id),
            "context_key": self.context_key,
            "evaluation_mode": self.evaluation_mode.value,
            "care_setting": self.care_setting.value,
            "encounter_type": self.encounter_type.value,
            "assessment_date": self.assessment_date,
            "effective_at": iso_local(self.effective_at),
            "recorded_at": iso_local(self.recorded_at),
            "source": self.source,
            "encounter_key": self.encounter_key,
            "encounter_event_id": self.encounter_event_id,
            "encounter_status": (
                self.encounter_status.value if self.encounter_status else None
            ),
            "appointment_id": self.appointment_id,
            "reason_codes": list(self.reason_codes),
            "chief_complaint": self.chief_complaint,
            "responsible_actor": self.responsible_actor,
        }

    def payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "content_hash": self.content_hash}


def make_context(**kwargs) -> ClinicalEvaluationContext:
    provisional = ClinicalEvaluationContext.__new__(ClinicalEvaluationContext)
    values = {
        "schema_version": "1.0",
        "reason_codes": (),
        "chief_complaint": None,
        "responsible_actor": None,
        "encounter_key": None,
        "encounter_event_id": None,
        "encounter_status": None,
        "appointment_id": None,
        **kwargs,
        "content_hash": "",
    }
    for field, value in values.items():
        object.__setattr__(provisional, field, value)
    payload = provisional.identity_payload()
    return replace(provisional, content_hash=context_digest(payload))


def longitudinal_context(
    patient_link_id: int,
    *,
    as_of_at: datetime,
    care_setting: CareSetting = CareSetting.SPECIALTY_CLINIC,
    responsible_actor: str | None = None,
) -> ClinicalEvaluationContext:
    recorded = local_naive(as_of_at)
    assessment_date = recorded.date().isoformat()
    return make_context(
        patient_link_id=int(patient_link_id),
        context_key=f"longitudinal:{int(patient_link_id)}:{assessment_date}",
        evaluation_mode=EvaluationMode.LONGITUDINAL,
        care_setting=CareSetting(care_setting),
        encounter_type=EncounterType.LONGITUDINAL_REVIEW,
        assessment_date=assessment_date,
        effective_at=recorded.replace(hour=0, minute=0, second=0, microsecond=0),
        recorded_at=recorded,
        source="runtime-longitudinal-review",
        responsible_actor=(responsible_actor or "").strip() or None,
    )


def context_from_payload(payload: Mapping[str, Any]) -> ClinicalEvaluationContext:
    try:
        return ClinicalEvaluationContext(
            schema_version=str(payload["schema_version"]),
            patient_link_id=int(payload["patient_link_id"]),
            context_key=str(payload["context_key"]),
            evaluation_mode=EvaluationMode(payload["evaluation_mode"]),
            care_setting=CareSetting(payload["care_setting"]),
            encounter_type=EncounterType(payload["encounter_type"]),
            assessment_date=str(payload["assessment_date"]),
            effective_at=datetime.fromisoformat(str(payload["effective_at"])),
            recorded_at=datetime.fromisoformat(str(payload["recorded_at"])),
            source=str(payload["source"]),
            content_hash=str(payload["content_hash"]),
            encounter_key=payload.get("encounter_key"),
            encounter_event_id=(
                int(payload["encounter_event_id"])
                if payload.get("encounter_event_id") is not None
                else None
            ),
            encounter_status=(
                EncounterStatus(payload["encounter_status"])
                if payload.get("encounter_status") is not None
                else None
            ),
            appointment_id=(
                int(payload["appointment_id"])
                if payload.get("appointment_id") is not None
                else None
            ),
            reason_codes=normalize_reason_codes(payload.get("reason_codes") or ()),
            chief_complaint=(
                str(payload["chief_complaint"]).strip()
                if payload.get("chief_complaint")
                else None
            ),
            responsible_actor=(
                str(payload["responsible_actor"]).strip()
                if payload.get("responsible_actor")
                else None
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ClinicalContextError):
            raise
        raise ClinicalContextError("invalid clinical context payload") from exc
