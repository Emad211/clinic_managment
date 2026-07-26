from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A2 regression anchor missing in {relative}: {old[:140]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Schema installation/backfill is invoked before repository-owned BEGIN IMMEDIATE.
# It must not leave an implicit SQLite transaction open.
replace_once(
    "specialist_clinic/src/adapters/sqlite/clinical_task_contract_schema.py",
    "    _legacy_contracts(db)\n",
    "    _legacy_contracts(db)\n    db.commit()\n",
)

# Keep current_task and list_current projections contract-compatible.
replace_once(
    "specialist_clinic/src/adapters/sqlite/clinical_care_loop_repo.py",
    '''        task["current_event_id"] = int(head["id"])
        task["current_status"] = str(head["status"])
        outcomes = db.execute(
''',
    '''        task["current_event_id"] = int(head["id"])
        task["current_status"] = str(head["status"])
        task["current_assigned_to"] = head["assigned_to"]
        task["current_appointment_id"] = head["appointment_id"]
        task["current_due_at"] = head["due_at"]
        task["current_disposition_code"] = head["disposition_code"]
        task["completion_outcome_event_id"] = head["outcome_event_id"]
        task["current_recorded_at"] = head["recorded_at"]
        outcomes = db.execute(
''',
)

# Preserve the default valid task contract while a test overrides due_period.
replace_once(
    "specialist_clinic/tests/test_clinical_engine_v2_followups.py",
    '''        recommendation.update(recommendation_overrides or {})
''',
    '''        overrides = deepcopy(recommendation_overrides or {})
        params_override = overrides.pop("params", None)
        if params_override is not None:
            recommendation["params"].update(params_override)
        recommendation.update(overrides)
''',
)

# recorded_at is server time and must not move behind the CREATED event.
test_path = ROOT / "specialist_clinic/tests/test_clinical_task_contracts.py"
test_text = test_path.read_text(encoding="utf-8")
test_text = test_text.replace(
    "clock=lambda: datetime(2026, 7, 22, 10, 5, 0)",
    "clock=lambda: datetime(2026, 7, 27, 10, 5, 0)",
)
test_path.write_text(test_text, encoding="utf-8")

Path(__file__).unlink()
