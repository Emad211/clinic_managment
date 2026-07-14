"""Stale-artifact regression tests for cutover-time reconciliation."""
from __future__ import annotations

import json

from clinical.secure_report_io import write_private_text
from clinical.specialist_record_fresh_verification import (
    run_fresh_import_verification,
)


def test_existing_fresh_report_is_removed_before_verifier_execution(
    tmp_path,
    monkeypatch,
):
    target = write_private_text(
        tmp_path / "fresh.json",
        json.dumps(
            {
                "decision": "GO",
                "source_id": "stale-source",
                "tenant_id": 1,
                "source_file_sha256": "a" * 64,
                "source_manifest_sha256": "b" * 64,
                "summary": {"passed": 1, "warnings": 0, "failed": 0},
                "checks": [
                    {"key": "stale", "status": "pass", "detail": "old"}
                ],
            },
            sort_keys=True,
        )
        + "\n",
    )
    stale_bytes = target.read_bytes()

    def verifier_writes_nothing(_name, **_kwargs):
        assert not target.exists(), "stale report must be removed before command call"

    monkeypatch.setattr(
        "clinical.specialist_record_fresh_verification.call_command",
        verifier_writes_nothing,
    )
    result = run_fresh_import_verification(
        sqlite_path=tmp_path / "source.db",
        apply_report_path=tmp_path / "apply.json",
        replay_report_path=tmp_path / "replay.json",
        saved_verification_report={
            "checks": [{"key": "stale", "status": "pass"}],
            "source_file_sha256": "a" * 64,
            "source_manifest_sha256": "b" * 64,
        },
        source_id="stale-source",
        tenant_id=1,
        report_path=target,
    )

    assert result.passed is False
    assert result.report_sha256 is None
    assert not target.exists()
    assert stale_bytes not in (target.read_bytes() if target.exists() else b"")
