"""Management command for read-only specialist-record reconciliation."""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from clinical.secure_report_io import SecureReportIOError, write_private_text
from clinical.specialist_record_reconciliation import (
    SpecialistRecordReconciliationError,
    SpecialistRecordReconciler,
)


class Command(BaseCommand):
    help = (
        "Verify a committed specialist-record import and its idempotent replay "
        "against the secured SQLite snapshot, append-only ledger and domain invariants."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--sqlite",
            required=True,
            help="Path to the same quiesced SQLite snapshot used for rehearsal.",
        )
        parser.add_argument(
            "--apply-report",
            required=True,
            help="Private JSON report from the first committed --apply run.",
        )
        parser.add_argument(
            "--replay-report",
            help="Private JSON report from the immediate second idempotent --apply run.",
        )
        parser.add_argument("--source-id", required=True)
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument(
            "--allow-skipped-unresolved",
            action="store_true",
            help=(
                "Downgrade unresolved/skipped patient rows from NO_GO to warning. "
                "Requires a separate documented waiver."
            ),
        )
        parser.add_argument(
            "--allow-live-source",
            action="store_true",
            help=(
                "Allow a source with a non-empty SQLite WAL during the verification "
                "dry-run. A quiesced copy remains the normal requirement."
            ),
        )
        parser.add_argument(
            "--strict-warnings",
            action="store_true",
            help="Treat any warning as NO_GO.",
        )
        parser.add_argument(
            "--allow-missing-replay",
            action="store_true",
            help=(
                "Allow verification without a second apply report. The missing "
                "idempotency certificate is still reported as a warning."
            ),
        )
        parser.add_argument(
            "--report",
            help=(
                "Optional private JSON output. It is atomically replaced using "
                "owner-only permissions."
            ),
        )
        parser.add_argument(
            "--print-report",
            action="store_true",
            help="Print the complete PHI-redacted verifier JSON to stdout.",
        )

    def handle(self, *args, **options):
        try:
            result = SpecialistRecordReconciler(
                sqlite_path=options["sqlite"],
                apply_report_path=options["apply_report"],
                replay_report_path=options.get("replay_report"),
                source_id=options["source_id"],
                tenant_id=options["tenant_id"],
                allow_skipped_unresolved=options["allow_skipped_unresolved"],
                allow_live_source=options["allow_live_source"],
                strict_warnings=options["strict_warnings"],
                require_replay=not options["allow_missing_replay"],
            ).run()
        except SpecialistRecordReconciliationError as exc:
            raise CommandError(str(exc)) from exc

        payload = result.to_dict()
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        if options["print_report"]:
            self.stdout.write(rendered)
        if options.get("report"):
            try:
                target = write_private_text(options["report"], rendered + "\n")
            except SecureReportIOError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(f"Wrote private verification report (0600): {target}")

        summary = payload["summary"]
        message = (
            f"Specialist record reconciliation {result.decision}: "
            f"source_id={result.source_id}, tenant={result.tenant_id}, "
            f"passed={summary['passed']}, warnings={summary['warnings']}, "
            f"failed={summary['failed']}"
        )
        if result.decision != "GO":
            raise CommandError(message)
        self.stdout.write(self.style.SUCCESS(message))
