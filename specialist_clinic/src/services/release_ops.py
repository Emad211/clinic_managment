"""Release preflight and isolated self-test for source and frozen runtimes."""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any

from src.common.install_secret import is_strong_secret
from src.common.network_policy import validate_server_exposure
from src.services.backup_integrity import BackupIntegrityService, sqlite_integrity
from src.services.first_run_service import FirstRunService


def _check(name: str, ok: bool, *, required: bool = True, detail: str = ""):
    return {
        "name": name,
        "ok": bool(ok),
        "required": bool(required),
        "detail": detail,
    }


def _asset_checks(app) -> list[dict[str, Any]]:
    roots = [
        ("templates", Path(app.template_folder or ""), True),
        ("static", Path(app.static_folder or ""), True),
    ]
    package_root = Path(__file__).resolve().parents[1]
    roots.extend(
        [
            (
                "schema",
                package_root / "adapters" / "sqlite" / "schema.sql",
                True,
            ),
            (
                "clinical_schemas",
                package_root / "domain" / "clinical_engine" / "schemas",
                True,
            ),
            (
                "clinical_rule_artifacts",
                package_root
                / "domain"
                / "clinical_engine"
                / "rule_artifacts",
                True,
            ),
        ]
    )
    return [
        _check(f"asset:{name}", path.exists(), required=required)
        for name, path, required in roots
    ]


def _accounting_read_only_check(path_text: str) -> bool:
    try:
        path = Path(path_text).resolve()
    except (OSError, TypeError, ValueError):
        return False
    if not path.is_file():
        return False
    connection = None
    try:
        uri = f"file:{path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        present = {
            str(row[0])
            for row in connection.execute(
                """SELECT name FROM sqlite_master
                   WHERE type='table' AND name IN ('patients','invoices')"""
            ).fetchall()
        }
        try:
            connection.execute(
                "CREATE TABLE __release_write_probe (id INTEGER)"
            )
        except sqlite3.OperationalError:
            write_blocked = True
        else:
            write_blocked = False
        return present == {"patients", "invoices"} and write_blocked
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return False
    finally:
        if connection is not None:
            connection.close()


def run_preflight(app, *, host: str | None = None) -> dict[str, Any]:
    """Return non-PHI checks. Pending local first-run is a warning, not a crash."""
    checks: list[dict[str, Any]] = []
    database_path = Path(app.config["DATABASE_PATH"]).resolve()
    database_exists = database_path.is_file()
    checks.append(_check("database_exists", database_exists))
    try:
        database_integrity_ok = (
            database_exists and sqlite_integrity(database_path).lower() == "ok"
        )
    except (OSError, sqlite3.Error):
        database_integrity_ok = False
    checks.append(_check("database_integrity", database_integrity_ok))
    foreign_keys_ok = False
    if database_exists:
        try:
            connection = sqlite3.connect(str(database_path))
            try:
                foreign_keys_ok = (
                    connection.execute("PRAGMA foreign_key_check").fetchone()
                    is None
                )
            finally:
                connection.close()
        except (OSError, sqlite3.Error):
            foreign_keys_ok = False
    checks.append(_check("database_foreign_keys", foreign_keys_ok))
    checks.append(
        _check(
            "accounting_bridge_read_only",
            _accounting_read_only_check(app.config["ACCOUNTING_DB_PATH"]),
        )
    )
    checks.extend(_asset_checks(app))
    checks.append(
        _check("session_secret", is_strong_secret(app.config.get("SECRET_KEY")))
    )

    with app.app_context():
        setup_complete = not FirstRunService().setup_required()
    checks.append(
        _check(
            "first_run_complete",
            setup_complete,
            required=False,
            detail="local_setup_required" if not setup_complete else "",
        )
    )
    exposure_ok = True
    try:
        validate_server_exposure(
            host=host or app.config["HOST"],
            secret_key=app.config.get("SECRET_KEY"),
            setup_complete=setup_complete,
        )
    except RuntimeError:
        exposure_ok = False
    checks.append(_check("network_exposure", exposure_ok))

    required_ok = all(item["ok"] for item in checks if item["required"])
    return {
        "status": "pass" if required_ok else "fail",
        "required_ok": required_ok,
        "setup_complete": setup_complete,
        "checks": checks,
    }


def _create_accounting_fixture(path: Path) -> None:
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(
            """
            CREATE TABLE patients (
                id INTEGER PRIMARY KEY,
                full_name TEXT,
                national_id TEXT,
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
                patient_id INTEGER,
                status TEXT,
                work_date TEXT,
                opened_at TEXT,
                closed_at TEXT,
                total_amount INTEGER DEFAULT 0
            );
            CREATE TABLE visits (
                id INTEGER PRIMARY KEY, invoice_id INTEGER,
                patient_id INTEGER, price INTEGER DEFAULT 0
            );
            CREATE TABLE injections (
                id INTEGER PRIMARY KEY, invoice_id INTEGER,
                patient_id INTEGER, injection_type TEXT,
                total_price INTEGER DEFAULT 0
            );
            CREATE TABLE procedures (
                id INTEGER PRIMARY KEY, invoice_id INTEGER,
                patient_id INTEGER, procedure_type TEXT,
                price INTEGER DEFAULT 0
            );
            """
        )
        connection.commit()
    finally:
        connection.close()


def run_self_test() -> dict[str, Any]:
    """Exercise bootstrap, endpoints and backup round-trip in an isolated folder."""
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="specialist-self-test-") as folder:
        root = Path(folder)
        database = root / "specialist.db"
        accounting = root / "accounting.db"
        backup_folder = root / "backups"
        restored = root / "restored.db"
        _create_accounting_fixture(accounting)

        from src.app import create_app

        app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": str(database),
                "ACCOUNTING_DB_PATH": str(accounting),
                "BACKUP_FOLDER": str(backup_folder),
                "SECRET_KEY": "self-test-session-secret-" + ("x" * 48),
                "CREATE_TEST_ADMIN": True,
                "START_SCHEDULER": False,
                "CSRF_PROTECTION_ENABLED": False,
            }
        )
        client = app.test_client()
        checks.append(_check("live_endpoint", client.get("/health/live").status_code == 200))
        checks.append(_check("ready_endpoint", client.get("/health/ready").status_code == 200))
        checks.extend(_asset_checks(app))
        checks.append(
            _check(
                "accounting_bridge_read_only",
                _accounting_read_only_check(str(accounting)),
            )
        )

        backup = BackupIntegrityService().create(
            database, backup_folder, prefix="self_test", keep=1
        )
        BackupIntegrityService().restore(
            backup.database_path,
            restored,
            manifest_path=backup.manifest_path,
        )
        checks.append(
            _check(
                "backup_restore_round_trip",
                sqlite_integrity(restored).lower() == "ok",
            )
        )

    ok = all(item["ok"] for item in checks if item["required"])
    return {
        "status": "pass" if ok else "fail",
        "required_ok": ok,
        "checks": checks,
    }


__all__ = ["run_preflight", "run_self_test"]
