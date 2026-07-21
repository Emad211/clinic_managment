"""Immutable compiler/evaluation contracts shared across engine layers."""

from dataclasses import dataclass
from typing import Any

from .enums import ClinicalPhase, DiagnosticSeverity, PredicateState, RuleOutcome


@dataclass(frozen=True, slots=True)
class CompilationDiagnostic:
    code: str
    message: str
    path: str = "$"
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR


class RuleCompilationError(ValueError):
    """Raised when a rule cannot safely become a CompiledRule."""

    def __init__(self, diagnostics: tuple[CompilationDiagnostic, ...]):
        self.diagnostics = diagnostics
        summary = "; ".join(
            f"{item.code} at {item.path}: {item.message}" for item in diagnostics
        )
        super().__init__(summary or "Rule compilation failed")


@dataclass(frozen=True, slots=True)
class PredicateResult:
    node_id: str
    state: PredicateState
    kind: str = "PREDICATE"
    message: str | None = None
    fact_keys: tuple[str, ...] = ()
    fact_ids: tuple[str, ...] = ()
    actual: Any = None
    expected: Any = None
    reason_code: str | None = None
    data_issues: tuple["DataIssue", ...] = ()
    children: tuple["PredicateResult", ...] = ()


@dataclass(frozen=True, slots=True)
class DataIssue:
    fact_key: str
    issue: str
    message_fa: str


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    rule_code: str
    rule_version: str
    outcome: RuleOutcome
    predicate: PredicateResult
    phase: ClinicalPhase = ClinicalPhase.ROUTINE
    data_issues: tuple[DataIssue, ...] = ()
    missing_facts: tuple[str, ...] = ()
    suppression_reasons: tuple[str, ...] = ()
    diagnostics: tuple[CompilationDiagnostic, ...] = ()
    error_code: str | None = None
    error_message: str | None = None
