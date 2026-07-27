from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
S = ROOT / "specialist_clinic"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_once(path: Path, old: str, new: str) -> None:
    text = read(path)
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"A15 anchor missing in {path}: {old[:160]!r}")
    write(path, text.replace(old, new, 1))


write(
    S / "src/common/network_policy.py",
    r'''"""Fail-closed bind and bootstrap policy for local and clinic-LAN runtimes."""
from __future__ import annotations

from ipaddress import ip_address

from src.config.settings import DEFAULT_SECRET_KEY


_LOOPBACK_NAMES = frozenset({"localhost", "ip6-localhost"})


def is_loopback_bind(host: str | None) -> bool:
    value = str(host or "").strip().lower()
    if value in _LOOPBACK_NAMES:
        return True
    try:
        return ip_address(value).is_loopback
    except ValueError:
        return False


def strong_secret(value: str | None) -> bool:
    secret = str(value or "")
    return len(secret) >= 32 and secret != DEFAULT_SECRET_KEY


def strong_bootstrap_password(value: str | None) -> bool:
    password = str(value or "")
    return len(password) >= 12 and password.lower() != "admin"


def validate_runtime_security(
    *, host: str | None, secret_key: str | None, production: bool
) -> None:
    exposed = not is_loopback_bind(host)
    if (production or exposed) and not strong_secret(secret_key):
        raise RuntimeError(
            "LAN/production startup requires SECRET_KEY with at least 32 characters; "
            "the local fallback is forbidden outside loopback."
        )


__all__ = [
    "is_loopback_bind",
    "strong_bootstrap_password",
    "strong_secret",
    "validate_runtime_security",
]
''',
)

write(
    S / "src/services/release_ops.py",
    r'''"""Machine-readable release preflight, smoke, backup, verification and restore."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from typing import Any, Iterator

from src.common.network_policy import (
    is_loopback_bind,
    strong_bootstrap_password,
    validate_runtime_security,
)
from src.common.utils import iran_now
from src.config.settings import Config
from src.services.backup_integrity import BackupIntegrityService


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _integrity(path: Path) -> str:
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
        return str(row[0] if row else "missing")
    finally:
        connection.close()


def _asset_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def required_assets() -> dict[str, Path]:
    root = _asset_root()
    return {
        "templates": root / "src/templates",
        "static": root / "src/static",
        "schema": root / "src/adapters/sqlite/schema.sql",
        "clinical_schema": root / "src/domain/clinical_engine/schemas/clinical-rule.schema.json",
        "rule_artifacts": root / "src/domain/clinical_engine/rule_artifacts",
    }


def _accounting_read_only(path: Path) -> bool:
    if not path.is_file():
        return False
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        connection.execute("SELECT 1 FROM patients LIMIT 1").fetchall()
        try:
            connection.execute("CREATE TABLE __specialist_release_write_probe(id INTEGER)")
        except sqlite3.OperationalError:
            return True
        return False
    finally:
        connection.close()


def _needs_bootstrap(database: Path) -> bool:
    if not database.is_file():
        return True
    try:
        connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
        try:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
            ).fetchone()
            if not table:
                return True
            row = connection.execute("SELECT COUNT(*) FROM users").fetchone()
            return not row or int(row[0] or 0) == 0
        finally:
            connection.close()
    except sqlite3.Error:
        return True


def create_verified_backup(
    database_path: str | os.PathLike,
    backup_directory: str | os.PathLike,
    *,
    prefix: str = "backup_manual",
) -> dict[str, Any]:
    source_path = Path(database_path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"specialist database does not exist: {source_path}")
    destination_dir = Path(backup_directory).resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    now = iran_now()
    destination = destination_dir / f"{prefix}_{now.strftime('%Y%m%d_%H%M%S_%f')}.db"
    staging = destination.with_suffix(".db.tmp")
    manifest = destination.with_suffix(".manifest.json")
    manifest_staging = manifest.with_suffix(".json.tmp")
    try:
        source = sqlite3.connect(str(source_path), timeout=30)
        try:
            output = sqlite3.connect(str(staging), timeout=30)
            try:
                source.backup(output, pages=-1)
                output.commit()
            finally:
                output.close()
        finally:
            source.close()
        integrity = _integrity(staging)
        if integrity.lower() != "ok":
            raise RuntimeError(f"backup integrity failed: {integrity[:80]}")
        digest = _hash(staging)
        size = staging.stat().st_size
        os.replace(staging, destination)
        payload = {
            "schema_version": "1.0",
            "backup_file": destination.name,
            "sha256": digest,
            "size_bytes": size,
            "integrity_check": "ok",
            "created_at": now.isoformat(sep=" ", timespec="seconds"),
        }
        manifest_staging.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(manifest_staging, manifest)
        verified = BackupIntegrityService().verify(destination, manifest_path=manifest)
        return {
            "ok": True,
            "database": str(verified.database_path),
            "manifest": str(verified.manifest_path),
            "sha256": verified.sha256,
            "size_bytes": verified.size_bytes,
            "created_at": verified.created_at,
        }
    finally:
        staging.unlink(missing_ok=True)
        manifest_staging.unlink(missing_ok=True)


def verify_backup(database_path: str | os.PathLike) -> dict[str, Any]:
    verified = BackupIntegrityService().verify(database_path)
    return {
        "ok": True,
        "database": str(verified.database_path),
        "manifest": str(verified.manifest_path),
        "sha256": verified.sha256,
        "size_bytes": verified.size_bytes,
        "created_at": verified.created_at,
    }


def restore_backup(
    database_path: str | os.PathLike,
    destination_path: str | os.PathLike,
) -> dict[str, Any]:
    verified = BackupIntegrityService().restore(database_path, destination_path)
    return {
        "ok": True,
        "restored_to": str(Path(destination_path).resolve()),
        "source_sha256": verified.sha256,
        "source_created_at": verified.created_at,
    }


def _minimal_accounting_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE patients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                status TEXT DEFAULT 'open',
                total_amount REAL DEFAULT 0,
                work_date TEXT,
                closed_at TEXT,
                opened_at TEXT DEFAULT (datetime('now'))
            );
            INSERT INTO patients(full_name,national_id,phone_number)
            VALUES ('Release Smoke Patient','RELEASE-SMOKE-1','09000000000');
            """
        )
        connection.commit()
    finally:
        connection.close()


@contextmanager
def _isolated_app(*, specialist: Path, accounting: Path, backups: Path) -> Iterator[Any]:
    from src.adapters.sqlite import core
    from src.app import create_app

    previous = core._initialized
    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(specialist),
            "ACCOUNTING_DB_PATH": str(accounting),
            "BACKUP_FOLDER": str(backups),
            "SECRET_KEY": "release-self-test-secret-not-for-deployment",
            "HOST": "127.0.0.1",
        }
    )
    try:
        yield app
    finally:
        core._initialized = previous


def self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="specialist-release-smoke-") as raw:
        root = Path(raw)
        specialist = root / "specialist.db"
        accounting = root / "clinic_new.db"
        backups = root / "backups"
        restored = root / "restored.db"
        _minimal_accounting_database(accounting)
        accounting_before = _hash(accounting)
        checks: dict[str, bool] = {}
        with _isolated_app(
            specialist=specialist,
            accounting=accounting,
            backups=backups,
        ) as app:
            client = app.test_client()
            checks["live"] = client.get("/health/live").status_code == 200
            ready = client.get("/health/ready")
            checks["ready"] = ready.status_code == 200 and ready.get_json() == {
                "status": "ready"
            }
            checks["login_surface"] = client.get("/auth/login").status_code == 200
        backup = create_verified_backup(specialist, backups, prefix="backup_smoke")
        checks["backup_verified"] = bool(backup["ok"])
        restored_result = restore_backup(backup["database"], restored)
        checks["restore_integrity"] = (
            restored_result["ok"] and _integrity(restored).lower() == "ok"
        )
        checks["accounting_read_only"] = _accounting_read_only(accounting)
        checks["accounting_unchanged"] = accounting_before == _hash(accounting)
        assets = required_assets()
        checks["bundled_assets"] = all(path.exists() for path in assets.values())
        return {
            "ok": all(checks.values()),
            "checks": checks,
            "test_count": len(checks),
        }


def preflight() -> dict[str, Any]:
    specialist = Path(Config.DATABASE_PATH).resolve()
    accounting = Path(Config.ACCOUNTING_DB_PATH).resolve()
    backups = Path(Config.BACKUP_FOLDER).resolve()
    checks: dict[str, bool] = {}
    errors: list[str] = []
    try:
        validate_runtime_security(
            host=Config.HOST,
            secret_key=Config.SECRET_KEY,
            production=Config.PRODUCTION,
        )
        checks["bind_security"] = True
    except RuntimeError as exc:
        checks["bind_security"] = False
        errors.append(str(exc))
    if (
        not is_loopback_bind(Config.HOST)
        and _needs_bootstrap(specialist)
        and not strong_bootstrap_password(
            os.environ.get("CLINIC_BOOTSTRAP_ADMIN_PASSWORD")
        )
    ):
        checks["bootstrap_admin"] = False
        errors.append(
            "Fresh LAN database requires CLINIC_BOOTSTRAP_ADMIN_PASSWORD with at least 12 characters."
        )
    else:
        checks["bootstrap_admin"] = True
    checks["accounting_exists"] = accounting.is_file()
    checks["accounting_read_only"] = (
        _accounting_read_only(accounting) if accounting.is_file() else False
    )
    checks["bundled_assets"] = all(path.exists() for path in required_assets().values())
    if all((checks["bind_security"], checks["bootstrap_admin"], checks["accounting_read_only"])):
        try:
            from src.adapters.sqlite import core
            from src.app import create_app

            previous = core._initialized
            core._initialized = False
            app = create_app(
                {
                    "TESTING": True,
                    "DATABASE_PATH": str(specialist),
                    "ACCOUNTING_DB_PATH": str(accounting),
                    "BACKUP_FOLDER": str(backups),
                    "SECRET_KEY": Config.SECRET_KEY,
                    "HOST": Config.HOST,
                }
            )
            try:
                client = app.test_client()
                checks["live"] = client.get("/health/live").status_code == 200
                checks["ready"] = client.get("/health/ready").status_code == 200
            finally:
                core._initialized = previous
        except Exception as exc:
            checks["live"] = False
            checks["ready"] = False
            errors.append(f"startup/readiness failed: {type(exc).__name__}: {exc}")
    else:
        checks["live"] = False
        checks["ready"] = False
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "errors": errors,
        "host": Config.HOST,
        "port": Config.PORT,
        "specialist_database": str(specialist),
        "accounting_database": str(accounting),
        "backup_directory": str(backups),
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }


__all__ = [
    "create_verified_backup",
    "preflight",
    "required_assets",
    "restore_backup",
    "self_test",
    "verify_backup",
]
''',
)

# Config receives explicit safe bind and server controls.
settings = S / "src/config/settings.py"
replace_once(
    settings,
    "def _env_flag(name: str) -> bool:\n    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')\n",
    "def _env_flag(name: str) -> bool:\n    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')\n\n\ndef _env_int(name: str, default: int, minimum: int, maximum: int) -> int:\n    try:\n        value = int(os.environ.get(name, default))\n    except (TypeError, ValueError):\n        value = default\n    return min(max(value, minimum), maximum)\n",
)
replace_once(
    settings,
    "    # Network\n    PORT = int(os.environ.get('PORT', 8090))\n\n    DEBUG = _env_flag('DEBUG')\n",
    "    # Network. Loopback is the default; LAN exposure must be explicit.\n    HOST = (os.environ.get('CLINIC_BIND_HOST') or '127.0.0.1').strip()\n    PORT = _env_int('PORT', 8090, 1, 65535)\n    SERVER_THREADS = _env_int('CLINIC_SERVER_THREADS', 8, 2, 64)\n    OPEN_BROWSER = os.environ.get('CLINIC_OPEN_BROWSER', '1').strip().lower() in (\n        '1', 'true', 'yes', 'on'\n    )\n\n    DEBUG = _env_flag('DEBUG')\n",
)

# App factory validates any non-test exposed runtime and fixes status keys.
app_path = S / "src/app.py"
replace_once(
    app_path,
    "from src.config.settings import Config, DEFAULT_SECRET_KEY\n",
    "from src.config.settings import Config\nfrom src.common.network_policy import validate_runtime_security\n",
)
replace_once(
    app_path,
    '''    if app.config.get("PRODUCTION") and not app.config.get("TESTING", False):
        if app.config.get("SECRET_KEY") in (None, DEFAULT_SECRET_KEY):
            raise RuntimeError(
                "PRODUCTION=1 but SECRET_KEY is unset or the insecure default. "
                "Set a strong SECRET_KEY before production startup."
            )
''',
    '''    if not app.config.get("TESTING", False):
        validate_runtime_security(
            host=app.config.get("HOST"),
            secret_key=app.config.get("SECRET_KEY"),
            production=bool(app.config.get("PRODUCTION")),
        )
''',
)
replace_once(
    app_path,
    '            "clinical_approval": state.get_json("mapproval_clinical"),\n            "technical_approval": state.get_json("mapproval_technical"),\n',
    '            "clinical_approval": state.get_json("approval_clinical"),\n            "technical_approval": state.get_json("approval_technical"),\n',
)

# Fresh LAN installs cannot silently create admin/admin.
core_path = S / "src/adapters/sqlite/core.py"
replace_once(
    core_path,
    '    production = bool(current_app.config.get("PRODUCTION")) and not bool(\n        current_app.config.get("TESTING", False)\n    )\n',
    '    from src.common.network_policy import (\n        is_loopback_bind, strong_bootstrap_password,\n    )\n\n    production = bool(current_app.config.get("PRODUCTION")) and not bool(\n        current_app.config.get("TESTING", False)\n    )\n    exposed = not is_loopback_bind(current_app.config.get("HOST"))\n',
)
replace_once(
    core_path,
    '    if production and (len(password) < 12 or password == "admin"):\n        raise RuntimeError(\n            "Production bootstrap requires CLINIC_BOOTSTRAP_ADMIN_PASSWORD "\n            "with at least 12 characters; admin/admin is forbidden."\n        )\n',
    '    if (production or exposed) and not strong_bootstrap_password(password):\n        raise RuntimeError(\n            "LAN/production bootstrap requires CLINIC_BOOTSTRAP_ADMIN_PASSWORD "\n            "with at least 12 characters; admin/admin is forbidden."\n        )\n',
)

# Readiness includes the accounting read-only boundary.
health_path = S / "src/api/health.py"
replace_once(
    health_path,
    "from src.adapters.sqlite.core import get_db\n",
    "from src.adapters.sqlite.core import get_db\nfrom src.adapters import accounting_bridge\n",
)
replace_once(
    health_path,
    '    integrity_ok = bool(quick and str(quick[0]).lower() == "ok")\n',
    '    integrity_ok = bool(quick and str(quick[0]).lower() == "ok")\n    accounting_bridge_ok = accounting_bridge.is_available()\n',
)
replace_once(
    health_path,
    '        "database": integrity_ok,\n        "schema": schema_ok,\n',
    '        "database": integrity_ok,\n        "accounting_bridge": accounting_bridge_ok,\n        "schema": schema_ok,\n',
)
# Both fallback dictionaries.
health_text = read(health_path)
health_text = health_text.replace(
    '            "database": False,\n            "schema": False,\n',
    '            "database": False,\n            "accounting_bridge": False,\n            "schema": False,\n',
)
write(health_path, health_text)

# Safe Waitress launcher and release CLI.
write(
    S / "start.py",
    r'''from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import threading

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
    sys.path.insert(0, BASE_DIR)
    if hasattr(sys, "_MEIPASS"):
        sys.path.insert(0, sys._MEIPASS)
else:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    sys.path.insert(0, BASE_DIR)


def _emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("ok") else 1


def _serve() -> int:
    from waitress import serve
    from src.app import create_app, open_browser
    from src.common.network_policy import is_loopback_bind
    from src.config.settings import Config

    app = create_app()
    if Config.OPEN_BROWSER and is_loopback_bind(Config.HOST):
        threading.Timer(1.5, open_browser).start()
    print(f"Specialist Clinic listening on http://{Config.HOST}:{Config.PORT}")
    serve(
        app,
        host=Config.HOST,
        port=Config.PORT,
        threads=Config.SERVER_THREADS,
        channel_timeout=120,
        cleanup_interval=30,
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="SpecialistClinic")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="Run the clinic server (default).")
    sub.add_parser("preflight", help="Validate configured databases, bind policy and readiness.")
    sub.add_parser("self-test", help="Run an isolated release smoke test.")
    backup = sub.add_parser("backup", help="Create and verify a manual online backup.")
    backup.add_argument("--directory")
    verify = sub.add_parser("verify-backup", help="Verify a backup and its manifest.")
    verify.add_argument("backup")
    restore = sub.add_parser("restore-backup", help="Verify and atomically restore a backup while the server is stopped.")
    restore.add_argument("backup")
    restore.add_argument("--destination")
    restore.add_argument("--confirm", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command = args.command or "serve"
    if command == "serve":
        return _serve()
    from src.config.settings import Config
    from src.services.release_ops import (
        create_verified_backup,
        preflight,
        restore_backup,
        self_test,
        verify_backup,
    )
    try:
        if command == "preflight":
            return _emit(preflight())
        if command == "self-test":
            return _emit(self_test())
        if command == "backup":
            directory = args.directory or Config.BACKUP_FOLDER
            return _emit(create_verified_backup(Config.DATABASE_PATH, directory))
        if command == "verify-backup":
            return _emit(verify_backup(args.backup))
        if command == "restore-backup":
            if args.confirm != "RESTORE":
                return _emit({"ok": False, "error": "--confirm RESTORE is required"})
            destination = args.destination or Config.DATABASE_PATH
            return _emit(restore_backup(args.backup, destination))
    except Exception as exc:
        return _emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return _emit({"ok": False, "error": f"unknown command: {command}"})


if __name__ == "__main__":
    raise SystemExit(main())
''',
)

# Runtime dependency.
requirements = S / "requirements.txt"
text = read(requirements)
if "waitress" not in text.lower():
    text = text.rstrip() + "\nwaitress>=3.0,<4  # production-grade local/LAN WSGI server\n"
write(requirements, text)

write(
    S / "requirements-build.txt",
    "-r requirements.txt\npyinstaller>=6.14,<7\n",
)

write(
    S / "SpecialistClinic.spec",
    r'''# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("segno") + collect_submodules("jsonschema")
datas = [
    ("src/templates", "src/templates"),
    ("src/static", "src/static"),
    ("src/adapters/sqlite/schema.sql", "src/adapters/sqlite"),
    ("src/domain/clinical_engine/schemas", "src/domain/clinical_engine/schemas"),
    ("src/domain/clinical_engine/rule_artifacts", "src/domain/clinical_engine/rule_artifacts"),
]

a = Analysis(
    ["start.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SpecialistClinic",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
)
''',
)

write(
    S / "scripts/build_release.ps1",
    r'''param(
    [switch]$SkipInstall,
    [switch]$SkipTests
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    python -m venv .venv
}
if (-not $SkipInstall) {
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r requirements-build.txt pytest
}
if (-not $SkipTests) {
    & $Python -m pytest tests -q --tb=short
}
Remove-Item -Recurse -Force build, dist, release -ErrorAction SilentlyContinue
& $Python -m PyInstaller --noconfirm --clean SpecialistClinic.spec
$Exe = Join-Path $Root "dist\SpecialistClinic.exe"
if (-not (Test-Path $Exe)) { throw "SpecialistClinic.exe was not created" }
& $Exe self-test
if ($LASTEXITCODE -ne 0) { throw "Frozen self-test failed" }
$Stage = Join-Path $Root "release\SpecialistClinic"
New-Item -ItemType Directory -Force $Stage | Out-Null
Copy-Item $Exe $Stage
Copy-Item "release.env.example.ps1" $Stage
Copy-Item "docs\release_runbook.md" $Stage
Copy-Item "docs\deploy_checklist.md" $Stage
$Zip = Join-Path $Root "release\SpecialistClinic-Windows-x64.zip"
Compress-Archive -Path "$Stage\*" -DestinationPath $Zip -Force
$Hash = (Get-FileHash $Zip -Algorithm SHA256).Hash.ToLowerInvariant()
"$Hash  SpecialistClinic-Windows-x64.zip" | Set-Content "$Zip.sha256" -Encoding ascii
Write-Host "Release: $Zip"
Write-Host "SHA256: $Hash"
''',
)

write(
    S / "release.env.example.ps1",
    r'''# Copy this file to release.env.ps1, edit values, then dot-source it:
#   . .\release.env.ps1
$env:SPECIALIST_DB_PATH = "$PSScriptRoot\specialist.db"
$env:ACCOUNTING_DB_PATH = "C:\ClinicAccounting\clinic_new.db"
$env:SECRET_KEY = "replace-with-at-least-32-random-characters"
$env:CLINIC_BIND_HOST = "127.0.0.1"  # For LAN use 0.0.0.0 only after setting strong secrets below.
$env:PORT = "8090"
$env:CLINIC_OPEN_BROWSER = "1"
$env:CLINIC_SERVER_THREADS = "8"
$env:CLINIC_BOOTSTRAP_ADMIN_USERNAME = "admin"
$env:CLINIC_BOOTSTRAP_ADMIN_PASSWORD = "replace-with-at-least-12-characters"
# Leave PRODUCTION unset for an in-clinic HTTP LAN. Set PRODUCTION=1 only behind HTTPS.
''',
)

write(
    S / ".github-placeholder",
    "temporary marker",
)
(S / ".github-placeholder").unlink(missing_ok=True)

write(
    ROOT / ".github/workflows/specialist-release.yml",
    r'''name: Specialist Windows Release

on:
  pull_request:
    paths:
      - "specialist_clinic/**"
      - ".github/workflows/specialist-release.yml"
  workflow_dispatch:
  push:
    tags:
      - "specialist-v*"

concurrency:
  group: specialist-release-${{ github.head_ref || github.ref_name }}
  cancel-in-progress: true

jobs:
  windows-release:
    runs-on: windows-latest
    defaults:
      run:
        working-directory: specialist_clinic
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
          cache: pip
          cache-dependency-path: |
            specialist_clinic/requirements.txt
            specialist_clinic/requirements-build.txt
      - name: Install build dependencies
        run: python -m pip install -r requirements-build.txt pytest
      - name: Run release-readiness tests
        run: python -m pytest tests -q --tb=short
      - name: Build, frozen-smoke and package
        shell: powershell
        run: .\scripts\build_release.ps1 -SkipInstall -SkipTests
      - name: Upload Windows release
        uses: actions/upload-artifact@v4
        with:
          name: SpecialistClinic-Windows-x64
          path: |
            specialist_clinic/release/SpecialistClinic-Windows-x64.zip
            specialist_clinic/release/SpecialistClinic-Windows-x64.zip.sha256
          if-no-files-found: error
          retention-days: 14
''',
)

write(
    S / "docs/release_runbook.md",
    r'''# راهنمای انتشار و اجرای نهایی Specialist Clinic

## ۱. اجرای امن روی همان کامپیوتر

```powershell
cd specialist_clinic
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:ACCOUNTING_DB_PATH = "C:\مسیر\clinic_new.db"
.\.venv\Scripts\python.exe start.py preflight
.\.venv\Scripts\python.exe start.py serve
```

حالت پیش‌فرض فقط روی `127.0.0.1:8090` گوش می‌دهد.

## ۲. اجرای LAN

```powershell
$env:CLINIC_BIND_HOST = "0.0.0.0"
$env:SECRET_KEY = "یک-رشته-تصادفی-حداقل-۳۲-کاراکتری"
$env:CLINIC_BOOTSTRAP_ADMIN_PASSWORD = "رمز-اولیه-حداقل-۱۲-کاراکتری"
.\SpecialistClinic.exe preflight
.\SpecialistClinic.exe serve
```

Windows Firewall باید فقط پورت 8090 را برای شبکهٔ Private درمانگاه باز کند. برای اینترنت/VPS، `PRODUCTION=1` فقط پشت HTTPS مجاز است.

## ۳. تست مستقل release

```powershell
.\SpecialistClinic.exe self-test
```

این تست از دیتابیس‌های موقت استفاده می‌کند، health/readiness، دارایی‌های bundle، پل read-only حسابداری و backup/restore را بررسی می‌کند و هیچ دادهٔ واقعی را تغییر نمی‌دهد.

## ۴. بک‌آپ دستی

```powershell
.\SpecialistClinic.exe backup
.\SpecialistClinic.exe verify-backup .\backups\backup_manual_....db
```

هر بک‌آپ یک فایل DB و manifest هم‌نام با SHA-256 و integrity check دارد.

## ۵. Restore

ابتدا برنامه را کاملاً ببندید و از DB فعلی یک کپی جدا بگیرید:

```powershell
.\SpecialistClinic.exe restore-backup .\backups\backup_manual_....db `
  --destination .\specialist.db --confirm RESTORE
```

Restore ابتدا منبع و staging را تأیید و سپس با `os.replace` جایگزین می‌کند. در صورت بازبودن DB روی Windows، عملیات باید fail شود؛ برنامه را نباید هم‌زمان اجرا کرد.

## ۶. Build ویندوز

```powershell
cd specialist_clinic
powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

خروجی‌ها:

- `release\SpecialistClinic-Windows-x64.zip`
- `release\SpecialistClinic-Windows-x64.zip.sha256`

build فقط زمانی بسته‌بندی می‌شود که full test suite و self-test فایل exe پاس شوند.

## ۷. چک نهایی

- `preflight` باید `ok: true` بدهد.
- `/health/live` باید 200 باشد.
- `/health/ready` باید `ready` باشد.
- DB حسابداری فقط با `mode=ro` باز می‌شود.
- روی نصب تازهٔ LAN، `admin/admin` ممنوع است.
- موتور بالینی تا review/validation/pilot واقعی در حالت off باقی می‌ماند.
''',
)

write(
    S / "docs/deploy_checklist.md",
    r'''# چک‌لیست انتشار نهایی Specialist Clinic

## پیش از build

- [ ] `python -m pytest tests -q` بدون failure پاس شده است.
- [ ] `ACCOUNTING_DB_PATH` به فایل واقعی و فقط‌خواندنی `clinic_new.db` اشاره می‌کند.
- [ ] برای LAN، `SECRET_KEY` حداقل ۳۲ و bootstrap password حداقل ۱۲ کاراکتر است.
- [ ] موتور بالینی بدون تأیید واقعی پزشک فعال نشده است.

## build

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

- [ ] ZIP و فایل SHA-256 ساخته شده‌اند.
- [ ] frozen `self-test` داخل build پاس شده است.
- [ ] hash فایل تحویلی با `.sha256` برابر است.

## پیش از جایگزینی نسخهٔ درمانگاه

- [ ] برنامهٔ قبلی بسته شده است.
- [ ] `SpecialistClinic.exe backup` اجرا و سپس `verify-backup` پاس شده است.
- [ ] exe قبلی برای rollback نگه داشته شده است.
- [ ] فایل env واقعی خارج از Git نگه‌داری می‌شود.

## پس از نصب

- [ ] `SpecialistClinic.exe preflight` مقدار `ok: true` می‌دهد.
- [ ] login، dashboard، صف پزشک و یک Encounter آزمایشی سالم‌اند.
- [ ] `/health/live` و `/health/ready` سبز هستند.
- [ ] hash دیتابیس حسابداری قبل و بعد یکسان است.
- [ ] بعد از ۲۰ ثانیه scheduler خطایی در `specialist_errors.log` ثبت نکرده است.
- [ ] از یک کامپیوتر دوم LAN فقط در صورت فعال‌سازی آگاهانهٔ bind، صفحه باز می‌شود.

## rollback

- [ ] برنامه را ببندید.
- [ ] exe قبلی را برگردانید؛ schema additive است.
- [ ] در صورت نیاز فقط از backup تأییدشده و فرمان `restore-backup --confirm RESTORE` استفاده کنید.
- [ ] audit و تاریخچهٔ بالینی حذف نشوند.
''',
)

write(
    S / "README.md",
    r'''# کلینیک تخصصی (Specialist Clinic)

سامانهٔ مدیریت بیماری‌های مزمن، پروندهٔ تخصصی، صف پزشک، مراقبت پیوسته، پیامک governشده و Clinical Engine v2؛ مستقل از حسابداری و متصل به آن فقط با SQLite `mode=ro`.

## وضعیت کیفیت

- full Specialist Clinic suite و Accounting suite در CI اجرا می‌شوند.
- build ویندوز فقط بعد از تست کامل و frozen self-test تولید می‌شود.
- موتور بالینی بدون Rule review دوگانه، validation، pilot و seal معتبر قابل نمایش نیست.

## اجرای توسعه/لوکال

```powershell
cd specialist_clinic
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:ACCOUNTING_DB_PATH = "C:\مسیر\clinic_new.db"
.\.venv\Scripts\python.exe start.py preflight
.\.venv\Scripts\python.exe start.py serve
```

آدرس پیش‌فرض: `http://127.0.0.1:8090`

در اجرای فقط‌لوکال و دیتابیس تازه، حساب توسعه `admin/admin` ساخته می‌شود و باید فوراً تغییر کند. در LAN یا production، این credential ممنوع است و bootstrap password امن الزامی است.

## ابزارهای عملیاتی

```powershell
.\.venv\Scripts\python.exe start.py self-test
.\.venv\Scripts\python.exe start.py backup
.\.venv\Scripts\python.exe start.py verify-backup .\backups\backup_manual_....db
.\.venv\Scripts\python.exe start.py restore-backup .\backups\backup_manual_....db --confirm RESTORE
```

## LAN

LAN به‌صورت پیش‌فرض خاموش است. برای فعال‌سازی آگاهانه:

```powershell
$env:CLINIC_BIND_HOST = "0.0.0.0"
$env:SECRET_KEY = "حداقل-۳۲-کاراکتر-تصادفی"
$env:CLINIC_BOOTSTRAP_ADMIN_PASSWORD = "حداقل-۱۲-کاراکتر"
```

سپس `preflight` را اجرا کنید. جزئیات در [`docs/release_runbook.md`](docs/release_runbook.md) آمده است.

## ساخت نسخهٔ ویندوز

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

خروجی ZIP و SHA-256 در پوشهٔ `release` ساخته می‌شوند. همان فرایند در GitHub Actions روی `windows-latest` اجرا می‌شود.

## معماری داده

```text
clinic_new.db (Accounting, read-only) ──► Specialist Clinic ──► specialist.db
```

- لایه‌ها: `api/ → services/ → adapters/sqlite/`
- حسابداری هرگز از این برنامه نوشته نمی‌شود.
- backup از SQLite online backup + integrity check + manifest SHA-256 استفاده می‌کند.
- `/health/live` و `/health/ready` خروجی عمومی و بدون PHI دارند.

## Clinical Engine v2

چرخهٔ مجاز `off/shadow → on_selected → on` است. Ruleهای bundled به‌تنهایی مجوز استفادهٔ بالینی نیستند. review مستقل بالینی/فنی، golden-case validation، pilot محدود و seal دقیق برای rollout لازم‌اند.
''',
)

# Tests.
write(
    S / "tests/test_release_readiness_a15.py",
    r'''from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.network_policy import (
    is_loopback_bind,
    validate_runtime_security,
)
from src.config.settings import DEFAULT_SECRET_KEY
from src.services.release_ops import (
    create_verified_backup,
    restore_backup,
    self_test,
    verify_backup,
)


def test_default_bind_is_loopback_and_exposed_default_secret_is_rejected():
    assert is_loopback_bind("127.0.0.1")
    assert is_loopback_bind("::1")
    assert not is_loopback_bind("0.0.0.0")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        validate_runtime_security(
            host="0.0.0.0",
            secret_key=DEFAULT_SECRET_KEY,
            production=False,
        )
    validate_runtime_security(
        host="0.0.0.0",
        secret_key="x" * 32,
        production=False,
    )


def test_release_self_test_is_isolated_and_complete():
    result = self_test()
    assert result["ok"] is True, result
    assert result["test_count"] >= 8
    assert all(result["checks"].values())


def test_manual_backup_verify_and_restore_roundtrip(tmp_path):
    source = tmp_path / "source.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)")
    connection.execute("INSERT INTO sample(value) VALUES ('kept')")
    connection.commit()
    connection.close()

    backup = create_verified_backup(source, tmp_path / "backups")
    verified = verify_backup(backup["database"])
    restored = tmp_path / "restored.db"
    result = restore_backup(backup["database"], restored)
    assert verified["sha256"] == backup["sha256"]
    assert result["ok"] is True
    connection = sqlite3.connect(restored)
    try:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "kept"
    finally:
        connection.close()


def test_status_cli_reads_real_activation_approval_keys(tmp_path):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.clinical_engine_activation_repo import (
        ClinicalEngineActivationRepository,
    )
    from src.app import create_app

    previous = core._initialized
    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "status.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "release-status-test",
        }
    )
    try:
        with app.app_context():
            state = ClinicalEngineActivationRepository()
            state.put_json("approval_clinical", {"report_hash": "clinical"})
            state.put_json("approval_technical", {"report_hash": "technical"})
        result = app.test_cli_runner().invoke(
            args=["clinical-v2", "status", "--format", "json"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["clinical_approval"]["report_hash"] == "clinical"
        assert payload["technical_approval"]["report_hash"] == "technical"
    finally:
        core._initialized = previous


def test_health_readiness_reports_accounting_bridge(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    accounting = tmp_path / "accounting.db"
    connection = sqlite3.connect(accounting)
    connection.execute("CREATE TABLE patients(id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()
    previous = core._initialized
    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "specialist.db"),
            "ACCOUNTING_DB_PATH": str(accounting),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "health-accounting-test",
        }
    )
    try:
        with app.app_context():
            from src.api.health import _readiness_checks
            checks = _readiness_checks()
        assert checks["accounting_bridge"] is True
    finally:
        core._initialized = previous


def test_release_workflow_and_spec_are_committed():
    assert (ROOT / "SpecialistClinic.spec").is_file()
    assert (ROOT / "scripts/build_release.ps1").is_file()
    assert (ROOT.parent / ".github/workflows/specialist-release.yml").is_file()
''',
)

# Existing health test gains the new explicit check.
health_test = S / "tests/test_operational_security_hardening.py"
replace_once(
    health_test,
    '        "database",\n        "schema",\n',
    '        "database",\n        "accounting_bridge",\n        "schema",\n',
)

print("A15 release-readiness finalizer applied")
