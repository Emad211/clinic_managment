"""Caller-owned SQLite transactions are never committed by legacy cleanup."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))

from src.adapters.sqlite.clinical_engine_legacy_cleanup_schema import (
    LegacyClinicalCleanupTransactionActive,
    cleanup_legacy_clinical_schema,
)


def test_cleanup_refuses_and_preserves_caller_owned_transaction(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "active-transaction.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "cleanup-transaction-test",
        }
    )
    try:
        with app.app_context():
            db = core.get_db()
            db.execute(
                """INSERT INTO patient_links
                   (national_id, full_name, enrolled_by)
                   VALUES ('TX-CLEANUP', 'Uncommitted Patient', 'pytest')"""
            )
            assert db.in_transaction is True

            with pytest.raises(
                LegacyClinicalCleanupTransactionActive,
                match="idle SQLite connection",
            ):
                cleanup_legacy_clinical_schema(db)

            assert db.in_transaction is True
            assert db.execute(
                "SELECT COUNT(*) AS count FROM patient_links "
                "WHERE national_id='TX-CLEANUP'"
            ).fetchone()["count"] == 1
            db.rollback()
            assert db.execute(
                "SELECT COUNT(*) AS count FROM patient_links "
                "WHERE national_id='TX-CLEANUP'"
            ).fetchone()["count"] == 0
    finally:
        core._initialized = False
