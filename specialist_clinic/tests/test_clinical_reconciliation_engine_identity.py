"""Fact-contract changes invalidate prior runs, reports, approvals and seals."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))

from src.adapters.sqlite.clinical_engine_activation_repo import (
    ClinicalEngineActivationRepository,
    content_hash,
)
from src.adapters.sqlite.clinical_engine_audit_repo import (
    ClinicalEngineAuditRepository,
)
from src.adapters.sqlite.clinical_engine_runtime_repo import (
    ClinicalEngineRuntimeRepository,
)
from src.domain.clinical_engine import RunStatus
from src.domain.clinical_engine.release import CURRENT_ENGINE_VERSION
from src.services.clinical_engine.fact_builder import ENGINE_VERSION


@pytest.fixture()
def engine_identity_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "engine-identity.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "engine-identity-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def test_reconciliation_contract_has_one_engine_identity():
    assert CURRENT_ENGINE_VERSION == "2.6.0-evaluation-context"
    assert ENGINE_VERSION == CURRENT_ENGINE_VERSION


def test_previous_engine_run_is_never_current(engine_identity_app):
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
            sep=" ",
            timespec="seconds",
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
    ) is None


def test_pre_engine_bound_report_and_seal_fail_closed(engine_identity_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    db.execute(
        """INSERT INTO clinical_rulesets
           (id, ruleset_code, version, content_hash, status,
            created_by, created_at)
           VALUES (901, 'general-outpatient', '2026.1-draft.2',
                   'legacy-report-ruleset', 'SILENT', 'pytest',
                   '2026-07-22 10:00:00')"""
    )
    db.commit()
    state = ClinicalEngineActivationRepository()
    old_core = {
        "schema_version": "1.0",
        "as_of_at": "2026-07-22 12:00:00",
        "cohort": [],
        "ruleset": {
            "id": 901,
            "ruleset_code": "general-outpatient",
            "version": "2026.1-draft.2",
            "content_hash": "legacy-report-ruleset",
            "status": "SILENT",
        },
        "patients": [],
        "failures": [],
        "checks": {"legacy": True},
    }
    report = {
        **old_core,
        "status": "PASS",
        "report_hash": content_hash(old_core),
    }
    state.put_json("last_report", report)
    for role in ("clinical", "technical"):
        state.put_json(
            f"approval_{role}",
            {"report_hash": report["report_hash"]},
        )
    seal_body = {
        "mode": "on_selected",
        "report_hash": report["report_hash"],
        "ruleset_id": 901,
    }
    state.put_json(
        "seal",
        {**seal_body, "seal_hash": content_hash(seal_body)},
    )
    state.set_raw_mode("on_selected")

    assert state.valid_seal("on_selected") is False
