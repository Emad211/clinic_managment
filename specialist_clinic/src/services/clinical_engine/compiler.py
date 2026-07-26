"""Structural and semantic compiler for Clinical Engine v2 rule artefacts.

The compiler is deliberately isolated from Flask, SQLite and patient data. A
rule that fails compilation must never be eligible for ruleset activation.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from src.domain.clinical_engine.enums import (
    ActionType,
    ClinicalPhase,
    RuleSeverity,
)
from src.domain.clinical_engine.results import (
    CompilationDiagnostic,
    RuleCompilationError,
)
from src.domain.clinical_engine.rules import (
    CompiledRule,
    HardExclusion,
    RuleDefinition,
    SafetyPolicy,
    freeze,
)
from src.services.clinical_engine.compiler_support import (
    CONFIRMATION_REQUIRED,
    DSL_VERSION,
    EXPECTED_PHASE,
    INTERNAL_TASK_ACTIONS,
    SCHEMA_PATH,
    SCHEMA_VERSION,
    SUPPORTED_OPERATORS,
    SUPPORTED_UNITS,
    ExpressionCompilerMixin,
)

# Backward-compatible module constants for technical tests and callers. They refer
# only to the v2 contract; no retired v1 lineage is accepted or projected.
_EXPECTED_PHASE = EXPECTED_PHASE
_CONFIRMATION_REQUIRED = CONFIRMATION_REQUIRED
_INTERNAL_TASK_ACTIONS = INTERNAL_TASK_ACTIONS


class RuleCompiler(ExpressionCompilerMixin):
    """Compile JSON-compatible rule mappings into immutable typed plans."""

    def __init__(self, schema_path: str | Path | None = None):
        path = Path(schema_path) if schema_path else SCHEMA_PATH
        self._schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(self._schema)
        self._validator = Draft202012Validator(
            self._schema,
            format_checker=FormatChecker(),
        )

    def validate(self, raw: Any) -> tuple[CompilationDiagnostic, ...]:
        """Return every deterministic compile diagnostic without raising."""
        structural = self._structural_diagnostics(raw)
        if structural:
            return structural
        _, semantic = self._compile_semantics(raw)
        return semantic

    def validate_json(
        self,
        text: str,
    ) -> tuple[CompilationDiagnostic, ...]:
        """Parse and validate JSON without leaking decoder exceptions."""
        try:
            raw = json.loads(text)
        except (json.JSONDecodeError, TypeError) as exc:
            return (
                CompilationDiagnostic(
                    code="MALFORMED_JSON",
                    path="$",
                    message=str(exc),
                ),
            )
        return self.validate(raw)

    def compile_json(self, text: str) -> CompiledRule:
        """Compile serialized JSON with the fail-closed diagnostic model."""
        diagnostics = self.validate_json(text)
        if diagnostics:
            raise RuleCompilationError(diagnostics)
        return self.compile(json.loads(text))

    def compile(self, raw: Any) -> CompiledRule:
        """Return a compiled immutable rule or raise RuleCompilationError."""
        structural = self._structural_diagnostics(raw)
        if structural:
            raise RuleCompilationError(structural)

        components, semantic = self._compile_semantics(raw)
        if semantic:
            raise RuleCompilationError(semantic)

        canonical = json.dumps(
            raw,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        definition = RuleDefinition(
            schema_version=raw["schema_version"],
            dsl_version=raw["dsl_version"],
            rule_code=raw["rule_code"],
            version=raw["version"],
            title=raw["title"],
            phase=ClinicalPhase(raw["phase"]),
            action_type=ActionType(raw["action_type"]),
            severity=RuleSeverity(raw["severity"]),
            priority=raw["priority"],
            semantic_key=raw.get("semantic_key"),
            scope=freeze(raw["scope"]),
            required_facts=tuple(
                freeze(item) for item in raw["required_facts"]
            ),
            eligibility=components["eligibility"],
            condition=components["condition"],
            safety=components["safety"],
            recommendation=freeze(raw["recommendation"]),
            evidence=freeze(raw["evidence"]),
            governance=freeze(raw["governance"]),
        )
        return CompiledRule(
            definition=definition,
            referenced_fact_keys=frozenset(components["fact_keys"]),
            node_ids=frozenset(components["node_ids"]),
            canonical_json=canonical,
            content_hash=hashlib.sha256(
                canonical.encode("utf-8")
            ).hexdigest(),
        )

    def _structural_diagnostics(
        self,
        raw: Any,
    ) -> tuple[CompilationDiagnostic, ...]:
        try:
            json.dumps(raw, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            return (
                CompilationDiagnostic(
                    code="NOT_JSON_SERIALIZABLE",
                    path="$",
                    message=str(exc),
                ),
            )
        errors = sorted(
            self._validator.iter_errors(raw),
            key=lambda error: tuple(
                str(part) for part in error.absolute_path
            ),
        )
        return tuple(
            CompilationDiagnostic(
                code="SCHEMA_VALIDATION_ERROR",
                path=self._json_path(error.absolute_path),
                message=error.message,
            )
            for error in errors
        )

    def _compile_semantics(
        self,
        raw: Mapping[str, Any],
    ) -> tuple[dict[str, Any], tuple[CompilationDiagnostic, ...]]:
        diagnostics: list[CompilationDiagnostic] = []
        node_ids: set[str] = set()
        fact_keys: set[str] = set()

        required = raw["required_facts"]
        declared_keys = [item["key"] for item in required]
        duplicate_facts = sorted(
            {
                key
                for key in declared_keys
                if declared_keys.count(key) > 1
            }
        )
        for key in duplicate_facts:
            diagnostics.append(
                self._error(
                    "DUPLICATE_REQUIRED_FACT",
                    "$.required_facts",
                    f"Fact {key!r} is declared more than once.",
                )
            )

        for index, item in enumerate(required):
            path = f"$.required_facts[{index}]"
            if (
                item["criticality"] == "CRITICAL"
                and item["on_unusable"] != "NEEDS_DATA"
            ):
                diagnostics.append(
                    self._error(
                        "UNSAFE_CRITICAL_FACT_POLICY",
                        path,
                        "CRITICAL facts must use on_unusable=NEEDS_DATA.",
                    )
                )
            if (
                item["criticality"] in {"CRITICAL", "REQUIRED"}
                and not item.get("minimum_verification")
            ):
                diagnostics.append(
                    self._error(
                        "MISSING_VERIFICATION_POLICY",
                        path,
                        "CRITICAL/REQUIRED facts need minimum_verification.",
                    )
                )

        scope = raw["scope"]
        if (
            scope.get("age_min") is not None
            and scope.get("age_max") is not None
            and scope["age_min"] > scope["age_max"]
        ):
            diagnostics.append(
                self._error(
                    "INVALID_AGE_RANGE",
                    "$.scope",
                    "age_min cannot exceed age_max.",
                )
            )
        if "any" in scope.get("sex", []) and len(scope["sex"]) > 1:
            diagnostics.append(
                self._error(
                    "AMBIGUOUS_SEX_SCOPE",
                    "$.scope.sex",
                    "'any' cannot be combined with another sex value.",
                )
            )

        eligibility = self._compile_expression(
            raw["eligibility"],
            "$.eligibility",
            node_ids,
            fact_keys,
            diagnostics,
        )
        condition = self._compile_expression(
            raw["condition"],
            "$.condition",
            node_ids,
            fact_keys,
            diagnostics,
        )
        redflag_exclusions = tuple(
            self._compile_expression(
                expression,
                f"$.safety.redflag_exclusions[{index}]",
                node_ids,
                fact_keys,
                diagnostics,
            )
            for index, expression in enumerate(
                raw["safety"]["redflag_exclusions"]
            )
        )

        exclusion_ids: set[str] = set()
        hard_exclusions: list[HardExclusion] = []
        for index, exclusion in enumerate(
            raw["safety"]["hard_exclusions"]
        ):
            path = f"$.safety.hard_exclusions[{index}]"
            exclusion_id = exclusion["exclusion_id"]
            if exclusion_id in exclusion_ids:
                diagnostics.append(
                    self._error(
                        "DUPLICATE_EXCLUSION_ID",
                        path,
                        f"Duplicate exclusion_id {exclusion_id!r}.",
                    )
                )
            exclusion_ids.add(exclusion_id)
            condition_expression = self._compile_expression(
                exclusion["condition"],
                f"{path}.condition",
                node_ids,
                fact_keys,
                diagnostics,
            )
            hard_exclusions.append(
                HardExclusion(
                    exclusion_id=exclusion_id,
                    condition=condition_expression,
                    effect=exclusion["effect"],
                    message_fa=exclusion["message_fa"],
                )
            )

        undeclared = sorted(fact_keys - set(declared_keys))
        for key in undeclared:
            diagnostics.append(
                self._error(
                    "UNDECLARED_FACT_REFERENCE",
                    "$",
                    f"Expression references {key!r}, but required_facts "
                    "does not declare it.",
                )
            )

        action = ActionType(raw["action_type"])
        phase = ClinicalPhase(raw["phase"])
        expected = EXPECTED_PHASE.get(action, ClinicalPhase.ROUTINE)
        if phase != expected:
            diagnostics.append(
                self._error(
                    "ACTION_PHASE_MISMATCH",
                    "$.phase",
                    f"{action.value} rules must use phase={expected.value}.",
                )
            )

        recommendation = raw["recommendation"]
        if (
            action in CONFIRMATION_REQUIRED
            and not recommendation["requires_clinician_confirmation"]
        ):
            diagnostics.append(
                self._error(
                    "CLINICIAN_CONFIRMATION_REQUIRED",
                    "$.recommendation.requires_clinician_confirmation",
                    f"{action.value} requires explicit clinician confirmation.",
                )
            )
        if (
            recommendation["may_create_internal_task"]
            and action not in INTERNAL_TASK_ACTIONS
        ):
            diagnostics.append(
                self._error(
                    "AUTOMATIC_TASK_NOT_ALLOWED",
                    "$.recommendation.may_create_internal_task",
                    f"{action.value} cannot directly create an internal task.",
                )
            )
        if recommendation["may_create_internal_task"]:
            params = recommendation.get("params") or {}
            if not isinstance(params.get("task_contract"), dict):
                diagnostics.append(
                    self._error(
                        "MISSING_TASK_CONTRACT",
                        "$.recommendation.params.task_contract",
                        "Internal tasks require an explicit due/completion contract.",
                    )
                )
            due_count = int(params.get("due_in_hours") is not None) + int(
                params.get("due_in_days") is not None
            )
            if due_count != 1:
                diagnostics.append(
                    self._error(
                        "INVALID_TASK_DUE_CONTRACT",
                        "$.recommendation.params",
                        "Exactly one of due_in_hours or due_in_days is required.",
                    )
                )

        governance = raw["governance"]
        validation_status = raw["evidence"]["local_validation_status"]
        if governance["status"] == "ACTIVE":
            if validation_status != "APPROVED_FOR_ACTIVE":
                diagnostics.append(
                    self._error(
                        "ACTIVE_RULE_NOT_CLINICALLY_APPROVED",
                        "$.evidence.local_validation_status",
                        "ACTIVE rules require APPROVED_FOR_ACTIVE.",
                    )
                )
            if (
                not governance.get("clinical_reviewer")
                or not governance.get("technical_reviewer")
            ):
                diagnostics.append(
                    self._error(
                        "ACTIVE_RULE_MISSING_REVIEWERS",
                        "$.governance",
                        "ACTIVE rules require clinical and technical reviewers.",
                    )
                )
            if not raw.get("semantic_key"):
                diagnostics.append(
                    self._error(
                        "ACTIVE_RULE_MISSING_SEMANTIC_KEY",
                        "$.semantic_key",
                        "ACTIVE rules require a semantic_key for deduplication.",
                    )
                )

        components = {
            "eligibility": eligibility,
            "condition": condition,
            "safety": SafetyPolicy(
                redflag_exclusions=redflag_exclusions,
                hard_exclusions=tuple(hard_exclusions),
                on_safety_error=raw["safety"]["on_safety_error"],
            ),
            "node_ids": node_ids,
            "fact_keys": fact_keys,
        }
        return components, tuple(diagnostics)


__all__ = [
    "DSL_VERSION",
    "RuleCompiler",
    "SCHEMA_PATH",
    "SCHEMA_VERSION",
    "SUPPORTED_OPERATORS",
    "SUPPORTED_UNITS",
]
