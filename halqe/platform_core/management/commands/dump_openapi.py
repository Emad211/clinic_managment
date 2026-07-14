"""Generate or verify the exact Halqe OpenAPI contract."""
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
    from config.api import api
    return json.dumps(
        api.get_openapi_schema(), indent=2, sort_keys=True, ensure_ascii=False
    ) + "\n"


def _digest_words(digest: bytes) -> list[int]:
    return [
        int.from_bytes(digest[offset:offset + 8], "big", signed=True)
        for offset in range(0, len(digest), 8)
    ]


def _schema_lock(rendered: str) -> dict:
    schema = json.loads(rendered)
    path_methods = {
        path: sorted(
            verb.lower() for verb in methods if verb.lower() in _HTTP_VERBS
        )
        for path, methods in sorted(schema.get("paths", {}).items())
    }
    return {
        "operations": sum(len(methods) for methods in path_methods.values()),
        "paths": len(path_methods),
        "sha256_words": _digest_words(
            hashlib.sha256(rendered.encode("utf-8")).digest()
        ),
        "version": schema.get("info", {}).get("version"),
    }


def _digest_hex(lock: dict) -> str:
    digest = b"".join(
        int(word).to_bytes(8, "big", signed=True)
        for word in lock["sha256_words"]
    )
    return digest.hex()


def _resolve(path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else Path(settings.BASE_DIR) / path


class Command(BaseCommand):
    help = "Generate or verify the exact OpenAPI contract lock."

    def add_arguments(self, parser):
        parser.add_argument("--output", "-o", dest="output", default=_DEFAULT_OUTPUT)
        parser.add_argument("--lock-output", dest="lock_output", default=_DEFAULT_LOCK)
        parser.add_argument("--check", action="store_true")
        parser.add_argument("--check-lock", action="store_true")
        parser.add_argument("--write-lock", action="store_true")

    def handle(self, *args, **options):
        if sum(bool(options[name]) for name in ("check", "check_lock", "write_lock")) > 1:
            raise CommandError("Choose only one OpenAPI output mode.")
        rendered = _render_schema()
        lock = _schema_lock(rendered)
        out_path = _resolve(options["output"])
        lock_path = _resolve(options["lock_output"])

        if options["check_lock"]:
            if not lock_path.exists():
                raise CommandError(f"OpenAPI lock missing: {lock_path}")
            try:
                existing = json.loads(lock_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CommandError(f"OpenAPI lock is unreadable: {exc}") from exc
            if existing != lock:
                raise CommandError(
                    "OpenAPI lock is STALE. Review the generated contract artifact "
                    "and regenerate the lock for an intentional API change."
                )
            self.stdout.write(self.style.SUCCESS(
                f"OpenAPI lock is up to date: {lock_path} "
                f"({lock['paths']} paths, {lock['operations']} operations, "
                f"sha256={_digest_hex(lock)})"
            ))
            return

        if options["write_lock"]:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.write_text(
                json.dumps(lock, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            self.stdout.write(self.style.SUCCESS(
                f"Wrote OpenAPI lock → {lock_path}\n"
                f"  paths: {lock['paths']}\n"
                f"  operations: {lock['operations']}\n"
                f"  sha256: {_digest_hex(lock)}"
            ))
            return

        if options["check"]:
            if not out_path.exists() or out_path.read_text(encoding="utf-8") != rendered:
                raise CommandError("OpenAPI full snapshot is STALE.")
            self.stdout.write(self.style.SUCCESS(f"OpenAPI snapshot is up to date: {out_path}"))
            return

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(
            f"Wrote OpenAPI contract → {out_path}\n"
            f"  paths: {lock['paths']}\n"
            f"  operations: {lock['operations']}\n"
            f"  sha256: {_digest_hex(lock)}"
        ))
