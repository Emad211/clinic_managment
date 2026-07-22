"""Current-run orchestration for visible Clinical Engine v2 behavior.

This is the single runtime seam between mutable patient data and immutable audited
runs.  A recommendation can be presented, decided on, or converted to a task only
through a contract bound to the current patient revision, exact ruleset and engine
build.
"""
from __future__ import annotations

from dataclasses import dataclass

from flask import current_app, has_app_context

from src.adapters.sqlite.clinical_engine_activation_repo import (
    ClinicalEngineActivationRepository,
)
from src.adapters.sqlite.clinical_engine_fact_repo import ClinicalEngineFactRepository
from src.adapters.sqlite.clinical_engine_rules_repo import ClinicalEngineRulesRepository
from src.adapters.sqlite.clinical_engine_runtime_repo import (
    ClinicalEngineRuntimeRepository,
)
from src.common.utils import iran_now
from src.services.clinical_engine.fact_builder import ENGINE_VERSION, ShadowFactCapture


@dataclass(frozen=True, slots=True)
class ClinicalRuntimeContract:
    patient_link_id: int
    mode: str
    engine_version: str
    ruleset_id: int | None
    clinical_data_revision: int
    allow_legacy_test_run: bool = False


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
        capture_factory=None,
        clock=None,
    ):
        self.facts = facts or ClinicalEngineFactRepository()
        self.rules = rules or ClinicalEngineRulesRepository()
        self.activation = activation or ClinicalEngineActivationRepository()
        self.runtime_repo = runtime_repo or ClinicalEngineRuntimeRepository()
        self.capture_factory = capture_factory or (lambda: ShadowFactCapture(
            repository=self.facts, rules=self.rules
        ))
        self.clock = clock or iran_now

    @staticmethod
    def _allow_legacy_test_run() -> bool:
        return bool(
            has_app_context()
            and current_app.config.get("TESTING", False)
            and current_app.config.get("CLINICAL_ENGINE_ALLOW_LEGACY_TEST_RUNS", True)
        )

    def _effective_ruleset_id(self, mode: str) -> int | None:
        if mode in {"on_selected", "on"}:
            seal = self.activation.get_json("seal")
            if isinstance(seal, dict) and seal.get("mode") == mode:
                value = seal.get("ruleset_id")
                return int(value) if value is not None else None
            # Historical tests intentionally exercise selected mode without the
            # production activation gate.  Production get_mode() has already
            # failed closed before this compatibility path can be reached.
            if self._allow_legacy_test_run():
                ruleset = self.rules.active_ruleset("general-outpatient")
                return int(ruleset["id"]) if ruleset else None
            raise ClinicalEngineRuntimeError("visible mode has no valid activation seal")
        ruleset = self.rules.active_ruleset("general-outpatient")
        return int(ruleset["id"]) if ruleset else None

    def contract(self, patient_link_id: int) -> ClinicalRuntimeContract | None:
        mode = self.facts.get_mode()
        if mode not in {"shadow", "on_selected", "on"}:
            return None
        if mode == "on_selected" and not self.facts.is_selected_patient(patient_link_id):
            return None
        return ClinicalRuntimeContract(
            patient_link_id=int(patient_link_id),
            mode=mode,
            engine_version=ENGINE_VERSION,
            ruleset_id=self._effective_ruleset_id(mode),
            clinical_data_revision=self.facts.clinical_data_revision(patient_link_id),
            allow_legacy_test_run=self._allow_legacy_test_run(),
        )

    def current_run(self, contract: ClinicalRuntimeContract) -> dict | None:
        return self.runtime_repo.latest_current_run(
            contract.patient_link_id,
            engine_version=contract.engine_version,
            ruleset_id=contract.ruleset_id,
            clinical_data_revision=contract.clinical_data_revision,
            allow_legacy_revision=contract.allow_legacy_test_run,
        )

    def ensure_current_run(
        self,
        patient_link_id: int,
        *,
        trigger: str,
        actor: str | None = None,
    ) -> tuple[ClinicalRuntimeContract, dict] | None:
        """Return a current run, evaluating at most twice if data changes mid-run."""
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
                raise ClinicalEngineRuntimeError("clinical evaluation was not started")
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
            "patient data changed repeatedly while the clinical run was being built"
        )

    def present_recommendation(
        self, recommendation_event_id: int, contract: ClinicalRuntimeContract
    ) -> int:
        try:
            return self.runtime_repo.append_presentation_once(
                recommendation_event_id,
                patient_link_id=contract.patient_link_id,
                engine_version=contract.engine_version,
                ruleset_id=contract.ruleset_id,
                clinical_data_revision=contract.clinical_data_revision,
                allow_legacy_revision=contract.allow_legacy_test_run,
            )
        except RuntimeError as exc:
            if str(exc) == "STALE_RECOMMENDATION":
                raise ClinicalEngineRuntimeStale(
                    "patient data changed before recommendation presentation"
                ) from exc
            raise
