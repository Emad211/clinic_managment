"""Single-operator end-to-end activation via ClinicalEngineActivationService.simple_activate."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def simple_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "simple-activate.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "simple-activate-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app, tmp_path
    context.pop()
    core._initialized = False


def _freeze_bundled_package(actor: str) -> int:
    from src.services.clinical_engine.package_service import (
        ClinicalRulePackageService,
    )

    service = ClinicalRulePackageService()
    ruleset = service.prepare(actor=actor)
    decisions = {
        member["rule_code"]: "APPROVE" for member in ruleset["members"]
    }
    service.review_rules(
        ruleset["id"], role="technical", decisions=decisions,
        actor_username=actor, reviewer_display_name="مدیر کلینیک",
        note="technical review by the single operator",
    )
    service.review_rules(
        ruleset["id"], role="clinical", decisions=decisions,
        actor_username=actor, reviewer_display_name="مدیر کلینیک",
        note="clinical review by the single operator",
    )
    frozen = service.freeze_reviewed_package(
        ruleset["id"], activated_by=actor, note="single-operator freeze",
    )
    assert frozen["status"] == "SILENT"
    return int(ruleset["id"])


def test_simple_activate_reaches_global_on_with_one_operator(simple_app):
    from src.adapters.sqlite.clinical_engine_activation_repo import (
        ClinicalEngineActivationRepository,
    )
    from src.adapters.sqlite.clinical_engine_fact_repo import (
        ClinicalEngineFactRepository,
    )
    from src.adapters.sqlite.clinical_engine_rules_repo import (
        ClinicalEngineRulesRepository,
    )
    from src.services.clinical_engine.activation import (
        ClinicalEngineActivationService,
    )

    _app, _tmp_path = simple_app
    ruleset_id = _freeze_bundled_package("single-operator")

    service = ClinicalEngineActivationService()
    seal = service.simple_activate(
        "on",
        actor="single-operator",
        display_name="مدیر کلینیک",
        note="راه‌اندازی تک‌اپراتور تأیید شد",
    )

    state = ClinicalEngineActivationRepository()
    assert seal["mode"] == "on"
    assert state.valid_seal("on")
    assert ClinicalEngineFactRepository().get_mode() == "on"
    approvals = {
        role: state.get_json(f"approval_{role}")
        for role in ("clinical", "technical")
    }
    assert approvals["clinical"]["reviewer"] == "مدیر کلینیک"
    assert approvals["technical"]["reviewer"] == "مدیر کلینیک"
    assert (
        approvals["clinical"]["report_hash"]
        == approvals["technical"]["report_hash"]
        == seal["report_hash"]
    )
    verification = state.get_json("selected_rollout_verification")
    assert verification["reviewer"] == "مدیر کلینیک"
    assert verification["note"] == "بازبینی خودکار انتشار محدود — تک‌اپراتور"
    ruleset = ClinicalEngineRulesRepository().get_ruleset(ruleset_id)
    assert ruleset["status"] == "ACTIVE"


def test_simple_activate_fails_closed_when_validation_cannot_pass(
    simple_app, monkeypatch,
):
    from src.adapters.sqlite.clinical_engine_activation_repo import (
        ClinicalEngineActivationRepository,
    )
    from src.adapters.sqlite.clinical_engine_fact_repo import (
        ClinicalEngineFactRepository,
    )
    from src.services.clinical_engine import validation_service
    from src.services.clinical_engine.activation import (
        ClinicalEngineActivationService,
    )
    from src.services.clinical_engine.validation_harness import (
        GoldenCaseValidationHarness,
        validation_bundle_path,
    )
    from src.adapters.sqlite.clinical_validation_repo import (
        ClinicalValidationError,
    )

    _app, tmp_path = simple_app

    class _BlockedHarness(GoldenCaseValidationHarness):
        def run(self, **kwargs):
            source = json.loads(
                validation_bundle_path().read_text(encoding="utf-8")
            )
            source["cases"][0]["expected"]["outcomes"]["T2-REDFLAG-BP"] = (
                "NOT_FIRED"
            )
            tampered = tmp_path / "blocked-cases.json"
            tampered.write_text(
                json.dumps(source, ensure_ascii=False),
                encoding="utf-8",
            )
            return super().run(case_path=tampered)

    monkeypatch.setattr(
        validation_service,
        "GoldenCaseValidationHarness",
        _BlockedHarness,
    )

    service = ClinicalEngineActivationService()
    with pytest.raises(ClinicalValidationError):
        service.simple_activate(
            "on",
            actor="single-operator",
            display_name="مدیر کلینیک",
            note="راه‌اندازی تک‌اپراتور تأیید شد",
        )

    state = ClinicalEngineActivationRepository()
    assert ClinicalEngineFactRepository().get_mode() == "off"
    assert state.raw_mode() == "off"
    assert state.get_json("seal") is None
    assert state.get_json("approval_clinical") is None
    assert state.get_json("approval_technical") is None
