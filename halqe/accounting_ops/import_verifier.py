from __future__ import annotations

from pathlib import Path
from typing import Any

from django.db import connections, transaction

from accounting_ops.import_common import file_sha256, payload_sha256, source_key
from accounting_ops.import_engine import _load_rows
from accounting_ops.import_preflight import AccountingImportPreflight
from accounting_ops.import_verify_db import invoice_children, read_target, target_money
from accounting_ops.import_verify_models import VerificationReport


_SOURCE_TARGET = {
    "medical_staff": "accounting.medical_staff",
    "patients": "accounting.patients",
    "visit_tariffs": "accounting.visit_tariffs",
    "services": "accounting.services",
    "visit_items": "accounting.visit_items",
    "nursing_services": "accounting.nursing_services",
    "injection_types": "accounting.injection_types",
    "procedure_tariffs": "accounting.procedure_tariffs",
    "consumable_tariffs": "accounting.consumable_tariffs",
    "insurance_nursing_exclusions": "accounting.insurance_nursing_exclusions",
    "payroll_settings": "accounting.payroll_settings",
    "invoices": "accounting.invoices",
    "visits": "accounting.visits",
    "injections": "accounting.injections",
    "procedures": "accounting.procedures",
    "consumables_ledger": "accounting.consumables_ledger",
    "invoice_item_payments": "accounting.invoice_item_payments",
}


class AccountingImportVerifier:
    def __init__(self, *, sqlite_path: str | Path, source_id: str, tenant_id: int):
        self.path = Path(sqlite_path).expanduser().absolute()
        self.source_id = source_id.strip()
        self.tenant_id = int(tenant_id)
        if self.tenant_id <= 0:
            raise ValueError("tenant_id must be positive")

    def run(self) -> VerificationReport:
        preflight = AccountingImportPreflight(
            sqlite_path=self.path,
            source_id=self.source_id,
        ).run()
        report = VerificationReport(
            source_id=self.source_id,
            source_path=str(self.path),
            tenant_id=self.tenant_id,
            source_file_sha256=preflight.source_file_sha256,
            source_manifest_sha256=preflight.source_manifest_sha256,
            source_money=dict(preflight.money),
        )
        report.check(
            "source_preflight",
            preflight.decision == "GO",
            "Source snapshot must still pass the no-write preflight",
            preflight_decision=preflight.decision,
        )
        if preflight.decision != "GO":
            return report.finalize()

        rows = _load_rows(self.path)
        source_digests: dict[tuple[str, str], str] = {}
        for table, table_rows in rows.items():
            for row in table_rows:
                source_digests[(table, source_key(table, row))] = payload_sha256(row)
        report.source_rows = len(source_digests)

        target_payloads: dict[tuple[str, str], dict[str, Any]] = {}
        with transaction.atomic(using="accounting_read"):
            with connections["accounting_read"].cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('app.current_tenant', %s, true)",
                    [str(self.tenant_id)],
                )
                cursor.execute(
                    """
                    SELECT source_table,source_key,target_table,target_key,
                           source_sha256,target_sha256
                    FROM accounting.accounting_import_ledger
                    WHERE tenant_id=%s AND source_id=%s
                    ORDER BY source_table,source_key
                    """,
                    [self.tenant_id, self.source_id],
                )
                columns = (
                    "source_table", "source_key", "target_table", "target_key",
                    "source_sha256", "target_sha256",
                )
                entries = [dict(zip(columns, row)) for row in cursor.fetchall()]
                ledger = {
                    (entry["source_table"], entry["source_key"]): entry
                    for entry in entries
                }
                report.ledger_rows = len(entries)
                source_keys = set(source_digests)
                ledger_keys = set(ledger)
                report.check(
                    "ledger_coverage",
                    source_keys == ledger_keys,
                    "Ledger keys must exactly cover current source rows",
                    missing=len(source_keys - ledger_keys),
                    extra=len(ledger_keys - source_keys),
                )

                source_digest_errors = 0
                target_table_errors = 0
                target_digest_errors = 0
                missing_targets = 0
                for identity in sorted(source_keys & ledger_keys):
                    entry = ledger[identity]
                    if entry["source_sha256"] != source_digests[identity]:
                        source_digest_errors += 1
                    if entry["target_table"] != _SOURCE_TARGET[identity[0]]:
                        target_table_errors += 1
                    payload = read_target(
                        cursor,
                        tenant_id=self.tenant_id,
                        table=entry["target_table"],
                        key=entry["target_key"],
                    )
                    if payload is None:
                        missing_targets += 1
                        continue
                    target_payloads[identity] = payload
                    if payload_sha256(payload) != entry["target_sha256"]:
                        target_digest_errors += 1

                report.target_rows = len(target_payloads)
                report.check(
                    "source_digest_continuity",
                    source_digest_errors == 0,
                    "Every source row digest must match its committed ledger entry",
                    mismatches=source_digest_errors,
                )
                report.check(
                    "target_table_continuity",
                    target_table_errors == 0,
                    "Every source table must remain mapped to its approved target table",
                    mismatches=target_table_errors,
                )
                report.check(
                    "target_fingerprint_continuity",
                    missing_targets == 0 and target_digest_errors == 0,
                    "Every target row must exist and match its committed fingerprint",
                    missing=missing_targets,
                    mismatches=target_digest_errors,
                )

                invoice_ids = [
                    int(entry["target_key"])
                    for entry in entries
                    if entry["source_table"] == "invoices"
                ]
                actual_children = invoice_children(
                    cursor,
                    tenant_id=self.tenant_id,
                    invoice_ids=invoice_ids,
                )
                child_errors: dict[str, dict[str, int]] = {}
                for child in (
                    "visits", "injections", "procedures", "consumables_ledger"
                ):
                    expected = {
                        ledger[identity]["target_key"]
                        for identity, payload in target_payloads.items()
                        if identity[0] == child
                        and payload.get("invoice_id") in invoice_ids
                    }
                    actual = actual_children[child]
                    if expected != actual:
                        child_errors[child] = {
                            "missing": len(expected - actual),
                            "extra": len(actual - expected),
                        }
                expected_payments = {
                    entry["target_key"]
                    for entry in entries
                    if entry["source_table"] == "invoice_item_payments"
                }
                if expected_payments != actual_children["invoice_item_payments"]:
                    child_errors["invoice_item_payments"] = {
                        "missing": len(
                            expected_payments - actual_children["invoice_item_payments"]
                        ),
                        "extra": len(
                            actual_children["invoice_item_payments"] - expected_payments
                        ),
                    }
                report.check(
                    "invoice_child_completeness",
                    not child_errors,
                    "Imported invoices must have exactly the ledger-bound items and payments",
                    mismatches=child_errors,
                )

                report.target_money = target_money(
                    cursor,
                    tenant_id=self.tenant_id,
                    entries=entries,
                )
                report.check(
                    "money_reconciliation",
                    report.target_money == report.source_money,
                    "Imported-scope target money must equal the current source snapshot",
                    source=report.source_money,
                    target=report.target_money,
                )

        report.check(
            "source_immutable",
            file_sha256(self.path) == preflight.source_file_sha256,
            "Source snapshot must remain byte-identical during verification",
        )
        return report.finalize()
