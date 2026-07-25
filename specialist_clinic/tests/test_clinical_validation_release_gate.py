from __future__ import annotations

import copy
import json
from pathlib import Path
import sqlite3
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.adapters.sqlite.clinical_engine_activation_repo import (
    ClinicalEngineActivationRepository,
    valid_report,
)
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


def _tampered_case_file(tmp_path: Path) -> Path:
    source = json.loads(
        validation_bundle_path().read_text(encoding="utf-8")
    )
    source["cases"][0]["expected"]["outcomes"]["T2-REDFLAG-BP"] = (
        "NOT_FIRED"
    )
    target = tmp_path / "tampered-cases.json"
    target.write_text(
        json.dumps(source, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


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
    assert first["rule_identity_hash"]
    for rule_metrics in first["metrics"].values():
        assert rule_metrics["true_positive"] > 0
        assert rule_metrics["true_negative"] > 0


def test_wrong_expected_outcome_blocks_release_and_status_is_hashed(tmp_path):
    report = GoldenCaseValidationHarness().run(
        case_path=_tampered_case_file(tmp_path)
    )
    assert report["status"] == "BLOCKED"
    assert report["checks"]["all_cases_pass"] is False
    assert report["checks"]["zero_false_positive"] is False

    forged = copy.deepcopy(report)
    forged["status"] = "PASS"
    assert forged["report_hash"] == report["report_hash"]
    # Repository derives status from checks and then validates the status-bound hash.
    app_error = ClinicalValidationError
    with pytest.raises(app_error, match="status"):
        ClinicalValidationReportRepository().create(
            forged,
            created_by="forger",
        )


def test_newest_blocked_report_invalidates_older_pass(validation_app):
    _app, tmp_path = validation_app
    service = ClinicalValidationService()
    passed = service.run_current(created_by="validator")
    assert passed["status"] == "PASS"

    blocked = service.run_current(
        created_by="validator",
        case_path=_tampered_case_file(tmp_path),
    )
    assert blocked["status"] == "BLOCKED"
    repository = ClinicalValidationReportRepository()
    assert repository.latest_current(
        engine_version=CURRENT_ENGINE_VERSION,
        ruleset_code=RULESET_CODE,
        package_version=CURRENT_BUNDLED_PACKAGE_VERSION,
    )["id"] == blocked["id"]
    assert repository.latest_passing(
        engine_version=CURRENT_ENGINE_VERSION,
        ruleset_code=RULESET_CODE,
        package_version=CURRENT_BUNDLED_PACKAGE_VERSION,
    ) is None
    assert service.current_release_evidence(
        activation_report_hash="a" * 64
    ) is None


def test_attestations_are_independent_and_bound_to_activation_report(
    validation_app,
):
    from src.adapters.sqlite.core import get_db

    service = ClinicalValidationService()
    report = service.run_current(created_by="validator")
    activation_hash = "a" * 64
    clinical = service.attest_current(
        role="clinical",
        reviewer="physician-a",
        note="Golden cases and clinical explanations reviewed.",
        report_hash=report["report_hash"],
        activation_report_hash=activation_hash,
    )
    with pytest.raises(ClinicalValidationError, match="must differ"):
        service.attest_current(
            role="technical",
            reviewer="physician-a",
            note="Attempted second-role attestation.",
            report_hash=report["report_hash"],
            activation_report_hash=activation_hash,
        )
    technical = service.attest_current(
        role="technical",
        reviewer="engineer-b",
        note="Determinism, storage and failure metrics reviewed.",
        report_hash=report["report_hash"],
        activation_report_hash=activation_hash,
    )
    assert clinical["role"] == "CLINICAL"
    assert technical["role"] == "TECHNICAL"
    evidence = service.current_release_evidence(
        activation_report_hash=activation_hash,
        package_hash=report["package_hash"],
    )
    assert evidence
    assert evidence["validation_report_id"] == report["id"]
    assert evidence["activation_report_hash"] == activation_hash
    assert service.current_release_evidence(
        activation_report_hash="b" * 64,
        package_hash=report["package_hash"],
    ) is None

    db = get_db()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute(
            "UPDATE clinical_validation_reports SET status='BLOCKED' WHERE id=?",
            (report["id"],),
        )
    db.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        db.execute(
            "DELETE FROM clinical_validation_attestations WHERE id=?",
            (technical["id"],),
        )
    db.rollback()


def _prepare_full_workflow():
    from src.services.clinical_engine.activation import (
        ClinicalEngineActivationService,
    )
    from src.services.clinical_engine.demo_cohort import DemoCohortService
    from src.services.clinical_engine.package_service import (
        ClinicalRulePackageService,
    )

    package_service = ClinicalRulePackageService()
    prepared = package_service.prepare(actor="technical-reviewer")
    projection = package_service.projection()
    package_service.approve_and_freeze(
        int(prepared["id"]),
        reviewer="clinical-rule-reviewer",
        attested_codes=[rule["code"] for rule in projection["rules"]],
        note="All bundled rule scopes and recommendations reviewed.",
    )
    cohort = DemoCohortService()
    cohort.ensure(actor="validation-test", force=True)
    activation = ClinicalEngineActivationService()
    report = activation.build_report(
        as_of_at=cohort.reference_at(),
        created_by="validation-test",
    )
    return activation, report


def test_activation_report_approval_seal_and_ui_are_validation_bound(
    validation_app,
):
    app, tmp_path = validation_app
    from src.adapters.sqlite.clinical_engine_fact_repo import (
        ClinicalEngineFactRepository,
    )

    activation, report = _prepare_full_workflow()
    assert report["status"] == "PASS"
    assert report["validation"]["status"] == "PASS"
    assert report["validation"]["ruleset_identity_match"] is True
    assert valid_report(report)

    activation.approve(
        "clinical",
        reviewer="physician-a",
        report_hash=report["report_hash"],
        note="Clinical validation and cohort report reviewed.",
    )
    activation.approve(
        "technical",
        reviewer="engineer-b",
        report_hash=report["report_hash"],
        note="Technical validation, hashes and deterministic replay reviewed.",
    )
    seal = activation.activate(
        "on_selected",
        activated_by="release-manager",
    )
    assert seal["validation_report_hash"] == report["validation"][
        "validation_report_hash"
    ]
    assert seal["validation_activation_report_hash"] == report["report_hash"]
    assert seal["validation_clinical_attestation_hash"]
    assert seal["validation_technical_attestation_hash"]
    assert seal["validation_release_evidence_hash"]
    assert activation.state.valid_seal("on_selected")
    assert ClinicalEngineFactRepository().get_mode() == "on_selected"

    client = app.test_client()
    logged_in = client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin"},
    )
    assert logged_in.status_code in {302, 303}
    html = client.get(
        "/manager/clinical-engine?step=3#engine-actions"
    ).get_data(as_text=True)
    assert "اعتبارسنجی Golden Case" in html
    assert "ماتریس کیس‌ها" in html
    assert "GC-POS-001" in html
    assert "False Positive" in html

    # A later BLOCKED report makes the prior release evidence and seal stale.
    ClinicalValidationService().run_current(
        created_by="validator",
        case_path=_tampered_case_file(tmp_path),
    )
    assert not ClinicalEngineActivationRepository().valid_seal("on_selected")
    assert ClinicalEngineFactRepository().get_mode() == "off"
