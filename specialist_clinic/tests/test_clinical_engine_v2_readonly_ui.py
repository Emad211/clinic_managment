"""Current-run patient projection and template safety tests."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))
TESTS_ROOT = str(SPECIALIST_ROOT / "tests")
if TESTS_ROOT not in sys.path:
    sys.path.insert(0, TESTS_ROOT)

from clinical_engine_current_test_support import (
    current_snapshot,
    install_sealed_rollout,
)
from test_clinical_engine_v2_compiler import valid_rule
from src.services.clinical_engine.facade import ClinicalEngineReadOnlyFacade


@pytest.fixture()
def readonly_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "readonly.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "readonly-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


class _Runtime:
    def __init__(self, run, *, mode="on_selected", selected=True):
        self.run = run
        self.mode = mode
        self.selected = selected
        self.presentations: list[tuple[int, int]] = []
        self.ensure_calls = 0

    def contract(self, patient_link_id):
        assert patient_link_id == 7
        if self.mode not in {"on_selected", "on"}:
            return None
        if self.mode == "on_selected" and not self.selected:
            return None
        return SimpleNamespace(
            patient_link_id=patient_link_id,
            mode=self.mode,
            engine_version=self.run["engine_version"],
            ruleset_id=11,
            clinical_data_revision=3,
        )

    def ensure_current_run(self, patient_link_id, *, trigger, actor):
        assert trigger == "patient-detail"
        assert actor == "patient-detail"
        contract = self.contract(patient_link_id)
        if contract is None:
            return None
        self.ensure_calls += 1
        return contract, deepcopy(self.run)

    def present_recommendation(self, event_id, contract):
        self.presentations.append((event_id, contract.patient_link_id))
        return event_id + 1000


def _evaluation(
    code,
    action_type,
    semantic_key,
    *,
    outcome="FIRED",
    suppression=None,
    recommendation=True,
):
    return {
        "rule_code": code,
        "rule_title": f"عنوان {code}",
        "action_type": action_type,
        "semantic_key": semantic_key,
        "outcome": outcome,
        "trace": {
            "fact_ids": [f"fact:{code}"],
            "children": [
                {"fact_ids": ["fact:shared"], "children": []}
            ],
        },
        "data_issues": [],
        "suppression": suppression,
        "error": None,
        "recommendation": (
            {
                "recommendation_key": f"rec:{code}",
                "action_type": action_type,
                "text_fa": f"پیشنهاد {code}",
                "title_fa": f"عنوان {code}",
                "semantic_key": semantic_key,
                "suggestion_only": True,
                "requires_clinician_confirmation": True,
                "presentation": "NON_INTERRUPTIVE",
                "may_create_internal_task": False,
            }
            if recommendation
            else None
        ),
        "recommendation_event": (
            {
                "id": 700 + len(code),
                "current_decision": None,
            }
            if recommendation
            else None
        ),
    }


def _run(evaluations):
    from src.services.clinical_engine.fact_builder import ENGINE_VERSION

    return {
        "run_id": "run-1",
        "as_of_at": "2026-07-22 10:00:00",
        "run_status": "COMPLETED",
        "engine_version": ENGINE_VERSION,
        "evaluations": evaluations,
    }


def test_distinct_medication_options_form_one_grouped_card_model():
    runtime = _Runtime(
        _run(
            [
                _evaluation("ASCVD", "suggest_med", "med:ascvd"),
                _evaluation("HF", "suggest_med", "med:hf"),
                _evaluation("CKD", "suggest_med", "med:ckd"),
                _evaluation("OBESITY", "suggest_med", "med:obesity"),
            ]
        )
    )
    original = deepcopy(runtime.run)

    projection = ClinicalEngineReadOnlyFacade(
        runtime=runtime
    ).patient_detail(7)

    assert len(projection["groups"]) == 1
    assert projection["groups"][0]["label"] == "گزینه‌های دارویی"
    assert len(projection["groups"][0]["items"]) == 4
    assert runtime.run == original
    assert runtime.ensure_calls == 1
    assert len(runtime.presentations) == 4


def test_reason_trace_and_nondeduplicated_suppression_remain_visible():
    runtime = _Runtime(
        _run(
            [
                _evaluation("DM", "classify", "dm:classify"),
                _evaluation(
                    "CONFLICT",
                    "set_target",
                    "dm:classify",
                    outcome="SUPPRESSED",
                    recommendation=False,
                    suppression={
                        "reason_code": "UNRESOLVED_CONFLICT",
                        "message_fa": "تعارض حل‌نشده است.",
                    },
                ),
            ]
        )
    )
    projection = ClinicalEngineReadOnlyFacade(
        runtime=runtime
    ).patient_detail(7)

    assert projection["groups"][0]["items"][0]["fact_ids"] == [
        "fact:DM",
        "fact:shared",
    ]
    assert projection["notices"] == [
        {
            "rule_code": "CONFLICT",
            "title": "عنوان CONFLICT",
            "outcome": "SUPPRESSED",
            "reason_code": "UNRESOLVED_CONFLICT",
            "message": "تعارض حل‌نشده است.",
            "data_issues": [],
        }
    ]


def test_projection_is_hidden_outside_visible_rollout_without_run_read():
    for runtime in (
        _Runtime(_run([]), mode="off"),
        _Runtime(_run([]), mode="shadow"),
        _Runtime(_run([]), selected=False),
    ):
        assert ClinicalEngineReadOnlyFacade(
            runtime=runtime
        ).patient_detail(7) is None
        assert runtime.ensure_calls == 0


def test_partial_has_no_action_execution_controls_and_labels_inert_output():
    partial = (
        SPECIALIST_ROOT
        / "src"
        / "templates"
        / "patients"
        / "_clinical_engine_v2.html"
    ).read_text(encoding="utf-8")

    assert "پیشنهاد برای مرور پزشک" in partial
    assert "اعمال نشده" in partial
    assert "چرا این پیشنهاد نمایش داده شده؟" in partial
    assert "patients.clinical_v2_decision" in partial
    assert "ثبت فقط به‌عنوان تصمیم" in partial
    assert "rx_class" not in partial
    assert "suggestion_action" not in partial
    assert "<details" in partial and "<summary" in partial


def test_partial_renders_valid_current_projection_html(readonly_app):
    from flask import render_template

    runtime = _Runtime(
        _run([_evaluation("DM", "suggest_med", "med:dm")])
    )
    projection = ClinicalEngineReadOnlyFacade(
        runtime=runtime
    ).patient_detail(7)
    with readonly_app.test_request_context("/"):
        html = render_template(
            "patients/_clinical_engine_v2.html",
            clinical_v2=projection,
            patient={"id": 7},
        )

    assert '<section class="cev2 card"' in html
    assert '<article class="cev2-group tone-info"' in html
    assert "پیشنهاد DM" in html
    assert "ثبت فقط به‌عنوان تصمیم" in html
    assert "تغییر نمی‌دهد" in html


def test_real_current_projection_records_one_presentation_only(readonly_app):
    from src.adapters.sqlite.clinical_engine_audit_repo import (
        ClinicalEngineAuditRepository,
    )
    from src.adapters.sqlite.clinical_engine_rules_repo import (
        ClinicalEngineRulesRepository,
    )
    from src.adapters.sqlite.core import get_db
    from src.domain.clinical_engine import (
        PredicateState,
        RuleOutcome,
        RunStatus,
    )
    from src.services.clinical_engine.compiler import RuleCompiler
    from src.services.clinical_engine.fact_builder import ENGINE_VERSION

    db = get_db()
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, enrolled_by, enrolled_at, updated_at)
               VALUES ('TEST0001', 'Readonly Patient', 'pytest',
                       '2026-07-22 09:00:00', '2026-07-22 09:00:00')"""
        ).lastrowid
    )
    db.commit()
    ruleset_id = install_sealed_rollout()
    compiled = RuleCompiler().compile(valid_rule())
    rule_id = ClinicalEngineRulesRepository().create_rule_version(
        compiled,
        created_by="pytest",
    )
    audit = ClinicalEngineAuditRepository()
    run_id = audit.start_run(
        patient_link_id=patient_id,
        as_of_at="2026-07-22 10:00:00",
        engine_version=ENGINE_VERSION,
        ruleset_id=ruleset_id,
        fact_snapshot=current_snapshot(patient_id),
    )
    evaluation_id = audit.append_evaluation(
        run_id=run_id,
        rule_version_id=rule_id,
        predicate_state=PredicateState.TRUE,
        outcome=RuleOutcome.FIRED,
        trace={"fact_ids": ["condition:dm"], "children": []},
        recommendation={
            "recommendation_key": "rec:test",
            "action_type": "educate",
            "text_fa": "آموزش بیمار",
            "title_fa": "آموزش",
            "suggestion_only": True,
            "requires_clinician_confirmation": False,
            "presentation": "NON_INTERRUPTIVE",
            "may_create_internal_task": False,
        },
    )
    audit.append_recommendation_event(
        run_id=run_id,
        evaluation_id=evaluation_id,
        recommendation_key="rec:test",
        action_type="educate",
        event_type="CREATED",
        payload={
            "suggestion_only": True,
            "action_type": "educate",
            "text_fa": "آموزش بیمار",
        },
    )
    audit.complete_run(run_id, status=RunStatus.COMPLETED)

    first = ClinicalEngineReadOnlyFacade().patient_detail(patient_id)
    second = ClinicalEngineReadOnlyFacade().patient_detail(patient_id)

    assert first["run_id"] == second["run_id"] == run_id
    assert first["groups"][0]["items"][0]["text"] == "آموزش بیمار"
    assert db.execute(
        "SELECT COUNT(*) AS count FROM clinical_recommendation_events "
        "WHERE event_type='PRESENTED'"
    ).fetchone()["count"] == 1
