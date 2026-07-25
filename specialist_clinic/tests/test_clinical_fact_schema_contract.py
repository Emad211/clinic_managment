"""Keep generated Clinical Facts aligned with both published JSON schemas.

The project intentionally avoids adding a production JSON-schema dependency merely for
CI.  This test reads the authoritative schema itself and verifies every generated enum,
key, required field, nullability rule and timestamp against that contract.  It also
requires the bundled runtime and research copies to remain byte-semantically identical.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SPECIALIST_ROOT.parent
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))

from src.adapters.sqlite.clinical_reconciliation_repo import (
    ClinicalReconciliationRepository,
)
from src.adapters.sqlite.patients_repo import PatientRepository
from src.services.clinical_engine.fact_builder import (
    FactBuilder,
    snapshot_payload,
)


AS_OF = datetime(2026, 7, 22, 12, 0, 0)
RUNTIME_SCHEMA = (
    SPECIALIST_ROOT
    / "src"
    / "domain"
    / "clinical_engine"
    / "schemas"
    / "clinical-fact.schema.json"
)
RESEARCH_SCHEMA = (
    REPOSITORY_ROOT
    / "clinical_engine_v2_research"
    / "clinical-fact.schema.json"
)


@pytest.fixture()
def fact_schema_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "fact-schema.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"),
        "SECRET_KEY": "fact-schema-test",
    })
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _enum(schema: dict, *path: str) -> set[str]:
    node = schema
    for part in path:
        node = node[part]
    return set(node["enum"])


def test_runtime_and_research_fact_schemas_are_identical():
    runtime = json.loads(RUNTIME_SCHEMA.read_text(encoding="utf-8"))
    research = json.loads(RESEARCH_SCHEMA.read_text(encoding="utf-8"))
    assert runtime == research


def test_generated_reconciliation_facts_obey_published_schema_vocabulary(
    fact_schema_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, gender, birthdate, enrolled_by,
                enrolled_at)
               VALUES ('SCHEMA01', 'Schema Patient', 'female', '1980-01-02',
                       'pytest', '2026-01-01 09:00:00')"""
        ).lastrowid
    )
    db.execute(
        """INSERT INTO vital_readings
           (patient_link_id, type, value, unit, measured_at, source,
            recorded_by)
           VALUES (?, 'bp_systolic', 181, 'mmHg',
                   '2026-07-22 09:00:00', 'self', 'patient')""",
        (patient_id,),
    )
    db.execute(
        """INSERT INTO allergies
           (patient_link_id, substance, reaction, severity, is_active,
            created_at)
           VALUES (?, 'Legacy allergen', 'unknown', 'unknown', 1, NULL)""",
        (patient_id,),
    )
    db.commit()

    PatientRepository().add_medication(
        patient_id,
        drug_name="Free text metformin",
        dose="500 mg",
        schedule="روزانه",
        start_date="2025-01-01",
        refill_due_date=None,
        notes="intentionally unmapped",
        drug_class="metformin",
        created_by="doctor",
    )
    ClinicalReconciliationRepository().record(
        patient_link_id=patient_id,
        collection_key="medications",
        completeness="complete",
        actor_username="doctor",
        source="clinician",
        patient_confirmed=True,
        reconciled_at=AS_OF,
    )

    payload = snapshot_payload(
        FactBuilder().build(patient_id, as_of_at=AS_OF)
    )
    schema = json.loads(RUNTIME_SCHEMA.read_text(encoding="utf-8"))
    properties = schema["properties"]
    required = set(schema["required"])
    allowed_top_level = set(properties)
    key_pattern = re.compile(properties["key"]["pattern"])
    allowed_statuses = _enum(schema, "properties", "status")
    allowed_verifications = _enum(schema, "properties", "verification")
    allowed_freshness = _enum(
        schema, "properties", "freshness", "properties", "state"
    )
    allowed_sources = _enum(
        schema, "properties", "source", "properties", "type"
    )
    allowed_conflicts = _enum(
        schema, "properties", "conflict", "properties", "state"
    )
    allowed_warnings = _enum(
        schema, "properties", "warnings", "items"
    )

    seen_warnings: set[str] = set()
    for fact in payload["facts"]:
        assert required <= set(fact)
        assert set(fact) <= allowed_top_level
        assert key_pattern.fullmatch(fact["key"])
        assert fact["status"] in allowed_statuses
        assert fact["verification"] in allowed_verifications
        assert fact["freshness"]["state"] in allowed_freshness
        assert fact["source"]["type"] in allowed_sources
        assert fact["conflict"]["state"] in allowed_conflicts
        assert len(fact["warnings"]) == len(set(fact["warnings"]))
        assert set(fact["warnings"]) <= allowed_warnings
        assert len(fact["derived_from"]) == len(set(fact["derived_from"]))
        datetime.fromisoformat(fact["effective_at"])
        datetime.fromisoformat(fact["recorded_at"])
        if fact["status"] == "PRESENT":
            assert fact["value"] is not None
        else:
            assert fact["value"] is None
        seen_warnings.update(fact["warnings"])

    assert {
        "PATIENT_REPORTED",
        "UNRECONCILED_COLLECTION",
        "UNMAPPED_MEDICATION_CONCEPT",
        "CANONICAL_MAPPING_INCOMPLETE",
        "HISTORICAL_INTERVAL_APPROXIMATION",
    } <= seen_warnings
