"""Fact-contract changes must invalidate runs produced by the previous engine build."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))

from src.adapters.sqlite.clinical_engine_audit_repo import (
    ClinicalEngineAuditRepository,
)
from src.adapters.sqlite.clinical_engine_runtime_repo import (
    ClinicalEngineRuntimeRepository,
)
from src.domain.clinical_engine import RunStatus
from src.services.clinical_engine.fact_builder import ENGINE_VERSION


@pytest.fixture()
def engine_identity_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True,
        "CLINICAL_ENGINE_ALLOW_LEGACY_TEST_RUNS": False,
        "DATABASE_PATH": str(tmp_path / "engine-identity.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"),
        "SECRET_KEY": "engine-identity-test",
    })
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def test_reconciliation_contract_has_a_new_engine_identity():
    assert ENGINE_VERSION == "2.4.0-reconciliation-history"


def test_previous_runtime_freshness_run_is_not_current_after_fact_contract_change(
    engine_identity_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, enrolled_by)
               VALUES ('ENGINE01', 'Engine Identity Patient', 'pytest')"""
        ).lastrowid
    )
    db.commit()
    audit = ClinicalEngineAuditRepository()
    run_id = audit.start_run(
        patient_link_id=patient_id,
        as_of_at=datetime(2026, 7, 22, 12, 0, 0).isoformat(
            sep=" ", timespec="seconds"
        ),
        engine_version="2.3.0-runtime-freshness",
        fact_snapshot={
            "schema_version": "2.0",
            "patient_link_id": patient_id,
            "clinical_data_revision": 0,
            "facts": [],
        },
    )
    audit.complete_run(run_id, status=RunStatus.COMPLETED)

    assert ClinicalEngineRuntimeRepository().latest_current_run(
        patient_id,
        engine_version=ENGINE_VERSION,
        ruleset_id=None,
        clinical_data_revision=0,
        allow_legacy_revision=False,
    ) is None
