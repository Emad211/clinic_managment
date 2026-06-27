"""
tests/test_apply_schema_ledger.py — Step 67 (schema-version ledger).

WHAT THIS TESTS
───────────────
apply_schema now records every applied `schema_pg_slice*.sql` file (filename +
sha256 checksum + applied_at) into a `platform.schema_version` bookkeeping
table — the command's OWN ledger, created after the slice loop (so the
`platform` schema exists), idempotent on re-run.

  T1. After a fresh apply, platform.schema_version exists and has EXACTLY one
      row per slice file on disk (count matches the glob), every row has a
      non-empty checksum and a non-null applied_at.
  T2. Idempotency: running apply_schema a SECOND time does not error and does
      not duplicate rows (still one row per file), and applied_at is refreshed
      (>= the first run's applied_at).

STRATEGY
────────
- Provision a THROWAWAY DB (`halqe_ledger_check`) via superuser psycopg
  (terminate backends + DROP + CREATE), exactly like conftest.django_db_setup
  and the slice15 idempotency check do — NEVER the shared `halqe_app_test` DB
  the suites use.
- Run the REAL command against it by adding a temporary Django DATABASES alias
  pointing at the throwaway DB, then `call_command('apply_schema',
  database=<alias>)`.  apply_schema itself overrides USER/PASSWORD with the
  PG_USER/PG_PASSWORD superuser env (needed for DDL/GRANT/CREATE ROLE), so the
  alias only needs the right NAME/HOST/PORT.
- Verify with independent superuser psycopg connections to the throwaway DB.
- This test is NOT @pytest.mark.django_db: it does not touch the session test
  DB or the autouse tenant-GUC fixture; it owns its own throwaway DB lifecycle.
- Drop the throwaway DB in finally.

Run SOLO (never two DB-test processes at once):
  cd halqe && PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -q \
      -p no:cacheprovider tests/test_apply_schema_ledger.py
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import psycopg
import pytest

from django.conf import settings
from django.core.management import call_command

# ---------------------------------------------------------------------------
# Throwaway DB + superuser coordinates (mirror conftest / settings defaults)
# ---------------------------------------------------------------------------
LEDGER_DB_NAME = "halqe_ledger_check"
PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = os.environ.get("PG_PORT", "55432")
PG_SU_USER = os.environ.get("PG_USER", "postgres")
PG_SU_PASSWORD = os.environ.get("PG_PASSWORD", "validate_only")

_ALIAS = "ledger_check"


def _su_conninfo(dbname: str) -> str:
    return (
        f"host='{PG_HOST}' port='{PG_PORT}' "
        f"user='{PG_SU_USER}' password='{PG_SU_PASSWORD}' dbname='{dbname}'"
    )


def _slice_files() -> list[Path]:
    """All schema_pg_slice*.sql files, numeric-aware (same key apply_schema uses)."""
    slice_dir = Path(settings.SCHEMA_SLICE_DIR)

    def _order(p: Path):
        m = re.search(r"schema_pg_slice(\d+)([a-z]*)", p.name)
        return (int(m.group(1)), m.group(2)) if m else (9999, p.name)

    files = sorted(slice_dir.glob("schema_pg_slice*.sql"), key=_order)
    assert files, f"No slice files found in {slice_dir}"
    return files


def _create_throwaway_db() -> None:
    with psycopg.connect(_su_conninfo("postgres"), autocommit=True) as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname=%s AND pid <> pg_backend_pid()",
            (LEDGER_DB_NAME,),
        )
        conn.execute(f"DROP DATABASE IF EXISTS {LEDGER_DB_NAME}")
        conn.execute(f"CREATE DATABASE {LEDGER_DB_NAME}")


def _drop_throwaway_db() -> None:
    with psycopg.connect(_su_conninfo("postgres"), autocommit=True) as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname=%s AND pid <> pg_backend_pid()",
            (LEDGER_DB_NAME,),
        )
        conn.execute(f"DROP DATABASE IF EXISTS {LEDGER_DB_NAME}")


@pytest.fixture()
def throwaway_db(monkeypatch):
    """
    Create the throwaway DB and register a Django DATABASES alias pointing at it
    so call_command('apply_schema', database=_ALIAS) targets the right DB.

    apply_schema needs SUPERUSER for DDL/GRANT/CREATE ROLE; it picks the
    superuser up ONLY from the PG_USER/PG_PASSWORD env vars (it overrides
    USER/PASSWORD on the alias when those are set). The CI/dev shell that runs
    the suite normally has them; we set them here to the same defaults the rest
    of the suite uses so this test is self-contained either way.
    """
    monkeypatch.setenv("PG_USER", PG_SU_USER)
    monkeypatch.setenv("PG_PASSWORD", PG_SU_PASSWORD)

    _create_throwaway_db()
    # Clone the 'default' entry (engine/options) but point NAME at the throwaway
    # DB. apply_schema swaps in the superuser env (above) for the actual DDL.
    alias_conf = dict(settings.DATABASES["default"])
    alias_conf["NAME"] = LEDGER_DB_NAME
    settings.DATABASES[_ALIAS] = alias_conf
    try:
        yield
    finally:
        settings.DATABASES.pop(_ALIAS, None)
        _drop_throwaway_db()


def _ledger_rows():
    with psycopg.connect(_su_conninfo(LEDGER_DB_NAME), autocommit=True) as conn:
        return conn.execute(
            "SELECT filename, checksum, applied_at "
            "FROM platform.schema_version ORDER BY filename"
        ).fetchall()


def _ledger_table_exists() -> bool:
    with psycopg.connect(_su_conninfo(LEDGER_DB_NAME), autocommit=True) as conn:
        row = conn.execute(
            "SELECT to_regclass('platform.schema_version')"
        ).fetchone()
    return row is not None and row[0] is not None


# ===========================================================================
# T1 — fresh apply records one ledger row per slice file, fully populated
# ===========================================================================
def test_ledger_records_every_slice(throwaway_db):
    slice_files = _slice_files()
    expected_names = {p.name for p in slice_files}

    call_command("apply_schema", database=_ALIAS, verbosity=0)

    # Table exists.
    assert _ledger_table_exists(), (
        "platform.schema_version must exist after apply_schema"
    )

    rows = _ledger_rows()
    got_names = {r[0] for r in rows}

    # Exactly one row per slice file.
    assert len(rows) == len(slice_files), (
        f"expected {len(slice_files)} ledger rows (one per slice), "
        f"got {len(rows)}: {sorted(got_names)}"
    )
    assert got_names == expected_names, (
        f"ledger filenames must match the slice files exactly.\n"
        f"missing: {expected_names - got_names}\n"
        f"unexpected: {got_names - expected_names}"
    )

    # Every row: non-empty checksum + non-null applied_at.
    for filename, checksum, applied_at in rows:
        assert checksum, f"{filename}: checksum must be non-empty"
        assert len(checksum) == 64, (
            f"{filename}: checksum must be a sha256 hexdigest (64 chars), "
            f"got {len(checksum)}"
        )
        assert applied_at is not None, f"{filename}: applied_at must be non-null"


# ===========================================================================
# T2 — second apply is idempotent: no duplicates, applied_at refreshed
# ===========================================================================
def test_ledger_idempotent_second_run(throwaway_db):
    slice_files = _slice_files()

    # First run.
    call_command("apply_schema", database=_ALIAS, verbosity=0)
    first = {r[0]: (r[1], r[2]) for r in _ledger_rows()}
    assert len(first) == len(slice_files)

    # Second run must NOT error and must NOT duplicate rows.
    call_command("apply_schema", database=_ALIAS, verbosity=0)
    second_rows = _ledger_rows()
    second = {r[0]: (r[1], r[2]) for r in second_rows}

    # Still exactly one row per file (no duplicates — PRIMARY KEY on filename).
    assert len(second_rows) == len(slice_files), (
        f"second run must not duplicate rows: expected {len(slice_files)}, "
        f"got {len(second_rows)}"
    )
    assert set(second) == set(first), "filenames must be unchanged across runs"

    # Checksums unchanged (same files); applied_at refreshed (>= first run).
    for filename, (chk1, at1) in first.items():
        chk2, at2 = second[filename]
        assert chk2 == chk1, f"{filename}: checksum changed unexpectedly"
        assert at2 >= at1, (
            f"{filename}: applied_at must be refreshed on re-run "
            f"(was {at1}, now {at2})"
        )
