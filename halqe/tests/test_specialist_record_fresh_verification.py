"""Tests for the fresh pre-cutover database reconciliation helper."""
from __future__ import annotations

import json
import os
from pathlib import Path

from django.core.management.base import CommandError
import pytest

from clinical.secure_report_io import write_private_text
from clinical.specialist_record_fresh_verification import (
    run_fresh_import_verification,
)


SOURCE_ID = "fresh-verification-test"
SOURCE_HASH = "a" * 64
MANIFEST_HASH = "b" * 64


def _report(*, status: str = "pass", source_hash: str = SOURCE_HASH) -> dict:
    return {
        "decision": "GO" if status == "pass" else "NO_GO",
        "source_id": SOURCE_ID,
        "tenant_id": 1,
        "source_file_sha256": source_hash,
        "source_manifest_sha256": MANIFEST_HASH,
        "summary": {
            "passed": 2 if status == "pass" else 1,
            "warnings": 0,
            "failed": 0 if status == "pass" else 1,
        },
        "checks": [
            {"key": "ledger_targets", "status": status, "detail": "ledger"},
            {"key": "target_fingerprints", "status": "pass", "detail": "rows"},
        ],
    }


def _run(tmp_path: Path, monkeypatch, fresh_payload: dict, *, command_error=False):
    output = tmp_path / "fresh.json"

    def fake_call_command(_name, **kwargs):
        assert _name == "verify_specialist_record_import"
        write_private_text(
            kwargs["report"],
            json.dumps(fresh_payload, sort_keys=True) + "\n",
        )
        if command_error:
            raise CommandError("fresh verifier NO_GO")

    monkeypatch.setattr(
        "clinical.specialist_record_fresh_verification.call_command",
        fake_call_command,
    )
    result = run_fresh_import_verification(
        sqlite_path=tmp_path / "source.db",
        apply_report_path=tmp_path / "apply.json",
        replay_report_path=tmp_path / "replay.json",
        saved_verification_report=_report(),
        source_id=SOURCE_ID,
        tenant_id=1,
        report_path=output,
    )
    return result, output


def test_fresh_go_matching_saved_check_contract_passes(tmp_path, monkeypatch):
    result, output = _run(tmp_path, monkeypatch, _report())

    assert result.passed is True
    assert result.report_path == output
    assert len(result.report_sha256 or "") == 64
    assert len(result.semantic_fingerprint or "") == 64
    assert result.payload["decision"] == "GO"
    assert "matches the saved verifier" in result.detail


def test_fresh_command_no_go_fails_even_when_report_is_written(tmp_path, monkeypatch):
    result, _output = _run(
        tmp_path,
        monkeypatch,
        _report(status="fail"),
        command_error=True,
    )
    assert result.passed is False
    assert "verifier-command-returned-NO_GO" in result.detail
    assert "fresh-verifier-not-clean-GO" in result.detail


def test_fresh_source_hash_drift_fails(tmp_path, monkeypatch):
    result, _output = _run(
        tmp_path,
        monkeypatch,
        _report(source_hash="c" * 64),
    )
    assert result.passed is False
    assert "fresh-source-hash-differs" in result.detail


def test_fresh_check_status_contract_drift_fails(tmp_path, monkeypatch):
    fresh = _report()
    fresh["checks"].append(
        {"key": "new_release_gate", "status": "pass", "detail": "new"}
    )
    result, _output = _run(tmp_path, monkeypatch, fresh)
    assert result.passed is False
    assert "fresh-check-status-map-differs" in result.detail


def test_missing_or_public_fresh_report_fails_closed(tmp_path, monkeypatch):
    def no_report(_name, **_kwargs):
        return None

    monkeypatch.setattr(
        "clinical.specialist_record_fresh_verification.call_command",
        no_report,
    )
    result = run_fresh_import_verification(
        sqlite_path=tmp_path / "source.db",
        apply_report_path=tmp_path / "apply.json",
        replay_report_path=tmp_path / "replay.json",
        saved_verification_report=_report(),
        source_id=SOURCE_ID,
        tenant_id=1,
        report_path=tmp_path / "missing.json",
    )
    assert result.passed is False
    assert result.report_sha256 is None

    def public_report(_name, **kwargs):
        path = Path(kwargs["report"])
        path.write_text(json.dumps(_report()), encoding="utf-8")
        os.chmod(path, 0o644)

    monkeypatch.setattr(
        "clinical.specialist_record_fresh_verification.call_command",
        public_report,
    )
    result = run_fresh_import_verification(
        sqlite_path=tmp_path / "source.db",
        apply_report_path=tmp_path / "apply.json",
        replay_report_path=tmp_path / "replay.json",
        saved_verification_report=_report(),
        source_id=SOURCE_ID,
        tenant_id=1,
        report_path=tmp_path / "public.json",
    )
    assert result.passed is False
    assert "owner-only" in result.detail
