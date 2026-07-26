"""Targeted operational/security release gate for Clinical Engine infrastructure."""
from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import re
import sqlite3
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.adapters.sqlite.operational_lease_repo import (
    LeaseLost,
    OperationalLeaseRepository,
)
from src.adapters.sqlite.security_permission_repo import (
    SecurityPermissionRepository,
    SecurityPermissionValidationError,
)
from src.common.utils import iran_now
from src.security.permissions import Permission, resolved_permissions
from src.services.backup_integrity import (
    BackupIntegrityService,
    BackupVerificationError,
)
from src.services.clinical_audit_integrity import (
    ClinicalAuditIntegrityService,
)


_TOKEN = re.compile(r'name="_csrf_token" value="([^"]+)"')


@pytest.fixture()
def secure_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "CSRF_PROTECTION_ENABLED": True,
            "DATABASE_PATH": str(tmp_path / "secure.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "operational-security-test",
            "PROPAGATE_EXCEPTIONS": True,
        }
    )
    context = app.app_context()
    context.push()
    yield app, tmp_path
    context.pop()
    core._initialized = False


def _csrf(html: str) -> str:
    match = _TOKEN.search(html)
    assert match, "POST form did not receive a CSRF token"
    return match.group(1)


def _login(client):
    page = client.get("/auth/login")
    token = _csrf(page.get_data(as_text=True))
    response = client.post(
        "/auth/login",
        data={
            "username": "admin",
            "password": "admin",
            "_csrf_token": token,
        },
    )
    assert response.status_code in {302, 303}


def _staff(db, username="staff-sec") -> int:
    row = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if row:
        return int(row["id"])
    cursor = db.execute(
        """INSERT INTO users
           (username, password_hash, role, full_name, is_active)
           VALUES (?, X'00', 'staff', 'Security Staff', 1)""",
        (username,),
    )
    db.commit()
    return int(cursor.lastrowid)


def test_csrf_is_required_rotated_and_injected(secure_app):
    app, _ = secure_app
    client = app.test_client()

    rejected = client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin"},
    )
    assert rejected.status_code == 400
    login_page = client.get("/auth/login")
    login_token = _csrf(login_page.get_data(as_text=True))
    accepted = client.post(
        "/auth/login",
        data={
            "username": "admin",
            "password": "admin",
            "_csrf_token": login_token,
        },
    )
    assert accepted.status_code in {302, 303}

    worklist = client.get("/followups/")
    post_login_token = _csrf(worklist.get_data(as_text=True))
    assert post_login_token != login_token
    missing = client.post("/followups/generate")
    assert missing.status_code == 400


def test_permission_overrides_are_append_only_and_fail_closed(secure_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    admin = db.execute("SELECT * FROM users WHERE username='admin'").fetchone()
    staff_id = _staff(db)
    repo = SecurityPermissionRepository()

    granted = repo.record(
        user_id=staff_id,
        permission=Permission.CLINICAL_TASK_TRANSITION,
        effect="GRANTED",
        actor_username="admin",
        actor_user_id=int(admin["id"]),
        reason="Temporary clinical task responsibility",
        expected_current_event_id=None,
    )
    staff = db.execute("SELECT * FROM users WHERE id=?", (staff_id,)).fetchone()
    assert Permission.CLINICAL_TASK_TRANSITION in resolved_permissions(staff)

    revoked = repo.record(
        user_id=staff_id,
        permission=Permission.CLINICAL_TASK_TRANSITION,
        effect="REVOKED",
        actor_username="admin",
        actor_user_id=int(admin["id"]),
        reason="Temporary responsibility ended",
        expected_current_event_id=int(granted["id"]),
    )
    assert Permission.CLINICAL_TASK_TRANSITION not in resolved_permissions(staff)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute(
            "UPDATE security_permission_events SET reason='changed' WHERE id=?",
            (revoked["id"],),
        )
    db.rollback()
    with pytest.raises(SecurityPermissionValidationError, match="self-granting"):
        repo.record(
            user_id=int(admin["id"]),
            permission=Permission.RULE_ACTIVATE,
            effect="GRANTED",
            actor_username="admin",
            actor_user_id=int(admin["id"]),
            reason="Unsafe self elevation",
            expected_current_event_id=None,
        )


def test_lease_is_exclusive_monotonic_and_fenced(secure_app):
    repo = OperationalLeaseRepository()
    start = iran_now().replace(tzinfo=None, microsecond=0)
    first = repo.acquire(
        "scheduler:test",
        owner_id="worker:first",
        ttl_seconds=60,
        now=start,
    )
    assert first and first.fencing_token == 1
    assert repo.acquire(
        "scheduler:test",
        owner_id="worker:second",
        ttl_seconds=60,
        now=start + timedelta(seconds=10),
    ) is None
    assert repo.begin_job("daily:test:2026-07-25", first) is True
    repo.finish_job("daily:test:2026-07-25", first, succeeded=True)
    assert repo.begin_job("daily:test:2026-07-25", first) is False

    assert repo.release(first, now=start + timedelta(seconds=20))
    second = repo.acquire(
        "scheduler:test",
        owner_id="worker:second",
        ttl_seconds=60,
        now=start + timedelta(seconds=21),
    )
    assert second and second.fencing_token == 2
    with pytest.raises(LeaseLost):
        repo.assert_current(first, now=start + timedelta(seconds=22))


def test_verified_backup_manifest_and_restore_detect_tampering(secure_app):
    app, tmp_path = secure_app
    from src.adapters.sqlite.core import get_db
    from src.services.scheduler import Scheduler

    db = get_db()
    db.execute(
        """INSERT INTO patient_links
           (national_id, full_name, enrolled_by)
           VALUES ('SEC-BACKUP-01', 'Backup Patient', 'pytest')"""
    )
    db.commit()
    scheduler = Scheduler()
    scheduler.init_app(app)
    assert scheduler._backup() is True
    backups = list((tmp_path / "backups").glob("backup_auto_*.db"))
    assert len(backups) == 1
    backup = backups[0]
    manifest = backup.with_suffix(".manifest.json")
    verified = BackupIntegrityService().verify(backup)
    assert verified.sha256 == json.loads(
        manifest.read_text(encoding="utf-8")
    )["sha256"]

    restored = tmp_path / "restored.db"
    BackupIntegrityService().restore(backup, restored)
    connection = sqlite3.connect(restored)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()

    with backup.open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(BackupVerificationError, match="size|SHA-256|integrity"):
        BackupIntegrityService().verify(backup)


def test_audit_checkpoint_detects_offline_row_tampering(secure_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    admin = db.execute("SELECT * FROM users WHERE username='admin'").fetchone()
    staff_id = _staff(db, "audit-staff")
    event = SecurityPermissionRepository().record(
        user_id=staff_id,
        permission=Permission.CLINICAL_TASK_VIEW,
        effect="GRANTED",
        actor_username="admin",
        actor_user_id=int(admin["id"]),
        reason="Audit checkpoint candidate",
        expected_current_event_id=None,
    )
    service = ClinicalAuditIntegrityService()
    checkpoint = service.seal(created_by="pytest-auditor")
    assert service.verify_checkpoint(checkpoint["id"]).ok

    # Simulate an attacker with offline SQLite access who first removes the normal
    # immutability trigger. The checkpoint must still detect the changed historical row.
    db.execute("DROP TRIGGER trg_security_permission_events_no_update")
    db.execute(
        "UPDATE security_permission_events SET reason='tampered' WHERE id=?",
        (event["id"],),
    )
    db.commit()
    verification = service.verify_checkpoint(checkpoint["id"])
    assert verification.ok is False
    assert verification.reason in {"audit_root_mismatch", "audit_row_count_mismatch"}


def test_health_is_phi_free_and_permission_protected(secure_app):
    app, tmp_path = secure_app
    client = app.test_client()
    live = client.get("/health/live")
    ready = client.get("/health/ready")
    assert live.get_json() == {"status": "ok"}
    assert set(ready.get_json()) == {"status"}
    text = ready.get_data(as_text=True)
    for forbidden in ("patient_links", str(tmp_path), "clinical_engine_v2_mode"):
        assert forbidden not in text

    anonymous = client.get("/health/details")
    assert anonymous.status_code in {302, 303}
    _login(client)
    details = client.get("/health/details")
    assert details.status_code in {200, 503}
    payload = details.get_json()
    assert set(payload["checks"]) == {
        "database",
        "schema",
        "activation",
        "audit",
        "worker",
        "revenue_scope",
        "finance_projection",
        "sms_governance",
        "campaign_economics",
        "payer_adjustments",
        "service_lineage",
        "encounter_documentation",
    }
