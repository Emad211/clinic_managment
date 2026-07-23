"""Current-run orchestration for visible Clinical Engine v2 behavior.

This is the single runtime seam between mutable patient data and immutable audited
runs. There is no compatibility bypass: tests and production resolve the same exact
engine identity, patient revision, ruleset, evaluation context and activation seal.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.adapters.sqlite.clinical_engine_action_repo import (
    ClinicalEngineActionRepository,
)
from src.adapters.sqlite.clinical_engine_activation_repo import (
    ClinicalEngineActivationRepository,
)
from src.adapters.sqlite.clinical_engine_fact_repo import (
    ClinicalEngineFactRepository,
)
from src.adapters.sqlite.clinical_engine_rules_repo import (
    ClinicalEngineRulesRepository,
)
from src.adapters.sqlite.clinical_engine_runtime_repo import (
    ClinicalEngineRuntimeRepository,
)
from src.common.utils import iran_now
from src.domain.clinical_engine import ClinicalEvaluationContext
from src.services.clinical_engine.context_service import (
    ClinicalContextStale,
    ClinicalEvaluationContextService,
)
from src.services.clinical_engine.fact_builder import (
    ENGINE_VERSION,
    ShadowFactCapture,
)


@dataclass(frozen=True, slots=True)
class ClinicalRuntimeContract:
    patient_link_id: int
    mode: str
    engine_version: str
    ruleset_id: int | None
    clinical_data_revision: int
    evaluation_context: ClinicalEvaluationContext
    context_hash: str


class ClinicalEngineRuntimeError(RuntimeError):
    pass


class ClinicalEngineRuntimeStale(ClinicalEngineRuntimeError):
    pass


class ClinicalEngineRuntimeService:
    """Resolve or create the one audited run valid for patient and context state."""

    def __init__(
        self,
        *,
        facts=None,
        rules=None,
        activation=None,
        runtime_repo=None,
        action_repo=None,
        context_service=None,
        capture_factory=None,
        clock=None,
    ):
        self.facts = facts or ClinicalEngineFactRepository()
        self.rules = rules or ClinicalEngineRulesRepository()
        self.activation = activation or ClinicalEngineActivationRepository()
        self.runtime_repo = runtime_repo or ClinicalEngineRuntimeRepository()
        self.action_repo = action_repo or ClinicalEngineActionRepository(
            runtime_repo=self.runtime_repo,
            activation=self.activation,
        )
        self.context_service = (
            context_service or ClinicalEvaluationContextService()
        )
        self.capture_factory = capture_factory or (
            lambda: ShadowFactCapture(
                repository=self.facts,
                rules=self.rules,
                context_service=self.context_service,
            )
        )
        self.clock = clock or iran_now

    def _effective_ruleset_id(self, mode: str) -> int | None:
        if mode in {"on_selected", "on"}:
            if not self.activation.valid_seal(mode):
                raise ClinicalEngineRuntimeError(
                    "visible mode has no valid activation seal"
                )
            seal = self.activation.get_json("seal")
            value = seal.get("ruleset_id") if isinstance(seal, dict) else None
            if value is None:
                raise ClinicalEngineRuntimeError(
                    "activation seal does not identify a ruleset"
                )
            return int(value)
        ruleset = self.rules.active_ruleset("general-outpatient")
        return int(ruleset["id"]) if ruleset else None

    def contract(
        self,
        patient_link_id: int,
        *,
        evaluation_context: ClinicalEvaluationContext | None = None,
    ) -> ClinicalRuntimeContract | None:
        mode = self.facts.get_mode()
        if mode not in {"shadow", "on_selected", "on"}:
            return None
        if mode == "on_selected" and not self.facts.is_selected_patient(
            patient_link_id
        ):
            return None
        now = self.clock()
        try:
            context = (
                self.context_service.longitudinal(
                    patient_link_id,
                    assessed_at=now,
                )
                if evaluation_context is None
                else self.context_service.assert_current(
                    evaluation_context,
                    assessed_at=now,
                )
            )
        except ClinicalContextStale as exc:
            raise ClinicalEngineRuntimeStale(str(exc)) from exc
        if int(context.patient_link_id) != int(patient_link_id):
            raise ClinicalEngineRuntimeError(
                "evaluation context does not belong to patient"
            )
        return ClinicalRuntimeContract(
            patient_link_id=int(patient_link_id),
            mode=mode,
            engine_version=ENGINE_VERSION,
            ruleset_id=self._effective_ruleset_id(mode),
            clinical_data_revision=self.facts.clinical_data_revision(
                patient_link_id
            ),
            evaluation_context=context,
            context_hash=context.content_hash,
        )

    def current_run(
        self, contract: ClinicalRuntimeContract
    ) -> dict | None:
        return self.runtime_repo.latest_current_run(
            contract.patient_link_id,
            engine_version=contract.engine_version,
            ruleset_id=contract.ruleset_id,
            clinical_data_revision=contract.clinical_data_revision,
            context_hash=contract.context_hash,
        )

    def ensure_current_run(
        self,
        patient_link_id: int,
        *,
        trigger: str,
        actor: str | None = None,
        evaluation_context: ClinicalEvaluationContext | None = None,
    ) -> tuple[ClinicalRuntimeContract, dict] | None:
        """Return a current run, retrying once if patient/context state changes."""
        contract = self.contract(
            patient_link_id,
            evaluation_context=evaluation_context,
        )
        if contract is None:
            return None
        current = self.current_run(contract)
        if current:
            return contract, current

        for _attempt in range(2):
            run_id = self.capture_factory().capture(
                patient_link_id,
                as_of_at=self.clock(),
                evaluation_context=contract.evaluation_context,
                created_by=(actor or f"runtime:{trigger}"),
                ruleset_id=contract.ruleset_id,
            )
            if not run_id:
                raise ClinicalEngineRuntimeError(
                    "clinical evaluation was not started"
                )
            refreshed = self.contract(
                patient_link_id,
                evaluation_context=contract.evaluation_context,
            )
            if refreshed is None:
                raise ClinicalEngineRuntimeStale(
                    "clinical engine mode changed during evaluation"
                )
            if refreshed.ruleset_id != contract.ruleset_id:
                raise ClinicalEngineRuntimeStale(
                    "clinical ruleset changed during evaluation"
                )
            if refreshed.context_hash != contract.context_hash:
                raise ClinicalEngineRuntimeStale(
                    "clinical evaluation context changed during evaluation"
                )
            current = self.current_run(refreshed)
            if current:
                return refreshed, current
            contract = refreshed
        raise ClinicalEngineRuntimeStale(
            "patient data changed repeatedly while the clinical run was built"
        )

    def present_recommendation(
        self,
        recommendation_event_id: int,
        contract: ClinicalRuntimeContract,
    ) -> int:
        try:
            return self.action_repo.append_presentation_once(
                recommendation_event_id,
                patient_link_id=contract.patient_link_id,
                mode=contract.mode,
                engine_version=contract.engine_version,
                ruleset_id=contract.ruleset_id,
                clinical_data_revision=contract.clinical_data_revision,
                context_hash=contract.context_hash,
            )
        except RuntimeError as exc:
            if str(exc) == "STALE_RECOMMENDATION":
                raise ClinicalEngineRuntimeStale(
                    "patient data, context or rollout state changed before presentation"
                ) from exc
            raise
