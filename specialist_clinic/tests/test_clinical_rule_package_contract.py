"""A11 intake gates for governed Clinical Engine rule-library packages."""
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
