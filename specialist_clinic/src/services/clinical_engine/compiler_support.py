"""Constants and expression compilation helpers for Clinical Engine v2."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.domain.clinical_engine.enums import (
    ActionType,
    ClinicalPhase,
    DiagnosticSeverity,
)
from src.domain.clinical_engine.results import CompilationDiagnostic
from src.domain.clinical_engine.rules import (
    AllExpression,
    AnyExpression,
    Expression,
    LeafExpression,
    NotExpression,
    freeze,
)


SCHEMA_VERSION = "2.0"
DSL_VERSION = "2.0"
SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "domain"
    / "clinical_engine"
    / "schemas"
    / "clinical-rule.schema.json"
)
SUPPORTED_OPERATORS = frozenset(
    {
        "has",
        "not_has",
        "in",
        "truthy",
        "exists",
        "==",
        "!=",
        "between",
        ">=",
        "<=",
        ">",
        "<",
    }
)
SUPPORTED_UNITS = frozenset(
    {
        "%",
        "a",
        "d",
        "cm",
        "m",
        "g",
        "kg",
        "kg/m2",
        "mg/dL",
        "mmol/L",
        "mm[Hg]",
        "mL/min/{1.73_m2}",
        "mg/g",
        "U",
        "U/d",
    }
)
EXPECTED_PHASE = {
    ActionType.REDFLAG: ClinicalPhase.PREFLIGHT,
    ActionType.SAFETY_ALERT: ClinicalPhase.SAFETY,
}
CONFIRMATION_REQUIRED = {
    ActionType.SUGGEST_MED,
    ActionType.SET_TARGET,
    ActionType.CLASSIFY,
}
INTERNAL_TASK_ACTIONS = {
    ActionType.CREATE_FOLLOWUP,
    ActionType.SCHEDULE_SCREENING,
    ActionType.VACCINE,
}


class ExpressionCompilerMixin:
    """Compile a validated expression tree and collect deterministic diagnostics."""

    def _compile_expression(
        self,
        node: Mapping[str, Any],
        path: str,
        node_ids: set[str],
        fact_keys: set[str],
        diagnostics: list[CompilationDiagnostic],
    ) -> Expression:
        node_id = node["node_id"]
        if node_id in node_ids:
            diagnostics.append(
                self._error(
                    "DUPLICATE_NODE_ID",
                    f"{path}.node_id",
                    f"Duplicate node_id {node_id!r}.",
                )
            )
        node_ids.add(node_id)

        if "all" in node:
            return AllExpression(
                node_id,
                tuple(
                    self._compile_expression(
                        child,
                        f"{path}.all[{index}]",
                        node_ids,
                        fact_keys,
                        diagnostics,
                    )
                    for index, child in enumerate(node["all"])
                ),
            )
        if "any" in node:
            return AnyExpression(
                node_id,
                tuple(
                    self._compile_expression(
                        child,
                        f"{path}.any[{index}]",
                        node_ids,
                        fact_keys,
                        diagnostics,
                    )
                    for index, child in enumerate(node["any"])
                ),
            )
        if "not" in node:
            return NotExpression(
                node_id,
                self._compile_expression(
                    node["not"],
                    f"{path}.not",
                    node_ids,
                    fact_keys,
                    diagnostics,
                ),
            )

        fact = node["fact"]
        op = node["op"]
        fact_keys.add(fact)
        if op not in SUPPORTED_OPERATORS:
            diagnostics.append(
                self._error(
                    "UNSUPPORTED_OPERATOR",
                    f"{path}.op",
                    f"Unsupported operator {op!r}.",
                )
            )

        has_value = "value" in node
        if op in {"exists", "truthy"} and has_value:
            diagnostics.append(
                self._error(
                    "UNEXPECTED_OPERATOR_VALUE",
                    f"{path}.value",
                    f"{op} must not define value.",
                )
            )
        if op not in {"exists", "truthy"} and not has_value:
            diagnostics.append(
                self._error(
                    "MISSING_OPERATOR_VALUE",
                    path,
                    f"{op} requires value.",
                )
            )
        if op == "in" and (
            not isinstance(node.get("value"), list)
            or not node["value"]
        ):
            diagnostics.append(
                self._error(
                    "INVALID_IN_VALUE",
                    f"{path}.value",
                    "in requires a non-empty array.",
                )
            )
        if op == "between":
            value = node.get("value")
            if (
                not isinstance(value, list)
                or len(value) != 2
                or not all(self._is_number(item) for item in value)
            ):
                diagnostics.append(
                    self._error(
                        "INVALID_BETWEEN_VALUE",
                        f"{path}.value",
                        "between requires exactly two numeric bounds.",
                    )
                )
            elif value[0] > value[1]:
                diagnostics.append(
                    self._error(
                        "REVERSED_BETWEEN_BOUNDS",
                        f"{path}.value",
                        "between lower bound cannot exceed upper bound.",
                    )
                )
        if op in {">=", "<=", ">", "<"} and not self._is_number(
            node.get("value")
        ):
            diagnostics.append(
                self._error(
                    "INVALID_NUMERIC_COMPARISON",
                    f"{path}.value",
                    f"{op} requires a numeric value.",
                )
            )

        unit = node.get("unit")
        if unit is not None and unit not in SUPPORTED_UNITS:
            diagnostics.append(
                self._error(
                    "UNSUPPORTED_UNIT",
                    f"{path}.unit",
                    f"Unit {unit!r} is not registered.",
                )
            )

        selector = node.get("selector")
        if selector:
            aggregation = selector.get("aggregation", "single")
            temporal = {
                "within_days",
                "count_within_days",
                "recently_completed",
            }
            if aggregation in temporal and "within_days" not in selector:
                diagnostics.append(
                    self._error(
                        "MISSING_SELECTOR_WINDOW",
                        f"{path}.selector",
                        f"{aggregation} requires within_days.",
                    )
                )
            if (
                "within_days" in selector
                and aggregation not in {*temporal, "latest"}
            ):
                diagnostics.append(
                    self._error(
                        "INCOMPATIBLE_SELECTOR_WINDOW",
                        f"{path}.selector",
                        "within_days is incompatible with this aggregation.",
                    )
                )
            if (
                "minimum_count" in selector
                and aggregation
                not in {
                    "count",
                    "count_within_days",
                    "recently_completed",
                }
            ):
                diagnostics.append(
                    self._error(
                        "INCOMPATIBLE_SELECTOR_MINIMUM_COUNT",
                        f"{path}.selector",
                        "minimum_count requires a count or recently_completed "
                        "aggregation.",
                    )
                )

        return LeafExpression(
            node_id=node_id,
            fact=fact,
            op=op,
            value=freeze(node.get("value")),
            unit=unit,
            selector=freeze(selector) if selector is not None else None,
        )

    @staticmethod
    def _is_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    @staticmethod
    def _json_path(parts) -> str:
        path = "$"
        for part in parts:
            path += f"[{part}]" if isinstance(part, int) else f".{part}"
        return path

    @staticmethod
    def _error(
        code: str,
        path: str,
        message: str,
    ) -> CompilationDiagnostic:
        return CompilationDiagnostic(
            code=code,
            path=path,
            message=message,
            severity=DiagnosticSeverity.ERROR,
        )
