"""Regression guards for bounded reconciliation projection work."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))

from src.domain.clinical_engine import reconciliation as reconciliation_domain
from src.services.clinical_reconciliation_service import (
    ClinicalReconciliationService,
)


AS_OF = datetime(2026, 7, 22, 12, 0, 0)


@pytest.fixture()
def query_plan_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(
                tmp_path / "reconciliation-query-plan.db"
            ),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "query-plan-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def test_patient_status_reads_one_bundle_for_all_three_collections(
    query_plan_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, enrolled_by)
               VALUES ('QUERY001', 'Query Plan Patient', 'pytest')"""
        ).lastrowid
    )
    db.commit()

    statements: list[str] = []
    db.set_trace_callback(statements.append)
    try:
        status = ClinicalReconciliationService(
            clock=lambda: AS_OF
        ).patient_status(patient_id)
    finally:
        db.set_trace_callback(None)

    assert list(status) == [
        "conditions",
        "medications",
        "allergies",
    ]
    normalized = [
        " ".join(statement.lower().split())
        for statement in statements
        if statement.lstrip().lower().startswith("select")
    ]
    table_fragments = {
        "patient_links": "from patient_links where id=",
        "patient_conditions": "from patient_conditions pc",
        "patient_medications": (
            "from patient_medications where patient_link_id="
        ),
        "allergies": "from allergies where patient_link_id=",
        "medication_events": (
            "from medication_events where patient_link_id="
        ),
        "clinical_reconciliation_events": (
            "from clinical_reconciliation_events where patient_link_id="
        ),
    }
    for table, fragment in table_fragments.items():
        matches = [sql for sql in normalized if fragment in sql]
        assert len(matches) == 1, (table, matches, normalized)


def test_project_collection_calculates_each_medication_dose_once(monkeypatch):
    calls = 0
    original = reconciliation_domain._dose_at

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(reconciliation_domain, "_dose_at", counted)
    projection = reconciliation_domain.project_collection(
        "medications",
        [
            {
                "id": 10,
                "drug_catalog_id": 1,
                "drug_name": "متفورمین",
                "drug_class": "metformin",
                "dose": "500 mg",
                "schedule": "روزانه",
                "start_date": "2025-01-01",
                "created_at": "2025-01-01 09:00:00",
                "end_date": None,
                "is_active": 1,
            }
        ],
        [],
        as_of_at=AS_OF,
        medication_events=[
            {
                "id": 20,
                "medication_id": 10,
                "event_type": "start",
                "dose": "500 mg",
                "event_date": "2025-01-01",
                "created_at": "2025-01-01 09:00:00",
            }
        ],
    )

    assert calls == 1
    assert projection.items[0]["dose"] == "500 mg"
