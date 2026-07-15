from __future__ import annotations

from io import StringIO
import json
import os
import stat

from django.core.management import call_command
from django.core.management.base import CommandError
import pytest

from accounting_ops.cutover_signoff import verify_accounting_cutover_signoff
from tests.accounting_cutover_artifacts import (
    SOURCE_ID,
    TENANT_ID,
    build_cutover_artifacts,
)


def _verify(artifacts):
    return verify_accounting_cutover_signoff(
        packet_path=artifacts["packet"],
        import_verification_path=artifacts["import_report"],
        restore_verification_path=artifacts["restore_report"],
        dual_run_report_paths=artifacts["dual_reports"],
        source_id=SOURCE_ID,
        tenant_id=TENANT_ID,
    )


def test_complete_consecutive_evidence_chain_is_go(tmp_path):
    artifacts = build_cutover_artifacts(tmp_path / "go", days=2)
    report = _verify(artifacts)
    assert report.decision == "GO", report.errors
    assert report.observed_dates == ["2026-07-01", "2026-07-02"]
    assert {item.status for item in report.checks} == {"PASS"}
    assert len(report.artifact_sha256["dual_run_reports"]) == 8


def test_missing_shift_and_failed_restore_are_no_go(tmp_path):
    artifacts = build_cutover_artifacts(
        tmp_path / "missing",
        days=2,
        omit="2026-07-02:night",
        restore_decision="FAILED",
    )
    report = _verify(artifacts)
    assert report.decision == "NO_GO"
    assert "dual_run_scope_coverage" in report.errors
    assert "backup_restore_verification" in report.errors


def test_tampered_dual_report_and_sensitive_packet_key_are_no_go(tmp_path):
    artifacts = build_cutover_artifacts(
        tmp_path / "tamper",
        days=1,
        include_sensitive_key=True,
    )
    dual_path = artifacts["dual_reports"][0]
    payload = json.loads(dual_path.read_text(encoding="utf-8"))
    payload["financial_target"]["totals"]["invoice_amount"] += 1
    dual_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.chmod(dual_path, 0o600)

    report = _verify(artifacts)
    assert report.decision == "NO_GO"
    assert "artifact_hash_binding" in report.errors
    assert "dual_run_reports" in report.errors
    assert "packet_phi_free" in report.errors


def test_deferred_discrepancy_and_failed_import_are_no_go(tmp_path):
    artifacts = build_cutover_artifacts(
        tmp_path / "deferred",
        days=1,
        import_decision="FAILED",
        discrepancy_status="deferred",
    )
    report = _verify(artifacts)
    assert report.decision == "NO_GO"
    assert "import_verification" in report.errors
    assert "discrepancies_closed" in report.errors


def test_command_writes_private_report_before_nonzero_no_go(tmp_path):
    artifacts = build_cutover_artifacts(
        tmp_path / "command",
        days=1,
        omit="2026-07-01:night",
    )
    output = tmp_path / "private" / "signoff-report.json"
    with pytest.raises(CommandError, match="NO_GO"):
        call_command(
            "verify_accounting_cutover_signoff",
            packet=str(artifacts["packet"]),
            import_verification=str(artifacts["import_report"]),
            restore_verification=str(artifacts["restore_report"]),
            dual_run_reports=[str(path) for path in artifacts["dual_reports"]],
            source_id=SOURCE_ID,
            tenant_id=TENANT_ID,
            report=str(output),
            stdout=StringIO(),
        )
    assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(output.read_text(encoding="utf-8"))["decision"] == "NO_GO"
