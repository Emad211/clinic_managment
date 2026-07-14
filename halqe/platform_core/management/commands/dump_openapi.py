"""Generate or verify the Halqe OpenAPI contract.

The full pretty JSON remains available for local review and as a CI artifact.
The committed drift guard is ``docs/openapi.lock.json``: it stores the SHA-256 of
the complete canonical JSON plus the path/method manifest and counts. Therefore
any request/response schema change still changes the lock, without requiring a
365KB generated document to be committed on every integration branch.

Usage:
    python manage.py dump_openapi --output generated-openapi.json
    python manage.py dump_openapi --check-lock
    python manage.py dump_openapi --write-lock
    python manage.py dump_openapi --check          # legacy full-snapshot mode
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


_DEFAULT_OUTPUT = "docs/openapi.json"
_DEFAULT_LOCK = "docs/openapi.lock.json"
_HTTP_VERBS = ("get", "post", "put", "patch", "delete")


def _render_schema() -> str:
    """Serialize the live Ninja schema deterministically."""
    from config.api import api

    schema = api.get_openapi_schema()
    return (
        json.dumps(
            schema,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )


def _schema_lock(rendered: str) -> dict:
    """Build the exact, reviewable lock for a canonical rendered schema."""
    schema = json.loads(rendered)
    path_methods = {
        path: sorted(
            verb.lower()
            for verb in methods
            if verb.lower() in _HTTP_VERBS
        )
        for path, methods in sorted(schema.get("paths", {}).items())
    }
    operations = sum(len(methods) for methods in path_methods.values())
    return {
        "operations": operations,
        "path_methods": path_methods,
        "paths": len(path_methods),
        "sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        "version": schema.get("info", {}).get("version"),
    }


def _resolve(path_value: str) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = Path(settings.BASE_DIR) / path
    return path


class Command(BaseCommand):
    help = (
        "Generate the django-ninja OpenAPI JSON, verify a full snapshot, or "
        "verify/write the exact SHA/path-method lock used by unified CI."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            "-o",
            dest="output",
            default=_DEFAULT_OUTPUT,
            help=f"Full JSON output path. Default: {_DEFAULT_OUTPUT}",
        )
        parser.add_argument(
            "--lock-output",
            dest="lock_output",
            default=_DEFAULT_LOCK,
            help=f"OpenAPI lock path. Default: {_DEFAULT_LOCK}",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Legacy mode: compare the full JSON output file with the live schema.",
        )
        parser.add_argument(
            "--check-lock",
            action="store_true",
            help="Compare the committed SHA/path-method lock with the live schema.",
        )
        parser.add_argument(
            "--write-lock",
            action="store_true",
            help="Write the deterministic SHA/path-method lock instead of full JSON.",
        )

    def handle(self, *args, **options):
        modes = sum(
            bool(options[name])
            for name in ("check", "check_lock", "write_lock")
        )
        if modes > 1:
            raise CommandError(
                "Choose only one of --check, --check-lock, or --write-lock."
            )

        rendered = _render_schema()
        lock = _schema_lock(rendered)
        out_path = _resolve(options["output"])
        lock_path = _resolve(options["lock_output"])

        if options["check_lock"]:
            if not lock_path.exists():
                raise CommandError(
                    f"OpenAPI lock missing: {lock_path}. Run `manage.py "
                    "dump_openapi --write-lock`."
                )
            try:
                existing = json.loads(lock_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CommandError(f"OpenAPI lock is unreadable: {exc}") from exc
            if existing != lock:
                raise CommandError(
                    "OpenAPI lock is STALE — the complete schema hash or its "
                    "path/method manifest changed. Run `python manage.py "
                    "dump_openapi --write-lock`, review the full generated CI "
                    "artifact, and commit the lock only for intentional additive "
                    "v1 changes."
                )
            self.stdout.write(
                self.style.SUCCESS(
                    f"OpenAPI lock is up to date: {lock_path} "
                    f"({lock['paths']} paths, {lock['operations']} operations, "
                    f"sha256={lock['sha256']})"
                )
            )
            return

        if options["write_lock"]:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.write_text(
                json.dumps(lock, indent=2, sort_keys=True, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Wrote OpenAPI lock → {lock_path}\n"
                    f"  paths      : {lock['paths']}\n"
                    f"  operations : {lock['operations']}\n"
                    f"  sha256     : {lock['sha256']}\n"
                    f"  version    : {lock['version']}"
                )
            )
            return

        if options["check"]:
            if not out_path.exists():
                raise CommandError(
                    f"Snapshot missing: {out_path}. Run `manage.py dump_openapi`."
                )
            existing = out_path.read_text(encoding="utf-8")
            if existing != rendered:
                raise CommandError(
                    "OpenAPI full snapshot is STALE. Generate it again or use "
                    "--check-lock for the committed unified contract guard."
                )
            self.stdout.write(
                self.style.SUCCESS(f"OpenAPI snapshot is up to date: {out_path}")
            )
            return

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote OpenAPI contract → {out_path}\n"
                f"  paths      : {lock['paths']}\n"
                f"  operations : {lock['operations']}\n"
                f"  sha256     : {lock['sha256']}\n"
                f"  version    : {lock['version']}"
            )
        )
