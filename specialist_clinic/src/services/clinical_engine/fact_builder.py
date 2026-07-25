"""Canonical Clinical Engine v2 snapshot construction and audited evaluation."""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import datetime
import hashlib
import json
from typing import Any

from src.adapters.sqlite.clinical_engine_audit_repo import (
    ClinicalEngineAuditRepository,
)
from src.adapters.sqlite.clinical_engine_fact_repo import (
    ClinicalEngineFactRepository,
)
from src.adapters.sqlite.clinical_engine_rules_repo import (
    ClinicalEngineRulesRepository,
)
from src.common.utils import IRAN_TZ
from src.domain.clinical_engine import (
    ClinicalEvaluationContext,
    FactSnapshot,
    RunStatus,
    longitudinal_context,
)
from src.domain.clinical_engine.release import CURRENT_ENGINE_VERSION
from src.services.clinical_engine.compiler import RuleCompiler
from src.services.clinical_engine.composer import (
    RecommendationComposer,
    recommendation_payload,
)
from src.services.clinical_engine.conflicts import ConflictResolver
from src.services.clinical_engine.evaluator import evaluation_payload
from src.services.clinical_engine.reconciled_adapter import (
    ReconciledFactBundleAdapter,
)
from src.services.clinical_engine.safety import SafetyKernel
from src.services.clinical_engine.scope_evaluator import ContextualRuleEvaluator


ENGINE_VERSION = CURRENT_ENGINE_VERSION
DEFAULT_RULESET_CODE = "general-outpatient"


def _json_default(value: Any):
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        default=_json_default,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _iso(value: datetime) -> str:
    aware = value if value.tzinfo else value.replace(tzinfo=IRAN_TZ)
    return aware.isoformat(timespec="seconds")


def _fact_payload(fact, *, assessed_at: datetime) -> dict:
    source_types = {
        "laboratory": "laboratory",
        "clinician": "clinician",
        "derived": "derived",
        "patient": "patient",
        "caregiver": "caregiver",
        "device": "device",
        "accounting_bridge": "accounting_bridge",
    }
    source_type = source_types.get(fact.source.system, "system")
    conflict_state = {
        "NONE": "NONE",
        "PRESENT": "CONFIRMED",
        "UNKNOWN": "POSSIBLE",
        "POSSIBLE": "POSSIBLE",
        "CONFIRMED": "CONFIRMED",
        "RESOLVED": "RESOLVED",
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
        "reference_range": (
            dict(fact.reference_range)
            if fact.reference_range
            else None
        ),
        "effective_at": _iso(fact.effective_at),
        "recorded_at": _iso(fact.recorded_at),
        "source": {
            "type": source_type,
            "table": (
                None
                if fact.source.system in source_types
                else fact.source.system
            ),
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


def snapshot_payload(
    snapshot: FactSnapshot,
    *,
    include_hash: bool = True,
) -> dict:
    context = snapshot.evaluation_context
    if context is None:
        raise ValueError("fact snapshot requires an evaluation context")
    payload = {
        "schema_version": snapshot.schema_version,
        "patient_link_id": snapshot.patient_link_id,
        "clinical_data_revision": int(
            snapshot.clinical_data_revision
        ),
        "as_of_at": _iso(snapshot.as_of_at),
        "encounter_key": context.encounter_key,
        "evaluation_context": context.payload(),
        "context_hash": context.content_hash,
        "facts": [
            _fact_payload(fact, assessed_at=snapshot.as_of_at)
            for fact in snapshot.facts
        ],
    }
    if include_hash:
        payload["content_hash"] = snapshot.content_hash
    return payload


class FactBuilder:
    def __init__(self, repository=None, adapter=None):
        self.repository = repository or ClinicalEngineFactRepository()
        self.adapter = adapter or ReconciledFactBundleAdapter()

    def build(
        self,
        patient_link_id: int,
        *,
        as_of_at: datetime,
        encounter_key: str | None = None,
        evaluation_context: ClinicalEvaluationContext | None = None,
    ) -> FactSnapshot:
        if not isinstance(as_of_at, datetime):
            raise TypeError("as_of_at must be a datetime")
        context = evaluation_context or longitudinal_context(
            patient_link_id, as_of_at=as_of_at
        )
        if int(context.patient_link_id) != int(patient_link_id):
            raise ValueError("evaluation context does not belong to patient")
        if encounter_key is not None and encounter_key != context.encounter_key:
            raise ValueError("encounter_key disagrees with evaluation context")
        bundle = self.repository.load_bundle(patient_link_id)
        revision = int(
            bundle["patient"].get("clinical_data_revision") or 0
        )
        facts = self.adapter.adapt(bundle, as_of_at=as_of_at)
        provisional = FactSnapshot(
            schema_version="2.0",
            patient_link_id=patient_link_id,
            as_of_at=as_of_at,
            facts=facts,
            content_hash="",
            encounter_key=context.encounter_key,
            evaluation_context=context,
            clinical_data_revision=revision,
        )
        body = snapshot_payload(provisional, include_hash=False)
        digest = hashlib.sha256(
            canonical_json(body).encode("utf-8")
        ).hexdigest()
        return FactSnapshot(
            schema_version="2.0",
            patient_link_id=patient_link_id,
            as_of_at=as_of_at,
            facts=facts,
            content_hash=digest,
            encounter_key=context.encounter_key,
            evaluation_context=context,
            clinical_data_revision=revision,
        )


class ShadowFactCapture:
    """Persist deterministic audited evaluations for an executable ruleset."""

    def __init__(
        self,
        repository=None,
        builder=None,
        audit=None,
        rules=None,
        compiler=None,
        evaluator=None,
        safety=None,
        composer=None,
        conflicts=None,
        context_service=None,
        ruleset_code=DEFAULT_RULESET_CODE,
    ):
        self.repository = repository or ClinicalEngineFactRepository()
        self.builder = builder or FactBuilder(
            repository=self.repository
        )
        self.audit = audit or ClinicalEngineAuditRepository()
        self.rules = rules or ClinicalEngineRulesRepository()
        self.compiler = compiler or RuleCompiler()
        self.evaluator = evaluator or ContextualRuleEvaluator()
        self.safety = safety or SafetyKernel(self.evaluator)
        self.composer = composer or RecommendationComposer()
        self.conflicts = conflicts or ConflictResolver()
        self.context_service = context_service
        self.ruleset_code = ruleset_code

    def _ruleset(self, ruleset_id: int | None):
        ruleset = (
            self.rules.get_ruleset(int(ruleset_id))
            if ruleset_id is not None
            else self.rules.active_ruleset(self.ruleset_code)
        )
        if ruleset_id is not None:
            if (
                not ruleset
                or ruleset.get("ruleset_code") != self.ruleset_code
            ):
                raise LookupError(
                    "the requested clinical ruleset does not exist"
                )
            if ruleset.get("status") not in {"SILENT", "ACTIVE"}:
                raise ValueError(
                    "the requested clinical ruleset is not executable"
                )
        return ruleset

    @staticmethod
    def _compile_failure(exc: Exception) -> dict:
        return {
            "predicate_state": "ERROR",
            "outcome": "ERROR",
            "trace": {
                "node_id": "compile-error",
                "kind": "PREDICATE",
                "state": "ERROR",
                "message_fa": "قاعدهٔ ذخیره‌شده قابل اجرا نیست.",
                "fact_ids": [],
                "actual": None,
                "expected": None,
                "reason_code": "STORED_RULE_INVALID",
                "children": [],
            },
            "data_issues": [],
            "error": {
                "code": "STORED_RULE_INVALID",
                "message": str(exc),
            },
        }

    def capture(
        self,
        patient_link_id: int,
        *,
        as_of_at: datetime,
        encounter_key: str | None = None,
        evaluation_context: ClinicalEvaluationContext | None = None,
        created_by: str | None = None,
        ruleset_id: int | None = None,
    ) -> str | None:
        mode = self.repository.get_mode()
        if mode == "off" or (
            mode == "on_selected"
            and not self.repository.is_selected_patient(
                patient_link_id
            )
        ):
            return None

        context = evaluation_context
        if context is None:
            context = (
                self.context_service.longitudinal(
                    patient_link_id, assessed_at=as_of_at
                )
                if self.context_service is not None
                else longitudinal_context(patient_link_id, as_of_at=as_of_at)
            )
        snapshot = self.builder.build(
            patient_link_id,
            as_of_at=as_of_at,
            encounter_key=encounter_key,
            evaluation_context=context,
        )
        if snapshot.evaluation_context is None:
            # Custom builders used by audit/failure tests must still enter the same
            # canonical context contract. Production FactBuilder already supplies it.
            snapshot = replace(
                snapshot,
                encounter_key=context.encounter_key,
                evaluation_context=context,
                content_hash="",
            )
            digest = hashlib.sha256(
                canonical_json(
                    snapshot_payload(snapshot, include_hash=False)
                ).encode("utf-8")
            ).hexdigest()
            snapshot = replace(snapshot, content_hash=digest)
        ruleset = self._ruleset(ruleset_id)
        run_id = self.audit.start_run(
            patient_link_id=patient_link_id,
            encounter_key=context.encounter_key,
            evaluation_context=context,
            as_of_at=as_of_at.isoformat(
                sep=" ", timespec="seconds"
            ),
            engine_version=ENGINE_VERSION,
            ruleset_id=ruleset["id"] if ruleset else None,
            fact_snapshot=snapshot_payload(snapshot),
            created_by=created_by,
        )
        if not ruleset:
            self.audit.complete_run(
                run_id,
                status=RunStatus.COMPLETED,
                summary={
                    "mode": mode,
                    "engine_version": ENGINE_VERSION,
                    "clinical_data_revision": (
                        snapshot.clinical_data_revision
                    ),
                    "context_hash": context.content_hash,
                    "evaluated_rules": 0,
                    "recommendations": 0,
                },
            )
            return run_id

        counts: Counter[str] = Counter()
        try:
            compiled_entries: list[tuple[dict, Any]] = []
            compile_failures: dict[int, dict] = {}
            safety_precheck_failed = False
            for member in ruleset["members"]:
                member_id = int(member["rule_version_id"])
                try:
                    compiled_entries.append(
                        (
                            member,
                            self.compiler.compile(
                                json.loads(member["rule_json"])
                            ),
                        )
                    )
                except Exception as exc:
                    compile_failures[member_id] = self._compile_failure(
                        exc
                    )
                    if member.get("phase") != "ROUTINE":
                        safety_precheck_failed = True

            safety_run = self.safety.evaluate(
                [compiled for _, compiled in compiled_entries],
                snapshot,
                safety_precheck_failed=safety_precheck_failed,
            )
            resolved = self.conflicts.resolve(
                safety_run.evaluations
            )
            resolved_by_identity = {
                id(item.compiled): item for item in resolved
            }
            resolved_by_member = {
                int(member["rule_version_id"]): (
                    resolved_by_identity[id(compiled)]
                )
                for member, compiled in compiled_entries
            }
            compiled_by_member = {
                int(member["rule_version_id"]): compiled
                for member, compiled in compiled_entries
            }

            recommendation_count = 0
            for member in ruleset["members"]:
                member_id = int(member["rule_version_id"])
                if member_id in compile_failures:
                    payload = compile_failures[member_id]
                    predicate_state = payload["predicate_state"]
                    outcome = payload["outcome"]
                    recommendation = None
                    suppression = None
                else:
                    resolved_item = resolved_by_member[member_id]
                    result = resolved_item.result
                    compiled = compiled_by_member[member_id]
                    payload = evaluation_payload(result)
                    predicate_state = result.predicate.state
                    outcome = result.outcome
                    recommendation = recommendation_payload(
                        self.composer.compose(compiled, result),
                        title_fa=compiled.definition.title,
                        semantic_key=(
                            compiled.definition.semantic_key
                        ),
                        merged_rule_codes=(
                            resolved_item.merged_rule_codes
                        ),
                        merged_titles=resolved_item.merged_titles,
                    )
                    suppression = payload["suppression"]
                    recommendation_count += int(
                        recommendation is not None
                    )

                outcome_value = (
                    outcome.value
                    if hasattr(outcome, "value")
                    else outcome
                )
                counts[outcome_value] += 1
                evaluation_id = self.audit.append_evaluation(
                    run_id=run_id,
                    rule_version_id=member_id,
                    predicate_state=predicate_state,
                    outcome=outcome,
                    trace=payload["trace"],
                    data_issues=payload["data_issues"],
                    recommendation=recommendation,
                    suppression=suppression,
                    error=payload["error"],
                )
                if recommendation:
                    self.audit.append_recommendation_event(
                        run_id=run_id,
                        evaluation_id=evaluation_id,
                        recommendation_key=(
                            recommendation["recommendation_key"]
                        ),
                        action_type=recommendation["action_type"],
                        event_type="CREATED",
                        payload=recommendation,
                    )

            status = safety_run.status
            if (
                compile_failures
                and status is RunStatus.COMPLETED
            ):
                status = RunStatus.COMPLETED_WITH_ERRORS
            self.audit.complete_run(
                run_id,
                status=status,
                summary={
                    "mode": mode,
                    "engine_version": ENGINE_VERSION,
                    "clinical_data_revision": (
                        snapshot.clinical_data_revision
                    ),
                    "context_hash": context.content_hash,
                    "evaluated_rules": sum(counts.values()),
                    "recommendations": recommendation_count,
                    "redflag_active": bool(
                        safety_run.redflag_rule_codes
                    ),
                    "redflag_rule_codes": list(
                        safety_run.redflag_rule_codes
                    ),
                    "routine_outputs_blocked": (
                        safety_run.routine_outputs_blocked
                    ),
                    "counts": dict(sorted(counts.items())),
                },
            )
        except Exception as exc:
            self.audit.complete_run(
                run_id,
                status=RunStatus.AUDIT_FAILED,
                error={
                    "code": "SHADOW_EVALUATION_FAILED",
                    "message": str(exc),
                },
            )
            raise
        return run_id
