"""Integration tests for the explicit collection-review workspace."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))


@pytest.fixture()
def reconciliation_ui_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "reconciliation-ui.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"),
        "SECRET_KEY": "reconciliation-ui-test",
    })
    yield app
    core._initialized = False


def _patient(app, national_id="RECUI001") -> int:
    from src.adapters.sqlite.core import get_db

    with app.app_context():
        cursor = get_db().execute(
            """INSERT INTO patient_links
               (national_id, full_name, enrolled_by, enrolled_at)
               VALUES (?, 'بیمار مرور فهرست', 'pytest',
                       '2026-07-22 09:00:00')""",
            (national_id,),
        )
        get_db().commit()
        return int(cursor.lastrowid)


def _login(client, username="admin", password="admin"):
    response = client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )
    assert response.status_code in {302, 303}


def test_workspace_requires_login_and_renders_explicit_unknown_state(
    reconciliation_ui_app,
):
    patient_id = _patient(reconciliation_ui_app)
    anonymous = reconciliation_ui_app.test_client().get(
        f"/patients/{patient_id}/reconciliation"
    )
    assert anonymous.status_code in {302, 303}
    assert "/auth/login" in anonymous.headers["Location"]

    client = reconciliation_ui_app.test_client()
    _login(client)
    response = client.get(f"/patients/{patient_id}/reconciliation")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "مرور فهرست‌های بالینی" in html
    assert html.count("مرور نشده") >= 3
    assert "لیست خالی" not in html
    assert "نبود صریح" in html
    assert "ثبت رویداد مرور" in html


def test_manager_can_confirm_absence_and_later_change_marks_status_stale(
    reconciliation_ui_app,
):
    from src.adapters.sqlite.patients_repo import PatientRepository

    patient_id = _patient(reconciliation_ui_app, "RECUI002")
    client = reconciliation_ui_app.test_client()
    _login(client)

    recorded = client.post(
        f"/patients/{patient_id}/reconciliation/allergies",
        data={
            "completeness": "complete",
            "attested": "yes",
            "patient_confirmed": "yes",
            "return_to": "workspace",
        },
        follow_redirects=True,
    )
    html = recorded.get_data(as_text=True)
    assert recorded.status_code == 200
    assert "نبود مورد، صریحاً تأیید شده" in html

    with reconciliation_ui_app.app_context():
        PatientRepository().add_allergy(
            patient_id,
            substance="Penicillin",
            reaction="rash",
            severity="moderate",
        )

    status = client.get(
        f"/patients/{patient_id}/reconciliation/status"
    ).get_json()
    allergies = status["collections"]["allergies"]
    assert allergies["state"] == "stale"
    assert allergies["item_count"] == 1
    assert "COLLECTION_CHANGED_AFTER_RECONCILIATION" in allergies["warnings"]


def test_staff_can_inspect_but_cannot_append_clinical_attestation(
    reconciliation_ui_app,
):
    from src.adapters.sqlite.core import get_db
    from src.services.auth_service import AuthService

    patient_id = _patient(reconciliation_ui_app, "RECUI003")
    with reconciliation_ui_app.app_context():
        assert AuthService().register_user(
            "reconciliation-staff",
            "safe-password",
            "staff",
            "کارمند مرور",
        )

    client = reconciliation_ui_app.test_client()
    _login(client, "reconciliation-staff", "safe-password")
    workspace = client.get(f"/patients/{patient_id}/reconciliation")
    html = workspace.get_data(as_text=True)
    assert workspace.status_code == 200
    assert "ثبت attestation بالینی در نقش فعلی شما مجاز نیست" in html
    assert "ثبت رویداد مرور" not in html

    rejected = client.post(
        f"/patients/{patient_id}/reconciliation/medications",
        data={"completeness": "complete", "attested": "yes"},
    )
    assert rejected.status_code in {302, 303}
    assert rejected.headers["Location"].endswith("/")
    with reconciliation_ui_app.app_context():
        count = get_db().execute(
            "SELECT COUNT(*) AS count FROM clinical_reconciliation_events"
        ).fetchone()["count"]
        assert count == 0


def test_status_endpoint_rejects_missing_patient(reconciliation_ui_app):
    client = reconciliation_ui_app.test_client()
    _login(client)
    response = client.get("/patients/999999/reconciliation/status")
    assert response.status_code == 404
    assert response.get_json() == {"error": "patient_not_found"}
