"""
Management command: dump_openapi

نوشتنِ snapshotِ قراردادِ OpenAPI پلتفرم به یک فایلِ JSON (پیش‌فرض:
``halqe/docs/openapi.json``). این فایلِ متعهدشده «قفلِ قرارداد» است: reviewerها /
CI آن را diff می‌گیرند تا هر تغییرِ ناخواسته در سطحِ API (endpoint جدید/حذف‌شده،
تغییرِ schema) را زودهنگام بگیرند — همان ایده‌ای که در snapshotهای OpenAPIِ فازِ
cleanup استفاده شد.

طراحی:
  * منبعِ schema تنها ``config.api.api.get_openapi_schema()`` است (همان NinjaAPI
    که در ``urls.py`` زیر ``/api/v1/`` mount می‌شود) — هیچ سطحِ APIِ جدیدی اینجا
    ساخته یا تغییر داده نمی‌شود؛ فقط snapshot گرفته می‌شود.
  * خروجی با ``indent=2`` + ``sort_keys=True`` + ``ensure_ascii=False`` نوشته
    می‌شود تا diffها معنادار و پایدار باشند (ترتیبِ کلیدها مستقل از نسخهٔ پایتون)
    و رشته‌های فارسیِ توضیحات به‌صورتِ خوانا (نه ``\\uXXXX``) ذخیره شوند.
  * یک خطِ newline در انتها برای سازگاری با ابزارهای POSIX/Git.

idempotent: اجرای مجدد بدونِ تغییرِ کد → همان بایت‌ها (no-op diff).

Usage:
    python manage.py dump_openapi
    python manage.py dump_openapi --output docs/openapi.json
    python manage.py dump_openapi --check          # CI mode: fail اگر فایل قدیمی است
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


# Default snapshot location: halqe/docs/openapi.json (relative to BASE_DIR).
_DEFAULT_OUTPUT = "docs/openapi.json"


def _render_schema() -> str:
    """
    Serialize the live ninja OpenAPI schema to a stable, pretty JSON string.

    Import is done lazily inside the function so that simply *loading* this
    command module (as Django does at startup for command discovery) does not
    pull in the whole router graph before ``django.setup()`` has finished.
    """
    # Lazy import — config.api wires every domain router onto the NinjaAPI.
    from config.api import api

    schema = api.get_openapi_schema()
    # ``OpenAPISchema`` is a dict subclass, so json.dumps handles it directly.
    return (
        json.dumps(
            schema,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )


class Command(BaseCommand):
    help = (
        "Dump the django-ninja OpenAPI contract to a JSON file (default "
        "docs/openapi.json), pretty-printed with stable key order so diffs "
        "catch accidental contract changes. Use --check in CI to fail when the "
        "committed snapshot is stale."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            "-o",
            dest="output",
            default=_DEFAULT_OUTPUT,
            help=(
                "Output path (relative paths resolve against BASE_DIR). "
                f"Default: {_DEFAULT_OUTPUT}"
            ),
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help=(
                "Do not write. Exit non-zero if the on-disk snapshot differs "
                "from the live schema (CI drift guard)."
            ),
        )

    def handle(self, *args, **options):
        output = options["output"]
        out_path = Path(output)
        if not out_path.is_absolute():
            out_path = Path(settings.BASE_DIR) / out_path

        rendered = _render_schema()

        if options["check"]:
            if not out_path.exists():
                raise CommandError(
                    f"Snapshot missing: {out_path}. Run `manage.py dump_openapi`."
                )
            existing = out_path.read_text(encoding="utf-8")
            if existing != rendered:
                raise CommandError(
                    "OpenAPI snapshot is STALE — the live API schema differs "
                    f"from {out_path}.\n"
                    "Run `python manage.py dump_openapi` and commit the result. "
                    "If this is an intentional contract change, make sure it is "
                    "an additive change within /api/v1 (see docs/api_versioning.md)."
                )
            self.stdout.write(
                self.style.SUCCESS(f"OpenAPI snapshot is up to date: {out_path}")
            )
            return

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")

        # Count operations for the operator's confirmation line (PII-free).
        from config.api import api  # already imported by _render_schema

        schema = api.get_openapi_schema()
        ops = sum(
            1
            for methods in schema.get("paths", {}).values()
            for verb in methods
            if verb.lower() in ("get", "post", "put", "patch", "delete")
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote OpenAPI contract → {out_path}\n"
                f"  paths      : {len(schema.get('paths', {}))}\n"
                f"  operations : {ops}\n"
                f"  version    : {schema.get('info', {}).get('version')}"
            )
        )
