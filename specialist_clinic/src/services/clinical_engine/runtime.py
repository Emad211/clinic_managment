"""Current-run orchestration for visible Clinical Engine v2 behavior.

This is the single runtime seam between mutable patient data and immutable audited
runs.  There is no compatibility bypass: tests and production resolve the same exact
engine identity, patient revision, ruleset and activation seal.
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


class ClinicalEngineRuntimeError(RuntimeError):
    pass


class ClinicalEngineRuntimeStale(ClinicalEngineRuntimeError):
    pass


class ClinicalEngineRuntimeService:
    """Resolve or create the one audited run valid for current patient state."""

    def __init__(
        self,
        *,
        facts=None,
        rules=None,
        activation=None,
        runtime_repo=None,
        action_repo=None,
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
        self.capture_factory = capture_factory or (
            lambda: ShadowFactCapture(
                repository=self.facts,
                rules=self.rules,
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
        self, patient_link_id: int
    ) -> ClinicalRuntimeContract | None:
        mode = self.facts.get_mode()
        if mode not in {"shadow", "on_selected", "on"}:
            return None
        if mode == "on_selected" and not self.facts.is_selected_patient(
            patient_link_id
        ):
            return None
        return ClinicalRuntimeContract(
            patient_link_id=int(patient_link_id),
            mode=mode,
            engine_version=ENGINE_VERSION,
            ruleset_id=self._effective_ruleset_id(mode),
            clinical_data_revision=self.facts.clinical_data_revision(
                patient_link_id
            ),
        )

    def current_run(
        self, contract: ClinicalRuntimeContract
    ) -> dict | None:
        return self.runtime_repo.latest_current_run(
            contract.patient_link_id,
            engine_version=contract.engine_version,
            ruleset_id=contract.ruleset_id,
            clinical_data_revision=contract.clinical_data_revision,
        )

    def ensure_current_run(
        self,
        patient_link_id: int,
        *,
        trigger: str,
        actor: str | None = None,
    ) -> tuple[ClinicalRuntimeContract, dict] | None:
        """Return a current run, retrying once if patient state changes mid-run."""
        contract = self.contract(patient_link_id)
        if contract is None:
            return None
        current = self.current_run(contract)
        if current:
            return contract, current

        for _attempt in range(2):
            run_id = self.capture_factory().capture(
                patient_link_id,
                as_of_at=self.clock(),
                created_by=(actor or f"runtime:{trigger}"),
                ruleset_id=contract.ruleset_id,
            )
            if not run_id:
                raise ClinicalEngineRuntimeError(
                    "clinical evaluation was not started"
                )
            refreshed = self.contract(patient_link_id)
            if refreshed is None:
                raise ClinicalEngineRuntimeStale(
                    "clinical engine mode changed during evaluation"
                )
            if refreshed.ruleset_id != contract.ruleset_id:
                raise ClinicalEngineRuntimeStale(
                    "clinical ruleset changed during evaluation"
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
            )
        except RuntimeError as exc:
            if str(exc) == "STALE_RECOMMENDATION":
                raise ClinicalEngineRuntimeStale(
                    "patient data or rollout state changed before presentation"
                ) from exc
            raise
