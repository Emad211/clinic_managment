from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIXED_NOW = datetime(2026, 8, 5, 10, 7, 0)


def jalali_date(year: int, month: int, day: int) -> str:
    from src.common.utils import gregorian_to_jalali

    jy, jm, jd = gregorian_to_jalali(year, month, day)
    return f"{jy}/{jm:02d}/{jd:02d}"


@pytest.fixture()
def appointments_app(tmp_path, monkeypatch):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.core import get_db
    from src.api import appointments as appointments_api
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "appointments-v2.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "appointments-v2-test",
        }
    )
    context = app.app_context()
    context.push()
    monkeypatch.setattr(appointments_api, "iran_now", lambda: FIXED_NOW)
    db = get_db()

    patient_ids = []
    for index in range(1, 3):
        patient_ids.append(
            int(
                db.execute(
                    """INSERT INTO patient_links
                       (national_id, full_name, phone_number, enrolled_by,
                        enrolled_at, updated_at)
                       VALUES (?, ?, ?, 'pytest',
                               '2026-08-05 08:00:00', '2026-08-05 08:00:00')""",
                    (
                        f"APT2{index:06d}",
                        f"بیمار نوبت {index}",
                        f"0912333333{index}",
                    ),
                ).lastrowid
            )
        )
    db.execute(
        """INSERT INTO appointments
           (patient_link_id, scheduled_at, appt_type, status, created_by)
           VALUES (?, '2026-08-05 11:00:00', 'visit', 'scheduled', 'pytest')""",
        (patient_ids[0],),
    )
    db.execute(
        """INSERT INTO appointments
           (patient_link_id, scheduled_at, appt_type, status, created_by)
           VALUES (?, '2026-08-06 12:00:00', 'lab', 'scheduled', 'pytest')""",
        (patient_ids[1],),
    )
    db.commit()
    admin = db.execute(
        "SELECT id, username FROM users WHERE username='admin'"
    ).fetchone()

    yield {
        "app": app,
        "db": db,
        "admin": admin,
        "patient_ids": patient_ids,
    }

    context.pop()
    core._initialized = False


def client_for(fixture):
    client = fixture["app"].test_client()
    with client.session_transaction() as session:
        session["user_id"] = int(fixture["admin"]["id"])
    return client


def test_default_appointment_view_is_today_and_list_expands_range(appointments_app):
    client = client_for(appointments_app)
    today = client.get("/appointments/")
    today_html = today.get_data(as_text=True)

    assert today.status_code == 200
    assert "نوبت‌های امروز" in today_html
    assert "بیمار نوبت 1" in today_html
    assert "بیمار نوبت 2" not in today_html
    assert 'aria-current="page"' in today_html

    listing = client.get("/appointments/?view=list")
    list_html = listing.get_data(as_text=True)
    assert listing.status_code == 200
    assert "فهرست نوبت‌ها" in list_html
    assert "بیمار نوبت 1" in list_html
    assert "بیمار نوبت 2" in list_html
    assert 'name="view" value="list"' in list_html


def test_new_appointment_prefills_patient_return_context_and_next_quarter_hour(
    appointments_app,
):
    client = client_for(appointments_app)
    patient_id = appointments_app["patient_ids"][0]
    response = client.get(f"/appointments/new?patient_link_id={patient_id}")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert f'value="{patient_id}" selected' in html
    assert f'value="/patients/{patient_id}"' in html
    assert f'value="{jalali_date(2026, 8, 5)}"' in html
    assert 'value="10:15"' in html
    assert "زمان پیشنهادی" in html
    assert "پس از ثبت به همان مسیر برمی‌گردید" in html


def test_invalid_booking_renders_same_form_with_every_submitted_value(
    appointments_app,
):
    client = client_for(appointments_app)
    patient_id = appointments_app["patient_ids"][0]
    before = appointments_app["db"].execute(
        "SELECT COUNT(*) FROM appointments"
    ).fetchone()[0]
    response = client.post(
        "/appointments/new",
        data={
            "patient_link_id": str(patient_id),
            "date": "تاریخ نامعتبر",
            "time": "13:45",
            "appt_type": "lab",
            "recurrence_months": "3",
            "notes": "این متن نباید از بین برود",
            "return_url": f"/patients/{patient_id}",
        },
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 400
    assert "نوبت ثبت نشد" in html
    assert "تاریخ نامعتبر" in html
    assert 'value="13:45"' in html
    assert 'value="lab" selected' in html
    assert 'value="3" selected' in html
    assert "این متن نباید از بین برود" in html
    assert f'value="{patient_id}" selected' in html
    after = appointments_app["db"].execute(
        "SELECT COUNT(*) FROM appointments"
    ).fetchone()[0]
    assert after == before


def test_patient_context_booking_creates_appointment_and_returns_to_patient(
    appointments_app,
):
    client = client_for(appointments_app)
    patient_id = appointments_app["patient_ids"][0]
    response = client.post(
        "/appointments/new",
        data={
            "patient_link_id": str(patient_id),
            "date": jalali_date(2026, 8, 7),
            "time": "09:30",
            "appt_type": "checkup",
            "recurrence_months": "",
            "notes": "بازبینی دوره‌ای",
            "return_url": "",
        },
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    # Booking returns to the patient, and the Patient Workspace lands the clinician on
    # the tab where the appointment just created is visible instead of a bare patient
    # URL that would make them hunt for it.
    location = response.headers["Location"]
    assert location.startswith(f"/patients/{patient_id}/")
    assert location.endswith("/workspace?tab=encounters")
    row = appointments_app["db"].execute(
        """SELECT * FROM appointments
           WHERE patient_link_id=? AND scheduled_at='2026-08-07 09:30:00'""",
        (patient_id,),
    ).fetchone()
    assert row
    assert row["appt_type"] == "checkup"
    assert row["notes"] == "بازبینی دوره‌ای"
    assert row["status"] == "scheduled"


def test_external_return_url_is_rejected_after_successful_booking(appointments_app):
    client = client_for(appointments_app)
    patient_id = appointments_app["patient_ids"][1]
    response = client.post(
        "/appointments/new",
        data={
            "patient_link_id": str(patient_id),
            "date": jalali_date(2026, 8, 8),
            "time": "10:00",
            "appt_type": "visit",
            "return_url": "https://evil.example/steal",
        },
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith("/appointments/?view=today")
    assert "evil.example" not in response.headers["Location"]


def test_status_mutation_returns_to_same_filtered_view(appointments_app):
    client = client_for(appointments_app)
    appointment_id = appointments_app["db"].execute(
        "SELECT id FROM appointments WHERE scheduled_at='2026-08-05 11:00:00'"
    ).fetchone()["id"]
    return_url = "/appointments/?view=list&status=scheduled"
    response = client.post(
        f"/appointments/{appointment_id}/status",
        data={"status": "done", "return_url": return_url},
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith(return_url)
    status = appointments_app["db"].execute(
        "SELECT status FROM appointments WHERE id=?",
        (appointment_id,),
    ).fetchone()["status"]
    assert status == "done"


def test_work_center_booking_remains_the_only_task_episode_booking_seam():
    appointments_api = (ROOT / "src/api/appointments.py").read_text(encoding="utf-8")
    work_center = (
        ROOT
        / "src/services/followup_orchestration/work_center_action_service.py"
    ).read_text(encoding="utf-8")
    template = (ROOT / "src/templates/appointments/new.html").read_text(
        encoding="utf-8"
    )
    actions_css = (
        ROOT / "src/static/css/work-center-actions-v2.css"
    ).read_text(encoding="utf-8")

    assert "episode_id" not in appointments_api
    assert "FollowupBookingService" in work_center
    assert "form_values.return_url" in template
    assert '[data-contact-outcome="APPOINTMENT_BOOKED"]' in actions_css
