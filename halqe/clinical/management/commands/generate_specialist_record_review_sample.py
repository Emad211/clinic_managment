"""Generate a private deterministic clinician review packet after verifier GO."""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from clinical.secure_report_io import SecureReportIOError, write_private_text
from clinical.specialist_record_review_sample import (
    SpecialistRecordReviewSampleError,
    SpecialistRecordReviewSampler,
)


class Command(BaseCommand):
    help = (
        "Generate a deterministic, PHI-minimized clinician review sample from "
        "one GO verification report and its durable import ledger."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--verification-report",
            required=True,
            help="Private JSON report produced by verify_specialist_record_import.",
        )
        parser.add_argument("--source-id", required=True)
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument(
            "--per-scenario",
            type=int,
            default=1,
            help="Desired distinct patient samples for each present scenario (1-10).",
        )
        parser.add_argument(
            "--max-patients",
            type=int,
            default=25,
            help="Maximum unique patients in the packet (1-200).",
        )
        parser.add_argument(
            "--report",
            required=True,
            help="Private owner-only JSON output path for the review packet.",
        )
        parser.add_argument(
            "--print-report",
            action="store_true",
            help=(
                "Print the complete pseudonymous packet to stdout. Disabled by "
                "default because patient UUIDs are operationally sensitive."
            ),
        )

    def handle(self, *args, **options):
        try:
            sample = SpecialistRecordReviewSampler(
                verification_report_path=options["verification_report"],
                source_id=options["source_id"],
                tenant_id=options["tenant_id"],
                per_scenario=options["per_scenario"],
                max_patients=options["max_patients"],
            ).run()
        except SpecialistRecordReviewSampleError as exc:
            raise CommandError(str(exc)) from exc

        rendered = json.dumps(
            sample.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        try:
            target = write_private_text(options["report"], rendered + "\n")
        except SecureReportIOError as exc:
            raise CommandError(str(exc)) from exc

        if options["print_report"]:
            self.stdout.write(rendered)
        covered = sum(
            row["status"] == "covered" for row in sample.coverage.values()
        )
        present = sum(
            row["eligible_patients"] > 0 for row in sample.coverage.values()
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Specialist clinical review sample generated: "
                f"source_id={sample.source_id}, tenant={sample.tenant_id}, "
                f"patients={len(sample.patients)}, covered_scenarios={covered}/{present}, "
                f"report={target}"
            )
        )
