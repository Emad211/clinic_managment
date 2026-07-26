from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "specialist_clinic/src/adapters/sqlite/clinical_task_contract_schema.py"
REPO = ROOT / "specialist_clinic/src/adapters/sqlite/clinical_task_contract_repo.py"

schema = SCHEMA.read_text(encoding="utf-8")
replacements = (
    (
        '''"allowed_outcome_types": ["ENCOUNTER_COMPLETED"],
            "required_fact_keys": [],
            "minimum_verification": "CONFIRMED",
            "canonical_ingestion": "NONE",
            "requires_acknowledgement": True,''',
        '''"allowed_outcome_types": [
                "OBSERVATION", "PATIENT_REPORTED", "ENCOUNTER_COMPLETED",
                "PROCEDURE_COMPLETED", "LAB_COMPLETED", "OTHER"
            ],
            "required_fact_keys": [],
            "minimum_verification": "UNVERIFIED",
            "canonical_ingestion": "OPTIONAL",
            "requires_acknowledgement": False,''',
    ),
    (
        '''json.dumps(["ENCOUNTER_COMPLETED"], separators=(",", ":")),
                row["source_recommendation_event_id"],''',
        '''json.dumps([
                    "OBSERVATION", "PATIENT_REPORTED", "ENCOUNTER_COMPLETED",
                    "PROCEDURE_COMPLETED", "LAB_COMPLETED", "OTHER"
                ], separators=(",", ":")),
                row["source_recommendation_event_id"],''',
    ),
    (
        '''                       'PRIORITY', ?, '[]', 'CONFIRMED', 'NONE', 1,
''',
        '''                       'PRIORITY', ?, '[]', 'UNVERIFIED', 'OPTIONAL', 0,
''',
    ),
    (
        '''            source_recommendation_event_id INTEGER NOT NULL,
''',
        '''            source_recommendation_event_id INTEGER,
''',
    ),
    (
        '''        WHEN NOT EXISTS (
            SELECT 1 FROM followup_tasks task
''',
        '''        WHEN NEW.contract_origin='RULE_RECOMMENDATION' AND NOT EXISTS (
            SELECT 1 FROM followup_tasks task
''',
    ),
)
for old, new in replacements:
    if new in schema:
        continue
    if old not in schema:
        raise AssertionError(f"legacy contract anchor missing: {old[:100]!r}")
    schema = schema.replace(old, new, 1)
SCHEMA.write_text(schema, encoding="utf-8")

repo = REPO.read_text(encoding="utf-8")
repo = repo.replace('value in {None, ""}', 'value is None or value == ""')
REPO.write_text(repo, encoding="utf-8")

Path(__file__).unlink()
