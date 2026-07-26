from __future__ import annotations

from datetime import timedelta
import sqlite3

import pytest


@pytest.fixture()
def a10_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "a10.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "a10-secret",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _context(invoice_id: int = 7001):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.encounter_documentation_repo import (
        EncounterDocumentationRepository,
    )
    from src.adapters.sqlite.specialist_enrollment_repo import (
        SpecialistEnrollmentRepository,
    )
    from src.common.utils import iran_now
    from src.services.care_journey_service import CareJourneyService

    db = get_db()
    now = iran_now().replace(tzinfo=None)
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (accounting_patient_id,national_id,full_name,phone_number,enrolled_by,enrolled_at)
               VALUES (?,?,?,?,?,?)""",
            (invoice_id, f"A10-{invoice_id}", "بیمار A10", "09120000000", "pytest", now.strftime("%Y-%m-%d %H:%M:%S")),
        ).lastrowid
    )
    SpecialistEnrollmentRepository(db).create_once(
        patient_link_id=patient_id,
        accounting_patient_id=invoice_id,
        effective_at=now - timedelta(seconds=2),
        accounting_snapshot_at=now - timedelta(seconds=2),
        accounting_invoice_cutoff_id=0,
        created_by="pytest",
        commit=False,
    )
    started = CareJourneyService(db=db).start_accounting_visit(
        patient_link_id=patient_id,
        accounting_invoice_id=invoice_id,
        actor_username="doctor",
        expected_work_date=now.strftime("%Y-%m-%d"),
        effective_at=now - timedelta(seconds=1),
        commit=False,
    )
    encounter = started["encounter"]
    EncounterDocumentationRepository(db).require_for_encounter(
        encounter["encounter_id"], actor_username="doctor", commit=False
    )
    db.commit()
    user = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    return {
        "accounting_invoice_id": invoice_id,
        "patient_link_id": patient_id,
        "national_id": f"A10-{invoice_id}",
        "full_name": "بیمار A10",
        "work_date": now.strftime("%Y-%m-%d"),
        "encounter_id": encounter["encounter_id"],
        "journey_id": encounter["journey_id"],
        "actor_user_id": int(user["id"]),
        "now": now,
    }


def _commitment(ctx, *, kind="CALL_CHECK", days=2, assigned_to=None, key="commitment-client-0001"):
    return {
        "client_key": key,
        "commitment_type": kind,
        "instruction": "پیگیری صریح برنامه درمان",
        "due_at": (ctx["now"] + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S"),
        "fulfillment": "remote" if kind != "IN_PERSON_REVIEW" else "in_person",
        "assigned_to": assigned_to,
    }


def _document(ctx, *, outcome="FOLLOWUP_REQUIRED", commitments=None):
    return {
        "chief_complaint": "پیگیری بیماری مزمن",
        "objective_findings": "وضعیت عمومی پایدار",
        "assessment": "نیازمند پیگیری برنامه‌ریزی‌شده",
        "plan": "اقدام صریح در Worklist انجام شود",
        "followup_instructions": "با بیمار هماهنگ شود",
        "problems": ["کنترل ناکافی"],
        "outcome_code": outcome,
        "commitments": commitments or [],
    }


def _sign(ctx, *, commitments=None, outcome="FOLLOWUP_REQUIRED", key="a10-sign-request-0001", readings=None):
    from src.services.encounter_documentation_service import EncounterDocumentationService

    return EncounterDocumentationService().sign_and_complete(
        visit_snapshot=ctx,
        document=_document(ctx, outcome=outcome, commitments=commitments),
        readings=readings or [],
        measured_at=ctx["now"].strftime("%Y-%m-%d %H:%M:%S"),
        actor_username="admin",
        actor_user_id=ctx["actor_user_id"],
        idempotency_key=key,
        expected_current_event_id=None,
    )


def test_followup_outcome_without_commitment_rolls_back_everything(a10_app):
    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.adapters.sqlite.core import get_db
    from src.services.encounter_plan_commitment_service import (
        EncounterPlanCommitmentValidationError,
    )

    ctx = _context()
    with pytest.raises(EncounterPlanCommitmentValidationError, match="requires"):
        _sign(ctx, commitments=[], readings=[("weight", 82.0, "kg")])
    db = get_db()
    assert db.execute("SELECT COUNT(*) FROM vital_readings").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM care_encounter_document_events").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM care_plan_commitments").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM followup_tasks WHERE source_engine='encounter_plan'").fetchone()[0] == 0
    assert CareJourneyRepository().current_encounter_event(ctx["encounter_id"])["event_type"] == "STARTED"


def test_sign_materializes_exact_worklist_tasks_and_is_idempotent(a10_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.encounter_plan_commitment_repo import (
        EncounterPlanCommitmentRepository,
    )
    from src.services.followup_projection_service import FollowupProjectionService

    ctx = _context()
    commitments = [
        _commitment(ctx, key="commitment-client-0001"),
        _commitment(ctx, kind="LAB_REVIEW", days=5, key="commitment-client-0002"),
    ]
    first = _sign(ctx, commitments=commitments)
    second = _sign(ctx, commitments=commitments)
    assert first["document"]["id"] == second["document"]["id"]
    db = get_db()
    assert db.execute("SELECT COUNT(*) FROM care_plan_commitments").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM care_plan_commitment_task_links").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM care_plan_commitment_events").fetchone()[0] == 2
    tasks = FollowupProjectionService().open_tasks(reason="encounter_plan")
    assert len(tasks) == 2
    assert all(task["source_engine"] == "encounter_plan" for task in tasks)
    assert all(task["id"] == task["task_id"] for task in tasks)
    assert {task["commitment_type"] for task in tasks} == {"CALL_CHECK", "LAB_REVIEW"}
    assert len(EncounterPlanCommitmentRepository().list_current()) == 2


def test_direct_admin_resolve_and_sql_update_are_blocked(a10_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.followups_repo import FollowupRepository

    ctx = _context()
    _sign(ctx, commitments=[_commitment(ctx)])
    task_id = int(get_db().execute("SELECT task_id FROM care_plan_commitment_task_links").fetchone()[0])
    with pytest.raises(ValueError, match="append-only"):
        FollowupRepository().resolve(task_id, "done")
    with pytest.raises(sqlite3.IntegrityError, match="append-only lifecycle"):
        get_db().execute("UPDATE followup_tasks SET status='done' WHERE id=?", (task_id,))
    get_db().rollback()


def test_contact_evidence_must_be_in_scope_and_after_commitment(a10_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.encounter_plan_commitment_repo import (
        EncounterPlanCommitmentRepository,
    )
    from src.services.encounter_plan_commitment_service import (
        EncounterPlanCommitmentService,
        EncounterPlanCommitmentValidationError,
    )
    from src.services.followup_contact_service import FollowupContactService

    ctx = _context()
    _sign(ctx, commitments=[_commitment(ctx)])
    repo = EncounterPlanCommitmentRepository()
    current = repo.list_current()[0]
    stale = FollowupContactService().record(
        task_id=current["id"], channel="PHONE", outcome="REACHED",
        actor_username="admin", actor_user_id=ctx["actor_user_id"],
        idempotency_key="a10-stale-contact-0001",
        occurred_at=ctx["now"] - timedelta(days=2),
    )
    with pytest.raises(EncounterPlanCommitmentValidationError, match="stale"):
        EncounterPlanCommitmentService().transition(
            task_id=current["id"], transition="complete",
            expected_current_event_id=current["current_event_id"],
            actor_username="admin", actor_user_id=ctx["actor_user_id"],
            idempotency_key="a10-complete-stale-0001",
            evidence_type="CONTACT_EVENT", evidence_ref=str(stale["id"]),
            outcome_code="COMPLETED_AS_PLANNED",
        )
    fresh = FollowupContactService().record(
        task_id=current["id"], channel="PHONE", outcome="REACHED",
        actor_username="admin", actor_user_id=ctx["actor_user_id"],
        idempotency_key="a10-fresh-contact-0001",
    )
    done = EncounterPlanCommitmentService().transition(
        task_id=current["id"], transition="complete",
        expected_current_event_id=current["current_event_id"],
        actor_username="admin", actor_user_id=ctx["actor_user_id"],
        idempotency_key="a10-complete-fresh-0001",
        evidence_type="CONTACT_EVENT", evidence_ref=str(fresh["id"]),
        outcome_code="COMPLETED_AS_PLANNED",
    )
    assert done["status"] == "COMPLETED"
    assert repo.list_current(include_terminal=False) == []
    assert repo.list_current(include_terminal=True)[0]["current_evidence_ref"] == str(fresh["id"])


def test_booking_schedules_commitment_without_mutating_task_projection(a10_app):
    from src.adapters.sqlite.appointments_repo import AppointmentRepository
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.encounter_plan_commitment_repo import (
        EncounterPlanCommitmentRepository,
    )
    from src.services.followup_booking_service import FollowupBookingService

    ctx = _context()
    _sign(ctx, commitments=[_commitment(ctx, kind="IN_PERSON_REVIEW")])
    current = EncounterPlanCommitmentRepository().list_current()[0]
    scheduled_at = (ctx["now"] + timedelta(days=4)).strftime("%Y-%m-%d 09:00:00")
    result = FollowupBookingService().book(
        patient_link_id=ctx["patient_link_id"],
        task_ids=[current["id"]], scheduled_at=scheduled_at,
        actor_username="admin", actor_user_id=ctx["actor_user_id"],
        idempotency_key="a10-book-plan-0001",
    )
    assert result["plan_scheduled"] == 1
    duplicate = FollowupBookingService().book(
        patient_link_id=ctx["patient_link_id"],
        task_ids=[current["id"]], scheduled_at=scheduled_at,
        actor_username="admin", actor_user_id=ctx["actor_user_id"],
        idempotency_key="a10-book-plan-0001",
    )
    assert duplicate["duplicate"] is True
    head = EncounterPlanCommitmentRepository().current_for_task(current["id"])
    assert head["current_status"] == "SCHEDULED"
    assert int(head["current_appointment_id"]) == result["appointment_id"]
    task = get_db().execute("SELECT appointment_id,status FROM followup_tasks WHERE id=?", (current["id"],)).fetchone()
    assert task["appointment_id"] is None
    assert task["status"] == "open"
    assert AppointmentRepository().get(result["appointment_id"])["status"] == "scheduled"
    contact = get_db().execute("SELECT outcome FROM followup_contact_events WHERE task_id=?", (current["id"],)).fetchone()
    assert contact["outcome"] == "BOOKED"


def test_appointment_is_evidence_only_after_attendance(a10_app):
    from src.adapters.sqlite.appointments_repo import AppointmentRepository
    from src.adapters.sqlite.encounter_plan_commitment_repo import (
        EncounterPlanCommitmentRepository,
    )
    from src.services.encounter_plan_commitment_service import (
        EncounterPlanCommitmentService,
        EncounterPlanCommitmentValidationError,
    )
    from src.services.followup_booking_service import FollowupBookingService

    ctx = _context()
    _sign(ctx, commitments=[_commitment(ctx, kind="IN_PERSON_REVIEW")])
    current = EncounterPlanCommitmentRepository().list_current()[0]
    booked = FollowupBookingService().book(
        patient_link_id=ctx["patient_link_id"], task_ids=[current["id"]],
        scheduled_at=(ctx["now"] + timedelta(days=3)).strftime("%Y-%m-%d 09:00:00"),
        actor_username="admin", actor_user_id=ctx["actor_user_id"],
        idempotency_key="a10-book-evidence-0001",
    )
    head = EncounterPlanCommitmentRepository().current_for_task(current["id"])
    with pytest.raises(EncounterPlanCommitmentValidationError, match="stale|incomplete"):
        EncounterPlanCommitmentService().transition(
            task_id=current["id"], transition="complete",
            expected_current_event_id=head["current_event_id"],
            actor_username="admin", actor_user_id=ctx["actor_user_id"],
            idempotency_key="a10-before-attendance-0001",
            evidence_type="APPOINTMENT", evidence_ref=str(booked["appointment_id"]),
            outcome_code="COMPLETED_AS_PLANNED",
        )
    AppointmentRepository().set_status(booked["appointment_id"], "done")
    done = EncounterPlanCommitmentService().transition(
        task_id=current["id"], transition="complete",
        expected_current_event_id=head["current_event_id"],
        actor_username="admin", actor_user_id=ctx["actor_user_id"],
        idempotency_key="a10-after-attendance-0001",
        evidence_type="APPOINTMENT", evidence_ref=str(booked["appointment_id"]),
        outcome_code="COMPLETED_AS_PLANNED",
    )
    assert done["status"] == "COMPLETED"


def test_urgent_and_referred_outcomes_require_semantic_commitments(a10_app):
    from src.services.encounter_plan_commitment_service import (
        EncounterPlanCommitmentService,
        EncounterPlanCommitmentValidationError,
    )

    ctx = _context()
    service = EncounterPlanCommitmentService(clock=lambda: ctx["now"])
    with pytest.raises(EncounterPlanCommitmentValidationError, match="REFERRAL_CHECK"):
        service.validate_for_document(
            outcome_code="REFERRED", commitments=[_commitment(ctx)]
        )
    with pytest.raises(EncounterPlanCommitmentValidationError, match="24 hours"):
        service.validate_for_document(
            outcome_code="URGENT_ESCALATION",
            commitments=[_commitment(ctx, days=2, assigned_to="nurse")],
        )
    valid = _commitment(ctx, days=0, assigned_to="nurse")
    valid["due_at"] = (ctx["now"] + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    assert service.validate_for_document(
        outcome_code="URGENT_ESCALATION", commitments=[valid]
    )[0]["assigned_to"] == "nurse"


def test_worklist_renders_plan_lifecycle_and_health_contract(a10_app):
    from src.adapters.sqlite.encounter_plan_commitment_repo import (
        EncounterPlanCommitmentRepository,
    )

    app = a10_app
    ctx = _context()
    _sign(ctx, commitments=[_commitment(ctx)])
    client = app.test_client()
    login = client.post("/auth/login", data={"username": "admin", "password": "admin"})
    assert login.status_code in {302, 303}
    page = client.get("/followups/")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "تعهد طرح Encounter" in html
    assert "مدیریت تعهد طرح" in html
    assert "/plan/transition" in html
    task_id = EncounterPlanCommitmentRepository().list_current()[0]["id"]
    blocked = client.post(f"/followups/{task_id}/resolve", data={"status": "done"})
    assert blocked.status_code in {302, 303}
    assert EncounterPlanCommitmentRepository().current_for_task(task_id)["current_status"] == "OPEN"
    details = client.get("/health/details").get_json()
    assert "encounter_plan_commitments" in details["checks"]
