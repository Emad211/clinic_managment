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


def _patient(db, national_id: str, full_name: str, phone: str) -> int:
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id,full_name,phone_number,enrolled_by,enrolled_at,updated_at)
               VALUES (?,?,?,'admin','2026-08-06 10:00:00',
                       '2026-08-06 10:00:00')""",
            (national_id, full_name, phone),
        ).lastrowid
    )
    db.commit()
    return patient_id


def test_empty_cockpit_does_not_invent_revenue_or_forecast(growth_app):
    from src.services.growth_revenue_cockpit_service import (
        GrowthRevenueCockpitService,
    )

    result = GrowthRevenueCockpitService().build()

    assert result["today"]["collected"] == 0
    assert result["month"]["collected"] == 0
    assert result["revenue_by_source"] == []
    assert result["referral_leaders"] == []
    assert result["forecast"]["available"] is False
    assert "تعداد نوبت به‌تنهایی درآمد محسوب نمی‌شود" in result["forecast"]["reason"]


def test_converted_lead_revenue_is_attributed_to_its_source(growth_app):
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
    patient_id = _patient(
        growth_app["db"],
        "ATTR-001",
        "بیمار منتسب",
        "09127777777",
    )
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


def test_patient_referrer_gets_conversion_and_month_revenue_attribution(growth_app):
    from src.services.growth_revenue_cockpit_service import (
        GrowthRevenueCockpitService,
    )
    from src.services.lead_pipeline_service import LeadPipelineService

    referrer_id = _patient(
        growth_app["db"],
        "REF-ATTR-001",
        "بیمار معرف برتر",
        "09127770001",
    )
    referred_patient_id = _patient(
        growth_app["db"],
        "REFERRED-001",
        "بیمار معرفی‌شده",
        "09127770002",
    )
    service = LeadPipelineService(growth_app["db"])
    lead = service.create(
        full_name="بیمار معرفی‌شده",
        phone_number="09127770002",
        source_code="PATIENT_REFERRAL",
        referrer_patient_link_id=referrer_id,
        actor_username="admin",
    )
    growth_app["db"].execute(
        """UPDATE growth_leads
           SET status='CONVERTED',patient_link_id=?,
               converted_at='2026-08-06 11:00:00'
           WHERE id=?""",
        (referred_patient_id, lead["id"]),
    )
    growth_app["db"].commit()

    observations = [
        {
            "patient_link_id": referred_patient_id,
            "accounting_invoice_id": 7101,
            "invoice_status": "closed",
            "billed_amount": 1_500_000,
            "collected_amount": 1_200_000,
            "work_date": "2026-08-06",
            "observed_at": "2026-08-06 13:00:00",
        },
        {
            "patient_link_id": referred_patient_id,
            "accounting_invoice_id": 7102,
            "invoice_status": "closed",
            "billed_amount": 500_000,
            "collected_amount": 500_000,
            "work_date": "2026-08-06",
            "observed_at": "2026-08-06 14:00:00",
        },
    ]
    cockpit = GrowthRevenueCockpitService()
    leaders = cockpit._referral_leaders(observations)
    summary = cockpit._referral_summary(leaders)

    assert len(leaders) == 1
    leader = leaders[0]
    assert leader["referrer_id"] == referrer_id
    assert leader["referrer_name"] == "بیمار معرف برتر"
    assert leader["referrals"] == 1
    assert leader["converted"] == 1
    assert leader["conversion_rate"] == 100.0
    assert leader["revenue_patients"] == 1
    assert leader["invoices"] == 2
    assert leader["billed"] == 2_000_000
    assert leader["collected"] == 1_700_000
    assert summary == {
        "referrers": 1,
        "referrals": 1,
        "converted": 1,
        "billed": 2_000_000,
        "collected": 1_700_000,
    }


def test_referral_leader_ranking_prefers_collected_then_conversion(growth_app):
    from src.services.growth_revenue_cockpit_service import (
        GrowthRevenueCockpitService,
    )
    from src.services.lead_pipeline_service import LeadPipelineService

    db = growth_app["db"]
    first_referrer = _patient(db, "REF-RANK-1", "معرف اول", "09127770101")
    second_referrer = _patient(db, "REF-RANK-2", "معرف دوم", "09127770102")
    first_patient = _patient(db, "REFERRED-RANK-1", "ارجاع اول", "09127770201")
    second_patient = _patient(db, "REFERRED-RANK-2", "ارجاع دوم", "09127770202")
    service = LeadPipelineService(db)
    first = service.create(
        full_name="ارجاع اول",
        phone_number="09127770201",
        source_code="PATIENT_REFERRAL",
        referrer_patient_link_id=first_referrer,
        actor_username="admin",
    )
    second = service.create(
        full_name="ارجاع دوم",
        phone_number="09127770202",
        source_code="PATIENT_REFERRAL",
        referrer_patient_link_id=second_referrer,
        actor_username="admin",
    )
    db.execute(
        "UPDATE growth_leads SET status='CONVERTED',patient_link_id=? WHERE id=?",
        (first_patient, first["id"]),
    )
    db.execute(
        "UPDATE growth_leads SET status='CONVERTED',patient_link_id=? WHERE id=?",
        (second_patient, second["id"]),
    )
    db.commit()

    leaders = GrowthRevenueCockpitService()._referral_leaders(
        [
            {
                "patient_link_id": first_patient,
                "billed_amount": 900_000,
                "collected_amount": 700_000,
            },
            {
                "patient_link_id": second_patient,
                "billed_amount": 500_000,
                "collected_amount": 500_000,
            },
        ]
    )
    assert [row["referrer_id"] for row in leaders] == [
        first_referrer,
        second_referrer,
    ]


def test_growth_cockpit_route_renders_source_boundary(growth_app):
    client = _client(growth_app)
    response = client.get(_url(growth_app, "growth.cockpit"))
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "رشد و درآمد" in html
    assert "بدون شمردن مراجعات تاریخیِ فاقد انتساب" in html
    assert "پیش‌بینی معتبر هنوز ممکن نیست" in html
    assert "بیماران معرف برتر" in html
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
    assert "referral_leaders" in template
    assert "EXISTING_PATIENT" in service
    assert "referrer_patient_link_id" in service
    assert "latest_observations" in service
    assert "forecast" in service
