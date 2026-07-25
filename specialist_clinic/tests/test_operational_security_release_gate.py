from __future__ import annotations

import bcrypt
import re

import pytest


_TOKEN = re.compile(r'name="_csrf_token" value="([^"]+)"')


def _token(response) -> str:
    match = _TOKEN.search(response.get_data(as_text=True))
    assert match
    return match.group(1)


@pytest.fixture()
def release_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "CSRF_PROTECTION_ENABLED": True,
            "DATABASE_PATH": str(tmp_path / "release.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "release-gate-secret",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _login(client, username="admin", password="admin"):
    page = client.get("/auth/login")
    response = client.post(
        "/auth/login",
        data={
            "username": username,
            "password": password,
            "_csrf_token": _token(page),
        },
    )
    assert response.status_code in {302, 303}


def test_file_database_uses_wal_and_installs_operational_storage(release_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert int(db.execute("PRAGMA busy_timeout").fetchone()[0]) == 10000
    tables = {
        row["name"]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "security_permission_events",
        "operational_leases",
        "operational_job_runs",
        "clinical_audit_checkpoints",
    } <= tables


def test_production_rejects_default_bootstrap_password(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    with pytest.raises(RuntimeError, match="BOOTSTRAP_ADMIN_PASSWORD"):
        create_app(
            {
                "PRODUCTION": True,
                "SECRET_KEY": "x" * 64,
                "DATABASE_PATH": str(tmp_path / "production.db"),
                "BACKUP_FOLDER": str(tmp_path / "backups"),
            }
        )
    core._initialized = False


def test_logout_is_post_only_and_csrf_protected(release_app):
    client = release_app.test_client()
    _login(client)
    assert client.get("/auth/logout").status_code == 405
    assert client.post("/auth/logout").status_code == 400
    page = client.get("/followups/")
    response = client.post(
        "/auth/logout", data={"_csrf_token": _token(page)}
    )
    assert response.status_code in {302, 303}


def test_technical_reviewer_can_open_engine_without_manager_role(release_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.security_permission_repo import SecurityPermissionRepository
    from src.security.permissions import Permission

    db = get_db()
    password = bcrypt.hashpw(b"review-pass", bcrypt.gensalt())
    cursor = db.execute(
        "INSERT INTO users (username,password_hash,role,full_name,is_active) "
        "VALUES (?,?,?,?,1)",
        ("technical-reviewer", password, "staff", "Technical Reviewer"),
    )
    user_id = int(cursor.lastrowid)
    admin = db.execute(
        "SELECT id,username FROM users WHERE username='admin'"
    ).fetchone()
    db.commit()
    SecurityPermissionRepository().record(
        user_id=user_id,
        permission=Permission.RULE_REVIEW_TECHNICAL,
        effect="GRANTED",
        actor_username=admin["username"],
        actor_user_id=int(admin["id"]),
        reason="Independent technical rule review",
        expected_current_event_id=None,
    )

    client = release_app.test_client()
    _login(client, "technical-reviewer", "review-pass")
    assert client.get("/manager/clinical-engine").status_code == 200
    assert client.get("/manager/settings").status_code in {302, 303, 403}


def test_extension_origin_matching_rejects_prefix_confusion():
    from src.api.ext import _origin_allowed

    assert _origin_allowed("https://ep.tamin.ir")
    assert _origin_allowed("http://localhost:8090")
    assert not _origin_allowed("https://ep.tamin.ir.evil.example")
    assert not _origin_allowed("https://evil.example")


def test_scheduler_can_create_a_daily_audit_checkpoint(release_app):
    from src.services.scheduler import Scheduler
    from src.services.clinical_audit_integrity import ClinicalAuditIntegrityService

    scheduler = Scheduler()
    scheduler.init_app(release_app)
    assert scheduler._seal_clinical_audit() is True
    assert ClinicalAuditIntegrityService().verify_latest(
        require_checkpoint=True
    ).ok
