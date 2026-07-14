"""Regression tests preventing migration reports from overwriting evidence."""
from __future__ import annotations

import os

from django.core.management import call_command
from django.core.management.base import CommandError
import pytest

from clinical.secure_report_io import (
    SecureReportIOError,
    ensure_distinct_artifact_paths,
)


def test_direct_and_hardlink_aliases_are_rejected(tmp_path):
    source = tmp_path / "source.db"
    source.write_bytes(b"source-evidence")

    with pytest.raises(SecureReportIOError, match="must not overwrite"):
        ensure_distinct_artifact_paths(
            inputs={"source": source},
            outputs={"report": source},
        )

    alias = tmp_path / "source-hardlink.json"
    try:
        os.link(source, alias)
    except OSError as exc:
        pytest.skip(f"hard links are unavailable: {exc}")
    with pytest.raises(SecureReportIOError, match="must not overwrite"):
        ensure_distinct_artifact_paths(
            inputs={"source": source},
            outputs={"report": alias},
        )


def test_outputs_must_be_distinct_from_each_other(tmp_path):
    target = tmp_path / "same-output.json"
    with pytest.raises(SecureReportIOError, match="must be distinct"):
        ensure_distinct_artifact_paths(
            inputs={},
            outputs={"fresh": target, "manifest": target},
        )


def test_import_command_cannot_overwrite_sqlite_source(tmp_path):
    source = tmp_path / "specialist.db"
    original = b"SQLite format 3\x00do-not-overwrite"
    source.write_bytes(original)

    with pytest.raises(CommandError, match="must not overwrite"):
        call_command(
            "import_specialist_record",
            sqlite=str(source),
            source_id="collision-import",
            tenant_id=1,
            report=str(source),
            verbosity=0,
        )
    assert source.read_bytes() == original


def test_verifier_sample_and_signoff_commands_protect_input_artifacts(tmp_path):
    source = tmp_path / "source.db"
    apply = tmp_path / "apply.json"
    replay = tmp_path / "replay.json"
    verification = tmp_path / "verification.json"
    packet = tmp_path / "packet.json"
    for path in (source, apply, replay, verification, packet):
        path.write_text("{}", encoding="utf-8")

    with pytest.raises(CommandError, match="must not overwrite"):
        call_command(
            "verify_specialist_record_import",
            sqlite=str(source),
            apply_report=str(apply),
            replay_report=str(replay),
            source_id="collision-verifier",
            tenant_id=1,
            report=str(apply),
            verbosity=0,
        )

    with pytest.raises(CommandError, match="must not overwrite"):
        call_command(
            "generate_specialist_record_review_sample",
            verification_report=str(verification),
            source_id="collision-sample",
            tenant_id=1,
            report=str(verification),
            verbosity=0,
        )

    with pytest.raises(CommandError, match="must not overwrite"):
        call_command(
            "verify_specialist_record_clinician_signoff",
            review_packet=str(packet),
            verification_report=str(verification),
            source_id="collision-signoff",
            tenant_id=1,
            report=str(packet),
            verbosity=0,
        )


def test_release_command_protects_all_inputs_and_both_outputs(tmp_path):
    paths = {
        name: tmp_path / f"{name}.json"
        for name in (
            "source",
            "apply",
            "replay",
            "verification",
            "packet",
            "signoff",
        )
    }
    for path in paths.values():
        path.write_text("{}", encoding="utf-8")

    with pytest.raises(CommandError, match="must not overwrite"):
        call_command(
            "build_specialist_record_release_manifest",
            sqlite=str(paths["source"]),
            apply_report=str(paths["apply"]),
            replay_report=str(paths["replay"]),
            verification_report=str(paths["verification"]),
            review_packet=str(paths["packet"]),
            clinician_signoff_report=str(paths["signoff"]),
            source_id="collision-release",
            tenant_id=1,
            git_commit="a" * 40,
            fresh_verification_report=str(paths["verification"]),
            report=str(tmp_path / "manifest.json"),
            verbosity=0,
        )

    shared_output = tmp_path / "shared-output.json"
    with pytest.raises(CommandError, match="must be distinct"):
        call_command(
            "build_specialist_record_release_manifest",
            sqlite=str(paths["source"]),
            apply_report=str(paths["apply"]),
            replay_report=str(paths["replay"]),
            verification_report=str(paths["verification"]),
            review_packet=str(paths["packet"]),
            clinician_signoff_report=str(paths["signoff"]),
            source_id="collision-release",
            tenant_id=1,
            git_commit="a" * 40,
            fresh_verification_report=str(shared_output),
            report=str(shared_output),
            verbosity=0,
        )
