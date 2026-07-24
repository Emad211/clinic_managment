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
        """Validate the immutable context without silently replacing its identity.

        A longitudinal recommendation remains auditable after midnight; its exact
        assessment-day context does not become invalid merely because the wall clock
        advanced.  Encounter contexts additionally require that the referenced event
        is still the current executable head and that its clinical fields still match
        the stored context.
        """
        now = local_naive(assessed_at or self.clock())
        if local_naive(context.recorded_at) > now:
            raise ClinicalContextStale(
                "clinical evaluation context is recorded in the future"
            )
        if context.evaluation_mode is EvaluationMode.LONGITUDINAL:
            return context

        try:
            event = self.encounters.get_event(int(context.encounter_event_id))
        except (TypeError, ValueError) as exc:
            raise ClinicalContextStale(
                "clinical encounter reference is invalid"
            ) from exc
        if (
            not event
            or int(event["patient_link_id"]) != int(context.patient_link_id)
            or str(event["encounter_key"]) != str(context.encounter_key)
        ):
            raise ClinicalContextStale(
                "clinical encounter is unavailable for this patient"
            )
        current = self.encounters.current(str(event["encounter_key"]))
        if not current or int(current["id"]) != int(event["id"]):
            raise ClinicalContextStale(
                "clinical encounter changed after evaluation"
            )
        status = EncounterStatus(event["status"])
        if status not in {EncounterStatus.OPEN, EncounterStatus.FINALIZED}:
            raise ClinicalContextStale("clinical encounter is no longer executable")

        appointment_id = (
            int(event["appointment_id"])
            if event.get("appointment_id") is not None
            else None
        )
        effective_at = local_naive(
            parse_datetime(event["effective_at"]) or context.effective_at
        )
        expected = {
            "care_setting": CareSetting(event["care_setting"]),
            "encounter_type": EncounterType(event["encounter_type"]),
            "encounter_status": status,
            "appointment_id": appointment_id,
            "reason_codes": tuple(event["reason_codes"]),
            "chief_complaint": event.get("chief_complaint"),
            "responsible_actor": event.get("responsible_actor"),
            "effective_at": effective_at,
        }
        actual = {
            "care_setting": context.care_setting,
            "encounter_type": context.encounter_type,
            "encounter_status": context.encounter_status,
            "appointment_id": context.appointment_id,
            "reason_codes": tuple(context.reason_codes),
            "chief_complaint": context.chief_complaint,
            "responsible_actor": context.responsible_actor,
            "effective_at": local_naive(context.effective_at),
        }
        if expected != actual:
            raise ClinicalContextStale(
                "clinical encounter content changed after evaluation"
            )
        return context

    def from_payload(self, payload) -> ClinicalEvaluationContext:
        return context_from_payload(payload)
