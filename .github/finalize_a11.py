from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPECIALIST = ROOT / "specialist_clinic"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = content.rstrip() + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == normalized:
        return
    path.write_text(normalized, encoding="utf-8")


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"A11 anchor missing in {path}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


write(
    SPECIALIST / "src/services/clinical_engine/package_contract.py",
    r'''"""Authoritative intake contract for immutable Clinical Engine rule packages.

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
''',
)

package_service = SPECIALIST / "src/services/clinical_engine/package_service.py"
replace_once(
    package_service,
    "from src.services.clinical_engine.compiler import RuleCompiler\nfrom src.common.utils import iran_now\n",
    "from src.services.clinical_engine.compiler import RuleCompiler\n"
    "from src.services.clinical_engine.package_contract import load_rule_package\n"
    "from src.common.utils import iran_now\n",
)
replace_once(
    package_service,
    '''        package_dir = _package_dir()
        manifest_path = package_dir / "manifest.json"
        if not manifest_path.exists():
            raise LookupError("فایل بستهٔ قواعد در برنامه پیدا نشد")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
''',
    '''        package = load_rule_package(
            _package_dir(),
            expected_version=PACKAGE_VERSION,
            expected_ruleset_code=RULESET_CODE,
            compiler=self.compiler,
        )
        manifest = package.manifest
''',
)
replace_once(
    package_service,
    '''        members = []
        for item in manifest.get("rules") or []:
            raw = json.loads((package_dir / item["file"]).read_text(encoding="utf-8"))
            compiled = self.compiler.compile(raw)
''',
    '''        members = []
        for item, compiled in zip(
            manifest.get("rules") or [], package.compiled_rules, strict=True
        ):
''',
)
replace_once(
    package_service,
    '''        if not reviewer or not note:
            raise ValueError("نام بازبین و یادداشت بالینی الزامی است")
        ruleset = self.rules.get_ruleset(int(ruleset_id))
''',
    '''        if not reviewer or not note:
            raise ValueError("نام بازبین و یادداشت بالینی الزامی است")
        package = load_rule_package(
            _package_dir(),
            expected_version=PACKAGE_VERSION,
            expected_ruleset_code=RULESET_CODE,
            compiler=self.compiler,
        )
        ruleset = self.rules.get_ruleset(int(ruleset_id))
''',
)
replace_once(
    package_service,
    '''        expected = {member["rule_code"] for member in ruleset["members"]}
        if set(attested_codes or []) != expected:
''',
    '''        expected = {member["rule_code"] for member in ruleset["members"]}
        if expected != set(package.rule_codes):
            raise ValueError("اعضای بستهٔ ذخیره‌شده با بستهٔ immutable برنامه یکسان نیستند")
        if set(attested_codes or []) != expected:
''',
)
replace_once(
    package_service,
    '''            f"Clinically approved and froze ruleset {ruleset_id}: {note}",
''',
    '''            f"Clinically approved and froze ruleset {ruleset_id}: {note}; "
            f"package={package.package_hash}; cases={package.case_bundle_hash}",
''',
)

validation_harness = SPECIALIST / "src/services/clinical_engine/validation_harness.py"
replace_once(
    validation_harness,
    '''from src.services.clinical_engine.compiler import RuleCompiler
from src.services.clinical_engine.safety import SafetyKernel
''',
    '''from src.services.clinical_engine.compiler import RuleCompiler
from src.services.clinical_engine.package_contract import (
    REQUIRED_CASE_CATEGORIES,
    RulePackageContractError,
    canonical_json,
    content_hash,
    load_rule_package,
)
from src.services.clinical_engine.safety import SafetyKernel
''',
)
replace_once(
    validation_harness,
    '''REQUIRED_CASE_CATEGORIES = frozenset(
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


class ValidationBundleError(ValueError):
    pass


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
''',
    '''ValidationBundleError = RulePackageContractError
''',
)
replace_once(
    validation_harness,
    '''def _load_package(version: str):
    directory = package_directory(version)
    manifest = json.loads(
        (directory / "manifest.json").read_text(encoding="utf-8")
    )
    if manifest.get("version") != version:
        raise ValidationBundleError("manifest version does not match package")
    compiler = RuleCompiler()
    rules = []
    raw_documents = []
    for item in manifest.get("rules") or ():
        raw = json.loads(
            (directory / item["file"]).read_text(encoding="utf-8")
        )
        raw_documents.append(raw)
        rules.append(compiler.compile(raw))
    if not rules:
        raise ValidationBundleError("package has no rules")
    package_hash = content_hash(
        {"manifest": manifest, "rules": raw_documents}
    )
    return manifest, tuple(rules), package_hash
''',
    '''def _load_package(version: str, *, case_path: Path | None = None):
    return load_rule_package(
        package_directory(version),
        expected_version=version,
        expected_ruleset_code=RULESET_CODE,
        compiler=RuleCompiler(),
        case_path=case_path,
    )
''',
)
replace_once(
    validation_harness,
    '''        manifest, compiled_rules, package_hash = _load_package(package_version)
        bundle = self.load_cases(case_path)
        if bundle.get("package_version") != package_version:
            raise ValidationBundleError(
                "validation bundle targets another package version"
            )
''',
    '''        package = _load_package(package_version, case_path=case_path)
        manifest = package.manifest
        compiled_rules = package.compiled_rules
        package_hash = package.package_hash
        bundle = package.validation_bundle
''',
)

current_package_test = SPECIALIST / "tests/test_clinical_engine_v2_current_package.py"
replace_once(
    current_package_test,
    '''from src.domain.clinical_engine import RuleOutcome
from src.services.clinical_engine.compiler import RuleCompiler
''',
    '''from src.domain.clinical_engine import RuleOutcome
from src.domain.clinical_engine.release import CURRENT_BUNDLED_PACKAGE_VERSION
from src.services.clinical_engine.compiler import RuleCompiler
''',
)
replace_once(
    current_package_test,
    '''    / "2026.1-draft.2"
''',
    '''    / CURRENT_BUNDLED_PACKAGE_VERSION
''',
)
replace_once(
    current_package_test,
    '''def _rules():
    compiler = RuleCompiler()
    return [
        compiler.compile(json.loads((CURRENT_PACKAGE / filename).read_text(encoding="utf-8")))
        for filename in ("T2-REDFLAG-BP.json", "T2-SAFE-MET-STOP.json")
    ]
''',
    '''def _rules():
    compiler = RuleCompiler()
    manifest = json.loads(
        (CURRENT_PACKAGE / "manifest.json").read_text(encoding="utf-8")
    )
    return [
        compiler.compile(
            json.loads((CURRENT_PACKAGE / item["file"]).read_text(encoding="utf-8"))
        )
        for item in manifest["rules"]
    ]
''',
)

write(
    SPECIALIST / "tests/test_clinical_rule_package_contract.py",
    r'''"""A11 intake gates for governed Clinical Engine rule-library packages."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.domain.clinical_engine.release import (
    CURRENT_BUNDLED_PACKAGE_VERSION,
    RULESET_CODE,
)
from src.services.clinical_engine.package_contract import (
    REQUIRED_CASE_CATEGORIES,
    RulePackageContractError,
    load_rule_package,
)
from src.services.clinical_engine.validation_harness import (
    GoldenCaseValidationHarness,
    package_directory,
)


def _copy_package(tmp_path: Path) -> Path:
    target = tmp_path / "candidate"
    shutil.copytree(package_directory(), target)
    return target


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _load(path: Path):
    return load_rule_package(
        path,
        expected_version=CURRENT_BUNDLED_PACKAGE_VERSION,
        expected_ruleset_code=RULESET_CODE,
    )


def test_current_package_has_one_authoritative_manifest_case_and_hash_contract():
    package = _load(package_directory())
    report = GoldenCaseValidationHarness().run()

    assert package.rule_codes == tuple(
        item["rule_code"] for item in package.raw_rules
    )
    assert package.package_hash == report["package_hash"]
    assert package.case_bundle_hash == report["case_bundle_hash"]
    assert REQUIRED_CASE_CATEGORIES <= {
        category
        for case in package.validation_bundle["cases"]
        for category in case["categories"]
    }
    assert set(report["metrics"]) == set(package.rule_codes)


def test_manifest_version_and_ruleset_are_runtime_bound(tmp_path):
    candidate = _copy_package(tmp_path)
    manifest_path = candidate / "manifest.json"
    manifest = _json(manifest_path)
    manifest["version"] = "other-package"
    _write(manifest_path, manifest)

    with pytest.raises(RulePackageContractError, match="manifest version"):
        _load(candidate)


def test_manifest_cannot_escape_package_directory(tmp_path):
    candidate = _copy_package(tmp_path)
    manifest_path = candidate / "manifest.json"
    manifest = _json(manifest_path)
    manifest["rules"][0]["file"] = "../outside.json"
    _write(manifest_path, manifest)

    with pytest.raises(RulePackageContractError, match="unsafe rule filename"):
        _load(candidate)


def test_duplicate_semantic_identity_is_rejected_before_import(tmp_path):
    candidate = _copy_package(tmp_path)
    manifest = _json(candidate / "manifest.json")
    first = _json(candidate / manifest["rules"][0]["file"])
    second_path = candidate / manifest["rules"][1]["file"]
    second = _json(second_path)
    second["semantic_key"] = first["semantic_key"]
    _write(second_path, second)

    with pytest.raises(RulePackageContractError, match="duplicate semantic_key"):
        _load(candidate)


def test_every_case_must_declare_every_manifest_rule(tmp_path):
    candidate = _copy_package(tmp_path)
    cases_path = candidate / "validation-cases.json"
    bundle = _json(cases_path)
    removed = next(iter(bundle["cases"][0]["expected"]["outcomes"]))
    del bundle["cases"][0]["expected"]["outcomes"][removed]
    _write(cases_path, bundle)

    with pytest.raises(RulePackageContractError, match="must declare every rule outcome"):
        _load(candidate)


def test_expected_error_is_not_an_acceptable_golden_outcome(tmp_path):
    candidate = _copy_package(tmp_path)
    cases_path = candidate / "validation-cases.json"
    bundle = _json(cases_path)
    code = next(iter(bundle["cases"][0]["expected"]["outcomes"]))
    bundle["cases"][0]["expected"]["outcomes"][code] = "ERROR"
    _write(cases_path, bundle)

    with pytest.raises(RulePackageContractError, match="invalid expected outcome"):
        _load(candidate)


def test_static_clinical_approval_cannot_be_embedded_in_draft_json(tmp_path):
    candidate = _copy_package(tmp_path)
    manifest = _json(candidate / "manifest.json")
    rule_path = candidate / manifest["rules"][0]["file"]
    rule = _json(rule_path)
    rule["governance"]["clinical_reviewer"] = "embedded-reviewer"
    _write(rule_path, rule)

    with pytest.raises(RulePackageContractError, match="cannot embed a clinical reviewer"):
        _load(candidate)
''',
)

write(
    SPECIALIST / "docs/clinical_rule_library_intake_contract.md",
    r'''# A11 — قرارداد ورود کتابخانهٔ قواعد بالینی

## هدف

A11 هیچ threshold یا توصیهٔ بالینی تازه‌ای اضافه نمی‌کند. هدف آن است که پیش از توسعهٔ Rule Library، یک بستهٔ ناقص یا مبهم نتواند وارد مسیر import، shadow validation یا activation شود.

## منبع حقیقت واحد

```text
manifest.json
+ immutable rule JSON files
+ validation-cases.json
→ package contract
→ compiler/import
→ deterministic validation
→ append-only clinical + technical attestation
→ shadow/pilot/activation
```

import و validation هر دو از `package_contract.py` استفاده می‌کنند و hash بسته و case bundle را از همان محتوای canonical می‌سازند.

## Gateهای بسته

- version و `ruleset_code` باید دقیقاً با runtime جاری برابر باشند.
- artifact bundled همیشه `DRAFT / NOT_APPROVED` می‌ماند؛ approval واقعی داخل فایل JSON جاسازی نمی‌شود.
- filename امن و داخل همان package، sort order یکتا و phase منطبق الزامی است.
- `rule_code` و `semantic_key` در یک بسته یکتا هستند.
- evidence دارای منبع، سازمان، نسخه، locator، URL امن و وضعیت validation صریح است.
- هر golden case نتیجهٔ تمام Ruleهای manifest را مشخص می‌کند.
- `ERROR` نتیجهٔ مورد انتظار قابل قبول نیست.
- categoryهای positive، negative، borderline، missing-data، conflict، historical، contraindication و suppression پوشش داده می‌شوند.
- هر Rule حداقل یک positive و یک non-positive case دارد.
- import بستهٔ ذخیره‌شده را با package immutable برنامه دوباره تطبیق می‌دهد.

## مرز ایمنی

عبور A11 به معنی تأیید بالینی دو Rule فعلی نیست. بستهٔ `2026.1-draft.2` همچنان `NOT_REVIEWED` است و فقط پس از validation، تأیید مستقل بالینی/فنی، pilot و seal دقیق می‌تواند وارد rollout قابل مشاهده شود.

## مرحلهٔ بعد

Ruleهای جدید باید در trancheهای کوچک و بیماری‌محور اضافه شوند. برای هر Rule، evidence review، تصمیم مالک بالینی، Fact/Unit canonical، eligibility و exclusion اجرایی، golden matrix، dependency analysis، بازبینی پزشک، shadow و pilot مستقل لازم است.
''',
)

print("A11 package intake contract finalized")
