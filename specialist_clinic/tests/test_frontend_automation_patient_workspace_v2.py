from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def patient_workspace_app(tmp_path):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.drug_catalog_repo import DrugCatalogRepository
    from src.adapters.sqlite.flags_repo import ClinicalFlagsRepository
    from src.adapters.sqlite.lab_catalog_repo import LabCatalogRepository
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "patient-workspace-v2.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "patient-workspace-v2-test",
        }
    )
    context = app.app_context()
    context.push()
    db = get_db()

    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, phone_number, enrolled_by,
                enrolled_at, updated_at)
               VALUES ('PWS2000001', 'بیمار ورک‌اسپیس تست', '09120000001', 'pytest',
                       '2026-08-08 09:00:00', '2026-08-08 09:00:00')"""
        ).lastrowid
    )
    db.commit()

    LabCatalogRepository().upsert(
        test_key="pytest_workspace_lab",
        name_fa="آزمایش استاندارد ورک‌اسپیس",
        unit="mg/dL",
        ref_low=10,
        ref_high=20,
        category="other",
        display_order=1,
        is_active=1,
    )

    drug_classes = ClinicalFlagsRepository().drug_classes()
    assert drug_classes, "test database must seed at least one drug class"
    drug_class_key = drug_classes[0]["class_key"]
    DrugCatalogRepository().add(
        generic_fa="داروی استاندارد ورک‌اسپیس",
        drug_class_key=drug_class_key,
        standard_doses=["5 mg", "10 mg"],
    )

    admin = db.execute(
        "SELECT id, username FROM users WHERE username='admin'"
    ).fetchone()

    yield {
        "app": app,
        "db": db,
        "admin": admin,
        "patient_id": patient_id,
        "drug_class_key": drug_class_key,
    }

    context.pop()
    core._initialized = False


def client_for(fixture):
    client = fixture["app"].test_client()
    with client.session_transaction() as session:
        session["user_id"] = int(fixture["admin"]["id"])
    return client


def test_patient_detail_redirects_to_native_workspace_and_all_tabs_render(
    patient_workspace_app,
):
    client = client_for(patient_workspace_app)
    patient_id = patient_workspace_app["patient_id"]

    legacy = client.get(f"/patients/{patient_id}", follow_redirects=False)
    assert legacy.status_code in {302, 303}
    assert legacy.headers["Location"].endswith(
        f"/patients/{patient_id}/workspace?tab=summary"
    )

    markers = {
        "summary": "اقدام بعدی پیشنهادی پرونده",
        "actions": "ثبت سریع شاخص‌ها",
        "clinical": "آزمایش‌ها",
        "meds": "داروهای بیمار",
        "encounters": "تاریخچه مراقبت",
    }
    for tab, marker in markers.items():
        response = client.get(f"/patients/{patient_id}/workspace?tab={tab}")
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert marker in html
        assert f"tab={tab}" in html
        assert 'aria-current="page"' in html


def test_workspace_renders_catalog_bound_lab_and_medication_controls(
    patient_workspace_app,
):
    client = client_for(patient_workspace_app)
    patient_id = patient_workspace_app["patient_id"]

    clinical = client.get(f"/patients/{patient_id}/workspace?tab=clinical")
    clinical_html = clinical.get_data(as_text=True)
    assert clinical.status_code == 200
    assert 'name="catalog_test_key"' in clinical_html
    assert 'value="pytest_workspace_lab"' in clinical_html
    assert "آزمایش استاندارد ورک‌اسپیس" in clinical_html
    assert 'name="test_name"' not in clinical_html
    assert 'name="unit"' not in clinical_html

    meds = client.get(f"/patients/{patient_id}/workspace?tab=meds")
    meds_html = meds.get_data(as_text=True)
    assert meds.status_code == 200
    assert 'id="patientWorkspaceDrugCatalog"' in meds_html
    assert 'id="workspace-drug-name" name="drug_name" required' in meds_html
    assert "داروی استاندارد ورک‌اسپیس" in meds_html
    assert 'data-drug-class=' in meds_html
    assert 'list="workspace-drug-dose-options"' in meds_html
    assert "/static/js/patient-workspace-catalogs-v2.js" in meds_html


def test_catalog_lab_post_uses_server_canonical_identity_and_returns_to_clinical_tab(
    patient_workspace_app,
):
    client = client_for(patient_workspace_app)
    patient_id = patient_workspace_app["patient_id"]

    response = client.post(
        f"/vitals/{patient_id}/lab/add",
        data={
            "catalog_test_key": "pytest_workspace_lab",
            "value": "15",
            "taken_date": "",
            "workspace_tab": "clinical",
        },
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith(
        f"/patients/{patient_id}/workspace?tab=clinical"
    )
    row = patient_workspace_app["db"].execute(
        """SELECT test_name, test_key, value, unit, ref_low, ref_high
           FROM lab_results
           WHERE patient_link_id=? AND test_key='pytest_workspace_lab'
           ORDER BY id DESC LIMIT 1""",
        (patient_id,),
    ).fetchone()
    assert row
    assert row["test_name"] == "آزمایش استاندارد ورک‌اسپیس"
    assert row["unit"] == "mg/dL"
    assert row["ref_low"] == 10
    assert row["ref_high"] == 20
    assert row["value"] == 15


def test_catalog_medication_selection_keeps_workspace_context(patient_workspace_app):
    client = client_for(patient_workspace_app)
    patient_id = patient_workspace_app["patient_id"]
    drug_class_key = patient_workspace_app["drug_class_key"]

    response = client.post(
        f"/patients/{patient_id}/medication/add",
        data={
            "drug_name": "داروی استاندارد ورک‌اسپیس",
            "drug_class": drug_class_key,
            "dose": "5 mg",
            "schedule": "روزی یک بار",
            "refill_interval": "30",
            "workspace_tab": "meds",
        },
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith(
        f"/patients/{patient_id}/workspace?tab=meds"
    )
    row = patient_workspace_app["db"].execute(
        """SELECT drug_name, drug_class, dose, schedule
           FROM patient_medications
           WHERE patient_link_id=? ORDER BY id DESC LIMIT 1""",
        (patient_id,),
    ).fetchone()
    assert row
    assert row["drug_name"] == "داروی استاندارد ورک‌اسپیس"
    assert row["drug_class"] == drug_class_key
    assert row["dose"] == "5 mg"
    assert row["schedule"] == "روزی یک بار"


def test_catalog_enhancement_is_progressive_and_does_not_fake_persistence():
    script = (
        ROOT / "src/static/js/patient-workspace-catalogs-v2.js"
    ).read_text(encoding="utf-8")
    clinical = (
        ROOT / "src/templates/patients/workspace/_clinical.html"
    ).read_text(encoding="utf-8")
    meds = (
        ROOT / "src/templates/patients/workspace/_meds.html"
    ).read_text(encoding="utf-8")

    assert "JSON.parse" in script
    assert "replaceChildren" in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "fetch(" not in script
    assert 'name="catalog_test_key"' in clinical
    assert 'name="drug_name" required' in meds
    assert "drug_catalog|tojson" in meds


# A fixed clock. Retention answers ("how long since this patient came back?") are only
# reproducible when `now` is injected instead of read from the wall clock.
NOW = datetime(2026, 8, 19, 9, 0, 0)


def _open_task(db, patient_link_id: int, *, reason: str = "manual") -> int:
    """Insert the minimal administrative task a contact event can point at."""
    cursor = db.execute(
        "INSERT INTO followup_tasks (patient_link_id, reason, detail) VALUES (?,?,?)",
        (int(patient_link_id), reason, "کار آزمون تماس"),
    )
    db.commit()
    return int(cursor.lastrowid)


def _record_contact(
    db,
    patient_link_id: int,
    task_id: int,
    *,
    outcome: str,
    occurred_at: str,
    channel: str = "PHONE",
    note: str | None = None,
    next_contact_at: str | None = None,
    actor: str = "pytest-operator",
) -> None:
    """Insert one contact event that satisfies every CHECK on the events table.

    `content_hash` must be exactly 64 characters and `idempotency_key` at least 12,
    both unique, and `recorded_at` may not precede `occurred_at`. The seed is derived
    from the event itself rather than from a counter, so reordering the inserts in a
    test cannot make two distinct events collide.
    """
    seed = f"{patient_link_id}|{task_id}|{channel}|{outcome}|{occurred_at}"
    db.execute(
        """INSERT INTO followup_contact_events
               (task_id, patient_link_id, channel, outcome, occurred_at,
                recorded_at, actor_username, note, next_contact_at,
                idempotency_key, content_hash)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            int(task_id),
            int(patient_link_id),
            channel,
            outcome,
            occurred_at,
            occurred_at,
            actor,
            note,
            next_contact_at,
            f"pytest-contact-{seed}",
            hashlib.sha256(seed.encode("utf-8")).hexdigest(),
        ),
    )
    db.commit()


def test_contact_summary_is_read_per_patient_and_absent_before_any_contact(
    patient_workspace_app,
):
    from src.adapters.sqlite.followup_operations_repo import (
        FollowupOperationsRepository,
    )

    repo = FollowupOperationsRepository()
    db = patient_workspace_app["db"]
    patient_id = patient_workspace_app["patient_id"]

    assert repo.patient_summary(patient_id) is None

    task_id = _open_task(db, patient_id)
    _record_contact(
        db,
        patient_id,
        task_id,
        outcome="NO_ANSWER",
        occurred_at="2026-08-02 10:00:00",
        next_contact_at="2026-08-05 10:00:00",
    )
    _record_contact(
        db,
        patient_id,
        task_id,
        outcome="REACHED",
        occurred_at="2026-08-06 11:30:00",
        note="بیمار قند ناشتای جدید را می‌آورد",
        next_contact_at="2026-08-13 10:00:00",
    )

    summary = repo.patient_summary(patient_id)
    assert summary["contact_count"] == 2
    assert summary["reached_count"] == 1
    assert summary["last_contact_at"] == "2026-08-06 11:30:00"
    assert summary["last_contact_outcome"] == "REACHED"
    assert summary["last_contact_channel"] == "PHONE"
    assert summary["last_contact_actor"] == "pytest-operator"
    assert summary["last_contact_task_id"] == task_id
    assert summary["last_contact_note"] == "بیمار قند ناشتای جدید را می‌آورد"
    # The owed callback is the earliest one still on the books, not the newest event's:
    # an operator who is late on 05 must not have that debt hidden by a later promise.
    assert summary["next_contact_at"] == "2026-08-05 10:00:00"


def test_continuity_reports_absence_instead_of_inventing_values():
    from src.services.patient_cockpit_service import PatientCockpitService

    continuity = PatientCockpitService.continuity(
        contact=None, appointments=[], visits=[], now=NOW
    )

    assert continuity["last_contact"] is None
    assert continuity["callback"] is None
    assert continuity["contact_count"] == 0
    assert continuity["reached_count"] == 0
    attendance = continuity["attendance"]
    assert attendance["never_attended"] is True
    assert attendance["reliability"] is None
    assert attendance["last_attended_at"] is None
    assert attendance["days_since_attendance"] is None
    assert attendance["lapsed"] is False


@pytest.mark.parametrize(
    ("attended_on", "expected_days", "expected_lapsed"),
    [("2026-04-21", 120, False), ("2026-04-20", 121, True)],
)
def test_continuity_lapse_boundary_follows_the_shared_threshold(
    attended_on, expected_days, expected_lapsed
):
    from src.services.control_room_service import LAPSED_DAYS
    from src.services.patient_cockpit_service import PatientCockpitService

    continuity = PatientCockpitService.continuity(
        contact=None,
        appointments=[{"status": "done", "scheduled_at": attended_on}],
        visits=[],
        now=NOW,
    )

    attendance = continuity["attendance"]
    assert attendance["days_since_attendance"] == expected_days
    assert attendance["lapsed"] is expected_lapsed
    assert attendance["never_attended"] is False
    assert continuity["lapsed_days_threshold"] == LAPSED_DAYS


@pytest.mark.parametrize(
    ("next_contact_at", "expected_overdue", "expected_days"),
    [("2026-08-18 09:00:00", True, 1), ("2026-08-21 09:00:00", False, 2)],
)
def test_continuity_separates_an_owed_callback_from_a_future_one(
    next_contact_at, expected_overdue, expected_days
):
    from src.services.patient_cockpit_service import PatientCockpitService

    continuity = PatientCockpitService.continuity(
        contact={
            "contact_count": 1,
            "reached_count": 0,
            "last_contact_at": "2026-08-17 12:00:00",
            "last_contact_channel": "PHONE",
            "last_contact_outcome": "CALLBACK_REQUESTED",
            "next_contact_at": next_contact_at,
        },
        appointments=[],
        visits=[],
        now=NOW,
    )

    callback = continuity["callback"]
    assert callback["at"] == next_contact_at
    assert callback["overdue"] is expected_overdue
    assert callback["days"] == expected_days


def test_continuity_reuses_the_shared_channel_and_outcome_labels():
    from src.services.patient_cockpit_service import PatientCockpitService

    continuity = PatientCockpitService.continuity(
        contact={
            "contact_count": 3,
            "reached_count": 1,
            "last_contact_at": "2026-08-17 12:00:00",
            "last_contact_channel": "PHONE",
            "last_contact_outcome": "CALLBACK_REQUESTED",
            "last_contact_note": "درخواست تماس در ساعات عصر",
            "last_contact_actor": "reception",
            "next_contact_at": None,
        },
        appointments=[],
        visits=[],
        now=NOW,
    )

    last_contact = continuity["last_contact"]
    assert last_contact["days_ago"] == 1
    assert last_contact["channel_label"] == "تماس تلفنی"
    assert last_contact["outcome_label"] == "درخواست تماس مجدد"
    assert last_contact["reached"] is False
    assert last_contact["note"] == "درخواست تماس در ساعات عصر"
    assert last_contact["actor"] == "reception"
    assert continuity["contact_count"] == 3
    assert continuity["reached_count"] == 1
    assert continuity["callback"] is None


def test_continuity_labels_an_unrecognised_channel_or_outcome_as_unrecorded():
    from src.services.patient_cockpit_service import PatientCockpitService

    continuity = PatientCockpitService.continuity(
        contact={"last_contact_at": "2026-08-18 09:00:00"},
        appointments=[],
        visits=[],
        now=NOW,
    )

    last_contact = continuity["last_contact"]
    assert last_contact["channel_label"] == "کانال ثبت‌نشده"
    assert last_contact["outcome_label"] == "نتیجهٔ ثبت‌نشده"
    assert last_contact["reached"] is False


def test_continuity_counts_only_proven_attendance():
    from src.services.patient_cockpit_service import PatientCockpitService

    continuity = PatientCockpitService.continuity(
        contact=None,
        appointments=[
            {"status": "done", "scheduled_at": "2026-07-01 09:00:00"},
            {"status": "no_show", "scheduled_at": "2026-07-15 09:00:00"},
            {"status": "scheduled", "scheduled_at": "2026-09-01 09:00:00"},
        ],
        visits=[],
        now=NOW,
    )

    attendance = continuity["attendance"]
    assert attendance["attended"] == 1
    assert attendance["no_show"] == 1
    assert attendance["cancelled"] == 0
    # The future booking is an intention, so it decides nothing and is not a return.
    assert attendance["decided"] == 2
    assert attendance["reliability"] == 50
    assert attendance["last_attended_at"] == "2026-07-01 09:00:00"
    assert attendance["days_since_attendance"] == 49


def test_workspace_summary_and_actions_surface_a_recorded_contact(
    patient_workspace_app,
):
    client = client_for(patient_workspace_app)
    db = patient_workspace_app["db"]
    patient_id = patient_workspace_app["patient_id"]
    summary_url = f"/patients/{patient_id}/workspace?tab=summary"
    actions_url = f"/patients/{patient_id}/workspace?tab=actions"

    for url in (summary_url, actions_url):
        response = client.get(url)
        assert response.status_code == 200
        assert "تماسی ثبت نشده" in response.get_data(as_text=True)

    task_id = _open_task(db, patient_id)
    _record_contact(
        db,
        patient_id,
        task_id,
        outcome="REACHED",
        occurred_at="2026-08-06 11:30:00",
        note="بیمار برای هفتهٔ آینده نوبت می‌خواهد",
    )

    summary_html = client.get(summary_url).get_data(as_text=True)
    actions_html = client.get(actions_url).get_data(as_text=True)
    for html in (summary_html, actions_html):
        assert "پاسخ داد" in html
        assert "تماس تلفنی" in html
        assert "تماسی ثبت نشده" not in html
    # The operator note is long-form context, so only the summary tab carries it.
    assert "بیمار برای هفتهٔ آینده نوبت می‌خواهد" in summary_html
