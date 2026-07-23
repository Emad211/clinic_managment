"""Application boundary for resolving the context attached to an engine run."""
from __future__ import annotations

from datetime import datetime

from src.adapters.sqlite.clinical_encounter_repo import (
    ClinicalEncounterConflict,
    ClinicalEncounterRepository,
)
from src.common.utils import iran_now
from src.domain.clinical_engine.context import (
    ClinicalContextError,
    ClinicalEvaluationContext,
    EvaluationMode,
    context_from_payload,
    longitudinal_context,
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
        context = self.encounters.context_for_event(
            encounter_event_id,
            assessed_at=assessed_at or self.clock(),
            require_current=True,
        )
        if int(context.patient_link_id) != int(patient_link_id):
            raise ClinicalContextError("encounter does not belong to patient")
        return context

    def refresh(
        self,
        context: ClinicalEvaluationContext,
        *,
        assessed_at: datetime | None = None,
    ) -> ClinicalEvaluationContext:
        now = assessed_at or self.clock()
        if context.evaluation_mode is EvaluationMode.LONGITUDINAL:
            refreshed = self.longitudinal(
                context.patient_link_id,
                assessed_at=now,
                responsible_actor=context.responsible_actor,
            )
        else:
            try:
                refreshed = self.encounter(
                    context.patient_link_id,
                    int(context.encounter_event_id),
                    assessed_at=now,
                )
            except ClinicalEncounterConflict as exc:
                raise ClinicalContextStale(
                    "clinical encounter changed after evaluation"
                ) from exc
        return refreshed

    def from_payload(self, payload) -> ClinicalEvaluationContext:
        return context_from_payload(payload)
