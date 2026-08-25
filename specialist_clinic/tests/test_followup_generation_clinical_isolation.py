"""The separable clinical layer must never break administrative follow-up generation.

Contract: the analytical/clinical generators (red-flag alerts + clinical-v2 tasks)
are architecturally separable. If they are off or RAISE, the always-on
administrative engagement engine must still run and the ``/followups/generate``
route must return a redirect, not a 500. A clinical failure is surfaced loudly
(logged + funnelled into ``issues``), never silently converted into success.
"""
from __future__ import annotations

from pathlib import Path
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))


@pytest.fixture()
def followup_ctx(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "followup-isolation.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "followup-isolation-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _login(app):
    client = app.test_client()
    response = client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    return client


def _spy_engagement(monkeypatch):
    """Replace the admin engagement engine with a spy that records it ran."""
    from src.services import engagement_service as engagement_module

    calls = {"run_all": 0, "dispatch_patient": 0}

    def _run_all(self, *args, **kwargs):
        calls["run_all"] += 1
        return {"worklist": 0}

    def _dispatch_patient(self, patient_link_id, *args, **kwargs):
        calls["dispatch_patient"] += 1
        return {"worklist": 0}

    monkeypatch.setattr(engagement_module.EngagementService, "run_all", _run_all)
    monkeypatch.setattr(
        engagement_module.EngagementService, "dispatch_patient", _dispatch_patient
    )
    return calls


def test_generate_survives_clinical_v2_exception_and_still_runs_admin(
    followup_ctx, monkeypatch
):
    from src.services.followup_engine import ClinicalV2FollowupService
    from src.services.followup_service import FollowupService

    def _boom(self, *args, **kwargs):
        raise RuntimeError("clinical layer down")

    monkeypatch.setattr(ClinicalV2FollowupService, "generate_all", _boom)
    calls = _spy_engagement(monkeypatch)

    result = FollowupService().generate()  # must not raise

    assert calls["run_all"] == 1  # administrative engagement still executed
    assert result["clinical_v2"] == 0  # suppressed fail-closed, not invented
    assert any("پیگیری بالینی" in issue for issue in result["issues"])


def test_generate_survives_clinical_alert_exception_and_still_runs_admin(
    followup_ctx, monkeypatch
):
    from src.services.clinical_alert_service import ClinicalAlertService
    from src.services.followup_service import FollowupService

    def _boom(self, *args, **kwargs):
        raise RuntimeError("alert engine down")

    monkeypatch.setattr(ClinicalAlertService, "generate_all", _boom)
    calls = _spy_engagement(monkeypatch)

    result = FollowupService().generate()

    assert calls["run_all"] == 1
    assert result["clinical_alerts"] == 0
    assert any("هشدار بالینی" in issue for issue in result["issues"])


def test_generate_patient_survives_clinical_exception_and_still_runs_admin(
    followup_ctx, monkeypatch
):
    from src.adapters.sqlite.core import get_db
    from src.services.followup_engine import ClinicalV2FollowupService
    from src.services.followup_service import FollowupService

    db = get_db()
    pid = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, enrolled_by)
               VALUES ('ISO00001', 'Isolation Patient', 'pytest')"""
        ).lastrowid
    )
    db.commit()

    def _boom(self, *args, **kwargs):
        raise RuntimeError("clinical layer down")

    monkeypatch.setattr(ClinicalV2FollowupService, "generate_patient", _boom)
    calls = _spy_engagement(monkeypatch)

    result = FollowupService().generate_patient(pid)

    assert calls["dispatch_patient"] == 1
    assert result["clinical_v2"] == 0
    assert any("پیگیری بالینی" in issue for issue in result["issues"])


def test_generate_route_returns_redirect_not_500_when_clinical_raises(
    followup_ctx, monkeypatch
):
    from src.services.followup_engine import ClinicalV2FollowupService

    def _boom(self, *args, **kwargs):
        raise RuntimeError("clinical layer down")

    monkeypatch.setattr(ClinicalV2FollowupService, "generate_all", _boom)
    calls = _spy_engagement(monkeypatch)

    client = _login(followup_ctx)
    response = client.post("/followups/generate", follow_redirects=False)

    assert response.status_code in {302, 303}  # graceful redirect, not a 500
    assert calls["run_all"] == 1  # admin engagement ran despite clinical failure
