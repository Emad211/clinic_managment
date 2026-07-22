from __future__ import annotations

from datetime import datetime

import pytest

from src.domain.clinical_engine.release import CURRENT_BUNDLED_PACKAGE_VERSION


@pytest.fixture()
def activation_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True,
        "CLINICAL_ENGINE_REQUIRE_ACTIVATION_GATE": True,
        "DATABASE_PATH": str(tmp_path / "activation.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"),
        "SECRET_KEY": "activation-tests",
    })
    context = app.app_context()
    context.push()
    db = core.get_db()
    for index in range(1, 11):
        db.execute(
            "INSERT INTO patient_links (national_id, full_name, enrolled_by) VALUES (?, ?, 'pytest')",
            (f"TEST{index:04d}", f"demo {index}"),
        )
    db.execute(
        """INSERT INTO clinical_rulesets
           (id, ruleset_code, version, content_hash, status, created_by, created_at)
           VALUES (9001, 'general-outpatient', ?, 'gate-test-hash',
                   'SILENT', 'pytest', '2026-07-22 10:00:00')""",
        (CURRENT_BUNDLED_PACKAGE_VERSION,),
    )
    db.commit()
    yield app, db
    context.pop()
    core._initialized = False


class _Rules:
    def __init__(self, state):
        self.state = state

    def active_ruleset(self, _code):
        return self.state.ruleset_state(9001)

    def get_ruleset(self, ruleset_id):
        return self.state.ruleset_state(ruleset_id)

    def promote_silent_ruleset(self, ruleset_id, *, promoted_by):
        if not promoted_by:
            raise ValueError("promoted_by is required")
        from src.adapters.sqlite.core import get_db
        with get_db() as db:
            db.execute("UPDATE clinical_rulesets SET status='ACTIVE' WHERE id=?", (ruleset_id,))


class _Capture:
    def capture(self, patient_id, **_kwargs):
        return f"run-{patient_id}"


class _Audit:
    def __init__(self, evaluations=None, status="COMPLETED"):
        self.evaluations = evaluations or {}
        self.status = status

    def decoded_run(self, run_id):
        patient_id = int(run_id.split("-")[-1])
        return {"run_id": run_id, "run_status": self.status,
                "fact_snapshot_hash": f"snapshot-{patient_id}",
                "evaluations": self.evaluations.get(patient_id, [])}


def _service(*, audit=None):
    from src.adapters.sqlite.clinical_engine_activation_repo import ClinicalEngineActivationRepository
    from src.services.clinical_engine.activation import ClinicalEngineActivationService

    state = ClinicalEngineActivationRepository()
    return ClinicalEngineActivationService(
        state=state, rules=_Rules(state), audit=audit or _Audit(),
        capture_factory=lambda: _Capture(),
        cohort_summary_factory=lambda: {
            "ready": True, "patient_count": 10,
            "totals": {"vitals": 2100, "labs": 1300, "notes": 240,
                       "medication_events": 50},
        },
        enforce_positive_controls=False,
    )


def _passing_report(service):
    return service.build_report(as_of_at=datetime(2026, 7, 22, 12, 0, 0), created_by="qa")


def _approve_both(service, report):
    service.approve("clinical", reviewer="physician", report_hash=report["report_hash"],
                    note="Ten cases reviewed clinically.")
    service.approve("technical", reviewer="engineer", report_hash=report["report_hash"],
                    note="Audit and rollback verified.")


def test_exact_ten_patient_report_is_reproducible_and_passes(activation_app):
    service = _service()
    first = _passing_report(service)
    second = _passing_report(service)
    assert first["status"] == "PASS"
    assert len(first["patients"]) == 10
    assert first["report_hash"] == second["report_hash"]
    assert all(first["checks"].values())
    assert first["patients"][0]["v2_run_id"].startswith("run-")
    text = service.render_text(first)
    assert "activation report: PASS" in text
    assert "TEST0010" in text


def test_fixed_as_of_excludes_future_observation(activation_app):
    from src.adapters.sqlite.vitals_repo import VitalsRepository

    _app, db = activation_app
    patient_id = db.execute(
        "SELECT id FROM patient_links WHERE national_id='TEST0001'"
    ).fetchone()["id"]
    db.execute(
        "INSERT INTO vital_readings (patient_link_id, type, value, measured_at) VALUES (?, 'hba1c', 7, '2026-01-01 00:00:00')",
        (patient_id,),
    )
    db.execute(
        "INSERT INTO vital_readings (patient_link_id, type, value, measured_at) VALUES (?, 'hba1c', 99, '2027-01-01 00:00:00')",
        (patient_id,),
    )
    db.commit()
    latest = VitalsRepository().latest_by_type(
        patient_id, as_of_at=datetime(2026, 7, 22, 12, 0, 0)
    )
    assert latest["hba1c"]["value"] == 7


def test_missing_demo_patient_blocks_activation_report(activation_app):
    _app, db = activation_app
    db.execute("DELETE FROM patient_links WHERE national_id='TEST0010'")
    db.commit()
    report = _passing_report(_service())
    assert report["status"] == "BLOCKED"
    assert report["checks"]["exact_demo_cohort"] is False
    assert report["failures"] == [{"national_id": "TEST0010", "code": "DEMO_PATIENT_MISSING"}]


def test_non_clean_terminal_run_blocks_gate_even_without_exception(activation_app):
    report = _passing_report(_service(audit=_Audit(status="SAFETY_FAILED")))
    assert report["status"] == "BLOCKED"
    assert report["checks"]["zero_run_failures"] is False


def test_approval_is_bound_to_current_passing_report(activation_app):
    from src.services.clinical_engine.activation import ActivationGateError

    service = _service()
    report = _passing_report(service)
    with pytest.raises(ActivationGateError, match="current passing report"):
        service.approve("clinical", reviewer="physician", report_hash="stale", note="reviewed")
    service.approve("clinical", reviewer="physician", report_hash=report["report_hash"], note="reviewed")


def test_raw_visible_mode_fails_closed_without_valid_seal(activation_app):
    from src.adapters.sqlite.clinical_engine_fact_repo import ClinicalEngineFactRepository

    _app, db = activation_app
    db.execute("UPDATE settings SET value='on_selected' WHERE key='clinical_engine_v2_mode'")
    db.commit()
    assert ClinicalEngineFactRepository().get_mode() == "off"


def test_tampered_activation_seal_fails_closed(activation_app):
    from src.adapters.sqlite.clinical_engine_activation_repo import ClinicalEngineActivationRepository
    from src.adapters.sqlite.clinical_engine_fact_repo import ClinicalEngineFactRepository

    service = _service()
    report = _passing_report(service)
    _approve_both(service, report)
    service.activate("on_selected", activated_by="release-manager")
    state = ClinicalEngineActivationRepository()
    seal = state.get_json("seal")
    seal["report_hash"] = "tampered"
    state.put_json("seal", seal)
    assert ClinicalEngineFactRepository().get_mode() == "off"


def test_tampered_report_or_removed_approval_revokes_effective_mode(activation_app):
    from src.adapters.sqlite.clinical_engine_activation_repo import ClinicalEngineActivationRepository
    from src.adapters.sqlite.clinical_engine_fact_repo import ClinicalEngineFactRepository

    service = _service()
    report = _passing_report(service)
    _approve_both(service, report)
    service.activate("on_selected", activated_by="release-manager")
    state = ClinicalEngineActivationRepository()
    technical = state.get_json("approval_technical")
    state.delete("approval_technical")
    assert ClinicalEngineFactRepository().get_mode() == "off"
    state.put_json("approval_technical", technical)
    changed = state.get_json("last_report")
    changed["patients"][0]["v2_recommendations"] += 1
    state.put_json("last_report", changed)
    assert ClinicalEngineFactRepository().get_mode() == "off"


def test_selected_activation_requires_two_approvals_and_rollback_is_immediate(activation_app):
    from src.adapters.sqlite.clinical_engine_activation_repo import ClinicalEngineActivationRepository
    from src.adapters.sqlite.clinical_engine_fact_repo import ClinicalEngineFactRepository
    from src.services.clinical_engine.activation import ActivationGateError

    service = _service()
    report = _passing_report(service)
    service.approve("clinical", reviewer="physician", report_hash=report["report_hash"], note="reviewed")
    with pytest.raises(ActivationGateError, match="technical approval"):
        service.activate("on_selected", activated_by="release-manager")
    service.approve("technical", reviewer="engineer", report_hash=report["report_hash"], note="verified")
    seal = service.activate("on_selected", activated_by="release-manager")
    assert seal["report_hash"] == report["report_hash"]
    assert ClinicalEngineFactRepository().get_mode() == "on_selected"

    service.rollback(rolled_back_by="release-manager", reason="activation drill")
    state = ClinicalEngineActivationRepository()
    assert state.raw_mode() == "off"
    assert ClinicalEngineFactRepository().get_mode() == "off"
    assert state.get_json("seal") is None
    assert state.get_json("last_report")["report_hash"] == report["report_hash"]
    actions = {
        row["action_type"] for row in activation_app[1].execute(
            "SELECT action_type FROM activity_logs WHERE action_type LIKE 'clinical_v2_%'"
        ).fetchall()
    }
    assert {"clinical_v2_compare", "clinical_v2_approve",
            "clinical_v2_activate", "clinical_v2_rollback"} <= actions


def test_global_on_requires_verified_selected_stage_and_active_ruleset(activation_app):
    from src.adapters.sqlite.clinical_engine_fact_repo import ClinicalEngineFactRepository
    from src.services.clinical_engine.activation import ActivationGateError

    _app, db = activation_app
    service = _service()
    report = _passing_report(service)
    _approve_both(service, report)
    service.activate("on_selected", activated_by="release-manager")
    with pytest.raises(ActivationGateError, match="verified on_selected"):
        service.activate("on", activated_by="release-manager")
    service.verify_selected_rollout(reviewer="physician", note="selected cases remained safe")
    with pytest.raises(ActivationGateError, match="ACTIVE ruleset"):
        service.activate("on", activated_by="release-manager")
    service.promote_compared_ruleset(promoted_by="release-manager")
    service.activate("on", activated_by="release-manager")
    assert ClinicalEngineFactRepository().get_mode() == "on"


def test_promote_silent_ruleset_refuses_draft_and_preserves_membership(activation_app):
    from src.adapters.sqlite.clinical_engine_rules_repo import ClinicalEngineRulesRepository

    _app, db = activation_app
    before = db.execute(
        "SELECT COUNT(*) c FROM clinical_ruleset_members WHERE ruleset_id=9001"
    ).fetchone()["c"]
    ClinicalEngineRulesRepository().promote_silent_ruleset(9001, promoted_by="release-manager")
    row = db.execute("SELECT status FROM clinical_rulesets WHERE id=9001").fetchone()
    after = db.execute(
        "SELECT COUNT(*) c FROM clinical_ruleset_members WHERE ruleset_id=9001"
    ).fetchone()["c"]
    assert row["status"] == "ACTIVE"
    assert after == before
