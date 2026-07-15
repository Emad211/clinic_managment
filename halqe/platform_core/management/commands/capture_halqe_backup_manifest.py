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
from platform_core.backup_manifest import capture_backup_manifest


class Command(BaseCommand):
    help = (
        "Capture a PHI-free full-database fingerprint bound to an owner-only "
        "PostgreSQL custom-format dump."
    )

    def add_arguments(self, parser):
        parser.add_argument("--backup-file", required=True)
        parser.add_argument("--output", required=True)
        parser.add_argument("--database-name")
        parser.add_argument("--confirm-quiesced", action="store_true")

    def handle(self, *args, **options):
        backup = Path(options["backup_file"]).expanduser().absolute()
        output = Path(options["output"]).expanduser().absolute()
        try:
            ensure_distinct_artifact_paths(
                inputs={"backup_file": backup},
                outputs={"manifest": output},
            )
            manifest = capture_backup_manifest(
                backup_file=backup,
                confirmed_quiesced=bool(options["confirm_quiesced"]),
                database_name=options.get("database_name"),
            )
            rendered = json.dumps(
                manifest.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                default=str,
            ) + "\n"
            written = write_private_text(output, rendered)
        except (BackupVerificationError, SecureReportIOError, OSError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"Private backup manifest: {written}")
        self.stdout.write(
            self.style.SUCCESS(
                f"Backup manifest captured for database "
                f"{manifest.database['database_name']}: "
                f"{len(manifest.database['tables'])} tables, "
                f"{len(manifest.database['sequences'])} sequences"
            )
        )
