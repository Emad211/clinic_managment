from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import sqlite3

import pytest


@pytest.fixture()
def fo6_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "fo6.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "fo6-test",
            "FOLLOWUP_SMS_AUTO_GUARDED": True,
        }
    )
    context = app.app_context()
    context.push()
    from src.adapters.sqlite.sms_repo import SmsRepository

    settings = SmsRepository()
    settings.set_setting("engagement_quiet_start", "00:00")
    settings.set_setting("engagement_quiet_end", "00:00")
    settings.set_setting("engagement_daily_cap", "10")
    settings.set_setting("sms_provider", "kavenegar")
    yield app
    context.pop()
    core._initialized = False


def _seed_due_patient(db, *, suffix: str = "1") -> dict:
    from src.adapters.sqlite.sms_governance_repo import SmsGovernanceRepository
    from src.common.utils import iran_now

    current = iran_now().replace(tzinfo=None, microsecond=0)
    cursor = db.execute(
        """INSERT INTO patient_links
           (national_id, full_name, phone_number, is_active, enrolled_by,
            enrolled_at, updated_at)
           VALUES (?, ?, ?, 1, 'pytest', ?, ?)""",
        (
            f"FO6{suffix:0>7}",
            f"FO6 Patient {suffix}",
            f"0912000{int(suffix):04d}",
            current.isoformat(sep=" "),
            current.isoformat(sep=" "),
        ),
    )
    patient_id = int(cursor.lastrowid)
    appointment_at = current + timedelta(days=1)
    appointment_id = int(
        db.execute(
            """INSERT INTO appointments
               (patient_link_id, scheduled_at, status, created_by)
               VALUES (?, ?, 'scheduled', 'pytest')""",
            (patient_id, appointment_at.isoformat(sep=" ")),
        ).lastrowid
    )
    refill_date = current.date().isoformat()
    medication_id = int(
        db.execute(
            """INSERT INTO patient_medications
               (patient_link_id, drug_name, refill_due_date, is_active)
               VALUES (?, 'Metformin Test', ?, 1)""",
            (patient_id, refill_date),
        ).lastrowid
    )
    db.execute(
        """UPDATE engagement_events
           SET channel='sms', is_active=1, lead_days=30, cooldown_days=0,
               sms_template=CASE event_key
                 WHEN 'appointment_reminder'
                   THEN 'سلام {name}، یادآوری {detail}'
                 WHEN 'refill_due'
                   THEN 'سلام {name}، زمان پیگیری {detail}'
                 ELSE sms_template END
           WHERE event_key IN ('appointment_reminder','refill_due')"""
    )
    db.commit()
    SmsGovernanceRepository(db).ensure_patient_defaults(patient_id)
    return {
        "patient_id": patient_id,
        "name": f"FO6 Patient {suffix}",
        "phone": f"0912000{int(suffix):04d}",
        "appointment_id": appointment_id,
        "medication_id": medication_id,
    }


def _prepare(service, *, now=None):
    published = service.publish_current_contract(
        actor_username="fo6-test-manager",
        now=now,
    )
    collected = service.collect_candidates(
        actor_username="fo6-test-manager",
        now=now,
    )
    return published, collected


def _candidate_by_event(db, event_key: str) -> dict:
    row = db.execute(
        """SELECT * FROM sms_auto_guard_candidates
           WHERE event_key=? ORDER BY id DESC LIMIT 1""",
        (event_key,),
    ).fetchone()
    assert row is not None
    return dict(row)


def test_storage_is_additive_immutable_and_candidate_is_phi_minimized(fo6_app):
    from src.adapters.sqlite.core import get_db
    from src.services.sms.auto_guard_service import SmsAutoGuardService

    db = get_db()
    seeded = _seed_due_patient(db)
    service = SmsAutoGuardService(db)
    _prepare(service)

    columns = {
        row["name"]
        for row in db.execute(
            "PRAGMA table_info(sms_auto_guard_candidates)"
        ).fetchall()
    }
    for forbidden in (
        "recipient",
        "phone_number",
        "body",
        "template_text",
        "full_name",
        "note",
        "free_text",
    ):
        assert forbidden not in columns
    candidate = _candidate_by_event(db, "appointment_reminder")
    serialized = json.dumps(candidate, ensure_ascii=False)
    assert seeded["phone"] not in serialized
    assert seeded["name"] not in serialized
    assert "یادآوری" not in serialized
    assert len(candidate["phone_hash"]) == 64
    assert len(candidate["body_hash"]) == 64
    assert len(candidate["source_hash"]) == 64

    for statement in (
        "UPDATE sms_auto_guard_candidates SET period_key='x' WHERE id=1",
        "DELETE FROM sms_auto_guard_policy_versions",
        "UPDATE sms_auto_guard_template_versions SET version=99 WHERE id=1",
        "DELETE FROM sms_auto_guard_decision_events",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(statement)
        db.rollback()


def test_feature_off_denies_publish_collect_and_execute_without_send(fo6_app):
    from src.adapters.sqlite.core import get_db
    from src.services.sms.auto_guard_service import (
        SmsAutoGuardError,
        SmsAutoGuardService,
    )

    db = get_db()
    _seed_due_patient(db)
    sent = []
    service = SmsAutoGuardService(db, sender=lambda *a, **k: sent.append(1) or True)
    _prepare(service)
    candidate = _candidate_by_event(db, "appointment_reminder")

    fo6_app.config["FOLLOWUP_SMS_AUTO_GUARDED"] = False
    with pytest.raises(SmsAutoGuardError) as publish_error:
        service.publish_current_contract(actor_username="pytest")
    assert publish_error.value.code == "FEATURE_DISABLED"
    with pytest.raises(SmsAutoGuardError) as collect_error:
        service.collect_candidates(actor_username="pytest")
    assert collect_error.value.code == "FEATURE_DISABLED"
    result = service.execute_candidate(candidate["id"], actor_username="pytest")
    assert result["reason"] == "FEATURE_DISABLED"
    assert sent == []
    assert db.execute(
        """SELECT COUNT(*) FROM sms_auto_guard_decision_events
           WHERE candidate_id=? AND reason_code='FEATURE_DISABLED'""",
        (candidate["id"],),
    ).fetchone()[0] == 1


def test_policy_has_exact_care_allowlist_and_never_auto_levels(fo6_app):
    from src.adapters.sqlite.core import get_db
    from src.services.sms.auto_guard_service import SmsAutoGuardService

    db = get_db()
    _seed_due_patient(db)
    service = SmsAutoGuardService(db)
    _prepare(service)
    row = db.execute(
        "SELECT policy_json FROM sms_auto_guard_policy_versions"
    ).fetchone()
    policy = json.loads(row["policy_json"])
    assert policy["allowlist"] == ["appointment_reminder", "refill_due"]
    assert policy["purpose"] == "CARE"
    assert policy["free_text_allowed"] is False
    assert policy["policy_levels"] == {
        "*": "CLINICIAN_ONLY",
        "appointment_reminder": "AUTO_GUARDED",
        "lapsed": "MANUAL_APPROVAL",
        "refill_due": "AUTO_GUARDED",
    }
    assert {
        row["event_key"]
        for row in db.execute("SELECT event_key FROM sms_auto_guard_candidates")
    } == {"appointment_reminder", "refill_due"}


def test_collection_is_idempotent_and_changed_snapshot_supersedes(fo6_app):
    from src.adapters.sqlite.core import get_db
    from src.services.sms.auto_guard_service import SmsAutoGuardService

    db = get_db()
    seeded = _seed_due_patient(db)
    service = SmsAutoGuardService(db)
    _prepare(service)
    first_count = db.execute(
        "SELECT COUNT(*) FROM sms_auto_guard_candidates"
    ).fetchone()[0]
    replay = service.collect_candidates(actor_username="pytest")
    assert replay["counts"]["reused"] == 2
    assert db.execute(
        "SELECT COUNT(*) FROM sms_auto_guard_candidates"
    ).fetchone()[0] == first_count

    db.execute(
        "UPDATE patient_links SET phone_number='09129999999' WHERE id=?",
        (seeded["patient_id"],),
    )
    db.commit()
    refreshed = service.collect_candidates(actor_username="pytest")
    assert refreshed["counts"]["created"] == 2
    assert db.execute(
        """SELECT COUNT(*) FROM sms_auto_guard_decision_events
           WHERE decision_type='SUPERSEDED'"""
    ).fetchone()[0] == 2


def test_real_test_provider_submission_is_governed_and_replay_safe(fo6_app):
    from src.adapters.sqlite.core import get_db
    from src.services.sms.auto_guard_service import SmsAutoGuardService

    db = get_db()
    seeded = _seed_due_patient(db)
    service = SmsAutoGuardService(db)
    _prepare(service)
    candidate = _candidate_by_event(db, "appointment_reminder")

    result = service.execute_candidate(candidate["id"], actor_username="pytest")
    assert result["ok"] is True
    assert result["message_id"]
    message = db.execute(
        "SELECT * FROM sms_messages WHERE id=?",
        (result["message_id"],),
    ).fetchone()
    assert message["patient_link_id"] == seeded["patient_id"]
    assert message["source_type"] == "fo6_auto_guard"
    assert message["source_ref"] == str(candidate["id"])
    assert message["send_attempts"] == 1
    governance = db.execute(
        "SELECT * FROM sms_message_governance WHERE message_id=?",
        (result["message_id"],),
    ).fetchone()
    assert governance["purpose"] == "CARE"
    assert governance["allowed_at_submission"] == 1
    assert db.execute(
        """SELECT COUNT(*) FROM engagement_dispatch
           WHERE patient_link_id=? AND event_key='appointment_reminder'
             AND channel='sms'""",
        (seeded["patient_id"],),
    ).fetchone()[0] == 1

    replay = service.execute_candidate(candidate["id"], actor_username="pytest")
    assert replay["ok"] is False
    assert replay["reason"] == "SUBMITTED"
    assert db.execute(
        """SELECT COUNT(*) FROM sms_messages
           WHERE source_type='fo6_auto_guard' AND source_ref=?""",
        (str(candidate["id"]),),
    ).fetchone()[0] == 1
    assert db.execute(
        """SELECT COUNT(*) FROM sms_auto_guard_decision_events
           WHERE candidate_id=? AND decision_type='SUBMITTED'""",
        (candidate["id"],),
    ).fetchone()[0] == 1


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("phone", "PHONE_CHANGED"),
        ("template", "TEMPLATE_CHANGED"),
        ("source", "SOURCE_NOT_DUE"),
        ("consent", "CONSENT_REVOKED"),
        ("policy", "POLICY_CHANGED"),
    ],
)
def test_freshness_changes_fail_closed(fo6_app, mutation, expected):
    from src.adapters.sqlite.core import get_db
    from src.services.sms.auto_guard_service import SmsAutoGuardService
    from src.services.sms.governance_service import SmsGovernanceService

    db = get_db()
    seeded = _seed_due_patient(db)
    sent = []
    service = SmsAutoGuardService(db, sender=lambda *a, **k: sent.append(1) or True)
    _prepare(service)
    candidate = _candidate_by_event(db, "appointment_reminder")

    if mutation == "phone":
        db.execute(
            "UPDATE patient_links SET phone_number='09129999999' WHERE id=?",
            (seeded["patient_id"],),
        )
        db.commit()
    elif mutation == "template":
        db.execute(
            """UPDATE engagement_events SET sms_template='نسخهٔ تغییرکرده {name}'
               WHERE event_key='appointment_reminder'"""
        )
        db.commit()
    elif mutation == "source":
        db.execute(
            "UPDATE appointments SET status='cancelled' WHERE id=?",
            (seeded["appointment_id"],),
        )
        db.commit()
    elif mutation == "consent":
        current = SmsGovernanceService().summary(seeded["patient_id"])["CARE"]
        SmsGovernanceService().record(
            patient_link_id=seeded["patient_id"],
            purpose="CARE",
            decision="REVOKED",
            actor_username="pytest",
            actor_user_id=None,
            source_code="PATIENT_REQUEST",
            idempotency_key=f"fo6-revoke-{seeded['patient_id']}",
            expected_current_event_id=int(current["id"]),
        )
    else:
        service.publish_current_contract(
            actor_username="pytest",
            ttl_hours=25,
        )

    result = service.execute_candidate(candidate["id"], actor_username="pytest")
    assert result["ok"] is False
    assert result["reason"] == expected
    assert sent == []
    assert db.execute(
        """SELECT COUNT(*) FROM sms_auto_guard_decision_events
           WHERE candidate_id=? AND reason_code=?""",
        (candidate["id"], expected),
    ).fetchone()[0] == 1


def test_expiry_daily_cap_cooldown_and_provider_fail_closed(fo6_app, monkeypatch):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.engagement_repo import EngagementRepository
    from src.adapters.sqlite.sms_repo import SmsRepository
    from src.common.utils import iran_now
    from src.services.sms.auto_guard_service import SmsAutoGuardService
    from src.services.sms.campaign_service import send_single
    from src.services.sms.provider import UnconfiguredProvider

    db = get_db()
    seeded = _seed_due_patient(db)
    service = SmsAutoGuardService(db, sender=lambda *a, **k: True)
    past = iran_now().replace(tzinfo=None, microsecond=0) - timedelta(days=2)
    _prepare(service, now=past)
    expired = _candidate_by_event(db, "appointment_reminder")
    result = service.execute_candidate(expired["id"], actor_username="pytest")
    assert result["reason"] == "CANDIDATE_EXPIRED"

    # Fresh candidate after explicit recollection.
    service.collect_candidates(actor_username="pytest")
    candidate = _candidate_by_event(db, "appointment_reminder")
    SmsRepository().set_setting("engagement_daily_cap", "1")
    assert send_single(
        seeded["patient_id"],
        seeded["phone"],
        "manual cap test",
        idempotency_key="fo6-daily-cap-primer",
        purpose="CARE",
        source_type="manual",
        created_by="pytest",
        override_quiet=True,
    )
    capped = service.execute_candidate(candidate["id"], actor_username="pytest")
    assert capped["reason"] == "DAILY_CAP"

    # New patient for isolated cooldown/provider checks.
    seeded2 = _seed_due_patient(db, suffix="2")
    SmsRepository().set_setting("engagement_daily_cap", "10")
    service.collect_candidates(
        actor_username="pytest",
        patient_ids=[seeded2["patient_id"]],
    )
    candidate2 = db.execute(
        """SELECT * FROM sms_auto_guard_candidates
           WHERE patient_link_id=? AND event_key='appointment_reminder'
           ORDER BY id DESC LIMIT 1""",
        (seeded2["patient_id"],),
    ).fetchone()
    EngagementRepository().record_dispatch(
        seeded2["patient_id"],
        "appointment_reminder",
        "older-period",
        "sms",
        None,
        status="accepted",
    )
    db.execute(
        """UPDATE engagement_events SET cooldown_days=30
           WHERE event_key='appointment_reminder'"""
    )
    db.commit()
    cooled = service.execute_candidate(candidate2["id"], actor_username="pytest")
    assert cooled["reason"] == "COOLDOWN"

    seeded3 = _seed_due_patient(db, suffix="3")
    service.collect_candidates(
        actor_username="pytest",
        patient_ids=[seeded3["patient_id"]],
    )
    candidate3 = db.execute(
        """SELECT * FROM sms_auto_guard_candidates
           WHERE patient_link_id=? AND event_key='refill_due'
           ORDER BY id DESC LIMIT 1""",
        (seeded3["patient_id"],),
    ).fetchone()
    monkeypatch.setattr(
        "src.services.sms.auto_guard_service.get_provider",
        lambda name=None: UnconfiguredProvider(name),
    )
    provider_denied = service.execute_candidate(
        candidate3["id"], actor_username="pytest"
    )
    assert provider_denied["reason"] == "PROVIDER_UNCONFIGURED"


def test_claim_is_one_winner_and_provider_failure_is_audited(fo6_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.sms_auto_guard_repo import (
        SmsAutoGuardConflict,
        SmsAutoGuardRepository,
    )
    from src.common.utils import iran_now
    from src.services.sms.auto_guard_service import SmsAutoGuardService

    db = get_db()
    _seed_due_patient(db)
    service = SmsAutoGuardService(db, sender=lambda *a, **k: False)
    _prepare(service)
    candidate = _candidate_by_event(db, "appointment_reminder")
    validated = service.revalidate(candidate["id"])
    repo = SmsAutoGuardRepository(db)
    attempt = repo.claim(
        candidate_id=candidate["id"],
        revalidation_hash=validated.revalidation_hash,
        actor_username="worker-a",
        claimed_at=iran_now().replace(tzinfo=None, microsecond=0),
    )
    assert attempt == 1
    with pytest.raises(SmsAutoGuardConflict, match="IN_FLIGHT"):
        repo.claim(
            candidate_id=candidate["id"],
            revalidation_hash=validated.revalidation_hash,
            actor_username="worker-b",
            claimed_at=iran_now().replace(tzinfo=None, microsecond=0),
        )

    # Finish the claimed attempt, then explicitly recollect a new generation.
    repo.finish_attempt(
        candidate_id=candidate["id"],
        attempt_no=attempt,
        accepted=False,
        reason_code="PROVIDER_REJECTED",
        revalidation_hash=validated.revalidation_hash,
        actor_username="worker-a",
        recorded_at=iran_now().replace(tzinfo=None, microsecond=0),
    )
    assert db.execute(
        """SELECT COUNT(*) FROM sms_auto_guard_decision_events
           WHERE candidate_id=? AND decision_type='SUBMISSION_FAILED'""",
        (candidate["id"],),
    ).fetchone()[0] == 1


def test_cli_and_service_have_no_startup_get_scheduler_or_forbidden_writes():
    root = Path(__file__).resolve().parents[1]
    service = (
        root / "src" / "services" / "sms" / "auto_guard_service.py"
    ).read_text(encoding="utf-8")
    cli = (root / "scripts" / "run_fo6_sms_auto_guard.py").read_text(
        encoding="utf-8"
    )
    schema = (
        root / "src" / "adapters" / "sqlite" / "sms_auto_guard_schema.py"
    ).read_text(encoding="utf-8")

    assert "if __name__ == \"__main__\"" in cli
    assert "sub.add_parser(\"execute\"" in cli
    assert "before_request" not in service
    assert "scheduler" not in service.lower()
    assert "operational_outbox" not in schema
    upper = service.upper()
    for forbidden in (
        "UPDATE APPOINTMENTS",
        "INSERT INTO APPOINTMENTS",
        "UPDATE CLINICAL_",
        "INSERT INTO CLINICAL_",
        "CLINIC_NEW.DB",
        "SMS_CAMPAIGNS",
    ):
        assert forbidden not in upper
