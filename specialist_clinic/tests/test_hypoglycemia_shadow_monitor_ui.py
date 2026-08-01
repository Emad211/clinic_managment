from __future__ import annotations

from datetime import datetime

import pytest

from test_clinical_engine_v2_followups import _patient


@pytest.fixture()
def shadow_monitor_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "hypoglycemia-monitor.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "hypoglycemia-monitor-test",
        }
    )
    yield app
    core._initialized = False


def _login(app, username="admin", password="admin"):
    client = app.test_client()
    response = client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )
    assert response.status_code in {302, 303}
    return client


def _shadow_service(db):
    from src.services.hypoglycemia_shadow import HypoglycemiaShadowService

    return HypoglycemiaShadowService(
        db,
        clock=lambda: datetime(2026, 8, 1, 11, 0, 0),
    )


def _candidate(service, patient_id, source_record_id, **overrides):
    payload = {
        "patient_link_id": patient_id,
        "source_system": "synthetic_monitor",
        "source_record_id": source_record_id,
        "actor_username": "fixture-loader",
        "reporter_type": "DEVICE",
        "occurred_at": "2026-08-01 09:00:00",
        "event_level": "LEVEL_2",
        "glucose_value": 51,
        "glucose_unit": "mg/dL",
        "verification": "PROVISIONAL",
    }
    payload.update(overrides)
    return service.create_candidate(**payload)


def _confirm(service, candidate, **overrides):
    payload = {
        "expected_current_version_id": candidate["current"]["id"],
        "decision": "CONFIRMED",
        "actor_username": "doctor",
    }
    payload.update(overrides)
    return service.adjudicate(candidate["event_id"], **payload)


def test_shadow_monitor_requires_login(shadow_monitor_app):
    response = shadow_monitor_app.test_client().get(
        "/manager/hypoglycemia-shadow/"
    )
    assert response.status_code in {302, 303}
    assert "/auth/login" in response.headers["Location"]


def test_staff_without_operational_health_permission_cannot_view_monitor(
    shadow_monitor_app,
):
    from src.services.auth_service import AuthService

    with shadow_monitor_app.app_context():
        assert AuthService().register_user(
            "shadow-staff",
            "safe-password",
            "staff",
            "کاربر درمانگاه",
        )
    client = _login(shadow_monitor_app, "shadow-staff", "safe-password")
    response = client.get("/manager/hypoglycemia-shadow/")

    assert response.status_code in {302, 303}
    assert "/dashboard" in response.headers["Location"]


def test_empty_monitor_does_not_install_storage_and_disables_cache(
    shadow_monitor_app,
):
    from src.adapters.sqlite.core import get_db

    with shadow_monitor_app.app_context():
        db = get_db()
        table_count_before = db.execute(
            """SELECT COUNT(*) FROM sqlite_master
               WHERE type='table' AND name LIKE 'hypoglycemia_shadow_%'"""
        ).fetchone()[0]

    response = _login(shadow_monitor_app).get(
        "/manager/hypoglycemia-shadow/"
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "هنوز دادهٔ Shadow ثبت نشده است" in html
    assert 'data-storage-state="NOT_INSTALLED"' in html
    assert "هیچ عملیات نوشتنی ندارد" in html
    assert "احتمال سلول کوچک" in html
    assert response.headers["Cache-Control"] == "no-store, max-age=0"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"

    with shadow_monitor_app.app_context():
        db = get_db()
        assert db.execute(
            """SELECT COUNT(*) FROM sqlite_master
               WHERE type='table' AND name LIKE 'hypoglycemia_shadow_%'"""
        ).fetchone()[0] == table_count_before


def test_manager_home_links_to_shadow_monitor_only_for_permitted_user(
    shadow_monitor_app,
):
    html = _login(shadow_monitor_app).get("/manager/").get_data(as_text=True)

    assert "پایش هیپوگلیسمی Shadow" in html
    assert "/manager/hypoglycemia-shadow/" in html


def test_monitor_renders_aggregate_counts_without_direct_identifiers_or_actions(
    shadow_monitor_app,
):
    from src.adapters.sqlite.core import get_db

    with shadow_monitor_app.app_context():
        db = get_db()
        service = _shadow_service(db)
        p1 = _patient(db, national_id="HYPOMONUI001")
        p2 = _patient(db, national_id="HYPOMONUI002")
        p3 = _patient(db, national_id="HYPOMONUI003")

        candidate = service.create_candidate(
            patient_link_id=p1,
            source_system="synthetic_monitor",
            source_record_id="MON-001",
            actor_username="fixture-loader",
            reporter_type="PATIENT",
            occurred_at=None,
            event_level="UNKNOWN",
            verification="UNVERIFIED",
        )
        confirmed_without_review = _confirm(
            service,
            _candidate(service, p2, "MON-002"),
        )
        level3 = _candidate(
            service,
            p3,
            "MON-003",
            reporter_type="CAREGIVER",
            event_level="LEVEL_3",
            glucose_value=None,
            glucose_unit=None,
            external_assistance="YES",
            altered_function="YES",
        )
        confirmed_level3 = _confirm(service, level3)
        review = service.open_review(
            event_id=confirmed_level3["event_id"],
            expected_event_version_id=confirmed_level3["current"]["id"],
            owner_username="doctor",
            actor_username="doctor",
        )
        service.adjudicate(
            confirmed_level3["event_id"],
            expected_current_version_id=confirmed_level3["current"]["id"],
            decision="ENTERED_IN_ERROR",
            actor_username="doctor",
            note="شاهد مصنوعی ابطال شد.",
        )
        direct_identifiers = {
            "HYPOMONUI001",
            "HYPOMONUI002",
            "HYPOMONUI003",
            candidate["event_id"],
            confirmed_without_review["event_id"],
            confirmed_level3["event_id"],
            review["review_id"],
            "MON-001",
            "MON-002",
            "MON-003",
        }

    response = _login(shadow_monitor_app).get(
        "/manager/hypoglycemia-shadow/"
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'data-storage-state="READY"' in html
    assert 'data-count="event-total">۳<' in html
    assert 'data-count="event-candidate">۱<' in html
    assert 'data-count="event-confirmed">۱<' in html
    assert 'data-count="event-entered_in_error">۱<' in html
    assert 'data-count="review-opened">۱<' in html
    assert 'data-count="backlog-review">۱<' in html
    assert 'data-count="stale-review-source">۱<' in html
    assert "نیازمند بررسی" in html
    assert "هیچ پیشنهاد، نسخه، سفارش یا اجرای درمانی انجام نمی‌دهد" in html
    assert all(value not in html for value in direct_identifiers)
    assert "patient_link_id" not in html
    assert "source_record_id" not in html

    rule = next(
        item
        for item in shadow_monitor_app.url_map.iter_rules()
        if item.endpoint == "hypoglycemia_shadow_monitor.index"
    )
    assert rule.methods == {"GET", "HEAD", "OPTIONS"}
