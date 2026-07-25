"""Final pre-library validation and release-gate contracts."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.adapters.sqlite.clinical_validation_repo import (
    ClinicalValidationError,
    ClinicalValidationReportRepository,
)
from src.domain.clinical_engine.release import (
    CURRENT_BUNDLED_PACKAGE_VERSION,
    CURRENT_ENGINE_VERSION,
    RULESET_CODE,
)
from src.services.clinical_engine.validation_harness import (
    GoldenCaseValidationHarness,
    REQUIRED_CASE_CATEGORIES,
    validation_bundle_path,
)
from src.services.clinical_engine.validation_service import (
    ClinicalValidationService,
)


@pytest.fixture()
def validation_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "validation.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "validation-gate-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app, tmp_path
    context.pop()
    core._initialized = False


def test_current_package_golden_cases_pass_and_replay_deterministically():
    harness = GoldenCaseValidationHarness()
    first = harness.run()
    second = harness.run()

    assert first["status"] == "PASS"
    assert first["report_hash"] == second["report_hash"]
    assert first["package_version"] == CURRENT_BUNDLED_PACKAGE_VERSION
    assert first["engine_version"] == CURRENT_ENGINE_VERSION
    assert REQUIRED_CASE_CATEGORIES <= set(first["categories"])
    assert first["totals"]["false_positive"] == 0
    assert first["totals"]["false_negative"] == 0
    assert first["totals"]["error"] == 0
    assert all(first["checks"].values())
    assert all(row["passed"] for row in first["cases"])
    for rule_metrics in first["metrics"].values():
        assert rule_metrics["true_positive"] > 0
        assert rule_metrics["true_negative"] > 0


def test_wrong_expected_outcome_blocks_release(tmp_path):
    source = json.loads(
        validation_bundle_path().read_text(encoding="utf-8")
    )
    source["cases"][0]["expected"]["outcomes"]["T2-REDFLAG-BP"] = "NOT_FIRED"
    tampered = tmp_path / "tampered-cases.json"
    tampered.write_text(
        json.dumps(source, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    report = GoldenCaseValidationHarness().run(case_path=tampered)
    assert report["status"] == "BLOCKED"
    assert report["checks"]["all_cases_pass"] is False
    assert report["checks"]["zero_false_positive"] is False
    failed = next(row for row in report["cases"] if row["case_id"] == "GC-POS-001")
    assert failed["passed"] is False
    assert any("outcome_expected" in item for item in failed["failures"])


def test_validation_reports_are_append_only_and_require_independent_attestation(
    validation_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    service = ClinicalValidationService()
    stored = service.run_current(created_by="validator")
    assert stored["status"] == "PASS"

    clinical = service.attest_current(
        role="clinical",
        reviewer="physician-a",
        note="Golden cases and clinical explanations reviewed.",
        report_hash=stored["report_hash"],
    )
    with pytest.raises(ClinicalValidationError, match="must differ"):
        service.attest_current(
            role="technical",
            reviewer="physician-a",
            note="Attempted second-role attestation.",
            report_hash=stored["report_hash"],
        )
    technical = service.attest_current(
        role="technical",
        reviewer="engineer-b",
        note="Determinism, storage and failure metrics reviewed.",
        report_hash=stored["report_hash"],
    )
    assert clinical["role"] == "CLINICAL"
    assert technical["role"] == "TECHNICAL"
    evidence = service.current_release_evidence()
    assert evidence
    assert evidence["validation_report_id"] == stored["id"]
    assert evidence["validation_report_hash"] == stored["report_hash"]

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute(
            "UPDATE clinical_validation_reports SET status='BLOCKED' WHERE id=?",
            (stored["id"],),
        )
    db.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        db.execute(
            "DELETE FROM clinical_validation_attestations WHERE id=?",
            (technical["id"],),
        )
    db.rollback()


def test_release_reference_is_exact_to_engine_package_and_hash(validation_app):
    service = ClinicalValidationService()
    report = service.run_current(created_by="validator")
    service.attest_current(
        role="clinical",
        reviewer="physician-a",
        note="Clinical release review complete.",
        report_hash=report["report_hash"],
    )
    service.attest_current(
        role="technical",
        reviewer="engineer-b",
        note="Technical release review complete.",
        report_hash=report["report_hash"],
    )
    repository = ClinicalValidationReportRepository()
    assert repository.verify_release_reference(
        report_id=report["id"],
        report_hash=report["report_hash"],
        engine_version=CURRENT_ENGINE_VERSION,
        ruleset_code=RULESET_CODE,
        package_version=CURRENT_BUNDLED_PACKAGE_VERSION,
        package_hash=report["package_hash"],
    )
    assert not repository.verify_release_reference(
        report_id=report["id"],
        report_hash="0" * 64,
        engine_version=CURRENT_ENGINE_VERSION,
        ruleset_code=RULESET_CODE,
        package_version=CURRENT_BUNDLED_PACKAGE_VERSION,
        package_hash=report["package_hash"],
    )
    assert not repository.verify_release_reference(
        report_id=report["id"],
        report_hash=report["report_hash"],
        engine_version="other-engine",
        ruleset_code=RULESET_CODE,
        package_version=CURRENT_BUNDLED_PACKAGE_VERSION,
        package_hash=report["package_hash"],
    )
