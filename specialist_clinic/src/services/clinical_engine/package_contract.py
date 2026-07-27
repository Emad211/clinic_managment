"""Authoritative intake contract for immutable Clinical Engine rule packages.

The package importer and golden-case validator must agree on exactly the same
manifest, rule documents and validation matrix.  This module performs only
structural/governance checks; it does not approve clinical content or activate a
ruleset.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from src.domain.clinical_engine import RuleOutcome
from src.domain.clinical_engine.release import RULESET_CODE
from src.services.clinical_engine.compiler import RuleCompiler


REQUIRED_CASE_CATEGORIES = frozenset(
    {
        "positive",
        "negative",
        "borderline",
        "missing-data",
        "conflict",
        "historical-as-of",
        "contraindication",
        "suppression",
    }
)
_ALLOWED_EXPECTED_OUTCOMES = frozenset(
    outcome.value for outcome in RuleOutcome if outcome is not RuleOutcome.ERROR
)
_RESERVED_PACKAGE_FILES = frozenset({"manifest.json", "validation-cases.json"})


class RulePackageContractError(ValueError):
    """Raised when a bundled package is ambiguous, incomplete or unsafe to import."""


@dataclass(frozen=True)
class ValidatedRulePackage:
    directory: Path
    manifest: dict[str, Any]
    raw_rules: tuple[dict[str, Any], ...]
    compiled_rules: tuple[Any, ...]
    validation_bundle: dict[str, Any]
    package_hash: str
    case_bundle_hash: str
    rule_codes: tuple[str, ...]


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RulePackageContractError(f"{label} is missing: {path.name}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RulePackageContractError(f"{label} is not valid UTF-8 JSON: {path.name}") from exc
    if not isinstance(raw, dict):
        raise RulePackageContractError(f"{label} must be a JSON object: {path.name}")
    return raw


def _required_text(mapping: Mapping[str, Any], key: str, *, label: str) -> str:
    value = str(mapping.get(key) or "").strip()
    if not value:
        raise RulePackageContractError(f"{label}.{key} is required")
    return value


def _safe_filename(value: Any) -> str:
    filename = str(value or "").strip()
    candidate = Path(filename)
    if (
        not filename
        or candidate.name != filename
        or candidate.suffix.lower() != ".json"
        or filename in _RESERVED_PACKAGE_FILES
    ):
        raise RulePackageContractError(f"unsafe rule filename: {filename!r}")
    return filename


def _validate_review_metadata(raw: Mapping[str, Any], *, filename: str) -> None:
    evidence = raw.get("evidence")
    governance = raw.get("governance")
    if not isinstance(evidence, Mapping) or not isinstance(governance, Mapping):
        raise RulePackageContractError(f"{filename} requires evidence and governance objects")

    for key in (
        "source_title",
        "issuing_organization",
        "publication_date",
        "source_version",
        "source_locator",
        "evidence_certainty",
        "recommendation_strength",
        "local_validation_status",
        "local_adaptation_note",
    ):
        _required_text(evidence, key, label=f"{filename}.evidence")
    source_url = _required_text(evidence, "source_url", label=f"{filename}.evidence")
    if not source_url.startswith("https://"):
        raise RulePackageContractError(f"{filename}.evidence.source_url must use HTTPS")
    try:
        date.fromisoformat(str(evidence["publication_date"]))
    except (TypeError, ValueError) as exc:
        raise RulePackageContractError(
            f"{filename}.evidence.publication_date must be ISO YYYY-MM-DD"
        ) from exc

    if governance.get("status") != "DRAFT":
        raise RulePackageContractError(f"{filename} bundled governance status must be DRAFT")
    _required_text(governance, "author", label=f"{filename}.governance")
    _required_text(governance, "review_due_date", label=f"{filename}.governance")
    _required_text(governance, "change_note", label=f"{filename}.governance")
    try:
        date.fromisoformat(str(governance["review_due_date"]))
    except (TypeError, ValueError) as exc:
        raise RulePackageContractError(
            f"{filename}.governance.review_due_date must be ISO YYYY-MM-DD"
        ) from exc

    # Clinical approval is an authenticated append-only database event.  A bundled
    # source file may describe review work, but cannot carry a static approval.
    if governance.get("clinical_reviewer") not in {None, ""}:
        raise RulePackageContractError(
            f"{filename} cannot embed a clinical reviewer in a DRAFT artifact"
        )
    if evidence.get("local_validation_status") != "NOT_REVIEWED":
        raise RulePackageContractError(
            f"{filename} bundled DRAFT must use local_validation_status=NOT_REVIEWED"
        )


def _validate_case_references(
    expected: Mapping[str, Any],
    *,
    case_id: str,
    rule_codes: set[str],
) -> None:
    for field in (
        "required_missing_facts",
        "forbidden_missing_facts",
        "suppression_reasons",
    ):
        value = expected.get(field) or {}
        if not isinstance(value, Mapping):
            raise RulePackageContractError(f"case {case_id} expected.{field} must be an object")
        unknown = sorted(set(map(str, value)) - rule_codes)
        if unknown:
            raise RulePackageContractError(
                f"case {case_id} expected.{field} references unknown rules: {', '.join(unknown)}"
            )
    redflags = expected.get("redflag_rule_codes")
    if redflags is not None:
        if not isinstance(redflags, list):
            raise RulePackageContractError(
                f"case {case_id} expected.redflag_rule_codes must be an array"
            )
        unknown = sorted(set(map(str, redflags)) - rule_codes)
        if unknown:
            raise RulePackageContractError(
                f"case {case_id} references unknown red flags: {', '.join(unknown)}"
            )


def _validate_cases(
    bundle: Mapping[str, Any],
    *,
    expected_version: str,
    rule_codes: tuple[str, ...],
) -> None:
    if bundle.get("schema_version") != "1.0":
        raise RulePackageContractError("validation bundle schema_version must be 1.0")
    if bundle.get("package_version") != expected_version:
        raise RulePackageContractError("validation bundle targets another package version")
    cases = bundle.get("cases")
    if not isinstance(cases, list) or not cases:
        raise RulePackageContractError("validation bundle must contain at least one case")

    expected_codes = set(rule_codes)
    seen_ids: set[str] = set()
    categories: set[str] = set()
    positive = {code: 0 for code in rule_codes}
    negative = {code: 0 for code in rule_codes}

    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            raise RulePackageContractError(f"validation case {index} must be an object")
        case_id = _required_text(case, "case_id", label=f"cases[{index}]")
        if case_id in seen_ids:
            raise RulePackageContractError(f"duplicate validation case_id: {case_id}")
        seen_ids.add(case_id)

        raw_categories = case.get("categories")
        if not isinstance(raw_categories, list) or not raw_categories:
            raise RulePackageContractError(f"case {case_id} requires categories")
        normalized_categories = {str(value).strip() for value in raw_categories if str(value).strip()}
        if len(normalized_categories) != len(raw_categories):
            raise RulePackageContractError(f"case {case_id} has blank or duplicate categories")
        categories.update(normalized_categories)

        expected = case.get("expected")
        if not isinstance(expected, Mapping):
            raise RulePackageContractError(f"case {case_id} requires expected outcomes")
        outcomes = expected.get("outcomes")
        if not isinstance(outcomes, Mapping):
            raise RulePackageContractError(f"case {case_id} expected.outcomes must be an object")
        outcome_codes = set(map(str, outcomes))
        if outcome_codes != expected_codes:
            missing = sorted(expected_codes - outcome_codes)
            extra = sorted(outcome_codes - expected_codes)
            details = []
            if missing:
                details.append("missing=" + ",".join(missing))
            if extra:
                details.append("unknown=" + ",".join(extra))
            raise RulePackageContractError(
                f"case {case_id} must declare every rule outcome ({'; '.join(details)})"
            )
        for code in rule_codes:
            outcome = str(outcomes[code])
            if outcome not in _ALLOWED_EXPECTED_OUTCOMES:
                raise RulePackageContractError(
                    f"case {case_id} has invalid expected outcome {outcome!r} for {code}"
                )
            if outcome == RuleOutcome.FIRED.value:
                positive[code] += 1
            else:
                negative[code] += 1
        _validate_case_references(expected, case_id=case_id, rule_codes=expected_codes)

    missing_categories = sorted(REQUIRED_CASE_CATEGORIES - categories)
    if missing_categories:
        raise RulePackageContractError(
            "validation bundle misses required categories: " + ", ".join(missing_categories)
        )
    uncovered_positive = sorted(code for code, count in positive.items() if count == 0)
    uncovered_negative = sorted(code for code, count in negative.items() if count == 0)
    if uncovered_positive:
        raise RulePackageContractError(
            "rules without a positive golden case: " + ", ".join(uncovered_positive)
        )
    if uncovered_negative:
        raise RulePackageContractError(
            "rules without a negative golden case: " + ", ".join(uncovered_negative)
        )


def load_rule_package(
    directory: Path,
    *,
    expected_version: str,
    expected_ruleset_code: str = RULESET_CODE,
    compiler: RuleCompiler | None = None,
    case_path: Path | None = None,
) -> ValidatedRulePackage:
    """Load, compile and bind one candidate package to its complete case matrix."""
    root = Path(directory)
    manifest = _read_object(root / "manifest.json", label="package manifest")
    if manifest.get("ruleset_code") != expected_ruleset_code:
        raise RulePackageContractError("manifest ruleset_code does not match runtime")
    if manifest.get("version") != expected_version:
        raise RulePackageContractError("manifest version does not match expected package")
    if manifest.get("status") != "DRAFT" or manifest.get("clinical_use") != "NOT_APPROVED":
        raise RulePackageContractError(
            "bundled package must remain DRAFT and NOT_APPROVED until authenticated review"
        )

    entries = manifest.get("rules")
    if not isinstance(entries, list) or not entries:
        raise RulePackageContractError("manifest must contain at least one rule")
    filenames: set[str] = set()
    sort_orders: set[int] = set()
    raw_rules: list[dict[str, Any]] = []
    compiled_rules = []
    rule_codes: list[str] = []
    semantic_keys: set[str] = set()
    engine_compiler = compiler or RuleCompiler()

    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise RulePackageContractError(f"manifest rule entry {index} must be an object")
        filename = _safe_filename(entry.get("file"))
        if filename in filenames:
            raise RulePackageContractError(f"duplicate manifest rule file: {filename}")
        filenames.add(filename)
        try:
            sort_order = int(entry["sort_order"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RulePackageContractError(f"{filename} requires integer sort_order") from exc
        if sort_order <= 0 or sort_order in sort_orders:
            raise RulePackageContractError(f"duplicate or invalid sort_order: {sort_order}")
        sort_orders.add(sort_order)

        raw = _read_object(root / filename, label="rule document")
        _validate_review_metadata(raw, filename=filename)
        try:
            compiled = engine_compiler.compile(raw)
        except Exception as exc:
            raise RulePackageContractError(f"{filename} failed rule compilation: {exc}") from exc
        if str(entry.get("phase") or "") != compiled.definition.phase.value:
            raise RulePackageContractError(f"{filename} manifest phase disagrees with rule phase")
        code = compiled.definition.rule_code
        if code in rule_codes:
            raise RulePackageContractError(f"duplicate rule_code in package: {code}")
        semantic_key = str(compiled.definition.semantic_key or "").strip()
        if not semantic_key:
            raise RulePackageContractError(f"{filename} requires semantic_key")
        if semantic_key in semantic_keys:
            raise RulePackageContractError(f"duplicate semantic_key in package: {semantic_key}")
        semantic_keys.add(semantic_key)
        rule_codes.append(code)
        raw_rules.append(raw)
        compiled_rules.append(compiled)

    validation_path = Path(case_path) if case_path is not None else root / "validation-cases.json"
    validation_bundle = _read_object(validation_path, label="validation bundle")
    code_tuple = tuple(rule_codes)
    _validate_cases(
        validation_bundle,
        expected_version=expected_version,
        rule_codes=code_tuple,
    )
    return ValidatedRulePackage(
        directory=root,
        manifest=manifest,
        raw_rules=tuple(raw_rules),
        compiled_rules=tuple(compiled_rules),
        validation_bundle=validation_bundle,
        package_hash=content_hash({"manifest": manifest, "rules": raw_rules}),
        case_bundle_hash=content_hash(validation_bundle),
        rule_codes=code_tuple,
    )


__all__ = [
    "REQUIRED_CASE_CATEGORIES",
    "RulePackageContractError",
    "ValidatedRulePackage",
    "canonical_json",
    "content_hash",
    "load_rule_package",
]
