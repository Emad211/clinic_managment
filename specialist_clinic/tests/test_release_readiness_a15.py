from __future__ import annotations

import sqlite3
from pathlib import Path

import bcrypt
from werkzeug.security import generate_password_hash

from src.app import create_app
from src.common.install_secret import (
    default_secret_path,
    is_strong_secret,
    load_or_create_install_secret,
)
from src.common.network_policy import (
    is_loopback_host,
    validate_server_exposure,
)
from src.services.release_ops import run_self_test
from src.services.backup_integrity import BackupIntegrityService, sqlite_integrity


def _fresh_app(tmp_path: Path):
    return create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "fresh.db"),
            "ACCOUNTING_DB_PATH": str(tmp_path / "accounting.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "release-readiness-test",
            "CREATE_TEST_ADMIN": False,
            "START_SCHEDULER": False,
            "CSRF_PROTECTION_ENABLED": False,
        }
    )


def test_install_secret_is_random_persistent_and_not_stored_in_database(
    tmp_path: Path,
):
    database = tmp_path / "specialist.db"
    first = load_or_create_install_secret(
        database_path=str(database), project_root=str(tmp_path)
    )
    second = load_or_create_install_secret(
        database_path=str(database), project_root=str(tmp_path)
    )

    assert first == second
    assert is_strong_secret(first)
    secret_path = default_secret_path(str(database), str(tmp_path))
    assert secret_path.is_file()
    assert secret_path.read_text(encoding="utf-8").strip() == first
    assert secret_path != database


def test_first_run_has_no_default_user_and_requires_local_strong_setup(tmp_path):
    app = _fresh_app(tmp_path)
    client = app.test_client()

    with app.app_context():
        from src.adapters.sqlite.core import get_db

        assert get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0

    assert client.get("/").headers["Location"].endswith("/auth/setup")
    assert client.get(
        "/auth/setup", environ_overrides={"REMOTE_ADDR": "10.10.10.2"}
    ).status_code == 403
    assert client.get("/health/ready").status_code == 503

    weak = client.post(
        "/auth/setup",
        data={
            "username": "clinic_manager",
            "full_name": "مدیر درمانگاه",
            "password": "short1",
            "password_confirm": "short1",
        },
    )
    assert weak.status_code == 200

    completed = client.post(
        "/auth/setup",
        data={
            "username": "clinic_manager",
            "full_name": "مدیر درمانگاه",
            "password": "SafeClinicPass2026",
            "password_confirm": "SafeClinicPass2026",
        },
        follow_redirects=False,
    )
    assert completed.status_code == 302
    assert completed.headers["Location"].endswith("/auth/login")

    with app.app_context():
        from src.adapters.sqlite.core import get_db

        row = get_db().execute(
            "SELECT * FROM users WHERE username='clinic_manager'"
        ).fetchone()
        assert row["role"] == "manager"
        assert row["must_change_password"] == 0
        assert bcrypt.checkpw(b"SafeClinicPass2026", row["password_hash"])


def test_existing_admin_default_is_forced_through_local_password_change(tmp_path):
    database = tmp_path / "legacy.db"
    app = create_app(
        {
            "TESTING": False,
            "PRODUCTION": False,
            "DATABASE_PATH": str(database),
            "ACCOUNTING_DB_PATH": str(tmp_path / "accounting.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "INSTALL_SECRET_PATH": str(tmp_path / "secret"),
            "START_SCHEDULER": False,
        }
    )
    with app.app_context():
        from src.adapters.sqlite.core import get_db

        db = get_db()
        db.execute("DELETE FROM users")
        db.execute(
            """INSERT INTO users
               (username,password_hash,role,full_name,is_active,must_change_password)
               VALUES ('admin',?,'manager','مدیر سیستم',1,0)""",
            (bcrypt.hashpw(b"admin", bcrypt.gensalt()),),
        )
        db.commit()

    # Re-open through a new factory so startup migration identifies the legacy
    # known credential. Resetting the module guard simulates a fresh process.
    import src.adapters.sqlite.core as core

    core._initialized = False
    migrated = create_app(
        {
            "TESTING": False,
            "PRODUCTION": False,
            "DATABASE_PATH": str(database),
            "ACCOUNTING_DB_PATH": str(tmp_path / "accounting.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "INSTALL_SECRET_PATH": str(tmp_path / "secret"),
            "START_SCHEDULER": False,
        }
    )
    with migrated.app_context():
        row = core.get_db().execute(
            "SELECT must_change_password FROM users WHERE username='admin'"
        ).fetchone()
        assert row["must_change_password"] == 1
    assert migrated.test_client().get("/auth/login").headers[
        "Location"
    ].endswith("/auth/setup")


def test_legacy_werkzeug_admin_default_is_also_forced_to_change(tmp_path):
    app = create_app(
        {
            "TESTING": False,
            "PRODUCTION": False,
            "DATABASE_PATH": str(tmp_path / "werkzeug.db"),
            "ACCOUNTING_DB_PATH": str(tmp_path / "accounting.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "INSTALL_SECRET_PATH": str(tmp_path / "secret"),
            "START_SCHEDULER": False,
        }
    )
    with app.app_context():
        import src.adapters.sqlite.core as core

        db = core.get_db()
        db.execute("DELETE FROM users")
        db.execute(
            """INSERT INTO users
               (username,password_hash,role,full_name,is_active,must_change_password)
               VALUES ('admin',?,'manager','مدیر سیستم',1,0)""",
            (generate_password_hash("admin"),),
        )
        db.commit()
        core._mark_legacy_default_admin_for_change(db)
        row = db.execute(
            "SELECT must_change_password FROM users WHERE username='admin'"
        ).fetchone()
        assert row["must_change_password"] == 1


def test_network_policy_defaults_to_loopback_and_rejects_unfinished_lan():
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("::1")
    assert not is_loopback_host("0.0.0.0")
    validate_server_exposure(
        host="127.0.0.1", secret_key="s" * 64, setup_complete=False
    )
    try:
        validate_server_exposure(
            host="0.0.0.0", secret_key="s" * 64, setup_complete=False
        )
    except RuntimeError as exc:
        assert "loopback" in str(exc)
    else:
        raise AssertionError("unfinished first-run must not be exposed to LAN")


def test_release_self_test_exercises_isolated_backup_restore_cycle():
    report = run_self_test()
    assert report["required_ok"] is True
    assert report["status"] == "pass"
    assert {item["name"] for item in report["checks"]} >= {
        "live_endpoint",
        "ready_endpoint",
        "accounting_bridge_read_only",
        "backup_restore_round_trip",
    }


def test_verified_restore_can_recover_a_corrupt_current_database(tmp_path):
    source = tmp_path / "source.db"
    connection = sqlite3.connect(str(source))
    try:
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample VALUES ('verified')")
        connection.commit()
    finally:
        connection.close()

    service = BackupIntegrityService()
    backup = service.create(source, tmp_path / "backups", prefix="recovery")
    destination = tmp_path / "destination.db"
    destination.write_bytes(b"not-a-sqlite-database")

    service.restore(
        backup.database_path,
        destination,
        manifest_path=backup.manifest_path,
    )

    assert sqlite_integrity(destination).lower() == "ok"
    assert destination.with_suffix(".db.before-restore").read_bytes() == (
        b"not-a-sqlite-database"
    )


def test_production_entrypoint_uses_waitress_not_flask_development_server():
    source = (Path(__file__).parents[1] / "start.py").read_text(
        encoding="utf-8"
    )
    assert "from waitress import serve" in source
    assert "app.run(" not in source
