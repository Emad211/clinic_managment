from __future__ import annotations

from datetime import datetime

import pytest


@pytest.fixture()
def review_opening_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "hypoglycemia-review-opening.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "hypoglycemia-review-opening-test",
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


def _patient(db, national_id: str, full_name: str) -> int:
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, gender, birthdate, enrolled_by,
                enrolled_at)
               VALUES (?, ?, 'female', '1980-01-01', 'pytest',
                       '2026-01-01 09:00:00')""",
            (national_id, full_name),
        ).lastrowid
    )
    db.commit()
    return patient_id


def _shadow_service(db):
    from src.services.hypoglycemia_shadow import HypoglycemiaShadowService

    return HypoglycemiaShadowService(
        db,
        clock=lambda: datetime(2026, 8, 1, 13, 0, 0),
    )


def _candidate(db, patient_id: int, value: float = 52):
    from src.services.hypoglycemia_shadow_glucose_ingest import (
        HypoglycemiaShadowGlucoseIngestService,
    )

    ingest = HypoglycemiaShadowGlucoseIngestService(
        db,
        clock=lambda: datetime(2026, 8, 1, 12, 0, 0),
    )
    reading_id = ingest.add_vital_reading(
        patient_id,
        vtype="fbs",
        value=value,
        unit="mg/dL",
        measured_at="2026-08-01 08:00:00",
        recorded_by="nurse",
    )
    row = db.execute(
        """SELECT * FROM hypoglycemia_shadow_event_versions
           WHERE source_system='vital_readings' AND source_record_id=?
           ORDER BY version_number DESC LIMIT 1""",
        (str(reading_id),),
    ).fetchone()
    return dict(row)


def _confirm(db, candidate):
    return _shadow_service(db).adjudicate(
        candidate["event_id"],
        expected_current_version_id=int(candidate["id"]),
        decision="CONFIRMED",
        actor_username="doctor",
        note="عدد و زمان اندازه‌گیری بررسی شد.",
    )["current"]


def _post_open(client, confirmed):
    return client.post(
        f"/manager/hypoglycemia-shadow/reviews/{confirmed['event_id']}/open",
        data={"expected_version_id": str(confirmed["id"])},
    )


def test_review_queue_requires_login(review_opening_app):
    response = review_opening_app.test_client().get(
        "/manager/hypoglycemia-shadow/reviews"
    )
    assert response.status_code in {302, 303}
    assert "/auth/login" in response.headers["Location"]


def test_staff_without_clinical_decision_permission_is_denied(
    review_opening_app,
):
    from src.services.auth_service import AuthService

    with review_opening_app.app_context():
        assert AuthService().register_user(
            "review-staff",
            "safe-password",
            "staff",
            "کاربر ثبت داده",
        )
    response = _login(
        review_opening_app,
        "review-staff",
        "safe-password",
    ).get("/manager/hypoglycemia-shadow/reviews")

    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith("/")


def test_empty_review_queue_does_not_install_storage_and_disables_cache(
    review_opening_app,
):
    from src.adapters.sqlite.core import get_db

    with review_opening_app.app_context():
        db = get_db()
        before = db.execute(
            """SELECT COUNT(*) FROM sqlite_master
               WHERE type='table' AND name LIKE 'hypoglycemia_shadow_%'"""
        ).fetchone()[0]

    response = _login(review_opening_app).get(
        "/manager/hypoglycemia-shadow/reviews"
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "زیرساخت Shadow هنوز استفاده نشده است" in html
    assert response.headers["Cache-Control"] == "no-store, max-age=0"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"

    with review_opening_app.app_context():
        db = get_db()
        assert db.execute(
            """SELECT COUNT(*) FROM sqlite_master
               WHERE type='table' AND name LIKE 'hypoglycemia_shadow_%'"""
        ).fetchone()[0] == before


def test_queue_lists_only_current_confirmed_events_without_review(
    review_opening_app,
):
    from src.adapters.sqlite.core import get_db

    with review_opening_app.app_context():
        db = get_db()
        candidate_patient = _patient(
            db, "REVSECRET001", "بیمار کاندید"
        )
        confirmed_patient = _patient(
            db, "REVSECRET002", "بیمار تأییدشده"
        )
        _candidate(db, candidate_patient, 52)
        confirmed = _confirm(db, _candidate(db, confirmed_patient, 51))

    response = _login(review_opening_app).get(
        "/manager/hypoglycemia-shadow/reviews"
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "بیمار تأییدشده" in html
    assert "بیمار کاندید" not in html
    assert "REVSECRET001" not in html
    assert "REVSECRET002" not in html
    assert "بازکردن Review برای خودم" in html
    assert confirmed["event_id"] in html
    assert 'data-count="ready">۱<' in html


def test_open_review_is_explicit_idempotent_and_has_no_external_side_effect(
    review_opening_app,
):
    from src.adapters.sqlite.core import get_db

    with review_opening_app.app_context():
        db = get_db()
        patient_id = _patient(db, "REV003", "بیمار Review سه")
        confirmed = _confirm(db, _candidate(db, patient_id, 50))

    client = _login(review_opening_app)
    first = _post_open(client, confirmed)
    second = _post_open(client, confirmed)
    assert first.status_code in {302, 303}
    assert second.status_code in {302, 303}

    with review_opening_app.app_context():
        db = get_db()
        roots = db.execute(
            """SELECT * FROM hypoglycemia_shadow_review_events
               WHERE event_version_id=? AND sequence_number=1""",
            (int(confirmed["id"]),),
        ).fetchall()
        assert len(roots) == 1
        assert roots[0]["event_type"] == "OPENED"
        assert roots[0]["owner_username"] == "admin"
        assert roots[0]["actor_username"] == "admin"
        assert db.execute("SELECT COUNT(*) FROM followup_tasks").fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM clinical_recommendation_events"
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM clinical_alert_events"
        ).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM patient_medications").fetchone()[0] == 0

    html = client.get(
        "/manager/hypoglycemia-shadow/reviews"
    ).get_data(as_text=True)
    assert "بیمار Review سه" not in html
    assert 'data-count="ready">۰<' in html


def test_invalidated_or_stale_event_cannot_open_review(review_opening_app):
    from src.adapters.sqlite.core import get_db

    with review_opening_app.app_context():
        db = get_db()
        patient_id = _patient(db, "REV004", "بیمار Review چهار")
        confirmed = _confirm(db, _candidate(db, patient_id, 49))
        _shadow_service(db).adjudicate(
            confirmed["event_id"],
            expected_current_version_id=int(confirmed["id"]),
            decision="ENTERED_IN_ERROR",
            actor_username="doctor",
            note="منبع ابطال شد.",
        )

    response = _post_open(_login(review_opening_app), confirmed)
    assert response.status_code in {302, 303}

    with review_opening_app.app_context():
        db = get_db()
        assert db.execute(
            "SELECT COUNT(*) FROM hypoglycemia_shadow_review_events"
        ).fetchone()[0] == 0


def test_manager_home_links_to_review_queue_for_authorized_user(
    review_opening_app,
):
    html = _login(review_opening_app).get("/manager/").get_data(as_text=True)

    assert "بازکردن Reviewهای Shadow" in html
    assert "/manager/hypoglycemia-shadow/reviews" in html


def test_open_review_route_is_post_only(review_opening_app):
    rule = next(
        item
        for item in review_opening_app.url_map.iter_rules()
        if item.endpoint == "hypoglycemia_shadow_monitor.open_review"
    )
    assert rule.methods == {"POST", "OPTIONS"}
