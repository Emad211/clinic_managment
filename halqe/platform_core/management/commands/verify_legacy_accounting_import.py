from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounting_ops.import_verifier import AccountingImportVerifier
from clinical.secure_report_io import (
    SecureReportIOError,
    ensure_distinct_artifact_paths,
    write_private_text,
)


class Command(BaseCommand):
    help = (
        "Independently verify a committed legacy-accounting import against its "
        "immutable SQLite snapshot and append-only ledger."
    )

    def add_arguments(self, parser):
        parser.add_argument("--sqlite", required=True)
        parser.add_argument("--source-id", required=True)
        parser.add_argument("--tenant-id", type=int, default=1)
        parser.add_argument("--report", required=True)

    def handle(self, *args, **options):
        source = Path(options["sqlite"]).expanduser().absolute()
        report_path = Path(options["report"]).expanduser().absolute()
        try:
            ensure_distinct_artifact_paths(
                inputs={"sqlite": source},
                outputs={"verification_report": report_path},
            )
        except SecureReportIOError as exc:
            raise CommandError(str(exc)) from exc

        try:
            result = AccountingImportVerifier(
                sqlite_path=source,
                source_id=options["source_id"],
                tenant_id=options["tenant_id"],
            ).run()
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        rendered = json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        ) + "\n"
        try:
            written = write_private_text(report_path, rendered)
        except SecureReportIOError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"Private accounting verification report: {written}")
        if result.decision != "VERIFIED":
            raise CommandError(
                "Accounting import verification FAILED: "
                + ", ".join(result.errors)
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Accounting import VERIFIED: {result.source_rows} source rows, "
                f"{result.ledger_rows} ledger rows, {result.target_rows} targets"
            )
        )
