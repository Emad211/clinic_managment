"""Immutable compiler/evaluation contracts shared across engine layers."""

from dataclasses import dataclass

from .enums import DiagnosticSeverity, PredicateState, RuleOutcome


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
    message: str | None = None
    fact_keys: tuple[str, ...] = ()
    children: tuple["PredicateResult", ...] = ()


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    rule_code: str
    rule_version: str
    outcome: RuleOutcome
    predicate: PredicateResult
    missing_facts: tuple[str, ...] = ()
    suppression_reasons: tuple[str, ...] = ()
    diagnostics: tuple[CompilationDiagnostic, ...] = ()
