from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from accounting_ops.cutover_signoff import AccountingCutoverSignoffError
from accounting_ops.import_common import AccountingImportError
from accounting_ops.release_manifest import (
    AccountingReleaseManifestError,
    build_accounting_release_manifest,
)
from clinical.secure_report_io import (
    SecureReportIOError,
    ensure_distinct_artifact_paths,
    write_private_text,
)
from platform_core.backup_canonical import BackupVerificationError


class Command(BaseCommand):
    help = (
        "Build the final accounting cutover manifest after recomputing import and "
        "latest all-shift dual-run evidence."
    )

    def add_arguments(self, parser):
        parser.add_argument("--import-sqlite", required=True)
        parser.add_argument("--latest-dual-run-sqlite", required=True)
        parser.add_argument("--packet", required=True)
        parser.add_argument("--signoff-report", required=True)
        parser.add_argument("--import-verification", required=True)
        parser.add_argument("--restore-verification", required=True)
        parser.add_argument("--dual-run-report", nargs="+", required=True)
        parser.add_argument("--backup-manifest", required=True)
        parser.add_argument("--backup-file", required=True)
        parser.add_argument("--source-id", required=True)
        parser.add_argument("--tenant-id", required=True, type=int)
        parser.add_argument("--git-commit", required=True)
        parser.add_argument("--image-digest", required=True)
        parser.add_argument("--fresh-import-report", required=True)
        parser.add_argument("--fresh-dual-run-directory", required=True)
        parser.add_argument("--report", required=True)

    def handle(self, *args, **options):
        output = Path(options["report"]).expanduser().absolute()
        dual_paths = [Path(item).expanduser().absolute() for item in options["dual_run_report"]]
        input_paths = {
            "import_sqlite": options["import_sqlite"],
            "latest_dual_sqlite": options["latest_dual_run_sqlite"],
            "packet": options["packet"],
            "signoff_report": options["signoff_report"],
            "import_verification": options["import_verification"],
            "restore_verification": options["restore_verification"],
            "backup_manifest": options["backup_manifest"],
            "backup_file": options["backup_file"],
            **{f"dual_{index}": path for index, path in enumerate(dual_paths)},
        }
        try:
            ensure_distinct_artifact_paths(
                inputs=input_paths,
                outputs={
                    "release_manifest": output,
                    "fresh_import_report": options["fresh_import_report"],
                },
            )
            result = build_accounting_release_manifest(
                import_sqlite_path=options["import_sqlite"],
                latest_dual_run_sqlite_path=options["latest_dual_run_sqlite"],
                packet_path=options["packet"],
                signoff_report_path=options["signoff_report"],
                import_verification_path=options["import_verification"],
                restore_verification_path=options["restore_verification"],
                dual_run_report_paths=dual_paths,
                backup_manifest_path=options["backup_manifest"],
                backup_file_path=options["backup_file"],
                source_id=options["source_id"],
                tenant_id=options["tenant_id"],
                git_commit=options["git_commit"],
                image_digest=options["image_digest"],
                fresh_import_report_path=options["fresh_import_report"],
                fresh_dual_run_directory=options["fresh_dual_run_directory"],
            )
            written = write_private_text(
                output,
                json.dumps(
                    result.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    default=str,
                ) + "\n",
            )
        except (
            AccountingReleaseManifestError,
            AccountingCutoverSignoffError,
            AccountingImportError,
            BackupVerificationError,
            SecureReportIOError,
            DatabaseError,
            OSError,
            TypeError,
            ValueError,
        ) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"Private accounting release manifest: {written}")
        if result.decision != "GO":
            raise CommandError(
                "Accounting release manifest NO_GO: " + ", ".join(result.errors)
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Accounting release manifest GO: release_id={result.release_id}"
            )
        )
