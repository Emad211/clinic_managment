from __future__ import annotations

import stat

from accounting_ops.release_manifest import build_accounting_release_manifest
from platform_core.backup_canonical import file_sha256
from tests.accounting_release_fakes import FreshDual, Verifier, release_artifacts


def _run(tmp_path, monkeypatch):
    import_source = tmp_path / "import.db"
    latest_source = tmp_path / "latest.db"
    import_source.write_bytes(b"import-source")
    latest_source.write_bytes(b"latest-source")
    evidence = release_artifacts(import_source, latest_source)
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
    fresh_import = tmp_path / "fresh" / "import.json"
    fresh_dual = tmp_path / "fresh" / "dual"
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
        fresh_import_report_path=fresh_import,
        fresh_dual_run_directory=fresh_dual,
    )
    return result, fresh_import, fresh_dual


def test_release_manifest_is_go_deterministic_and_private(tmp_path, monkeypatch):
    first, fresh_import, fresh_dual = _run(tmp_path, monkeypatch)
    assert first.decision == "GO", first.errors
    assert len(first.release_id) == 64
    assert stat.S_IMODE(fresh_import.stat().st_mode) == 0o600
    assert set(first.fresh_dual_run_sha256) == {"all", "morning", "evening", "night"}
    for scope in first.fresh_dual_run_sha256:
        path = fresh_dual / f"fresh-dual-{scope}.json"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    second, _fresh_import, _fresh_dual = _run(tmp_path, monkeypatch)
    assert second.release_id == first.release_id
