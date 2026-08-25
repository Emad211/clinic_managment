"""Functional guards for administrative surfaces after parallel CDS retirement."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def app_ctx(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "descriptive-surfaces.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "descriptive-surfaces-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _patient() -> int:
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, phone_number, enrolled_by)
               VALUES ('DESCR001', 'Descriptive Patient', '09120000000', 'pytest')"""
        ).lastrowid
    )
    db.commit()
    return patient_id


def test_extreme_reading_does_not_enter_administrative_priority_queue(app_ctx):
    from src.adapters.sqlite.core import get_db
    from src.common.utils import iran_now
    from src.services.control_room_service import ControlRoomService

    patient_id = _patient()
    db = get_db()
    db.execute(
        """INSERT INTO vital_readings
           (patient_link_id, type, value, unit, measured_at, source, recorded_by)
           VALUES (?, 'bp_systolic', 300, 'mmHg', ?, 'clinic', 'pytest')""",
        (patient_id, iran_now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    db.commit()

    panel = ControlRoomService().panel(show_value=False)

    assert panel["summary"]["with_observation"] == 1
    assert panel["summary"]["lapsed"] == 0
    assert panel["patients"] == []
    assert panel["projection_policy"] == "ADMINISTRATIVE_ONLY"


def test_open_followup_enters_queue_without_reading_interpretation(app_ctx):
    from src.adapters.sqlite.followups_repo import FollowupRepository
    from src.services.control_room_service import ControlRoomService

    patient_id = _patient()
    FollowupRepository().create(
        patient_id,
        reason="manual",
        detail="Administrative callback",
    )

    panel = ControlRoomService().panel(show_value=False)

    item = next(row for row in panel["patients"] if row["id"] == patient_id)
    assert item["open_fu"] == 1
    assert "پیگیری باز" in item["reasons"]
    assert "control" not in item
    assert "flags" not in item
    assert "warns" not in item


def test_retired_uncontrolled_sms_segment_is_empty_even_for_extreme_value(app_ctx):
    from src.adapters.sqlite.core import get_db
    from src.common.utils import iran_now
    from src.services.sms.campaign_service import resolve_segment

    patient_id = _patient()
    db = get_db()
    db.execute(
        """INSERT INTO vital_readings
           (patient_link_id, type, value, unit, measured_at, source, recorded_by)
           VALUES (?, 'hba1c', 25, '%', ?, 'clinic', 'pytest')""",
        (patient_id, iran_now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    db.commit()

    assert resolve_segment("uncontrolled") == []


def test_indicator_catalog_has_no_threshold_target_or_risk_columns(app_ctx):
    from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository
    from src.adapters.sqlite.core import get_db

    db = get_db()
    columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(clinical_indicators)").fetchall()
    }
    assert not {"direction", "warn", "danger", "target", "goal_low", "goal_high", "risk_weight"} & columns

    projected = ClinicalRulesRepository().get("hba1c")
    assert projected is not None
    assert not {"direction", "warn", "danger", "target", "goal_low", "goal_high", "risk_weight"} & projected.keys()


def _login(app):
    client = app.test_client()
    response = client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    return client


def test_descriptive_and_administrative_pages_render_without_legacy_fields(app_ctx):
    patient_id = _patient()
    client = _login(app_ctx)

    for path in ("/doctor-queue/", "/control-room/", "/patients/", f"/patients/{patient_id}"):
        response = client.get(path)
        assert response.status_code == 200, path

    patient_list = client.get("/patients/").get_data(as_text=True)
    assert "کنترل‌نشده" not in patient_list
    assert "Clinical Engine v2" in patient_list

    patient_page = client.get(f"/patients/{patient_id}").get_data(as_text=True)
    assert "آزمایش‌های پیشنهادی" not in patient_page
    assert "اولویت بعدی پرونده" in patient_page

    control_room = client.get("/control-room/").get_data(as_text=True)
    assert "ADMINISTRATIVE_ONLY" not in control_room  # internal policy is not leaked
    assert "مقدارهای بالینی را تفسیر" in control_room


def test_copied_legacy_indicator_catalog_is_rebuilt_atomically(tmp_path):
    import sqlite3

    from src.adapters.sqlite.descriptive_indicator_catalog_schema import (
        ensure_descriptive_indicator_catalog,
    )

    db = sqlite3.connect(tmp_path / "legacy-indicators.db")
    db.row_factory = sqlite3.Row
    try:
        db.executescript(
            """
            CREATE TABLE clinical_indicators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                label TEXT NOT NULL,
                unit TEXT,
                category TEXT,
                direction TEXT,
                warn REAL,
                danger REAL,
                target REAL,
                goal_low REAL,
                goal_high REAL,
                conditions TEXT,
                risk_weight INTEGER,
                is_vital INTEGER,
                display_order INTEGER,
                is_active INTEGER,
                notes TEXT
            );
            INSERT INTO clinical_indicators
                (key,label,unit,category,direction,warn,danger,target,
                 conditions,risk_weight,is_vital,display_order,is_active,notes)
            VALUES
                ('hba1c','HbA1c','%','glycemic','high',7,8,7,
                 'diabetes',3,1,10,1,'legacy metadata');
            """
        )
        db.commit()

        assert ensure_descriptive_indicator_catalog(db) is True
        assert ensure_descriptive_indicator_catalog(db) is False
        columns = {
            row["name"]
            for row in db.execute(
                "PRAGMA table_info(clinical_indicators)"
            ).fetchall()
        }
        assert columns == {
            "id", "key", "label", "unit", "category", "conditions",
            "is_vital", "display_order", "is_active", "notes",
        }
        row = dict(
            db.execute(
                "SELECT * FROM clinical_indicators WHERE key='hba1c'"
            ).fetchone()
        )
        assert row["label"] == "HbA1c"
        assert row["conditions"] == "diabetes"
        assert row["notes"] == "legacy metadata"
    finally:
        db.close()




def test_malformed_legacy_indicator_catalog_rolls_back_without_data_loss(tmp_path):
    import sqlite3

    from src.adapters.sqlite.descriptive_indicator_catalog_schema import (
        ensure_descriptive_indicator_catalog,
    )

    db = sqlite3.connect(tmp_path / "malformed-indicators.db")
    db.row_factory = sqlite3.Row
    try:
        db.executescript(
            """
            CREATE TABLE clinical_indicators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                unit TEXT,
                warn REAL,
                danger REAL
            );
            INSERT INTO clinical_indicators (key, unit, warn, danger)
            VALUES ('legacy-only', 'mg/dL', 100, 200);
            """
        )
        db.commit()

        with pytest.raises(RuntimeError, match="missing columns: label"):
            ensure_descriptive_indicator_catalog(db)

        columns = {
            row["name"]
            for row in db.execute(
                "PRAGMA table_info(clinical_indicators)"
            ).fetchall()
        }
        assert {"key", "unit", "warn", "danger"} <= columns
        row = db.execute(
            "SELECT key, unit, warn, danger FROM clinical_indicators"
        ).fetchone()
        assert dict(row) == {
            "key": "legacy-only",
            "unit": "mg/dL",
            "warn": 100.0,
            "danger": 200.0,
        }
        assert db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='clinical_indicators_descriptive'"
        ).fetchone() is None
    finally:
        db.close()


def test_engagement_manager_exposes_only_operational_or_marketing_events(app_ctx):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.engagement_repo import (
        EngagementRepository,
        RETIRED_CLINICAL_EVENTS,
    )

    db = get_db()
    events = EngagementRepository().all_events()

    assert events
    assert not RETIRED_CLINICAL_EVENTS & {event["event_key"] for event in events}
    assert {event["category"] for event in events} <= {
        "operational",
        "marketing",
    }
    lapsed = next(event for event in events if event["event_key"] == "lapsed")
    assert lapsed["category"] == "operational"
    assert db.execute(
        "SELECT category FROM engagement_events WHERE event_key='lapsed'"
    ).fetchone()["category"] == "operational"

def test_legacy_protocol_routes_cannot_create_followup(app_ctx):
    from src.adapters.sqlite.core import get_db

    patient_id = _patient()
    client = _login(app_ctx)

    response = client.get("/manager/protocols", follow_redirects=False)
    assert response.status_code in {302, 303}
    assert "/manager/clinical-engine" in response.headers["Location"]

    before = get_db().execute(
        "SELECT COUNT(*) AS count FROM followup_tasks WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()["count"]
    response = client.post(
        "/manager/protocols/followup",
        data={"protocol_id": 1},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    after = get_db().execute(
        "SELECT COUNT(*) AS count FROM followup_tasks WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()["count"]
    assert after == before


def test_pending_retired_clinical_approval_is_rejected_before_send(app_ctx):
    from src.adapters.sqlite.core import get_db
    from src.services.engagement_service import EngagementService

    db = get_db()
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, phone_number, enrolled_by)
               VALUES ('RETAPP01', 'Retired Approval', '09120000000', 'pytest')"""
        ).lastrowid
    )
    approval_id = int(
        db.execute(
            """INSERT INTO engagement_approvals
               (patient_link_id, event_key, channel, message, period_key, status)
               VALUES (?, 'red_flag', 'sms', 'legacy alert', 'legacy:1', 'pending')""",
            (patient_id,),
        ).lastrowid
    )
    db.commit()

    result = EngagementService().approve(
        approval_id,
        decided_by="physician",
        override=True,
    )

    assert result == {"ok": False, "reason": "retired_clinical_event"}
    row = db.execute(
        "SELECT status, decided_by FROM engagement_approvals WHERE id=?",
        (approval_id,),
    ).fetchone()
    assert dict(row) == {
        "status": "rejected",
        "decided_by": "system:logic-consolidation",
    }
    assert db.execute(
        "SELECT COUNT(*) AS count FROM sms_messages WHERE source_type='engagement'"
    ).fetchone()["count"] == 0
