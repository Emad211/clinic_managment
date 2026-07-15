from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from clinical.secure_report_io import (
    SecureReportIOError,
    ensure_distinct_artifact_paths,
    write_private_text,
)
from platform_core.backup_canonical import BackupVerificationError
from platform_core.backup_restore import verify_restored_backup


class Command(BaseCommand):
    help = (
        "Verify an explicitly named restored database against a private Halqe "
        "backup manifest and the exact custom-format dump bytes."
    )

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--backup-file", required=True)
        parser.add_argument("--restored-database", required=True)
        parser.add_argument("--confirm-restored-database", required=True)
        parser.add_argument("--report", required=True)
        parser.add_argument("--allow-same-database", action="store_true")

    def handle(self, *args, **options):
        manifest_path = Path(options["manifest"]).expanduser().absolute()
        backup_path = Path(options["backup_file"]).expanduser().absolute()
        report_path = Path(options["report"]).expanduser().absolute()
        try:
            ensure_distinct_artifact_paths(
                inputs={"manifest": manifest_path, "backup_file": backup_path},
                outputs={"verification_report": report_path},
            )
            result = verify_restored_backup(
                manifest_file=str(manifest_path),
                backup_file=str(backup_path),
                restored_database=options["restored_database"],
                confirmed_restored_database=options["confirm_restored_database"],
                allow_same_database=bool(options["allow_same_database"]),
            )
            rendered = json.dumps(
                result.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                default=str,
            ) + "\n"
            written = write_private_text(report_path, rendered)
        except (BackupVerificationError, SecureReportIOError, OSError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"Private restore verification report: {written}")
        if result.decision != "VERIFIED":
            raise CommandError(
                "Restored backup verification FAILED: " + ", ".join(result.errors)
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Restored backup VERIFIED for database {result.restored_database}"
            )
        )
