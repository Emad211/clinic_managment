from __future__ import annotations

from pathlib import Path
import hashlib
import sqlite3
import uuid

import pytest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _accounting_schema(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE patients (
            id INTEGER PRIMARY KEY,
            full_name TEXT,
            national_id TEXT UNIQUE,
            phone_number TEXT,
            gender TEXT,
            birthdate TEXT,
            address TEXT,
            insurance_type TEXT,
            insurance_expiry TEXT,
            is_foreign INTEGER DEFAULT 0
        );
        CREATE TABLE invoices (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            insurance_type TEXT,
            supplementary_insurance TEXT,
            total_amount INTEGER,
            work_date TEXT,
            opened_at TEXT,
            closed_at TEXT
        );
        CREATE TABLE visits (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            doctor_name TEXT,
            visit_date TEXT,
            work_date TEXT,
            status TEXT,
            price INTEGER NOT NULL,
            invoice_id INTEGER NOT NULL,
            doctor_id INTEGER
        );
        CREATE TABLE injections (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            total_price INTEGER NOT NULL,
            invoice_id INTEGER NOT NULL
        );
        CREATE TABLE procedures (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            price INTEGER NOT NULL,
            invoice_id INTEGER NOT NULL
        );
        CREATE TABLE invoice_item_payments (
            invoice_id INTEGER NOT NULL,
            item_type TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            payment_type TEXT,
            is_paid INTEGER DEFAULT 0,
            PRIMARY KEY(invoice_id,item_type,item_id)
        );
        INSERT INTO patients
          (id,full_name,national_id,phone_number,gender,birthdate,address,
           insurance_type,is_foreign)
        VALUES (1,'A9 Patient','A900000001','09120000001','female',
                '1980-01-01','Tehran','base',0);
        """
    )
    db.commit()
    db.close()


@pytest.fixture()
def a9_app(tmp_path, monkeypatch):
    from src.adapters.sqlite import core
    from src.app import create_app

    accounting = tmp_path / "accounting-a9.db"
    specialist = tmp_path / "specialist-a9.db"
    _accounting_schema(accounting)
    monkeypatch.setenv("ACCOUNTING_DB_PATH", str(accounting))
    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(specialist),
            "ACCOUNTING_DB_PATH": str(accounting),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "a9-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app, accounting, specialist
    context.pop()
    core._initialized = False


def _enroll_and_add_invoice(accounting: Path, invoice_id: int = 101) -> int:
    from src.common.utils import today_str
    from src.services.patient_service import PatientService

    patient_id = int(PatientService().enroll_from_accounting(1, "pytest-a9"))
    work_date = today_str()
    db = sqlite3.connect(accounting)
    db.execute(
        """INSERT INTO invoices
           (id,patient_id,status,insurance_type,supplementary_insurance,
            total_amount,work_date,opened_at,closed_at)
           VALUES (?,1,'open','base',NULL,400000,?,datetime('now'),NULL)""",
        (int(invoice_id), work_date),
    )
    db.execute(
        """INSERT INTO visits
           (id,patient_id,doctor_name,visit_date,work_date,status,price,
            invoice_id,doctor_id)
           VALUES (?,1,'Dr A',datetime('now'),?,'pending',400000,?,7)""",
        (int(invoice_id) + 1000, work_date, int(invoice_id)),
    )
    db.commit()
    db.close()
    return patient_id


def _login(client, username="admin", password="admin") -> None:
    response = client.post(
        "/auth/login", data={"username": username, "password": password}
    )
    assert response.status_code in {302, 303}


def _start(client, invoice_id: int = 101):
    response = client.post(f"/doctor-queue/{invoice_id}/start", data={})
    assert response.status_code in {302, 303}
    return response


def _document_form(**overrides) -> dict:
    data = {
        "document_request_id": uuid.uuid4().hex,
        "chief_complaint": "پیگیری کنترل فشار خون",
        "objective_findings": "فشار خون در مطب اندازه‌گیری شد.",
        "problems": "فشار خون بالاتر از هدف\nنیاز به پایش خانگی",
        "assessment": "کنترل فشار خون هنوز مطلوب نیست.",
        "plan": "پایش خانگی و بازبینی درمان در مراجعه بعدی.",
        "followup_instructions": "ثبت فشار خون روزانه و تماس در صورت علامت.",
        "outcome_code": "FOLLOWUP_REQUIRED",
    }
    data.update(overrides)
    return data


def test_start_requires_document_and_direct_completion_is_blocked(a9_app):
    import sqlite3 as sqlite

    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.adapters.sqlite.encounter_documentation_repo import (
        EncounterDocumentationRepository,
    )
    from src.adapters.sqlite.core import get_db

    app, accounting, _specialist = a9_app
    _enroll_and_add_invoice(accounting)
    before = _sha256(accounting)
    client = app.test_client()
    _login(client)
    _start(client)

    encounter = CareJourneyRepository().encounter_for_invoice(101)
    requirement = EncounterDocumentationRepository().requirement(
        encounter["encounter_id"]
    )
    assert requirement["requirement_status"] == "REQUIRED"
    assert requirement["source_code"] == "DOCTOR_QUEUE_A9"
    assert CareJourneyRepository().current_encounter_event(
        encounter["encounter_id"]
    )["event_type"] == "STARTED"

    with pytest.raises(sqlite.IntegrityError, match="signed encounter document"):
        CareJourneyRepository().complete_encounter(
            encounter["encounter_id"], actor_username="pytest-a9"
        )
    get_db().rollback()
    assert CareJourneyRepository().current_encounter_event(
        encounter["encounter_id"]
    )["event_type"] == "STARTED"

    queue = client.get("/doctor-queue/").get_data(as_text=True)
    assert "ادامه مستندسازی" in queue
    assert f"/doctor-queue/101/done" not in queue
    assert _sha256(accounting) == before


def test_draft_and_vitals_are_atomic_and_invalid_sign_rolls_back(a9_app):
    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.encounter_documentation_repo import (
        EncounterDocumentationRepository,
    )

    app, accounting, _specialist = a9_app
    patient_id = _enroll_and_add_invoice(accounting)
    before = _sha256(accounting)
    client = app.test_client()
    _login(client)
    _start(client)

    draft = _document_form(
        action="draft",
        outcome_code="",
        bp_systolic="138",
    )
    response = client.post("/doctor-queue/101/save", data=draft)
    assert response.status_code in {302, 303}
    encounter = CareJourneyRepository().encounter_for_invoice(101)
    current = EncounterDocumentationRepository().current_document(
        encounter["encounter_id"]
    )
    assert current["document_status"] == "DRAFT"
    assert current["outcome_code"] is None
    assert get_db().execute(
        "SELECT COUNT(*) FROM vital_readings WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()[0] == 1

    invalid = _document_form(
        action="sign",
        assessment="",
        expected_current_event_id=current["id"],
        bp_diastolic="91",
    )
    response = client.post("/doctor-queue/101/save", data=invalid)
    assert response.status_code in {302, 303}
    assert EncounterDocumentationRepository().current_document(
        encounter["encounter_id"]
    )["id"] == current["id"]
    assert get_db().execute(
        "SELECT COUNT(*) FROM vital_readings WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()[0] == 1
    assert CareJourneyRepository().current_encounter_event(
        encounter["encounter_id"]
    )["event_type"] == "STARTED"
    assert _sha256(accounting) == before


def test_sign_completes_atomically_and_surfaces_in_patient_timeline(a9_app):
    import sqlite3 as sqlite

    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.encounter_documentation_repo import (
        EncounterDocumentationRepository,
    )

    app, accounting, _specialist = a9_app
    patient_id = _enroll_and_add_invoice(accounting)
    before = _sha256(accounting)
    client = app.test_client()
    _login(client)
    _start(client)

    response = client.post(
        "/doctor-queue/101/save",
        data=_document_form(action="sign", hba1c="7.2"),
    )
    assert response.status_code in {302, 303}
    encounter = CareJourneyRepository().encounter_for_invoice(101)
    current = EncounterDocumentationRepository().current_document(
        encounter["encounter_id"]
    )
    assert current["document_status"] == "SIGNED"
    assert current["outcome_code"] == "FOLLOWUP_REQUIRED"
    assert CareJourneyRepository().current_encounter_event(
        encounter["encounter_id"]
    )["event_type"] == "COMPLETED"
    assert get_db().execute(
        "SELECT status FROM doctor_visit_log WHERE accounting_invoice_id=101"
    ).fetchone()["status"] == "done"

    document_page = client.get("/doctor-queue/101/document")
    html = document_page.get_data(as_text=True)
    assert document_page.status_code == 200
    assert "کنترل فشار خون هنوز مطلوب نیست" in html
    assert "پیگیری لازم است" in html

    patient_page = client.get(f"/patients/{patient_id}")
    patient_html = patient_page.get_data(as_text=True)
    assert patient_page.status_code == 200
    assert "سند ویزیت امضاشده" in patient_html
    assert "/doctor-queue/101/document" in patient_html

    with pytest.raises(sqlite.IntegrityError, match="append-only"):
        get_db().execute(
            "UPDATE care_encounter_document_events SET assessment='x' WHERE id=?",
            (current["id"],),
        )
    get_db().rollback()
    assert _sha256(accounting) == before


def test_stale_draft_is_rejected_without_partial_vital_write(a9_app):
    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.encounter_documentation_repo import (
        EncounterDocumentationRepository,
    )

    app, accounting, _specialist = a9_app
    patient_id = _enroll_and_add_invoice(accounting)
    client = app.test_client()
    _login(client)
    _start(client)
    client.post("/doctor-queue/101/save", data=_document_form(action="draft"))
    encounter = CareJourneyRepository().encounter_for_invoice(101)
    first = EncounterDocumentationRepository().current_document(
        encounter["encounter_id"]
    )
    client.post(
        "/doctor-queue/101/save",
        data=_document_form(
            action="draft",
            expected_current_event_id=first["id"],
            assessment="ارزیابی نسخه دوم",
        ),
    )
    second = EncounterDocumentationRepository().current_document(
        encounter["encounter_id"]
    )
    assert second["id"] != first["id"]
    count_before = get_db().execute(
        "SELECT COUNT(*) FROM vital_readings WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()[0]
    client.post(
        "/doctor-queue/101/save",
        data=_document_form(
            action="draft",
            expected_current_event_id=first["id"],
            pulse="88",
        ),
    )
    assert EncounterDocumentationRepository().current_document(
        encounter["encounter_id"]
    )["id"] == second["id"]
    assert get_db().execute(
        "SELECT COUNT(*) FROM vital_readings WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()[0] == count_before


def test_completed_document_amendment_preserves_full_history(a9_app):
    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.adapters.sqlite.encounter_documentation_repo import (
        EncounterDocumentationRepository,
    )

    app, accounting, _specialist = a9_app
    _enroll_and_add_invoice(accounting)
    client = app.test_client()
    _login(client)
    _start(client)
    client.post("/doctor-queue/101/save", data=_document_form(action="sign"))
    encounter = CareJourneyRepository().encounter_for_invoice(101)
    repository = EncounterDocumentationRepository()
    signed = repository.current_document(encounter["encounter_id"])

    missing_reason = _document_form(
        expected_current_event_id=signed["id"],
        amendment_reason="",
        assessment="ارزیابی اصلاح‌شده",
    )
    client.post("/doctor-queue/101/document/amend", data=missing_reason)
    assert repository.current_document(encounter["encounter_id"])["id"] == signed["id"]

    valid = _document_form(
        expected_current_event_id=signed["id"],
        amendment_reason="اصلاح جمع‌بندی پس از بازبینی پرونده",
        assessment="ارزیابی اصلاح‌شده و تأییدشده",
        outcome_code="PLAN_CHANGED",
    )
    response = client.post("/doctor-queue/101/document/amend", data=valid)
    assert response.status_code in {302, 303}
    amended = repository.current_document(encounter["encounter_id"])
    assert amended["event_type"] == "AMENDED"
    assert amended["assessment"] == "ارزیابی اصلاح‌شده و تأییدشده"
    assert amended["supersedes_event_id"] == signed["id"]
    history = repository.history(encounter["encounter_id"])
    assert [row["event_type"] for row in history] == ["SIGNED", "AMENDED"]
    assert history[0]["assessment"] == "کنترل فشار خون هنوز مطلوب نیست."


def test_legacy_backfill_runs_once_and_does_not_exempt_new_programmatic_encounter(a9_app):
    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.encounter_documentation_repo import (
        EncounterDocumentationRepository,
    )
    from src.adapters.sqlite.encounter_documentation_schema import (
        ensure_encounter_documentation_storage,
    )
    from src.common.utils import iran_now, today_str
    from src.services.care_journey_service import CareJourneyService

    _app, accounting, _specialist = a9_app
    patient_id = _enroll_and_add_invoice(accounting, invoice_id=102)
    started = CareJourneyService().start_accounting_visit(
        patient_link_id=patient_id,
        accounting_invoice_id=102,
        actor_username="programmatic-test",
        expected_work_date=today_str(),
        effective_at=iran_now(),
    )
    encounter_id = started["encounter"]["encounter_id"]
    assert EncounterDocumentationRepository().requirement(encounter_id) is None
    ensure_encounter_documentation_storage(get_db())
    assert EncounterDocumentationRepository().requirement(encounter_id) is None
    assert get_db().execute(
        "SELECT COUNT(*) FROM encounter_documentation_migrations "
        "WHERE migration_key='A9_LEGACY_CUTOFF_V1'"
    ).fetchone()[0] == 1
    CareJourneyRepository().complete_encounter(
        encounter_id, actor_username="programmatic-test"
    )
    assert CareJourneyRepository().current_encounter_event(encounter_id)[
        "event_type"
    ] == "COMPLETED"



def test_document_request_idempotency_prevents_duplicate_vitals_and_signs(a9_app):
    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.encounter_documentation_repo import (
        EncounterDocumentationRepository,
    )

    app, accounting, _specialist = a9_app
    patient_id = _enroll_and_add_invoice(accounting)
    client = app.test_client()
    _login(client)
    _start(client)
    request_id = uuid.uuid4().hex
    draft = _document_form(
        action="draft",
        document_request_id=request_id,
        pulse="82",
        outcome_code="",
    )
    client.post("/doctor-queue/101/save", data=draft)
    client.post("/doctor-queue/101/save", data=draft)
    encounter = CareJourneyRepository().encounter_for_invoice(101)
    repository = EncounterDocumentationRepository()
    assert len(repository.history(encounter["encounter_id"])) == 1
    assert get_db().execute(
        "SELECT COUNT(*) FROM vital_readings WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()[0] == 1

    current = repository.current_document(encounter["encounter_id"])
    sign_id = uuid.uuid4().hex
    signed = _document_form(
        action="sign",
        document_request_id=sign_id,
        expected_current_event_id=current["id"],
        bp_systolic="132",
    )
    client.post("/doctor-queue/101/save", data=signed)
    client.post("/doctor-queue/101/save", data=signed)
    assert [row["event_type"] for row in repository.history(
        encounter["encounter_id"]
    )] == ["DRAFT_SAVED", "SIGNED"]
    assert get_db().execute(
        "SELECT COUNT(*) FROM vital_readings WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()[0] == 2



def test_a9_source_guard_has_no_direct_done_and_keeps_required_fields():
    root = Path(__file__).resolve().parents[1]
    queue = (root / "src/templates/doctor_queue/queue.html").read_text(
        encoding="utf-8"
    )
    visit = (root / "src/templates/doctor_queue/visit_quick.html").read_text(
        encoding="utf-8"
    )
    routes = (root / "src/api/doctor_queue.py").read_text(encoding="utf-8")
    assert "url_for('doctor_queue.done'" not in queue
    assert 'name="assessment"' in visit
    assert 'name="plan"' in visit
    assert 'name="outcome_code"' in visit
    assert 'name="action" value="sign"' in visit
    assert "permission_required(Permission.CLINICAL_DOCUMENT_WRITE)" in routes
    assert "permission_required(Permission.CLINICAL_DOCUMENT_AMEND)" in routes
