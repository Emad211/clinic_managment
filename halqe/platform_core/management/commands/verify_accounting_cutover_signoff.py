from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounting_ops.cutover_signoff import (
    AccountingCutoverSignoffError,
    verify_accounting_cutover_signoff,
)
from clinical.secure_report_io import (
    SecureReportIOError,
    ensure_distinct_artifact_paths,
    write_private_text,
)


class Command(BaseCommand):
    help = (
        "Verify the immutable accounting cutover evidence chain: import, restore, "
        "consecutive all-shift dual-runs and human financial approval."
    )

    def add_arguments(self, parser):
        parser.add_argument("--packet", required=True)
        parser.add_argument("--import-verification", required=True)
        parser.add_argument("--restore-verification", required=True)
        parser.add_argument(
            "--dual-run-report",
            action="append",
            dest="dual_run_reports",
            required=True,
            help="Repeat once for every all/morning/evening/night daily report.",
        )
        parser.add_argument("--source-id", required=True)
        parser.add_argument("--tenant-id", required=True, type=int)
        parser.add_argument("--report", required=True)

    def handle(self, *args, **options):
        packet = Path(options["packet"]).expanduser().absolute()
        import_report = Path(options["import_verification"]).expanduser().absolute()
        restore_report = Path(options["restore_verification"]).expanduser().absolute()
        dual_reports = [
            Path(item).expanduser().absolute()
            for item in options["dual_run_reports"]
        ]
        output = Path(options["report"]).expanduser().absolute()
        try:
            inputs = {
                "packet": packet,
                "import_verification": import_report,
                "restore_verification": restore_report,
                **{
                    f"dual_run_{index}": path
                    for index, path in enumerate(dual_reports)
                },
            }
            ensure_distinct_artifact_paths(
                inputs=inputs,
                outputs={"signoff_report": output},
            )
            result = verify_accounting_cutover_signoff(
                packet_path=packet,
                import_verification_path=import_report,
                restore_verification_path=restore_report,
                dual_run_report_paths=dual_reports,
                source_id=options["source_id"],
                tenant_id=options["tenant_id"],
            )
            rendered = json.dumps(
                result.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                default=str,
            ) + "\n"
            written = write_private_text(output, rendered)
        except (
            AccountingCutoverSignoffError,
            SecureReportIOError,
            OSError,
            TypeError,
            ValueError,
        ) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"Private accounting sign-off report: {written}")
        if result.decision != "GO":
            raise CommandError(
                "Accounting cutover sign-off NO_GO: " + ", ".join(result.errors)
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Accounting cutover sign-off GO: source_id={result.source_id}, "
                f"tenant={result.tenant_id}, days={len(result.observed_dates)}"
            )
        )
