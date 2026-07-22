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
    assert "مرکز کنترل انتشار و ایمنی" in html
    assert "وضعیت مؤثر" in html and "خاموش" in html
    assert "فعال‌سازی مسدود است" in html
    assert "هنوز گزارشی وجود ندارد" in html
    assert 'disabled' in html


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


def test_compare_action_builds_blocked_report_without_activating(manager_ui_app):
    from src.adapters.sqlite.clinical_engine_activation_repo import ClinicalEngineActivationRepository
    from src.adapters.sqlite.clinical_engine_fact_repo import ClinicalEngineFactRepository

    client = _manager_client(manager_ui_app)
    response = client.post("/manager/clinical-engine/compare", follow_redirects=True)
    assert response.status_code == 200
    assert "فعال‌سازی همچنان مسدود است" in response.get_data(as_text=True)
    with manager_ui_app.app_context():
        state = ClinicalEngineActivationRepository()
        assert state.get_json("last_report")["status"] == "BLOCKED"
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
