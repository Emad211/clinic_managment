"""Build the final hash-bound release manifest for specialist record cutover."""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from clinical.secure_report_io import SecureReportIOError, write_private_text
from clinical.specialist_record_release_manifest import (
    SpecialistRecordReleaseManifestBuilder,
    SpecialistRecordReleaseManifestError,
)


class Command(BaseCommand):
    help = (
        "Re-hash the source snapshot and every migration/review artifact, rerun "
        "clinician verification, and emit the final production GO/NO_GO manifest."
    )

    def add_arguments(self, parser):
        parser.add_argument("--sqlite", required=True, help="Quiesced source snapshot.")
        parser.add_argument("--apply-report", required=True)
        parser.add_argument("--replay-report", required=True)
        parser.add_argument("--verification-report", required=True)
        parser.add_argument("--review-packet", required=True)
        parser.add_argument("--clinician-signoff-report", required=True)
        parser.add_argument("--source-id", required=True)
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument(
            "--git-commit",
            required=True,
            help="Full 40-character commit SHA of the deployed Halqe code.",
        )
        parser.add_argument(
            "--image-digest",
            help="Optional immutable container digest in sha256:<64 hex> form.",
        )
        parser.add_argument(
            "--report",
            required=True,
            help="Owner-only output path for the final release manifest.",
        )
        parser.add_argument(
            "--print-report",
            action="store_true",
            help="Print the pseudonymous manifest JSON to stdout.",
        )

    def handle(self, *args, **options):
        try:
            result = SpecialistRecordReleaseManifestBuilder(
                source_snapshot_path=options["sqlite"],
                apply_report_path=options["apply_report"],
                replay_report_path=options["replay_report"],
                verification_report_path=options["verification_report"],
                review_packet_path=options["review_packet"],
                clinician_signoff_report_path=options[
                    "clinician_signoff_report"
                ],
                source_id=options["source_id"],
                tenant_id=options["tenant_id"],
                git_commit=options["git_commit"],
                image_digest=options.get("image_digest"),
            ).run()
        except SpecialistRecordReleaseManifestError as exc:
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
            f"Specialist record release manifest {result.decision}: "
            f"release_id={result.release_id}, source_id={result.source_id}, "
            f"tenant={result.tenant_id}, commit={result.git_commit}, "
            f"passed={summary['passed']}, warnings={summary['warnings']}, "
            f"failed={summary['failed']}, report={target}"
        )
        if result.decision != "GO":
            raise CommandError(message)
        self.stdout.write(self.style.SUCCESS(message))
