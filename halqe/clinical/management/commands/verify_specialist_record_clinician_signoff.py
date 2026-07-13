"""Verify a completed clinician review packet against its migration GO report."""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from clinical.secure_report_io import SecureReportIOError, write_private_text
from clinical.specialist_record_clinician_signoff import (
    SpecialistRecordClinicianSignoffError,
    SpecialistRecordClinicianSignoffVerifier,
)


class Command(BaseCommand):
    help = (
        "Bind a completed clinician review packet to the exact migration verifier "
        "GO report and emit a fail-closed release-level GO/NO_GO decision."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--review-packet",
            required=True,
            help=(
                "Owner-only JSON packet produced by "
                "generate_specialist_record_review_sample and completed by the reviewer."
            ),
        )
        parser.add_argument(
            "--verification-report",
            required=True,
            help="Owner-only GO report produced by verify_specialist_record_import.",
        )
        parser.add_argument("--source-id", required=True)
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument(
            "--report",
            required=True,
            help="Owner-only JSON output path for the clinician sign-off decision.",
        )
        parser.add_argument(
            "--print-report",
            action="store_true",
            help=(
                "Print the pseudonymous decision JSON to stdout. Disabled by default "
                "because packet hashes and indirect patient counts are operationally sensitive."
            ),
        )

    def handle(self, *args, **options):
        try:
            result = SpecialistRecordClinicianSignoffVerifier(
                review_packet_path=options["review_packet"],
                verification_report_path=options["verification_report"],
                source_id=options["source_id"],
                tenant_id=options["tenant_id"],
            ).run()
        except SpecialistRecordClinicianSignoffError as exc:
            raise CommandError(str(exc)) from exc

        rendered = json.dumps(
            result.to_dict(),
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

        summary = result.summary
        message = (
            f"Specialist clinician sign-off {result.decision}: "
            f"source_id={result.source_id}, tenant={result.tenant_id}, "
            f"patients={result.selected_patient_count}, "
            f"scenarios={result.covered_scenario_count}, "
            f"discrepancies={result.discrepancy_count}, "
            f"passed={summary['passed']}, warnings={summary['warnings']}, "
            f"failed={summary['failed']}, report={target}"
        )
        if result.decision != "GO":
            raise CommandError(message)
        self.stdout.write(self.style.SUCCESS(message))
