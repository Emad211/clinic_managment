from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from flask import url_for


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def workspace_app(tmp_path, monkeypatch):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.core import get_db
    from src.app import create_app
    from src.services.clinical_engine.facade import ClinicalEngineReadOnlyFacade

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "workspace.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "workspace-test",
            "FOLLOWUP_UNIFIED_WORKLIST_READONLY": True,
            "FOLLOWUP_UNIFIED_WORKLIST_ACTIONS": True,
        }
    )
    context = app.app_context()
    context.push()
    monkeypatch.setattr(
        ClinicalEngineReadOnlyFacade,
        "patient_detail",
        lambda self, patient_link_id: None,
    )
    db = get_db()
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, phone_number, gender, enrolled_by,
                enrolled_at, updated_at)
               VALUES ('PW-GROWTH-001', 'بیمار فضای کاری', '09124444444',
                       'male', 'pytest', '2026-08-06 08:00:00',
                       '2026-08-06 08:00:00')"""
        ).lastrowid
    )
    db.commit()
    admin = db.execute(
        "SELECT id, username FROM users WHERE username='admin'"
    ).fetchone()
    yield {
        "app": app,
        "db": db,
        "patient_id": patient_id,
        "admin": admin,
    }
    context.pop()
    core._initialized = False


def _client(fixture):
    client = fixture["app"].test_client()
    with client.session_transaction() as session:
        session["user_id"] = int(fixture["admin"]["id"])
    return client


def _url(fixture, endpoint: str, **values) -> str:
    with fixture["app"].test_request_context():
        return url_for(endpoint, **values)


def _future_jalali(days: int = 7) -> str:
    from src.common.utils import gregorian_to_jalali, iran_now

    target = (iran_now() + timedelta(days=days)).date()
    year, month, day = gregorian_to_jalali(
        target.year,
        target.month,
        target.day,
    )
    return f"{year}/{month:02d}/{day:02d}"


def test_legacy_patient_detail_redirects_to_native_workspace(workspace_app):
    client = _client(workspace_app)
    patient_id = workspace_app["patient_id"]
    response = client.get(
        _url(workspace_app, "patients.detail", pid=patient_id),
        follow_redirects=False,
    )

    assert response.status_code in {301, 302, 303, 307, 308}
    assert response.headers["Location"].endswith(
        f"/patients/{patient_id}/workspace?tab=summary"
    )


def test_explicit_legacy_fallback_stays_available(workspace_app):
    client = _client(workspace_app)
    patient_id = workspace_app["patient_id"]
    response = client.get(
        _url(workspace_app, "patients.detail", pid=patient_id, legacy=1)
    )

    assert response.status_code == 200
    assert "patient-hero" in response.get_data(as_text=True)


@pytest.mark.parametrize(
    ("tab", "expected"),
    [
        ("summary", "اقدام بعدی پیشنهادی پرونده"),
        ("actions", "ثبت سریع شاخص‌ها"),
        ("clinical", "بیماری‌های مزمن"),
        ("meds", "داروهای بیمار"),
        ("encounters", "گزارش‌های نهایی ویزیت"),
    ],
)
def test_all_five_tabs_render_server_side(workspace_app, tab, expected):
    client = _client(workspace_app)
    patient_id = workspace_app["patient_id"]
    response = client.get(
        _url(workspace_app, "patient_workspace.detail", pid=patient_id, tab=tab)
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert expected in html
    assert html.count('class="patient-workspace-tab') == 5
    assert 'aria-current="page"' in html
    assert "data-patient-workspace" in html
    assert "patient-workspace-v2.css" in html


def test_unknown_tab_falls_back_to_summary(workspace_app):
    client = _client(workspace_app)
    response = client.get(
        _url(
            workspace_app,
            "patient_workspace.detail",
            pid=workspace_app["patient_id"],
            tab="unknown",
        )
    )

    assert response.status_code == 200
    assert "اقدام بعدی پیشنهادی پرونده" in response.get_data(as_text=True)


def test_allergy_mutation_returns_to_clinical_tab(workspace_app):
    client = _client(workspace_app)
    patient_id = workspace_app["patient_id"]
    response = client.post(
        _url(workspace_app, "patients.add_allergy", pid=patient_id),
        data={
            "substance": "پنی‌سیلین",
            "severity": "شدید",
            "workspace_tab": "clinical",
        },
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith(
        f"/patients/{patient_id}/workspace?tab=clinical"
    )


def test_medication_mutation_returns_to_meds_tab(workspace_app):
    client = _client(workspace_app)
    patient_id = workspace_app["patient_id"]
    response = client.post(
        _url(workspace_app, "patients.add_medication", pid=patient_id),
        data={
            "drug_name": "آتورواستاتین",
            "dose": "20 mg",
            "schedule": "شب‌ها",
            "drug_class": "statin",
            "refill_interval": "30",
            "workspace_tab": "meds",
        },
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith(
        f"/patients/{patient_id}/workspace?tab=meds"
    )
    assert workspace_app["db"].execute(
        """SELECT 1 FROM patient_medications
           WHERE patient_link_id=? AND drug_name='آتورواستاتین'""",
        (patient_id,),
    ).fetchone()


def test_patient_context_appointment_returns_to_encounters_tab(workspace_app):
    client = _client(workspace_app)
    patient_id = workspace_app["patient_id"]
    response = client.post(
        _url(workspace_app, "appointments.new_appointment"),
        data={
            "patient_link_id": str(patient_id),
            "date": _future_jalali(),
            "time": "09:30",
            "appt_type": "visit",
            "return_url": "",
        },
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith(
        f"/patients/{patient_id}/workspace?tab=encounters"
    )


def test_workspace_navigation_does_not_require_tab_javascript():
    shell = (ROOT / "src/templates/patients/workspace.html").read_text(
        encoding="utf-8"
    )
    route = (ROOT / "src/api/patient_workspace.py").read_text(
        encoding="utf-8"
    )

    assert "{% if active_tab == 'summary' %}" in shell
    assert "patient-workspace.js" not in shell
    assert "data-pane=" not in shell
    assert "install_compatibility" in route
    assert "legacy=1" in route
