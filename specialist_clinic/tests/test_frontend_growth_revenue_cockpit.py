from __future__ import annotations

import pytest
from flask import url_for


@pytest.fixture()
def growth_app(tmp_path):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.core import get_db
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "growth-cockpit.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "growth-cockpit-test",
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


def test_empty_cockpit_does_not_invent_revenue_or_forecast(growth_app):
    from src.services.growth_revenue_cockpit_service import (
        GrowthRevenueCockpitService,
    )

    result = GrowthRevenueCockpitService().build()

    assert result["today"]["collected"] == 0
    assert result["month"]["collected"] == 0
    assert result["revenue_by_source"] == []
    assert result["forecast"]["available"] is False
    assert "تعداد نوبت به‌تنهایی درآمد محسوب نمی‌شود" in result["forecast"]["reason"]


def test_converted_lead_revenue_is_attributed_to_its_source(growth_app, monkeypatch):
    from src.services.growth_revenue_cockpit_service import (
        GrowthRevenueCockpitService,
    )
    from src.services.lead_pipeline_service import LeadPipelineService

    service = LeadPipelineService(growth_app["db"])
    lead = service.create(
        full_name="بیمار منتسب",
        phone_number="09127777777",
        source_code="INSTAGRAM",
        actor_username="admin",
    )
    growth_app["db"].execute(
        """INSERT INTO patient_links
           (national_id,full_name,phone_number,enrolled_by,enrolled_at,updated_at)
           VALUES ('ATTR-001','بیمار منتسب','09127777777','admin',
                   '2026-08-06 10:00:00','2026-08-06 10:00:00')"""
    )
    patient_id = int(growth_app["db"].execute(
        "SELECT id FROM patient_links WHERE national_id='ATTR-001'"
    ).fetchone()["id"])
    growth_app["db"].execute(
        """UPDATE growth_leads SET status='CONVERTED',patient_link_id=?,
                  converted_at='2026-08-06 10:00:00'
           WHERE id=?""",
        (patient_id, lead["id"]),
    )
    growth_app["db"].commit()

    cockpit = GrowthRevenueCockpitService()
    observations = [
        {
            "patient_link_id": patient_id,
            "accounting_invoice_id": 7001,
            "invoice_status": "closed",
            "billed_amount": 1_000_000,
            "collected_amount": 800_000,
            "work_date": "2026-08-06",
            "observed_at": "2026-08-06 12:00:00",
        }
    ]
    rows = cockpit._revenue_by_lead_source(observations)

    assert rows == [
        {
            "source_code": "INSTAGRAM",
            "source_label": "اینستاگرام",
            "patients": 1,
            "invoices": 1,
            "billed": 1_000_000,
            "collected": 800_000,
        }
    ]


def test_existing_patient_revenue_is_separate_from_lead_sources(growth_app):
    from src.services.growth_revenue_cockpit_service import (
        GrowthRevenueCockpitService,
    )

    rows = GrowthRevenueCockpitService()._revenue_by_lead_source(
        [
            {
                "patient_link_id": 999,
                "billed_amount": 500_000,
                "collected_amount": 500_000,
            }
        ]
    )
    assert rows[0]["source_code"] == "EXISTING_PATIENT"
    assert rows[0]["source_label"] == "بیماران موجود / منبع قدیمی"


def test_growth_cockpit_route_renders_source_boundary(growth_app):
    client = _client(growth_app)
    response = client.get(_url(growth_app, "growth.cockpit"))
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "رشد و درآمد" in html
    assert "بدون شمردن مراجعات تاریخیِ فاقد انتساب" in html
    assert "پیش‌بینی معتبر هنوز ممکن نیست" in html
    assert "سرنخ‌ها" in html


def test_growth_cockpit_template_uses_canonical_funnel_keys():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    template = (
        root / "src/templates/growth/cockpit.html"
    ).read_text(encoding="utf-8")
    service = (
        root / "src/services/growth_revenue_cockpit_service.py"
    ).read_text(encoding="utf-8")

    assert "financial_funnel.service_completed" in template
    assert "financial_funnel.completed" not in template
    assert "EXISTING_PATIENT" in service
    assert "latest_observations" in service
    assert "forecast" in service
