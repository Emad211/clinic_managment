from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    target = ROOT / relative
    text = target.read_text(encoding="utf-8")
    if old in text:
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
        return
    if new in text:
        return
    raise AssertionError(f"regression patch point missing: {relative}: {old[:140]!r}")


replace_once(
    "specialist_clinic/src/services/clinical_engine/validation_harness.py",
    '            "recommendation_present": bool(result.recommendation),',
    '''            "recommendation_present": bool(
                result.outcome is RuleOutcome.FIRED
                and getattr(item.compiled.definition, "recommendation", None)
            ),''',
)

# Activation tests now create the exact validation evidence required by production.
replace_once(
    "specialist_clinic/tests/test_clinical_engine_v2_activation.py",
    '''    db.commit()
    yield app, db
''',
    '''    db.commit()
    from src.services.clinical_engine.validation_service import ClinicalValidationService
    validation = ClinicalValidationService()
    validation_report = validation.run_current(created_by="pytest-validator")
    validation.attest_current(
        role="clinical",
        reviewer="pytest-validation-clinician",
        note="Clinical golden cases reviewed for activation tests.",
        report_hash=validation_report["report_hash"],
    )
    validation.attest_current(
        role="technical",
        reviewer="pytest-validation-engineer",
        note="Determinism, hashes and metrics reviewed for activation tests.",
        report_hash=validation_report["report_hash"],
    )
    yield app, db
''',
)

# Shared current-run support must construct the same report/attestation/seal chain.
replace_once(
    "specialist_clinic/tests/clinical_engine_current_test_support.py",
    '''    report = {
        "schema_version": "1.1",
''',
    '''    from src.services.clinical_engine.validation_service import ClinicalValidationService

    validation_service = ClinicalValidationService()
    validation_report = validation_service.run_current(created_by="pytest-validator")
    try:
        validation_service.attest_current(
            role="clinical",
            reviewer="pytest-validation-clinician",
            note="Clinical current-run contract reviewed.",
            report_hash=validation_report["report_hash"],
        )
    except ValueError as exc:
        if "UNIQUE" not in str(exc):
            raise
    try:
        validation_service.attest_current(
            role="technical",
            reviewer="pytest-validation-engineer",
            note="Technical current-run contract reviewed.",
            report_hash=validation_report["report_hash"],
        )
    except ValueError as exc:
        if "UNIQUE" not in str(exc):
            raise
    validation_evidence = validation_service.current_release_evidence()
    assert validation_evidence

    report = {
        "schema_version": "1.1",
''',
)
replace_once(
    "specialist_clinic/tests/clinical_engine_current_test_support.py",
    '''        "cohort": [],
        "ruleset": dict(ruleset),
''',
    '''        "cohort": [],
        "validation": {
            "status": "PASS",
            "engine_version": CURRENT_ENGINE_VERSION,
            "ruleset_code": RULESET_CODE,
            "package_version": CURRENT_BUNDLED_PACKAGE_VERSION,
            "validation_report_id": validation_evidence["validation_report_id"],
            "validation_report_hash": validation_evidence["validation_report_hash"],
            "package_hash": validation_evidence["package_hash"],
            "case_bundle_hash": validation_evidence["case_bundle_hash"],
        },
        "ruleset": dict(ruleset),
''',
)
replace_once(
    "specialist_clinic/tests/clinical_engine_current_test_support.py",
    '''        "report_hash": report["report_hash"],
        "activated_by": "pytest",
''',
    '''        "report_hash": report["report_hash"],
        "validation_report_id": validation_evidence["validation_report_id"],
        "validation_report_hash": validation_evidence["validation_report_hash"],
        "validation_package_hash": validation_evidence["package_hash"],
        "validation_case_bundle_hash": validation_evidence["case_bundle_hash"],
        "activated_by": "pytest",
''',
)

# The product tree must not retain transition helpers.
for relative in (
    ".github/fix_step7_regressions.py",
    ".github/finalize_step7.py",
    ".github/workflows/finalize-step7.yml",
):
    target = ROOT / relative
    if target.exists():
        target.unlink()
