"""Deterministic package-level golden-case validation for Clinical Engine v2."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

from src.domain.clinical_engine import (
    CareSetting,
    ClinicalFact,
    ConflictStatus,
    EncounterStatus,
    EncounterType,
    EvaluationMode,
    FactKind,
    FactSnapshot,
    FactSource,
    FactStatus,
    FreshnessStatus,
    RuleOutcome,
    VerificationStatus,
    longitudinal_context,
    make_context,
)
from src.domain.clinical_engine.release import (
    CURRENT_BUNDLED_PACKAGE_VERSION,
    CURRENT_ENGINE_VERSION,
    RULESET_CODE,
)
from src.services.clinical_engine.compiler import RuleCompiler
from src.services.clinical_engine.package_contract import (
    REQUIRED_CASE_CATEGORIES,
    RulePackageContractError,
    canonical_json,
    content_hash,
    load_rule_package,
)
from src.services.clinical_engine.safety import SafetyKernel
from src.services.clinical_engine.scope_evaluator import ContextualRuleEvaluator


ValidationBundleError = RulePackageContractError


def package_directory(version: str = CURRENT_BUNDLED_PACKAGE_VERSION) -> Path:
    source = (
        Path(__file__).resolve().parents[2]
        / "domain"
        / "clinical_engine"
        / "rule_artifacts"
        / version
    )
    if source.exists():
        return source
    bundle_root = Path(getattr(sys, "_MEIPASS", Path.cwd()))
    return (
        bundle_root
        / "src"
        / "domain"
        / "clinical_engine"
        / "rule_artifacts"
        / version
    )


def validation_bundle_path(
    version: str = CURRENT_BUNDLED_PACKAGE_VERSION,
) -> Path:
    return package_directory(version) / "validation-cases.json"


def _fact_kind(key: str) -> FactKind:
    prefix = str(key).split(".", 1)[0]
    try:
        return FactKind(prefix)
    except ValueError:
        return FactKind.OBSERVATION


def _case_context(case: Mapping[str, Any], *, as_of_at: datetime):
    raw = case.get("context") or {}
    mode = EvaluationMode(raw.get("evaluation_mode", "LONGITUDINAL"))
    setting = CareSetting(raw.get("care_setting", "specialty_clinic"))
    if mode is EvaluationMode.LONGITUDINAL:
        return longitudinal_context(
            1,
            as_of_at=as_of_at,
            care_setting=setting,
            responsible_actor="validation-harness",
        )
    encounter_type = EncounterType(raw.get("encounter_type", "office_visit"))
    return make_context(
        patient_link_id=1,
        context_key=f"validation:{case['case_id']}:{as_of_at.date().isoformat()}",
        evaluation_mode=mode,
        care_setting=setting,
        encounter_type=encounter_type,
        assessment_date=as_of_at.date().isoformat(),
        effective_at=as_of_at,
        recorded_at=as_of_at,
        source="golden-validation-case",
        encounter_key=f"validation-encounter:{case['case_id']}",
        encounter_event_id=int(case.get("sequence", 1)),
        encounter_status=EncounterStatus.OPEN,
        reason_codes=tuple(raw.get("reason_codes") or ()),
        chief_complaint=raw.get("chief_complaint"),
        responsible_actor="validation-harness",
    )


def _case_fact(raw: Mapping[str, Any], *, as_of_at: datetime) -> ClinicalFact:
    key = str(raw["key"])
    fact_id = str(raw.get("fact_id") or f"case:{key}")
    offset_days = int(raw.get("effective_days_before", 0))
    effective = as_of_at - timedelta(days=offset_days)
    recorded_offset = int(raw.get("recorded_days_before", offset_days))
    recorded = as_of_at - timedelta(days=recorded_offset)
    if effective > recorded:
        raise ValidationBundleError(
            f"fact {fact_id} has effective_at after recorded_at"
        )
    return ClinicalFact(
        schema_version="2.0",
        fact_id=fact_id,
        patient_link_id=1,
        kind=FactKind(raw.get("kind", _fact_kind(key).value)),
        key=key,
        status=FactStatus(raw.get("status", "PRESENT")),
        value=raw.get("value"),
        unit=raw.get("unit"),
        effective_at=effective,
        recorded_at=recorded,
        source=FactSource(
            str(raw.get("source_system") or "golden-case"),
            str(raw.get("source_record_id") or fact_id),
            "validation-harness",
        ),
        verification=VerificationStatus(
            raw.get("verification", "CONFIRMED")
        ),
        freshness=FreshnessStatus(raw.get("freshness", "FRESH")),
        conflict=ConflictStatus(raw.get("conflict", "NONE")),
        warnings=tuple(raw.get("warnings") or ()),
    )


def _snapshot(case: Mapping[str, Any]) -> FactSnapshot:
    try:
        as_of_at = datetime.fromisoformat(str(case["as_of_at"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise ValidationBundleError(
            f"case {case.get('case_id')} has invalid as_of_at"
        ) from exc
    context = _case_context(case, as_of_at=as_of_at)
    facts = tuple(
        _case_fact(raw, as_of_at=as_of_at)
        for raw in (case.get("facts") or ())
    )
    snapshot_body = {
        "case_id": case["case_id"],
        "as_of_at": as_of_at.isoformat(sep=" ", timespec="seconds"),
        "context_hash": context.content_hash,
        "facts": [
            {
                "fact_id": fact.fact_id,
                "key": fact.key,
                "status": fact.status.value,
                "value": fact.value,
                "unit": fact.unit,
                "verification": fact.verification.value,
                "freshness": fact.freshness.value,
                "conflict": fact.conflict.value,
                "effective_at": fact.effective_at.isoformat(),
                "recorded_at": fact.recorded_at.isoformat(),
            }
            for fact in facts
        ],
    }
    return FactSnapshot(
        schema_version="2.0",
        patient_link_id=1,
        as_of_at=as_of_at,
        facts=facts,
        content_hash=content_hash(snapshot_body),
        encounter_key=context.encounter_key,
        evaluation_context=context,
        clinical_data_revision=0,
    )


def _load_package(version: str, *, case_path: Path | None = None):
    return load_rule_package(
        package_directory(version),
        expected_version=version,
        expected_ruleset_code=RULESET_CODE,
        compiler=RuleCompiler(),
        case_path=case_path,
    )


def _result_payload(run) -> dict[str, Any]:
    evaluations = {}
    for item in run.evaluations:
        result = item.result
        evaluations[item.compiled.definition.rule_code] = {
            "outcome": result.outcome.value,
            "predicate_state": result.predicate.state.value,
            "missing_facts": list(result.missing_facts),
            "error_code": result.error_code,
            "suppression_reason": (
                result.suppression.reason_code if result.suppression else None
            ),
            "recommendation_present": bool(
                result.outcome is RuleOutcome.FIRED
                and getattr(item.compiled.definition, "recommendation", None)
            ),
            "fact_ids": list(result.predicate.fact_ids),
            "fact_keys": list(result.predicate.fact_keys),
            "trace_hash": content_hash(
                {
                    "node_id": result.predicate.node_id,
                    "state": result.predicate.state.value,
                    "reason_code": result.predicate.reason_code,
                    "fact_ids": list(result.predicate.fact_ids),
                    "fact_keys": list(result.predicate.fact_keys),
                }
            ),
        }
    return {
        "run_status": run.status.value,
        "redflag_rule_codes": list(run.redflag_rule_codes),
        "routine_outputs_blocked": bool(run.routine_outputs_blocked),
        "evaluations": evaluations,
    }


def _case_assertions(case: Mapping[str, Any], actual: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    expected = case.get("expected") or {}
    expected_outcomes = expected.get("outcomes") or {}
    actual_evaluations = actual["evaluations"]
    for rule_code, outcome in expected_outcomes.items():
        if rule_code not in actual_evaluations:
            failures.append(f"{rule_code}:evaluation_missing")
            continue
        observed = actual_evaluations[rule_code]["outcome"]
        if observed != outcome:
            failures.append(
                f"{rule_code}:outcome_expected_{outcome}_observed_{observed}"
            )
    if expected.get("run_status") and actual["run_status"] != expected["run_status"]:
        failures.append(
            f"run_status_expected_{expected['run_status']}_observed_{actual['run_status']}"
        )
    if "redflag_rule_codes" in expected and sorted(actual["redflag_rule_codes"]) != sorted(
        expected["redflag_rule_codes"]
    ):
        failures.append("redflag_rule_codes_mismatch")
    for rule_code, required in (expected.get("required_missing_facts") or {}).items():
        observed = set(actual_evaluations.get(rule_code, {}).get("missing_facts") or ())
        missing = sorted(set(required) - observed)
        if missing:
            failures.append(f"{rule_code}:missing_fact_assertion_failed:{','.join(missing)}")
    for rule_code, forbidden in (expected.get("forbidden_missing_facts") or {}).items():
        observed = set(actual_evaluations.get(rule_code, {}).get("missing_facts") or ())
        present = sorted(set(forbidden) & observed)
        if present:
            failures.append(f"{rule_code}:forbidden_missing_facts:{','.join(present)}")
    for rule_code, reason in (expected.get("suppression_reasons") or {}).items():
        observed = actual_evaluations.get(rule_code, {}).get("suppression_reason")
        if observed != reason:
            failures.append(
                f"{rule_code}:suppression_expected_{reason}_observed_{observed}"
            )
    return failures


def _empty_metrics() -> dict[str, int]:
    return {
        "true_positive": 0,
        "true_negative": 0,
        "false_positive": 0,
        "false_negative": 0,
        "needs_data": 0,
        "error": 0,
        "suppressed": 0,
        "not_applicable": 0,
    }


class GoldenCaseValidationHarness:
    def __init__(self, *, kernel=None):
        self.kernel = kernel or SafetyKernel(evaluator=ContextualRuleEvaluator())

    def load_cases(self, path: Path | None = None) -> dict[str, Any]:
        source = path or validation_bundle_path()
        bundle = json.loads(source.read_text(encoding="utf-8"))
        if bundle.get("schema_version") != "1.0":
            raise ValidationBundleError("unsupported validation bundle version")
        case_ids = [case.get("case_id") for case in bundle.get("cases") or ()]
        if not case_ids or any(not value for value in case_ids):
            raise ValidationBundleError("every validation case requires case_id")
        if len(case_ids) != len(set(case_ids)):
            raise ValidationBundleError("validation case_id values must be unique")
        return bundle

    def run(
        self,
        *,
        package_version: str = CURRENT_BUNDLED_PACKAGE_VERSION,
        case_path: Path | None = None,
    ) -> dict[str, Any]:
        package = _load_package(package_version, case_path=case_path)
        manifest = package.manifest
        compiled_rules = package.compiled_rules
        package_hash = package.package_hash
        bundle = package.validation_bundle
        cases = bundle.get("cases") or ()
        metrics = {
            rule.definition.rule_code: _empty_metrics()
            for rule in compiled_rules
        }
        categories: set[str] = set()
        rows = []
        deterministic = True

        for sequence, raw_case in enumerate(cases, start=1):
            case = {**raw_case, "sequence": sequence}
            case_categories = {str(value) for value in case.get("categories") or ()}
            categories.update(case_categories)
            snapshot = _snapshot(case)
            first = _result_payload(
                self.kernel.evaluate(compiled_rules, snapshot)
            )
            second = _result_payload(
                self.kernel.evaluate(compiled_rules, snapshot)
            )
            result_hash = content_hash(first)
            replay_hash = content_hash(second)
            case_deterministic = result_hash == replay_hash
            deterministic = deterministic and case_deterministic
            failures = _case_assertions(case, first)
            if not case_deterministic:
                failures.append("nondeterministic_replay")

            expected_outcomes = (case.get("expected") or {}).get("outcomes") or {}
            for rule_code, observed in first["evaluations"].items():
                outcome = observed["outcome"]
                if outcome == RuleOutcome.NEEDS_DATA.value:
                    metrics[rule_code]["needs_data"] += 1
                elif outcome == RuleOutcome.ERROR.value:
                    metrics[rule_code]["error"] += 1
                elif outcome == RuleOutcome.SUPPRESSED.value:
                    metrics[rule_code]["suppressed"] += 1
                elif outcome == RuleOutcome.NOT_APPLICABLE.value:
                    metrics[rule_code]["not_applicable"] += 1
                if rule_code not in expected_outcomes:
                    continue
                expected_positive = expected_outcomes[rule_code] == RuleOutcome.FIRED.value
                actual_positive = outcome == RuleOutcome.FIRED.value
                metric = (
                    "true_positive" if expected_positive and actual_positive
                    else "false_negative" if expected_positive
                    else "false_positive" if actual_positive
                    else "true_negative"
                )
                metrics[rule_code][metric] += 1

            rows.append(
                {
                    "case_id": case["case_id"],
                    "title": case.get("title"),
                    "categories": sorted(case_categories),
                    "passed": not failures,
                    "failures": failures,
                    "snapshot_hash": snapshot.content_hash,
                    "result_hash": result_hash,
                    "actual": first,
                }
            )

        missing_categories = sorted(REQUIRED_CASE_CATEGORIES - categories)
        totals = {
            key: sum(rule_metrics[key] for rule_metrics in metrics.values())
            for key in _empty_metrics()
        }
        checks = {
            "all_cases_pass": all(row["passed"] for row in rows),
            "deterministic_replay": deterministic,
            "required_case_categories": not missing_categories,
            "zero_false_positive": totals["false_positive"] == 0,
            "zero_false_negative": totals["false_negative"] == 0,
            "zero_errors": totals["error"] == 0,
            "every_rule_has_positive_case": all(
                value["true_positive"] > 0 for value in metrics.values()
            ),
            "every_rule_has_negative_case": all(
                value["true_negative"] > 0 for value in metrics.values()
            ),
        }
        report_body = {
            "schema_version": "1.0",
            "engine_version": CURRENT_ENGINE_VERSION,
            "ruleset_code": manifest.get("ruleset_code", RULESET_CODE),
            "package_version": package_version,
            "package_hash": package_hash,
            "case_bundle_hash": content_hash(bundle),
            "case_count": len(rows),
            "categories": sorted(categories),
            "missing_categories": missing_categories,
            "checks": checks,
            "metrics": metrics,
            "totals": totals,
            "cases": rows,
        }
        report_body["status"] = (
            "PASS" if all(checks.values()) else "BLOCKED"
        )
        return {
            **report_body,
            "report_hash": content_hash(report_body),
        }
