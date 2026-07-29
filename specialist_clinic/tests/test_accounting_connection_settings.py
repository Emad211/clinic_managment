from __future__ import annotations

import hashlib
from pathlib import Path
import re
import sqlite3

import pytest


_TOKEN = re.compile(r'name="_csrf_token" value="([^"]+)"')


def _token(response) -> str:
    match = _TOKEN.search(response.get_data(as_text=True))
    assert match
    return match.group(1)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def accounting_settings_app(tmp_path, monkeypatch):
    from src.adapters.sqlite import core
    from src.app import create_app
    from src.services.release_ops import _create_accounting_fixture

    monkeypatch.delenv("ACCOUNTING_DB_PATH", raising=False)
    accounting = tmp_path / "accounting" / "clinic_new.db"
    accounting.parent.mkdir()
    _create_accounting_fixture(accounting)
    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "CSRF_PROTECTION_ENABLED": True,
            "DATABASE_PATH": str(tmp_path / "specialist.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "ACCOUNTING_DB_PATH": str(tmp_path / "missing.db"),
            "SECRET_KEY": "accounting-settings-test-secret",
            "START_SCHEDULER": False,
        }
    )
    context = app.app_context()
    context.push()
    yield app, accounting, tmp_path
    context.pop()
    core._initialized = False


def _login(client):
    page = client.get("/auth/login")
    response = client.post(
        "/auth/login",
        data={
            "username": "admin",
            "password": "admin",
            "_csrf_token": _token(page),
        },
    )
    assert response.status_code in {302, 303}


def test_saved_path_becomes_live_active_read_only_connection(
    accounting_settings_app,
):
    app, accounting, _tmp_path = accounting_settings_app
    from src.adapters import accounting_bridge
    from src.adapters import specialist_accounting_invoice_reader
    from src.adapters.accounting_path import accounting_db_path
    from src.adapters.sqlite.system_settings_repo import SystemSettingsRepository
    from src.services.accounting_connection_service import (
        AccountingConnectionService,
    )

    before = _sha256(accounting)
    result = AccountingConnectionService().save(str(accounting))

    assert result.ok is True
    assert result.path == str(accounting.resolve())
    assert result.source == "saved"
    assert SystemSettingsRepository().get("accounting_db_path") == result.path
    assert accounting_db_path() == result.path
    assert accounting_bridge.is_available() is True
    assert specialist_accounting_invoice_reader.is_available() is True
    assert _sha256(accounting) == before
    assert app.config["ACCOUNTING_DB_PATH"] == result.path


def test_folder_and_executable_inputs_resolve_to_neighbor_database(
    accounting_settings_app,
):
    _app, accounting, _tmp_path = accounting_settings_app
    from src.services.accounting_connection_service import (
        AccountingConnectionService,
    )

    executable = accounting.with_name("HesabdariSib.exe")
    executable.write_bytes(b"test executable marker")
    service = AccountingConnectionService()

    assert service.validate(str(accounting.parent)).path == str(accounting.resolve())
    assert service.validate(str(executable)).path == str(accounting.resolve())


def test_real_hesabdari_sib_split_name_schema_is_normalized(
    accounting_settings_app,
):
    _app, accounting, _tmp_path = accounting_settings_app
    from src.adapters import accounting_bridge
    from src.services.accounting_connection_service import (
        AccountingConnectionService,
    )

    connection = sqlite3.connect(str(accounting))
    connection.execute("ALTER TABLE patients RENAME COLUMN full_name TO name")
    connection.execute("ALTER TABLE patients ADD COLUMN family_name TEXT")
    connection.execute(
        """INSERT INTO patients
           (id,name,family_name,national_id,phone_number,gender,birthdate,
            address,insurance_type,insurance_expiry,is_foreign)
           VALUES (1,'علی','احمدی','0012345678','09120000000','male',
                   '1980-01-01','','تأمین اجتماعی','2027-01-01',0)"""
    )
    connection.commit()
    connection.close()

    before = _sha256(accounting)
    AccountingConnectionService().save(str(accounting))
    rows = accounting_bridge.search_patients("احمدی")
    assert len(rows) == 1
    assert rows[0]["full_name"] == "علی احمدی"
    assert accounting_bridge.get_patient_by_id(1)["full_name"] == "علی احمدی"
    assert _sha256(accounting) == before


def test_invalid_database_is_rejected_without_replacing_saved_path(
    accounting_settings_app,
):
    _app, accounting, tmp_path = accounting_settings_app
    from src.adapters.sqlite.system_settings_repo import SystemSettingsRepository
    from src.services.accounting_connection_service import (
        AccountingConnectionError,
        AccountingConnectionService,
    )

    service = AccountingConnectionService()
    saved = service.save(str(accounting)).path
    invalid = tmp_path / "not-accounting.db"
    invalid.write_text("not sqlite", encoding="utf-8")

    with pytest.raises(AccountingConnectionError, match="SQLite"):
        service.save(str(invalid))
    assert SystemSettingsRepository().get("accounting_db_path") == saved


def test_environment_override_is_visible_and_cannot_be_replaced(
    accounting_settings_app,
    monkeypatch,
):
    _app, accounting, tmp_path = accounting_settings_app
    from src.adapters.accounting_path import accounting_db_path
    from src.services.accounting_connection_service import (
        AccountingConnectionError,
        AccountingConnectionService,
    )

    monkeypatch.setenv("ACCOUNTING_DB_PATH", str(accounting))
    service = AccountingConnectionService()
    status = service.status()
    assert status.ok is True
    assert status.source == "environment"
    assert accounting_db_path() == str(accounting)
    with pytest.raises(AccountingConnectionError, match="قفل"):
        service.save(str(tmp_path / "other.db"))


def test_discovery_prefers_hesabdari_sib_dist_layout(accounting_settings_app):
    _app, _accounting, tmp_path = accounting_settings_app
    from src.services.accounting_connection_service import (
        AccountingConnectionService,
    )
    from src.services.release_ops import _create_accounting_fixture

    discovered = tmp_path / "deployment" / "webapp" / "dist" / "clinic_new.db"
    discovered.parent.mkdir(parents=True)
    _create_accounting_fixture(discovered)

    result = AccountingConnectionService().discover([tmp_path / "deployment"])
    assert result.ok is True
    assert result.path == str(discovered.resolve())


def test_manager_can_save_connection_from_settings_ui(accounting_settings_app):
    _app, accounting, _tmp_path = accounting_settings_app
    client = _app.test_client()
    _login(client)
    page = client.get("/manager/settings")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "اتصال به حسابداری سیب" in html
    assert "ذخیره و بررسی اتصال" in html

    response = client.post(
        "/manager/settings/accounting",
        data={
            "_csrf_token": _token(page),
            "action": "save",
            "accounting_db_path": str(accounting),
        },
        follow_redirects=True,
    )
    rendered = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "اتصال برقرار است" in rendered
    assert "اتصال فقط‌خواندنی فعال شد" in rendered
    assert str(accounting.resolve()) in rendered


def test_readiness_fails_closed_when_accounting_is_unavailable(
    accounting_settings_app,
):
    _app, accounting, _tmp_path = accounting_settings_app
    from src.api.health import _readiness_checks
    from src.services.accounting_connection_service import (
        AccountingConnectionService,
    )

    assert _readiness_checks()["accounting_bridge"] is False
    AccountingConnectionService().save(str(accounting))
    assert _readiness_checks()["accounting_bridge"] is True
