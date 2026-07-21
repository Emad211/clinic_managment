"""Immutable rule DTOs produced by the v2 compiler."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, TypeAlias

from .enums import ActionType, ClinicalPhase, RuleSeverity


def freeze(value: Any) -> Any:
    """Recursively freeze JSON-compatible data for deterministic DTOs."""
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class LeafExpression:
    node_id: str
    fact: str
    op: str
    value: Any = None
    unit: str | None = None
    selector: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class AllExpression:
    node_id: str
    children: tuple["Expression", ...]


@dataclass(frozen=True, slots=True)
class AnyExpression:
    node_id: str
    children: tuple["Expression", ...]


@dataclass(frozen=True, slots=True)
class NotExpression:
    node_id: str
    child: "Expression"


Expression: TypeAlias = LeafExpression | AllExpression | AnyExpression | NotExpression


@dataclass(frozen=True, slots=True)
class HardExclusion:
    exclusion_id: str
    condition: Expression
    effect: str
    message_fa: str


@dataclass(frozen=True, slots=True)
class SafetyPolicy:
    redflag_exclusions: tuple[Expression, ...]
    hard_exclusions: tuple[HardExclusion, ...]
    on_safety_error: str


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    schema_version: str
    dsl_version: str
    rule_code: str
    version: str
    title: str
    phase: ClinicalPhase
    action_type: ActionType
    severity: RuleSeverity
    priority: int
    scope: Mapping[str, Any]
    required_facts: tuple[Mapping[str, Any], ...]
    eligibility: Expression
    condition: Expression
    safety: SafetyPolicy
    recommendation: Mapping[str, Any]
    evidence: Mapping[str, Any]
    governance: Mapping[str, Any]
    semantic_key: str | None = None
    legacy_rule_id: int | None = None


@dataclass(frozen=True, slots=True)
class CompiledRule:
    """A validated, typed plan. It contains no patient data or persistence."""

    definition: RuleDefinition
    referenced_fact_keys: frozenset[str]
    node_ids: frozenset[str]
    canonical_json: str
    content_hash: str
