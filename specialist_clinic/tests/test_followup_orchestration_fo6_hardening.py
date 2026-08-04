from __future__ import annotations

from datetime import datetime
import sqlite3


def _repository() -> tuple[sqlite3.Connection, object]:
    from src.adapters.sqlite.sms_auto_guard_repo import SmsAutoGuardRepository
    from src.adapters.sqlite.sms_auto_guard_schema import (
        ensure_sms_auto_guard_storage,
    )

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    ensure_sms_auto_guard_storage(db)
    return db, SmsAutoGuardRepository(db)


def test_policy_reversion_creates_a_new_immutable_head():
    db, repo = _repository()
    at = datetime(2026, 8, 4, 12, 0, 0)

    first, first_created = repo.publish_policy(
        policy_key="FOUX-SMS-AUTO-GUARD-V1",
        purpose="CARE",
        policy={"candidate_ttl_hours": 24, "purpose": "CARE"},
        actor_username="pytest",
        created_at=at,
    )
    second, second_created = repo.publish_policy(
        policy_key="FOUX-SMS-AUTO-GUARD-V1",
        purpose="CARE",
        policy={"candidate_ttl_hours": 25, "purpose": "CARE"},
        actor_username="pytest",
        created_at=at,
    )
    third, third_created = repo.publish_policy(
        policy_key="FOUX-SMS-AUTO-GUARD-V1",
        purpose="CARE",
        policy={"candidate_ttl_hours": 24, "purpose": "CARE"},
        actor_username="pytest",
        created_at=at,
    )
    replay, replay_created = repo.publish_policy(
        policy_key="FOUX-SMS-AUTO-GUARD-V1",
        purpose="CARE",
        policy={"candidate_ttl_hours": 24, "purpose": "CARE"},
        actor_username="pytest",
        created_at=at,
    )

    assert (first_created, second_created, third_created) == (True, True, True)
    assert [first["version"], second["version"], third["version"]] == [1, 2, 3]
    assert first["id"] != third["id"]
    assert first["content_hash"] == third["content_hash"]
    assert replay_created is False
    assert replay["id"] == third["id"]
    assert db.execute(
        "SELECT COUNT(*) FROM sms_auto_guard_policy_versions"
    ).fetchone()[0] == 3
    db.close()


def test_template_reversion_creates_a_new_immutable_head():
    db, repo = _repository()
    at = datetime(2026, 8, 4, 12, 0, 0)
    policy, _ = repo.publish_policy(
        policy_key="FOUX-SMS-AUTO-GUARD-V1",
        purpose="CARE",
        policy={"candidate_ttl_hours": 24, "purpose": "CARE"},
        actor_username="pytest",
        created_at=at,
    )

    def publish(text: str):
        return repo.publish_template(
            event_key="appointment_reminder",
            policy_version_id=int(policy["id"]),
            template_text=text,
            message_type="Informational",
            actor_username="pytest",
            approved_at=at,
        )

    first, first_created = publish("نسخه الف {name}")
    second, second_created = publish("نسخه ب {name}")
    third, third_created = publish("نسخه الف {name}")
    replay, replay_created = publish("نسخه الف {name}")

    assert (first_created, second_created, third_created) == (True, True, True)
    assert [first["version"], second["version"], third["version"]] == [1, 2, 3]
    assert first["id"] != third["id"]
    assert first["content_hash"] == third["content_hash"]
    assert replay_created is False
    assert replay["id"] == third["id"]
    assert db.execute(
        "SELECT COUNT(*) FROM sms_auto_guard_template_versions"
    ).fetchone()[0] == 3
    db.close()


def test_disabled_direct_execution_does_not_install_fo6_storage(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "fo6-disabled.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "fo6-disabled-test",
            "FOLLOWUP_SMS_AUTO_GUARDED": False,
        }
    )
    context = app.app_context()
    context.push()
    try:
        from src.adapters.sqlite.core import get_db
        from src.services.sms.auto_guard_service import SmsAutoGuardService

        db = get_db()
        before = {
            str(row["name"])
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        result = SmsAutoGuardService(db).execute_candidate(
            999999,
            actor_username="pytest",
        )
        after = {
            str(row["name"])
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        assert result == {
            "ok": False,
            "candidate_id": 999999,
            "reason": "FEATURE_DISABLED",
        }
        assert before == after
        assert not {name for name in after if name.startswith("sms_auto_guard_")}
    finally:
        context.pop()
        core._initialized = False
