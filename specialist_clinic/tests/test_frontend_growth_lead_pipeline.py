from __future__ import annotations

from datetime import timedelta

import pytest
from flask import url_for


@pytest.fixture()
def lead_app(tmp_path):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.core import get_db
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "lead-pipeline.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "lead-pipeline-test",
        }
    )
    context = app.app_context()
    context.push()
    db = get_db()
    admin = db.execute(
        "SELECT id,username FROM users WHERE username='admin'"
    ).fetchone()
    yield {"app": app, "db": db, "admin": admin}
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


def _future_text(days: int = 2) -> str:
    from src.common.utils import iran_now

    current = iran_now()
    if current.tzinfo is not None:
        current = current.replace(tzinfo=None)
    return (current + timedelta(days=days)).replace(
        hour=10,
        minute=0,
        second=0,
        microsecond=0,
    ).isoformat(sep=" ", timespec="seconds")


def test_lead_creation_does_not_create_patient(lead_app):
    from src.services.lead_pipeline_service import LeadPipelineService

    result = LeadPipelineService(lead_app["db"]).create(
        full_name="سرنخ آزمایشی",
        phone_number="09126666666",
        source_code="INSTAGRAM",
        interest_code="DIABETES",
        actor_username="admin",
    )

    assert result["status"] == "NEW"
    assert result["patient_link_id"] is None
    assert lead_app["db"].execute(
        "SELECT COUNT(*) FROM patient_links WHERE phone_number='09126666666'"
    ).fetchone()[0] == 0
    assert lead_app["db"].execute(
        "SELECT COUNT(*) FROM growth_lead_events WHERE lead_id=?",
        (result["id"],),
    ).fetchone()[0] == 1


def test_duplicate_open_phone_reuses_existing_lead(lead_app):
    from src.services.lead_pipeline_service import LeadPipelineService

    service = LeadPipelineService(lead_app["db"])
    first = service.create(
        full_name="سرنخ اول",
        phone_number="+989126666667",
        source_code="PHONE",
        actor_username="admin",
    )
    second = service.create(
        full_name="سرنخ تکراری",
        phone_number="09126666667",
        source_code="WEBSITE",
        actor_username="admin",
    )

    assert second["duplicate"] is True
    assert second["id"] == first["id"]
    assert lead_app["db"].execute(
        "SELECT COUNT(*) FROM growth_leads WHERE phone_number='09126666667'"
    ).fetchone()[0] == 1


def test_lead_lifecycle_requires_appointment_before_attendance(lead_app):
    from src.services.lead_pipeline_service import LeadPipelineError, LeadPipelineService

    service = LeadPipelineService(lead_app["db"])
    lead = service.create(
        full_name="سرنخ مرحله‌ای",
        phone_number="09126666668",
        source_code="PATIENT_REFERRAL",
        referrer_name="بیمار معرف",
        actor_username="admin",
    )

    with pytest.raises(LeadPipelineError):
        service.transition(
            lead["id"],
            to_status="ATTENDED",
            actor_username="admin",
        )

    contacted = service.transition(
        lead["id"],
        to_status="CONTACTED",
        actor_username="admin",
        next_action_at=_future_text(1),
        note="تماس موفق",
    )
    booked = service.transition(
        lead["id"],
        to_status="APPOINTMENT_BOOKED",
        actor_username="admin",
        appointment_at=_future_text(3),
    )
    attended = service.transition(
        lead["id"],
        to_status="ATTENDED",
        actor_username="admin",
    )

    assert contacted["status"] == "CONTACTED"
    assert booked["status"] == "APPOINTMENT_BOOKED"
    assert attended["status"] == "ATTENDED"
    assert lead_app["db"].execute(
        "SELECT COUNT(*) FROM growth_lead_events WHERE lead_id=?",
        (lead["id"],),
    ).fetchone()[0] == 4


def test_lost_lead_requires_structured_reason(lead_app):
    from src.services.lead_pipeline_service import LeadPipelineError, LeadPipelineService

    service = LeadPipelineService(lead_app["db"])
    lead = service.create(
        full_name="سرنخ از دست رفته",
        phone_number="09126666669",
        source_code="GOOGLE",
        actor_username="admin",
    )

    with pytest.raises(LeadPipelineError):
        service.transition(
            lead["id"],
            to_status="LOST",
            actor_username="admin",
        )

    lost = service.transition(
        lead["id"],
        to_status="LOST",
        lost_reason="PRICE",
        actor_username="admin",
        note="هزینه برای بیمار مناسب نبود",
    )
    assert lost["status"] == "LOST"
    assert lost["lost_reason"] == "PRICE"
    assert lost["next_action_at"] is None


def test_explicit_conversion_creates_patient_and_real_appointment(lead_app):
    from src.services.lead_pipeline_service import LeadPipelineService

    service = LeadPipelineService(lead_app["db"])
    lead = service.create(
        full_name="سرنخ تبدیل‌شونده",
        phone_number="09126666670",
        national_id="0011223344",
        source_code="DOCTOR_REFERRAL",
        referrer_name="دکتر معرف",
        interest_code="HYPERTENSION",
        actor_username="admin",
    )
    service.transition(
        lead["id"],
        to_status="APPOINTMENT_BOOKED",
        appointment_at=_future_text(4),
        actor_username="admin",
    )
    service.transition(
        lead["id"],
        to_status="ATTENDED",
        actor_username="admin",
    )
    result = service.convert(lead["id"], actor_username="admin")

    assert result["status"] == "CONVERTED"
    assert result["patient_link_id"]
    patient = lead_app["db"].execute(
        "SELECT * FROM patient_links WHERE id=?",
        (result["patient_link_id"],),
    ).fetchone()
    assert patient["full_name"] == "سرنخ تبدیل‌شونده"
    appointment = lead_app["db"].execute(
        "SELECT * FROM appointments WHERE id=?",
        (result["appointment_id"],),
    ).fetchone()
    assert int(appointment["patient_link_id"]) == int(result["patient_link_id"])
    assert appointment["status"] == "scheduled"


def test_lead_pages_render_pipeline_and_one_page_actions(lead_app):
    from src.services.lead_pipeline_service import LeadPipelineService

    lead = LeadPipelineService(lead_app["db"]).create(
        full_name="سرنخ رابط",
        phone_number="09126666671",
        source_code="CAMPAIGN",
        source_detail="کمپین تابستان",
        actor_username="admin",
    )
    client = _client(lead_app)

    listing = client.get(_url(lead_app, "leads.index"))
    detail = client.get(_url(lead_app, "leads.detail", lead_id=lead["id"]))

    assert listing.status_code == 200
    assert "سرنخ‌ها و رشد بیمار" in listing.get_data(as_text=True)
    assert "سرنخ رابط" in listing.get_data(as_text=True)
    assert detail.status_code == 200
    assert "اقدام بعدی" in detail.get_data(as_text=True)
    assert "ثبت تماس موفق" in detail.get_data(as_text=True)
    assert "تعیین زمان مراجعه" in detail.get_data(as_text=True)


def test_lead_pipeline_has_no_patient_foreign_key_until_conversion():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    schema = (
        root / "src/adapters/sqlite/lead_pipeline_schema.py"
    ).read_text(encoding="utf-8")
    service = (
        root / "src/services/lead_pipeline_service.py"
    ).read_text(encoding="utf-8")

    assert "patient_link_id INTEGER" in schema
    assert "status TEXT NOT NULL DEFAULT 'NEW'" in schema
    assert "PatientService().enroll_manual" in service
    assert "convert" in service
