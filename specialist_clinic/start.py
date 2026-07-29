"""Specialist Clinic production entrypoint and release-operations CLI."""
from __future__ import annotations

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

from src.config.settings import Config
from src.services.backup_integrity import BackupIntegrityService


def _print(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="SpecialistClinic")
    commands = parser.add_subparsers(dest="command")

    serve = commands.add_parser("serve", help="Run the application with Waitress")
    serve.add_argument("--host", default=Config.HOST)
    serve.add_argument("--port", type=int, default=Config.PORT)
    serve.add_argument("--no-browser", action="store_true")

    commands.add_parser("preflight", help="Validate the current installation")
    commands.add_parser("self-test", help="Run an isolated release smoke test")

    backup = commands.add_parser("backup", help="Create a verified online backup")
    backup.add_argument("--output-dir", default=Config.BACKUP_FOLDER)

    verify = commands.add_parser("verify-backup", help="Verify backup + manifest")
    verify.add_argument("backup")
    verify.add_argument("--manifest")

    restore = commands.add_parser(
        "restore-backup", help="Verify and atomically restore a backup"
    )
    restore.add_argument("backup")
    restore.add_argument("--manifest")
    restore.add_argument(
        "--confirm",
        required=True,
        help="Must exactly equal RESTORE-SPECIALIST-DATABASE",
    )
    return parser


def _create_runtime_app():
    from src.app import create_app

    return create_app({"START_SCHEDULER": False})


def _serve(args) -> int:
    from src.app import create_app, open_browser
    from src.common.network_policy import validate_server_exposure
    from src.services.first_run_service import FirstRunService
    from src.services.release_ops import run_preflight

    app = create_app({"START_SCHEDULER": False})
    with app.app_context():
        setup_complete = not FirstRunService().setup_required()
    validate_server_exposure(
        host=args.host,
        secret_key=app.config.get("SECRET_KEY"),
        setup_complete=setup_complete,
    )
    report = run_preflight(app, host=args.host)
    if not report["required_ok"]:
        _print(report)
        return 2

    app.config["START_SCHEDULER"] = True
    if setup_complete:
        from src.services.scheduler import init_scheduler

        init_scheduler(app)
    if app.config.get("OPEN_BROWSER", True) and not args.no_browser:
        threading.Timer(
            1.5,
            lambda: open_browser(port=args.port),
        ).start()
    try:
        from waitress import serve
    except ImportError as exc:
        raise RuntimeError(
            "Waitress is required. Install dependencies from requirements.lock."
        ) from exc
    serve(
        app,
        host=args.host,
        port=args.port,
        threads=app.config.get("SERVER_THREADS", 8),
        url_scheme="http",
        ident="SpecialistClinic",
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    args = _parser().parse_args(argv)
    command = args.command or "serve"

    if command == "serve":
        if args.command is None:
            args.host = Config.HOST
            args.port = Config.PORT
            args.no_browser = False
        return _serve(args)
    if command == "self-test":
        from src.services.release_ops import run_self_test

        report = run_self_test()
        _print(report)
        return 0 if report["required_ok"] else 2
    if command == "preflight":
        from src.services.release_ops import run_preflight

        app = _create_runtime_app()
        report = run_preflight(app)
        _print(report)
        return 0 if report["required_ok"] else 2
    if command == "backup":
        verified = BackupIntegrityService().create(
            Config.DATABASE_PATH,
            args.output_dir,
            prefix="backup_manual",
        )
        _print(
            {
                "status": "pass",
                "backup": str(verified.database_path),
                "manifest": str(verified.manifest_path),
                "sha256": verified.sha256,
                "size_bytes": verified.size_bytes,
            }
        )
        return 0
    if command == "verify-backup":
        verified = BackupIntegrityService().verify(
            args.backup, manifest_path=args.manifest
        )
        _print(
            {
                "status": "pass",
                "backup": str(verified.database_path),
                "sha256": verified.sha256,
                "size_bytes": verified.size_bytes,
            }
        )
        return 0
    if command == "restore-backup":
        if args.confirm != "RESTORE-SPECIALIST-DATABASE":
            raise RuntimeError("Restore confirmation phrase is invalid.")
        service = BackupIntegrityService()
        verified = service.verify(
            args.backup,
            manifest_path=args.manifest,
        )
        pre_restore_warning = None
        if Path(Config.DATABASE_PATH).is_file():
            try:
                service.create(
                    Config.DATABASE_PATH,
                    Config.BACKUP_FOLDER,
                    prefix="backup_pre_restore",
                )
            except Exception as exc:
                # A corrupt current database is one reason restore exists. Keep the
                # byte-for-byte .before-restore copy and continue from a verified source.
                pre_restore_warning = type(exc).__name__
        service.restore(
            args.backup,
            Config.DATABASE_PATH,
            manifest_path=args.manifest,
        )
        _print(
            {
                "status": "pass",
                "restored_from_sha256": verified.sha256,
                "destination": str(Path(Config.DATABASE_PATH).resolve()),
                "pre_restore_backup_warning": pre_restore_warning,
            }
        )
        return 0
    raise RuntimeError(f"Unsupported command: {command}")


if __name__ == "__main__":
    try:
        import multiprocessing

        multiprocessing.freeze_support()
        raise SystemExit(main())
    except Exception as exc:
        _print({"status": "fail", "error": type(exc).__name__, "detail": str(exc)})
        raise SystemExit(2)
