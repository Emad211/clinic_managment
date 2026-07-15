from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from accounting_ops.release_artifacts import ReleaseArtifacts
from platform_core.backup_canonical import file_sha256


class FreshImport:
    decision = "VERIFIED"
    errors: list[str] = []
    checks = [SimpleNamespace(status="PASS")]

    def to_dict(self):
        return {
            "decision": "VERIFIED",
            "errors": [],
            "checks": [{"status": "PASS"}],
        }


class Verifier:
    def __init__(self, **_kwargs):
        pass

    def run(self):
        return FreshImport()


class FreshDual:
    decision = "GO"
    differences: list[object] = []
    errors: list[str] = []

    def __init__(self, source_hash: str):
        self.source_file_sha256 = source_hash
        self.source_manifest_sha256 = "daily-manifest"

    def to_dict(self):
        return {
            "decision": "GO",
            "differences": [],
            "errors": [],
            "source_file_sha256": self.source_file_sha256,
            "source_manifest_sha256": self.source_manifest_sha256,
        }


def release_artifacts(
    import_source: Path,
    latest_source: Path,
    *,
    latest_hash: str | None = None,
) -> ReleaseArtifacts:
    source_hash = latest_hash or file_sha256(latest_source)
    dual = {
        f"2026-07-04:{scope}": {
            "source_file_sha256": source_hash,
            "source_manifest_sha256": "daily-manifest",
        }
        for scope in ("all", "morning", "evening", "night")
    }
    return ReleaseArtifacts(
        packet={},
        saved_signoff={"decision": "GO"},
        import_verification={"source_file_sha256": file_sha256(import_source)},
        restore_verification={"decision": "VERIFIED"},
        dual_reports=dual,
        hashes={
            "signoff_packet": "packet-digest",
            "signoff_report": "signoff-digest",
            "import_verification": "import-digest",
            "restore_verification": "restore-digest",
            "dual_run_reports": {key: "dual-digest" for key in dual},
            "backup_manifest": "manifest-digest",
            "backup_file": "backup-digest",
        },
        latest_date=date(2026, 7, 4),
    )
