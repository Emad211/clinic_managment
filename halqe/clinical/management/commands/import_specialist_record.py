"""Management command for the specialist-clinic historical record ETL."""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from clinical.secure_report_io import (
    SecureReportIOError,
    ensure_distinct_artifact_paths,
    write_private_text,
)
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
        parser.add_argument("--sqlite", required=True, help="Path to a quiesced/copy of specialist.db.")
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
                "permissions 0600; newly-created parent directories use 0700."
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
        try:
            ensure_distinct_artifact_paths(
                inputs={"sqlite_source": options["sqlite"]},
                outputs={"import_report": options.get("report")},
            )
        except SecureReportIOError as exc:
            raise CommandError(str(exc)) from exc

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
            try:
                path = write_private_text(report_path, rendered + "\n")
            except SecureReportIOError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(f"Wrote private reconciliation report (0600): {path}")
