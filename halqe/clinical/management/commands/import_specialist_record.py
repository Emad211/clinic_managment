"""Management command for the specialist-clinic historical record ETL."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from django.core.management.base import BaseCommand, CommandError

from clinical.specialist_record_import import (
    SpecialistRecordImportError,
    SpecialistRecordImporter,
)


class Command(BaseCommand):
    help = (
        "Dry-run or apply an idempotent historical patient-record import from "
        "specialist_clinic's SQLite database into one Halqe tenant."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--sqlite",
            required=True,
            help="Path to a quiesced/copy of specialist.db.",
        )
        parser.add_argument(
            "--source-id",
            required=True,
            help=(
                "Stable human-assigned identity for this source database, for "
                "example clinic-a-specialist-2026. Never reuse it for another DB."
            ),
        )
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Commit target rows. Without this flag the command is a no-write dry run.",
        )
        parser.add_argument(
            "--skip-unresolved",
            action="store_true",
            help=(
                "Skip source patients that cannot be resolved to accounting.patients, "
                "and all child rows belonging to them. Default is fail-closed."
            ),
        )
        parser.add_argument(
            "--acknowledge-financial-data-out-of-scope",
            action="store_true",
            help=(
                "Required for --apply when the source contains wallet balances or "
                "wallet_transactions. These financial rows are reported but never "
                "imported by the patient-record ETL."
            ),
        )
        parser.add_argument(
            "--allow-live-source",
            action="store_true",
            help=(
                "Allow a source with a non-empty SQLite WAL. Prefer a quiesced copy; "
                "this flag is an explicit exception."
            ),
        )
        parser.add_argument(
            "--imported-by",
            default="specialist-record-etl",
            help="Operator/service identity stored in the append-only ledger.",
        )
        parser.add_argument(
            "--report",
            help=(
                "Optional JSON report path. The file is replaced atomically with "
                "permissions 0600; parent directories are created."
            ),
        )
        parser.add_argument(
            "--print-report",
            action="store_true",
            help=(
                "Print the complete redacted JSON report to stdout. Disabled by "
                "default so generic shell/CI logs receive only a compact summary."
            ),
        )

    def handle(self, *args, **options):
        importer = SpecialistRecordImporter(
            sqlite_path=options["sqlite"],
            source_id=options["source_id"],
            tenant_id=options["tenant_id"],
            apply=options["apply"],
            skip_unresolved=options["skip_unresolved"],
            acknowledge_financial_data_out_of_scope=options[
                "acknowledge_financial_data_out_of_scope"
            ],
            allow_live_source=options["allow_live_source"],
            imported_by=options["imported_by"],
        )
        try:
            report = importer.run()
        except SpecialistRecordImportError as exc:
            importer.report.error = str(exc)
            self._emit(
                importer.report.to_dict(),
                options.get("report"),
                print_report=options["print_report"],
            )
            raise CommandError(str(exc)) from exc

        payload = report.to_dict()
        self._emit(
            payload,
            options.get("report"),
            print_report=options["print_report"],
        )
        action = "committed" if options["apply"] else "validated (dry-run; no writes)"
        total = sum(table["source_rows"] for table in payload["tables"].values())
        self.stdout.write(
            self.style.SUCCESS(
                f"Specialist record import {action}: source_id={report.source_id}, "
                f"tenant={report.tenant_id}, source_rows={total}, "
                f"manifest={report.source_manifest_sha256}"
            )
        )

    def _emit(
        self,
        payload: dict,
        report_path: str | None,
        *,
        print_report: bool,
    ) -> None:
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        if print_report:
            self.stdout.write(rendered)
        if report_path:
            path = Path(report_path).expanduser().absolute()
            self._write_private_report(path, rendered + "\n")
            self.stdout.write(f"Wrote private reconciliation report (0600): {path}")

    @staticmethod
    def _write_private_report(path: Path, content: str) -> None:
        """Atomically replace a regular report file with owner-only permissions."""
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise CommandError(
                f"Refusing to write reconciliation report through a symlink: {path}"
            )
        if path.exists() and not path.is_file():
            raise CommandError(
                f"Reconciliation report path is not a regular file: {path}"
            )

        fd: int | None = None
        temporary_name: str | None = None
        try:
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=path.parent,
                text=True,
            )
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                fd = None
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
            temporary_name = None
            os.chmod(path, 0o600)
        except OSError as exc:
            raise CommandError(f"Failed to write reconciliation report: {exc}") from exc
        finally:
            if fd is not None:
                os.close(fd)
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
