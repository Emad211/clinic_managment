from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from flask import url_for


@pytest.fixture()
def quality_app(tmp_path, monkeypatch):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.appointments_repo import AppointmentRepository
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.patients_repo import PatientRepository
    from src.adapters.sqlite.vitals_repo import VitalsRepository
    from src.app import create_app
    from src.common.utils import iran_now
    from src.services.clinical_engine.facade import ClinicalEngineReadOnlyFacade

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "quality.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "quality-test",
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
    now = iran_now()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)

    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id,full_name,phone_number,birthdate,enrolled_by,
                enrolled_at,updated_at)
               VALUES (NULL,'بیمار ناقص','12345',NULL,'pytest',?,?)""",
            (
                (now - timedelta(days=300)).isoformat(
                    sep=" ", timespec="seconds"
                ),
                now.isoformat(sep=" ", timespec="seconds"),
            ),
        ).lastrowid
    )
    referrer_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id,full_name,phone_number,birthdate,enrolled_by,
                enrolled_at,updated_at)
               VALUES ('0099887766','بیمار معرف','09135550000','1985-01-01',
                       'pytest',?,?)""",
            (
                now.isoformat(sep=" ", timespec="seconds"),
                now.isoformat(sep=" ", timespec="seconds"),
            ),
        ).lastrowid
    )
    duplicate_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id,full_name,phone_number,birthdate,enrolled_by,
                enrolled_at,updated_at)
               VALUES ('0011223344','بیمار دیگر','09135551111','1990-01-01',
                       'pytest',?,?)""",
            (
                now.isoformat(sep=" ", timespec="seconds"),
                now.isoformat(sep=" ", timespec="seconds"),
            ),
        ).lastrowid
    )
    db.commit()

    PatientRepository().add_medication(
        patient_id,
        drug_name="داروی آزاد قدیمی",
        dose=None,
        schedule=None,
        start_date="2026-01-01",
        created_by="pytest",
    )
    VitalsRepository().add_lab(
        patient_id,
        test_name="آزمایش آزاد قدیمی",
        test_key=None,
        value=7.2,
        unit="wrong-unit",
        taken_at="2026-08-01 12:00:00",
        recorded_by="pytest",
    )
    stale_appointment = AppointmentRepository(db).create(
        patient_id,
        scheduled_at=(now - timedelta(days=2)).isoformat(
            sep=" ", timespec="seconds"
        ),
        appt_type="visit",
        created_by="pytest",
    )

    admin = db.execute(
        "SELECT id,username FROM users WHERE username='admin'"
    ).fetchone()
    yield {
        "app": app,
        "db": db,
        "admin": admin,
        "patient_id": patient_id,
        "referrer_id": referrer_id,
        "duplicate_id": duplicate_id,
        "stale_appointment": stale_appointment,
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


def _jalali_birthdate() -> str:
    from src.common.utils import gregorian_to_jalali

    year, month, day = gregorian_to_jalali(1992, 5, 20)
    return f"{year}/{month:02d}/{day:02d}"


def _codes(result: dict) -> set[str]:
    return {issue["code"] for issue in result["issues"]}


def test_quality_service_detects_structural_patient_issues(quality_app):
    from src.services.patient_data_quality_service import PatientDataQualityService

    result = PatientDataQualityService(quality_app["db"]).build(
        quality_app["patient_id"]
    )
    codes = _codes(result)

    assert "IDENTITY_PHONE_INVALID" in codes
    assert "IDENTITY_NATIONAL_ID_MISSING" in codes
    assert "IDENTITY_BIRTHDATE_MISSING" in codes
    assert "MEDICATION_CATALOG_MISSING" in codes
    assert "MEDICATION_DOSE_MISSING" in codes
    assert "MEDICATION_SCHEDULE_MISSING" in codes
    assert "LAB_CATALOG_MISSING" in codes
    assert "APPOINTMENT_STALE_SCHEDULED" in codes
    assert "ACQUISITION_SOURCE_UNKNOWN" in codes
    assert result["counts"]["danger"] >= 3
    assert result["by_tab"]["meds"]
    assert result["by_tab"]["clinical"]
    assert result["by_tab"]["encounters"]


def test_workspace_renders_quality_panel_tab_badges_and_native_editors(quality_app):
    client = _client(quality_app)
    response = client.get(
        _url(
            quality_app,
            "patient_workspace.detail",
            pid=quality_app["patient_id"],
            tab="summary",
        )
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "دقت و کامل‌بودن داده" in html
    assert "داروی فعال بدون هویت کاتالوگی" in html
    assert "workspace-identity-editor" in html
    assert "workspace-acquisition-editor" in html
    assert "patient-workspace-quality-v1.css" in html
    assert "pill-warn" in html


def test_identity_duplicate_is_rejected_and_state_is_preserved(quality_app):
    client = _client(quality_app)
    response = client.post(
        _url(
            quality_app,
            "patient_workspace_mutations.update_identity",
            pid=quality_app["patient_id"],
        ),
        data={
            "full_name": "نام اصلاح‌شده",
            "phone_number": "09135551111",
            "national_id": "0011223344",
            "birthdate": _jalali_birthdate(),
            "gender": "female",
            "address": "نشانی حفظ‌شده",
        },
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 422
    assert "این کد ملی در پرونده" in html
    assert "این شماره موبایل در پرونده" in html
    assert "نام اصلاح‌شده" in html
    assert "نشانی حفظ‌شده" in html
    row = quality_app["db"].execute(
        "SELECT full_name,phone_number,national_id FROM patient_links WHERE id=?",
        (quality_app["patient_id"],),
    ).fetchone()
    assert row["full_name"] == "بیمار ناقص"
    assert row["phone_number"] == "12345"
    assert row["national_id"] is None


def test_valid_identity_update_removes_identity_exceptions(quality_app):
    client = _client(quality_app)
    response = client.post(
        _url(
            quality_app,
            "patient_workspace_mutations.update_identity",
            pid=quality_app["patient_id"],
        ),
        data={
            "full_name": "بیمار کامل‌شده",
            "phone_number": "09135552222",
            "national_id": "1234567890",
            "birthdate": _jalali_birthdate(),
            "gender": "female",
            "address": "نشانی جدید",
        },
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert "tab=summary#workspace-identity-editor" in response.headers["Location"]
    from src.services.patient_data_quality_service import PatientDataQualityService

    codes = _codes(
        PatientDataQualityService(quality_app["db"]).build(
            quality_app["patient_id"]
        )
    )
    assert "IDENTITY_PHONE_INVALID" not in codes
    assert "IDENTITY_PHONE_MISSING" not in codes
    assert "IDENTITY_NATIONAL_ID_MISSING" not in codes
    assert "IDENTITY_BIRTHDATE_MISSING" not in codes


def test_explicit_acquisition_removes_unknown_source_without_creating_lead(
    quality_app,
):
    client = _client(quality_app)
    patient_id = quality_app["patient_id"]
    before_leads = quality_app["db"].execute(
        "SELECT COUNT(*) FROM growth_leads"
    ).fetchone()[0]
    response = client.post(
        _url(quality_app, "patient_acquisition.update", pid=patient_id),
        data={
            "source_code": "INSTAGRAM",
            "source_detail": "پیج کلینیک",
        },
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    after_leads = quality_app["db"].execute(
        "SELECT COUNT(*) FROM growth_leads"
    ).fetchone()[0]
    assert after_leads == before_leads
    acquisition = quality_app["db"].execute(
        "SELECT * FROM growth_patient_acquisition WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()
    assert acquisition["source_code"] == "INSTAGRAM"
    assert acquisition["source_detail"] == "پیج کلینیک"

    from src.services.patient_data_quality_service import PatientDataQualityService

    codes = _codes(PatientDataQualityService(quality_app["db"]).build(patient_id))
    assert "ACQUISITION_SOURCE_UNKNOWN" not in codes


def test_patient_referral_attribution_requires_exact_non_self_referrer(quality_app):
    client = _client(quality_app)
    patient_id = quality_app["patient_id"]
    self_response = client.post(
        _url(quality_app, "patient_acquisition.update", pid=patient_id),
        data={
            "source_code": "PATIENT_REFERRAL",
            "referrer_patient_link_id": str(patient_id),
        },
    )
    assert self_response.status_code == 422
    assert "بیمار نمی‌تواند معرف خودش باشد" in self_response.get_data(as_text=True)

    valid = client.post(
        _url(quality_app, "patient_acquisition.update", pid=patient_id),
        data={
            "source_code": "PATIENT_REFERRAL",
            "referrer_patient_link_id": str(quality_app["referrer_id"]),
        },
        follow_redirects=False,
    )
    assert valid.status_code in {302, 303}
    row = quality_app["db"].execute(
        """SELECT source_code,referrer_patient_link_id,referrer_name
           FROM growth_patient_acquisition WHERE patient_link_id=?""",
        (patient_id,),
    ).fetchone()
    assert row["source_code"] == "PATIENT_REFERRAL"
    assert int(row["referrer_patient_link_id"]) == quality_app["referrer_id"]
    assert row["referrer_name"] == "بیمار معرف"


def test_explicit_acquisition_is_used_as_revenue_source_fallback(quality_app):
    from src.adapters.sqlite.patient_acquisition_schema import (
        ensure_patient_acquisition_storage,
    )
    from src.services.growth_revenue_cockpit_service import (
        GrowthRevenueCockpitService,
    )

    ensure_patient_acquisition_storage(quality_app["db"])
    quality_app["db"].execute(
        """INSERT INTO growth_patient_acquisition
           (patient_link_id,source_code,source_detail,recorded_at,recorded_by)
           VALUES (?,'GOOGLE','جست‌وجوی محلی','2026-08-06 12:00:00','admin')
           ON CONFLICT(patient_link_id) DO UPDATE SET source_code='GOOGLE'""",
        (quality_app["patient_id"],),
    )
    quality_app["db"].commit()
    rows = GrowthRevenueCockpitService()._revenue_by_lead_source(
        [
            {
                "patient_link_id": quality_app["patient_id"],
                "billed_amount": 900_000,
                "collected_amount": 700_000,
            }
        ]
    )
    assert rows[0]["source_code"] == "GOOGLE"
    assert rows[0]["source_label"] == "گوگل"
    assert rows[0]["collected"] == 700_000


def test_quality_javascript_only_changes_visibility():
    root = Path(__file__).resolve().parents[1]
    source = (
        root / "src/static/js/patient-workspace-catalogs.js"
    ).read_text(encoding="utf-8")

    assert "data-acquisition-form" in source
    assert "PATIENT_REFERRAL" in source
    assert "DOCTOR_REFERRAL" in source
    assert "fetch(" not in source
    assert "FormData" not in source
