from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounting_ops.import_common import AccountingImportError, file_sha256
from accounting_ops.import_engine import AccountingHistoryImporter
from clinical.secure_report_io import (
    SecureReportIOError,
    ensure_distinct_artifact_paths,
    write_private_text,
)


def _service_map(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise CommandError(
                "--map-service-type must use SOURCE=TARGET, for example custom=procedure"
            )
        source, target = (part.strip().lower() for part in value.split("=", 1))
        if not source or not target or source in result:
            raise CommandError("Invalid or duplicate --map-service-type value")
        result[source] = target
    return result


class Command(BaseCommand):
    help = "Dry-run or atomically import a quiesced legacy accounting SQLite snapshot."

    def add_arguments(self, parser):
        parser.add_argument("--sqlite", required=True)
        parser.add_argument("--source-id", required=True)
        parser.add_argument("--tenant-id", type=int, default=1)
        parser.add_argument("--imported-by", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--confirm-source-sha256")
        parser.add_argument("--report")
        parser.add_argument(
            "--map-service-type",
            action="append",
            default=[],
            metavar="SOURCE=TARGET",
        )

    def handle(self, *args, **options):
        source = Path(options["sqlite"]).expanduser().absolute()
        report_path = options.get("report")
        try:
            ensure_distinct_artifact_paths(
                inputs={"sqlite": source},
                outputs={"report": report_path},
            )
        except SecureReportIOError as exc:
            raise CommandError(str(exc)) from exc

        if options["apply"]:
            expected = (options.get("confirm_source_sha256") or "").strip().lower()
            actual = file_sha256(source) if source.is_file() else ""
            if not expected or expected != actual:
                raise CommandError(
                    "--apply requires --confirm-source-sha256 matching the current snapshot"
                )

        try:
            result = AccountingHistoryImporter(
                sqlite_path=source,
                source_id=options["source_id"],
                tenant_id=options["tenant_id"],
                imported_by=options["imported_by"],
                apply=options["apply"],
                service_type_map=_service_map(options["map_service_type"]),
            ).run()
        except (AccountingImportError, OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        rendered = json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        ) + "\n"
        if report_path:
            try:
                written = write_private_text(report_path, rendered)
            except SecureReportIOError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(f"Private accounting import report: {written}")
        self.stdout.write(
            self.style.SUCCESS(
                f"Accounting import {result.mode}: {result.transaction_status}; "
                f"ledger {result.ledger_rows_before}->{result.ledger_rows_after}"
            )
        )
