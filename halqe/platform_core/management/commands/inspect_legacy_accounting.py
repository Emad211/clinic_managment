"""Inspect a quiesced legacy accounting SQLite snapshot without importing it."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from django.core.management.base import BaseCommand, CommandError

from accounting_ops.import_preflight import AccountingImportPreflight


class Command(BaseCommand):
    help = (
        "Validate legacy clinic_new.db schema, relationships and money aggregates. "
        "This command never writes PostgreSQL or SQLite."
    )

    def add_arguments(self, parser):
        parser.add_argument("--sqlite", required=True)
        parser.add_argument("--source-id", required=True)
        parser.add_argument("--report")
        parser.add_argument(
            "--print-report",
            action="store_true",
            help="Print the complete PHI-minimised JSON report to stdout.",
        )

    def handle(self, *args, **options):
        source = Path(options["sqlite"]).expanduser().absolute()
        report_path = (
            Path(options["report"]).expanduser().absolute()
            if options.get("report")
            else None
        )
        if report_path is not None:
            self._assert_distinct(source, report_path)

        report = AccountingImportPreflight(
            sqlite_path=source,
            source_id=options["source_id"],
        ).run()
        payload = report.to_dict()
        rendered = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, indent=2
        ) + "\n"

        if report_path is not None:
            self._write_private(report_path, rendered)
            self.stdout.write(f"Wrote accounting preflight report (0600): {report_path}")
        if options["print_report"]:
            self.stdout.write(rendered)

        style = self.style.SUCCESS if report.decision == "GO" else self.style.ERROR
        self.stdout.write(style(
            f"Accounting import preflight {report.decision}: "
            f"source_id={report.source_id}, "
            f"tables={len(report.tables)}, "
            f"manifest={report.source_manifest_sha256 or 'unavailable'}"
        ))
        if report.decision != "GO":
            raise CommandError(
                "Accounting import preflight is NO_GO; inspect the private report."
            )

    @staticmethod
    def _assert_distinct(source: Path, report: Path) -> None:
        if source == report:
            raise CommandError("Report path cannot overwrite the SQLite source.")
        if source.exists() and report.exists():
            try:
                if os.path.samefile(source, report):
                    raise CommandError(
                        "Report path aliases the SQLite source through a hard link."
                    )
            except OSError as exc:
                raise CommandError(f"Cannot compare source/report paths: {exc}") from exc

    @staticmethod
    def _write_private(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.is_symlink():
            raise CommandError("Refusing to write accounting report through a symlink.")
        if path.exists() and not path.is_file():
            raise CommandError("Accounting report path is not a regular file.")
        descriptor = None
        temporary = None
        try:
            descriptor, temporary = tempfile.mkstemp(
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                text=True,
            )
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                descriptor = None
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            temporary = None
            os.chmod(path, 0o600)
        except OSError as exc:
            raise CommandError(f"Failed to write accounting preflight report: {exc}") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
