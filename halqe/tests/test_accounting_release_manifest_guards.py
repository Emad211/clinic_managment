from __future__ import annotations

import pytest

from accounting_ops.release_manifest import (
    AccountingReleaseManifestError,
    build_accounting_release_manifest,
)
from platform_core.backup_canonical import file_sha256
from tests.accounting_release_fakes import FreshDual, Verifier, release_artifacts


def test_latest_signed_snapshot_mismatch_is_no_go(tmp_path, monkeypatch):
    import_source = tmp_path / "import.db"
    latest_source = tmp_path / "latest.db"
    import_source.write_bytes(b"import-source")
    latest_source.write_bytes(b"latest-source")
    evidence = release_artifacts(
        import_source,
        latest_source,
        latest_hash="signed-different-snapshot",
    )
    monkeypatch.setattr(
        "accounting_ops.release_manifest.load_release_artifacts",
        lambda **_kwargs: evidence,
    )
    monkeypatch.setattr(
        "accounting_ops.release_manifest.AccountingImportVerifier",
        Verifier,
    )
    monkeypatch.setattr(
        "accounting_ops.release_manifest.compare_accounting_dual_run",
        lambda **_kwargs: FreshDual(file_sha256(latest_source)),
    )
    result = build_accounting_release_manifest(
        import_sqlite_path=import_source,
        latest_dual_run_sqlite_path=latest_source,
        packet_path=tmp_path / "packet.json",
        signoff_report_path=tmp_path / "signoff.json",
        import_verification_path=tmp_path / "verify.json",
        restore_verification_path=tmp_path / "restore.json",
        dual_run_report_paths=[tmp_path / "dual.json"],
        backup_manifest_path=tmp_path / "backup-manifest.json",
        backup_file_path=tmp_path / "backup.dump",
        source_id="release-source",
        tenant_id=1,
        git_commit="b" * 40,
        image_digest="sha256:" + ("a" * 64),
        fresh_import_report_path=tmp_path / "fresh-import.json",
        fresh_dual_run_directory=tmp_path / "fresh-dual",
    )
    assert result.decision == "NO_GO"
    assert "latest_dual_run_snapshot_identity" in result.errors
    assert "fresh_latest_dual_run" in result.errors


def test_release_rejects_branch_name_or_mutable_image_tag(tmp_path):
    with pytest.raises(AccountingReleaseManifestError, match="git_commit"):
        build_accounting_release_manifest(
            import_sqlite_path=tmp_path / "a",
            latest_dual_run_sqlite_path=tmp_path / "b",
            packet_path=tmp_path / "c",
            signoff_report_path=tmp_path / "d",
            import_verification_path=tmp_path / "e",
            restore_verification_path=tmp_path / "f",
            dual_run_report_paths=[],
            backup_manifest_path=tmp_path / "g",
            backup_file_path=tmp_path / "h",
            source_id="release-source",
            tenant_id=1,
            git_commit="main",
            image_digest="latest",
            fresh_import_report_path=tmp_path / "i",
            fresh_dual_run_directory=tmp_path / "j",
        )
