from __future__ import annotations

import pytest


@pytest.fixture()
def manager_ui_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True,
        "CLINICAL_ENGINE_REQUIRE_ACTIVATION_GATE": True,
        "DATABASE_PATH": str(tmp_path / "manager-ui.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"),
        "SECRET_KEY": "manager-ui-test",
    })
    yield app
    core._initialized = False


def _manager_client(app):
    client = app.test_client()
    response = client.post(
        "/auth/login", data={"username": "admin", "password": "admin"}
    )
    assert response.status_code in {302, 303}
    return client


def test_control_center_requires_login(manager_ui_app):
    response = manager_ui_app.test_client().get("/manager/clinical-engine")
    assert response.status_code in {302, 303}
    assert "/auth/login" in response.headers["Location"]


def test_control_center_renders_fail_closed_empty_state(manager_ui_app):
    response = _manager_client(manager_ui_app).get("/manager/clinical-engine")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "راه‌اندازی قدم‌به‌قدم" in html
    assert "وضعیت فعلی" in html and "خاموش" in html
    assert "بستهٔ اولیهٔ قواعد را آماده کنید" in html
    assert "آماده‌سازی بستهٔ اولیه" in html
    assert '<button class="btn btn-lg engine-primary-action" type="submit" disabled' not in html
    assert "گیت‌های ایمنی" not in html


def test_guided_package_prepare_then_dual_review_and_freeze(manager_ui_app):
    from src.adapters.sqlite.clinical_engine_activation_repo import ClinicalEngineActivationRepository
    from src.adapters.sqlite.clinical_engine_fact_repo import ClinicalEngineFactRepository
    from src.adapters.sqlite.clinical_engine_rules_repo import ClinicalEngineRulesRepository

    client = _manager_client(manager_ui_app)
    prepared = client.post(
        "/manager/clinical-engine/prepare-rules", follow_redirects=True,
    )
    html = prepared.get_data(as_text=True)
    assert prepared.status_code == 200
    assert "بازبینی مستقل بالینی و فنی" in html
    assert "سررسید ارزیابی HbA1c" in html
    assert "بازبینی فایده و خطر متفورمین" in html
    assert "یک حساب می‌تواند هر دو نقش را ثبت کند" in html
    with manager_ui_app.app_context():
        assert ClinicalEngineFactRepository().get_mode() == "off"
        package = ClinicalEngineRulesRepository().latest_ruleset("general-outpatient")
        assert package["status"] == "DRAFT"
        ruleset_id = package["id"]
        rule_codes = [item["rule_code"] for item in package["members"]]
        assert len(rule_codes) == 6

    technical_data = {
        "ruleset_id": ruleset_id,
        "role": "technical",
        "note": "Schema, facts, units and task contracts reviewed.",
        **{f"decision__{code}": "APPROVE" for code in rule_codes},
    }
    technical = client.post(
        "/manager/clinical-engine/review-rules",
        data=technical_data,
        follow_redirects=True,
    )
    assert "بازبینی فنی همهٔ قواعد ثبت شد" in technical.get_data(as_text=True)

    clinical_data = {
        **technical_data,
        "role": "clinical",
        "note": "Eligibility, exclusions and source locators reviewed.",
    }
    clinical = client.post(
        "/manager/clinical-engine/review-rules",
        data=clinical_data,
        follow_redirects=True,
    )
    assert "بازبینی بالینی همهٔ قواعد ثبت شد" in clinical.get_data(as_text=True)

    frozen_response = client.post(
        "/manager/clinical-engine/freeze-rules",
        data={"ruleset_id": ruleset_id, "note": "dual review complete"},
        follow_redirects=True,
    )
    html = frozen_response.get_data(as_text=True)
    assert "هر 6 قاعده با دو بازبینی مستقل فریز شد" in html
    assert "۱۰ پروندهٔ نمونهٔ کامل" in html
    with manager_ui_app.app_context():
        repo = ClinicalEngineRulesRepository()
        package = repo.latest_ruleset("general-outpatient")
        assert package["status"] == "SILENT"
        summary = repo.rule_review_summary(ruleset_id)
        assert summary["ready_to_freeze"] is False  # no longer DRAFT after freeze
        assert summary["roles"]["clinical"]["reviewer_username"] == "admin"
        assert summary["roles"]["technical"]["reviewer_username"] == "admin"
        assert ClinicalEngineFactRepository().get_mode() == "off"

    validation_run = client.post(
        "/manager/clinical-engine/validation/run", follow_redirects=True,
    )
    assert "اعتبارسنجی با وضعیت PASS" in validation_run.get_data(as_text=True)
    with manager_ui_app.app_context():
        from src.services.clinical_engine.validation_service import ClinicalValidationService
        validation_report = ClinicalValidationService().dashboard()["report"]
    client.post(
        "/manager/clinical-engine/validation/attest",
        data={"role": "clinical", "reviewer": "doctor-a",
              "note": "Clinical validation reviewed.",
              "report_hash": validation_report["report_hash"],
              "attestation": "yes"},
    )
    client.post(
        "/manager/clinical-engine/validation/attest",
        data={"role": "technical", "reviewer": "doctor-a",
              "note": "Technical validation reviewed by the same operator.",
              "report_hash": validation_report["report_hash"],
              "attestation": "yes"},
    )

    cohort = client.post(
        "/manager/clinical-engine/prepare-demo-cohort", follow_redirects=True,
    )
    assert "۱۰ پروندهٔ طولی آماده شد" in cohort.get_data(as_text=True)
    compared = client.post(
        "/manager/clinical-engine/compare", follow_redirects=True,
    )
    html = compared.get_data(as_text=True)
    assert "آزمون هر ۱۰ بیمار با موفقیت انجام شد" in html
    with manager_ui_app.app_context():
        state = ClinicalEngineActivationRepository()
        report = state.get_json("last_report")
        rows = {row["national_id"]: row for row in report["patients"]}
        assert "T2-REDFLAG-BP" in rows["TEST0008"]["v2_rule_codes"]
        assert "T2-SAFE-MET-STOP" in rows["TEST0010"]["v2_rule_codes"]


def test_workflow_reset_requires_confirmation_preserves_audit_and_can_restart(manager_ui_app):
    from src.adapters.sqlite.clinical_engine_activation_repo import ClinicalEngineActivationRepository
    from src.adapters.sqlite.clinical_engine_rules_repo import ClinicalEngineRulesRepository

    client = _manager_client(manager_ui_app)
    client.post("/manager/clinical-engine/prepare-rules")
    with manager_ui_app.app_context():
        first = ClinicalEngineRulesRepository().latest_ruleset("general-outpatient")

    rejected = client.post(
        "/manager/clinical-engine/reset-workflow",
        data={"note": "شروع دوباره برای تست"}, follow_redirects=True,
    )
    assert "تأیید آگاهانهٔ ریست الزامی است" in rejected.get_data(as_text=True)

    reset = client.post(
        "/manager/clinical-engine/reset-workflow",
        data={"note": "شروع دوباره برای تست", "confirm_reset": "yes"},
        follow_redirects=True,
    )
    html = reset.get_data(as_text=True)
    assert "پیشرفت راه‌اندازی ریست شد" in html
    assert "بستهٔ اولیهٔ قواعد را آماده کنید" in html
    with manager_ui_app.app_context():
        state = ClinicalEngineActivationRepository()
        retired = ClinicalEngineRulesRepository().get_ruleset(first["id"])
        assert retired["status"] == "RETIRED"
        assert state.raw_mode() == "off"
        assert state.get_json("last_report") is None
        assert state.get_json("last_reset")["reason"] == "شروع دوباره برای تست"

    client.post("/manager/clinical-engine/prepare-rules")
    with manager_ui_app.app_context():
        restarted = ClinicalEngineRulesRepository().latest_ruleset("general-outpatient")
        assert restarted["status"] == "DRAFT"
        assert restarted["id"] != first["id"]
        assert restarted["version"] != first["version"]


def test_manager_home_and_sidebar_make_v2_the_primary_engine_ui(manager_ui_app):
    client = _manager_client(manager_ui_app)
    home = client.get("/manager/").get_data(as_text=True)
    engine = client.get("/manager/clinical-engine").get_data(as_text=True)
    assert "موتور بالینی v2" in home
    assert "پروتکل بیماری‌ها" not in home
    assert "موتور بالینی" in engine
    assert "قواعد تصمیم بالینی — دیابت نوع ۲" not in engine


def test_old_rule_deep_links_land_on_v2_control_center(manager_ui_app):
    client = _manager_client(manager_ui_app)
    for path in ("/manager/rules", "/manager/decision-rules"):
        response = client.get(path)
        assert response.status_code in {302, 303}
        assert response.headers["Location"].endswith("/manager/clinical-engine")


def test_control_center_has_no_v1_comparison_or_adjudication_surface(manager_ui_app):
    html = _manager_client(manager_ui_app).get(
        "/manager/clinical-engine"
    ).get_data(as_text=True)
    assert "مقایسه با v1" not in html
    assert "داوری اختلاف" not in html
    assert "/adjudicate" not in html


def test_compare_action_requires_a_frozen_ruleset_without_activating(manager_ui_app):
    from src.adapters.sqlite.clinical_engine_activation_repo import ClinicalEngineActivationRepository
    from src.adapters.sqlite.clinical_engine_fact_repo import ClinicalEngineFactRepository

    client = _manager_client(manager_ui_app)
    response = client.post("/manager/clinical-engine/compare", follow_redirects=True)
    assert response.status_code == 200
    assert "ابتدا بستهٔ قواعد v2 باید وارد" in response.get_data(as_text=True)
    with manager_ui_app.app_context():
        state = ClinicalEngineActivationRepository()
        assert state.get_json("last_report") is None
        assert state.raw_mode() == "off"
        assert ClinicalEngineFactRepository().get_mode() == "off"


def test_approval_action_requires_passing_hash_and_attestation(manager_ui_app):
    client = _manager_client(manager_ui_app)
    response = client.post(
        "/manager/clinical-engine/approve",
        data={"role": "clinical", "reviewer": "doctor", "note": "reviewed",
              "report_hash": "missing", "attestation": "yes"},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "عملیات انجام نشد" in html


def test_unknown_or_incomplete_destructive_action_fails_closed(manager_ui_app):
    client = _manager_client(manager_ui_app)
    unknown = client.post("/manager/clinical-engine/not-real", follow_redirects=True)
    rollback = client.post(
        "/manager/clinical-engine/rollback", data={"note": ""}, follow_redirects=True
    )
    assert "عملیات ناشناخته است" in unknown.get_data(as_text=True)
    assert "عملیات انجام نشد" in rollback.get_data(as_text=True)


def test_staff_cannot_open_or_mutate_engine_control_center(manager_ui_app):
    from src.services.auth_service import AuthService

    with manager_ui_app.app_context():
        assert AuthService().register_user("staff-ui", "safe-password", "staff", "کارمند تست")
    client = manager_ui_app.test_client()
    client.post("/auth/login", data={"username": "staff-ui", "password": "safe-password"})
    get_response = client.get("/manager/clinical-engine")
    post_response = client.post("/manager/clinical-engine/compare")
    assert get_response.status_code in {302, 303}
    assert post_response.status_code in {302, 303}
    assert get_response.headers["Location"].endswith("/")
    assert post_response.headers["Location"].endswith("/")
