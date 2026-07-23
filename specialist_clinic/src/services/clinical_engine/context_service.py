"""Application boundary for resolving the context attached to an engine run."""
from __future__ import annotations

from datetime import datetime

from src.adapters.sqlite.clinical_encounter_repo import (
    ClinicalEncounterConflict,
    ClinicalEncounterRepository,
)
from src.common.utils import iran_now, parse_datetime
from src.domain.clinical_engine.context import (
    CareSetting,
    ClinicalContextError,
    ClinicalEvaluationContext,
    EncounterStatus,
    EncounterType,
    EvaluationMode,
    assessment_midnight,
    context_from_payload,
    local_naive,
    longitudinal_context,
    make_context,
)


class ClinicalContextStale(RuntimeError):
    pass


class ClinicalEvaluationContextService:
    def __init__(self, *, encounters=None, clock=None):
        self.encounters = encounters or ClinicalEncounterRepository()
        self.clock = clock or iran_now

    def longitudinal(
        self,
        patient_link_id: int,
        *,
        assessed_at: datetime | None = None,
        responsible_actor: str | None = None,
    ) -> ClinicalEvaluationContext:
        return longitudinal_context(
            patient_link_id,
            as_of_at=assessed_at or self.clock(),
            responsible_actor=responsible_actor,
        )

    def encounter(
        self,
        patient_link_id: int,
        encounter_event_id: int,
        *,
        assessed_at: datetime | None = None,
    ) -> ClinicalEvaluationContext:
        event = self.encounters.get_event(encounter_event_id)
        if not event or int(event["patient_link_id"]) != int(patient_link_id):
            raise ClinicalContextError("encounter does not belong to patient")
        current = self.encounters.current(str(event["encounter_key"]))
        if not current or int(current["id"]) != int(event["id"]):
            raise ClinicalEncounterConflict("encounter event is no longer current")
        status = EncounterStatus(event["status"])
        if status not in {EncounterStatus.OPEN, EncounterStatus.FINALIZED}:
            raise ClinicalContextError("encounter is not executable")

        assessment = assessment_midnight(assessed_at or self.clock())
        event_recorded = local_naive(
            parse_datetime(event["recorded_at"]) or assessment
        )
        recorded = max(assessment, event_recorded)
        return make_context(
            patient_link_id=int(event["patient_link_id"]),
            context_key=(
                f"encounter:{event['encounter_key']}:{assessment.date().isoformat()}"
            ),
            evaluation_mode=EvaluationMode.ENCOUNTER,
            care_setting=CareSetting(event["care_setting"]),
            encounter_type=EncounterType(event["encounter_type"]),
            assessment_date=recorded.date().isoformat(),
            effective_at=parse_datetime(event["effective_at"]) or recorded,
            recorded_at=recorded,
            source="clinical-encounter-event",
            encounter_key=str(event["encounter_key"]),
            encounter_event_id=int(event["id"]),
            encounter_status=status,
            appointment_id=(
                int(event["appointment_id"])
                if event.get("appointment_id") is not None
                else None
            ),
            reason_codes=tuple(event["reason_codes"]),
            chief_complaint=event.get("chief_complaint"),
            responsible_actor=event.get("responsible_actor"),
        )

    def assert_current(
        self,
        context: ClinicalEvaluationContext,
        *,
        assessed_at: datetime | None = None,
    ) -> ClinicalEvaluationContext:
        now = assessed_at or self.clock()
        if context.evaluation_mode is EvaluationMode.LONGITUDINAL:
            expected = self.longitudinal(
                context.patient_link_id,
                assessed_at=now,
                responsible_actor=context.responsible_actor,
            )
        else:
            try:
                expected = self.encounter(
                    context.patient_link_id,
                    int(context.encounter_event_id),
                    assessed_at=now,
                )
            except ClinicalEncounterConflict as exc:
                raise ClinicalContextStale(
                    "clinical encounter changed after evaluation"
                ) from exc
        if expected.content_hash != context.content_hash:
            raise ClinicalContextStale(
                "clinical evaluation context is no longer current"
            )
        return expected

    def from_payload(self, payload) -> ClinicalEvaluationContext:
        return context_from_payload(payload)
