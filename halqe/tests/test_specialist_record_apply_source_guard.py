"""Fail-closed source-snapshot guards for committed specialist imports."""
from __future__ import annotations

from pathlib import Path

import pytest

from clinical.specialist_record_import import (
    SourceDatabaseError,
    SpecialistRecordImporter,
)


def _importer(source: Path, *, apply: bool, allow_live_source: bool = False):
    return SpecialistRecordImporter(
        sqlite_path=source,
        source_id="apply-source-guard",
        tenant_id=1,
        apply=apply,
        allow_live_source=allow_live_source,
    )


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_apply_never_accepts_allow_live_source(seed_data, tmp_path):
    source = tmp_path / "specialist.db"
    source.write_bytes(b"not-opened-because-guard-runs-first")
    importer = _importer(source, apply=True, allow_live_source=True)

    with pytest.raises(SourceDatabaseError, match="never permitted"):
        importer.run()
    assert importer.report.transaction_status == "failed_no_commit"


@pytest.mark.django_db(databases=["default", "accounting_read"])
@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_nonempty_sqlite_sidecar_blocks_apply_before_target_writes(
    seed_data,
    tmp_path,
    suffix,
):
    source = tmp_path / "specialist.db"
    source.write_bytes(b"not-opened-because-sidecar-guard-runs-first")
    Path(str(source) + suffix).write_bytes(b"active-sidecar")
    importer = _importer(source, apply=True)

    with pytest.raises(SourceDatabaseError, match="quiesced SQLite snapshot"):
        importer.run()
    assert importer.report.transaction_status == "failed_no_commit"


def test_dry_run_may_explicitly_inspect_live_source_for_diagnostics(tmp_path):
    source = tmp_path / "specialist.db"
    source.write_bytes(b"diagnostic-only")
    Path(str(source) + "-wal").write_bytes(b"active-wal")
    importer = _importer(source, apply=False, allow_live_source=True)

    # This unit verifies the production guard distinction. The subsequent SQLite
    # integrity/schema checks remain responsible for accepting or rejecting the
    # diagnostic dry run itself.
    importer._assert_apply_source_is_quiesced()
