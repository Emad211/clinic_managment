from __future__ import annotations

import json

import pytest


@pytest.fixture()
def validation_ui_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "validation-ui.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"),
        "SECRET_KEY": "validation-ui-test",
    })
    yield app
    core._initialized = False


def manager_client(app):
    client = app.test_client()
    response = client.post(
        "/auth/login", data={"username": "admin", "password": "admin"}
    )
    assert response.status_code in {302, 303}
    return client


def test_validation_workspace_requires_login(validation_ui_app):
    response = validation_ui_app.test_client().get(
        "/manager/clinical-engine/validation"
    )
    assert response.status_code in {302, 303}


def test_validation_workspace_run_and_dual_attestation(validation_ui_app):
    from src.services.clinical_engine.validation_service import ClinicalValidationService

    client = manager_client(validation_ui_app)
    empty = client.get("/manager/clinical-engine/validation")
    html = empty.get_data(as_text=True)
    assert "مرکز اعتبارسنجی و دروازهٔ انتشار" in html
    assert "هنوز گزارشی ساخته نشده است" in html

    ran = client.post(
        "/manager/clinical-engine/validation/run", follow_redirects=True
    )
    html = ran.get_data(as_text=True)
    assert "اعتبارسنجی با وضعیت PASS" in html
    assert "GC-POS-001" in html and "GC-CONFLICT-001" in html
    assert "False positive" in html and "False negative" in html

    with validation_ui_app.app_context():
        report = ClinicalValidationService().dashboard()["report"]
        report_hash = report["report_hash"]

    clinical = client.post(
        "/manager/clinical-engine/validation/attest",
        data={
            "role": "clinical",
            "reviewer": "doctor-a",
            "note": "Clinical outcomes and explanations reviewed.",
            "report_hash": report_hash,
            "attestation": "yes",
        },
        follow_redirects=True,
    )
    assert "تأیید مستقل" in clinical.get_data(as_text=True)

    technical = client.post(
        "/manager/clinical-engine/validation/attest",
        data={
            "role": "technical",
            "reviewer": "engineer-b",
            "note": "Determinism, hashes and failure metrics reviewed.",
            "report_hash": report_hash,
            "attestation": "yes",
        },
        follow_redirects=True,
    )
    html = technical.get_data(as_text=True)
    assert "آمادهٔ اتصال به activation" in html
    with validation_ui_app.app_context():
        assert ClinicalValidationService().current_release_evidence()


def test_newer_blocked_report_invalidates_older_pass(validation_ui_app, tmp_path):
    from src.services.clinical_engine.validation_harness import validation_bundle_path
    from src.services.clinical_engine.validation_service import ClinicalValidationService

    with validation_ui_app.app_context():
        service = ClinicalValidationService()
        passed = service.run_current(created_by="validator")
        service.attest_current(
            role="clinical", reviewer="doctor-a", note="Clinical review.",
            report_hash=passed["report_hash"],
        )
        service.attest_current(
            role="technical", reviewer="engineer-b", note="Technical review.",
            report_hash=passed["report_hash"],
        )
        assert service.current_release_evidence()

        bundle = json.loads(validation_bundle_path().read_text(encoding="utf-8"))
        bundle["cases"][0]["expected"]["outcomes"]["T2-REDFLAG-BP"] = "NOT_FIRED"
        blocked_path = tmp_path / "blocked.json"
        blocked_path.write_text(json.dumps(bundle), encoding="utf-8")
        blocked = service.run_current(created_by="validator", case_path=blocked_path)
        assert blocked["status"] == "BLOCKED"
        assert service.current_release_evidence() is None
