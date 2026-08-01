from __future__ import annotations

from datetime import datetime

import pytest


@pytest.fixture()
def adjudication_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "hypoglycemia-adjudication.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "hypoglycemia-adjudication-test",
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


def _candidate(db, patient_id: int, value: float = 52):
    from src.services.hypoglycemia_shadow_glucose_ingest import (
        HypoglycemiaShadowGlucoseIngestService,
    )

    service = HypoglycemiaShadowGlucoseIngestService(
        db,
        clock=lambda: datetime(2026, 8, 1, 12, 0, 0),
    )
    reading_id = service.add_vital_reading(
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
    return dict(row), reading_id


def _post_decision(client, event, decision, rationale="منبع بررسی شد."):
    return client.post(
        f"/manager/hypoglycemia-shadow/candidates/{event['event_id']}/adjudicate",
        data={
            "expected_version_id": str(event["id"]),
            "decision": decision,
            "rationale": rationale,
        },
    )


def test_candidate_queue_requires_login(adjudication_app):
    response = adjudication_app.test_client().get(
        "/manager/hypoglycemia-shadow/candidates"
    )
    assert response.status_code in {302, 303}
    assert "/auth/login" in response.headers["Location"]


def test_staff_without_clinical_decision_permission_is_denied(adjudication_app):
    from src.services.auth_service import AuthService

    with adjudication_app.app_context():
        assert AuthService().register_user(
            "adjudication-staff",
            "safe-password",
            "staff",
            "کاربر ثبت داده",
        )
    client = _login(
        adjudication_app,
        "adjudication-staff",
        "safe-password",
    )
    response = client.get("/manager/hypoglycemia-shadow/candidates")

    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith("/")


def test_empty_queue_does_not_install_storage_and_is_not_cached(adjudication_app):
    from src.adapters.sqlite.core import get_db

    with adjudication_app.app_context():
        db = get_db()
        before = db.execute(
            """SELECT COUNT(*) FROM sqlite_master
               WHERE type='table' AND name LIKE 'hypoglycemia_shadow_%'"""
        ).fetchone()[0]

    response = _login(adjudication_app).get(
        "/manager/hypoglycemia-shadow/candidates"
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "هنوز Candidate ثبت نشده است" in html
    assert response.headers["Cache-Control"] == "no-store, max-age=0"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"

    with adjudication_app.app_context():
        db = get_db()
        assert db.execute(
            """SELECT COUNT(*) FROM sqlite_master
               WHERE type='table' AND name LIKE 'hypoglycemia_shadow_%'"""
        ).fetchone()[0] == before


def test_authorized_queue_shows_current_candidate_without_sensitive_source_identity(
    adjudication_app,
):
    from src.adapters.sqlite.core import get_db

    with adjudication_app.app_context():
        db = get_db()
        patient_id = _patient(db, "ADJSECRET001", "بیمار داوری یک")
        event, reading_id = _candidate(db, patient_id, 52)

    response = _login(adjudication_app).get(
        "/manager/hypoglycemia-shadow/candidates"
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "بیمار داوری یک" in html
    assert "۵۲ mg/dL" in html
    assert "LEVEL 2" in html
    assert "تأیید رخداد" in html
    assert "رد Candidate" in html
    assert "ثبت تعارض" in html
    assert "ADJSECRET001" not in html
    assert "source_record_id" not in html
    assert f">{reading_id}<" not in html
    assert event["event_id"] in html  # internal form action only


def test_confirm_records_event_only_without_review_task_or_recommendation(
    adjudication_app,
):
    from src.adapters.sqlite.core import get_db
    from src.services.hypoglycemia_shadow_observability import (
        HypoglycemiaShadowObservability,
    )

    with adjudication_app.app_context():
        db = get_db()
        patient_id = _patient(db, "ADJ002", "بیمار داوری دو")
        event, _reading_id = _candidate(db, patient_id, 51)

    client = _login(adjudication_app)
    response = _post_decision(
        client,
        event,
        "CONFIRMED",
        "عدد و زمان اندازه‌گیری در پرونده بررسی شد.",
    )
    assert response.status_code in {302, 303}

    with adjudication_app.app_context():
        db = get_db()
        history = db.execute(
            """SELECT status, verification, actor_username, note
               FROM hypoglycemia_shadow_event_versions
               WHERE event_id=? ORDER BY version_number""",
            (event["event_id"],),
        ).fetchall()
        assert [row["status"] for row in history] == [
            "CANDIDATE",
            "CONFIRMED",
        ]
        assert history[-1]["verification"] == "CONFIRMED"
        assert history[-1]["actor_username"] == "admin"
        assert "اندازه‌گیری" in history[-1]["note"]
        assert db.execute(
            "SELECT COUNT(*) FROM hypoglycemia_shadow_review_events"
        ).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM followup_tasks").fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM clinical_recommendation_events"
        ).fetchone()[0] == 0
        snapshot = HypoglycemiaShadowObservability(db).snapshot()
        assert snapshot["event_counts"]["CONFIRMED"] == 1
        assert snapshot["backlog"]["confirmed_without_active_review"] == 1

    html = client.get(
        "/manager/hypoglycemia-shadow/candidates"
    ).get_data(as_text=True)
    assert "بیمار داوری دو" not in html


def test_empty_rationale_or_invalid_decision_does_not_change_event(
    adjudication_app,
):
    from src.adapters.sqlite.core import get_db

    with adjudication_app.app_context():
        db = get_db()
        patient_id = _patient(db, "ADJ003", "بیمار داوری سه")
        event, _reading_id = _candidate(db, patient_id, 50)

    client = _login(adjudication_app)
    empty = _post_decision(client, event, "REJECTED", rationale="   ")
    invalid = _post_decision(client, event, "MEDICATION_CHANGE")

    assert empty.status_code in {302, 303}
    assert invalid.status_code in {302, 303}
    with adjudication_app.app_context():
        db = get_db()
        assert db.execute(
            """SELECT COUNT(*) FROM hypoglycemia_shadow_event_versions
               WHERE event_id=?""",
            (event["event_id"],),
        ).fetchone()[0] == 1


def test_conflict_remains_in_queue_and_stale_form_cannot_overwrite_it(
    adjudication_app,
):
    from src.adapters.sqlite.core import get_db

    with adjudication_app.app_context():
        db = get_db()
        patient_id = _patient(db, "ADJ004", "بیمار داوری چهار")
        event, _reading_id = _candidate(db, patient_id, 49)

    client = _login(adjudication_app)
    conflict_response = _post_decision(
        client,
        event,
        "CONFLICT",
        "زمان گزارش بیمار با زمان ثبت دستگاه سازگار نیست.",
    )
    stale_response = _post_decision(
        client,
        event,
        "CONFIRMED",
        "فرم قدیمی نباید روی head جدید بنویسد.",
    )
    assert conflict_response.status_code in {302, 303}
    assert stale_response.status_code in {302, 303}

    with adjudication_app.app_context():
        db = get_db()
        history = db.execute(
            """SELECT status FROM hypoglycemia_shadow_event_versions
               WHERE event_id=? ORDER BY version_number""",
            (event["event_id"],),
        ).fetchall()
        assert [row["status"] for row in history] == [
            "CANDIDATE",
            "CONFLICT",
        ]

    html = client.get(
        "/manager/hypoglycemia-shadow/candidates"
    ).get_data(as_text=True)
    assert "بیمار داوری چهار" in html
    assert "متعارض" in html
    assert "ثبت تعارض" not in html


def test_adjudication_route_is_post_only(adjudication_app):
    rule = next(
        item
        for item in adjudication_app.url_map.iter_rules()
        if item.endpoint == "hypoglycemia_shadow_monitor.adjudicate"
    )
    assert rule.methods == {"POST", "OPTIONS"}
