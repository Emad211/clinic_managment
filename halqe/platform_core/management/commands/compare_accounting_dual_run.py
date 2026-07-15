from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from accounting_ops.dual_run_service import compare_accounting_dual_run
from accounting_ops.import_common import AccountingImportError
from clinical.secure_report_io import (
    SecureReportIOError,
    ensure_distinct_artifact_paths,
    write_private_text,
)


class Command(BaseCommand):
    help = (
        "Compare a quiesced legacy accounting SQLite snapshot with Halqe for one "
        "bounded dual-run date range, including financial and payroll aggregates."
    )

    def add_arguments(self, parser):
        parser.add_argument("--sqlite", required=True)
        parser.add_argument("--source-id", required=True)
        parser.add_argument("--tenant-id", required=True, type=int)
        parser.add_argument("--date-from", required=True)
        parser.add_argument("--date-to", required=True)
        parser.add_argument("--shift", choices=("morning", "evening", "night"))
        parser.add_argument("--report", required=True)

    def handle(self, *args, **options):
        source = Path(options["sqlite"]).expanduser().absolute()
        report_path = Path(options["report"]).expanduser().absolute()
        try:
            ensure_distinct_artifact_paths(
                inputs={"legacy_sqlite": source},
                outputs={"dual_run_report": report_path},
            )
            report = compare_accounting_dual_run(
                sqlite_path=source,
                source_id=options["source_id"],
                tenant_id=options["tenant_id"],
                date_from=options["date_from"],
                date_to=options["date_to"],
                shift=options.get("shift"),
            )
            rendered = json.dumps(
                report.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                default=str,
            ) + "\n"
            written = write_private_text(report_path, rendered)
        except (
            AccountingImportError,
            DatabaseError,
            SecureReportIOError,
            ValueError,
            OSError,
        ) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"Private dual-run report: {written}")
        if report.decision != "GO":
            paths = ", ".join(item.path for item in report.differences[:10])
            raise CommandError(
                "Accounting dual-run comparison NO_GO"
                + (f": {paths}" if paths else "")
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Accounting dual-run GO for tenant={report.tenant_id}, "
                f"range={report.date_from}..{report.date_to}, "
                f"shift={report.shift or 'all'}"
            )
        )
