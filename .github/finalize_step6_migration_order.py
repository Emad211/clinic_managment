from pathlib import Path

path = Path("specialist_clinic/src/adapters/sqlite/clinical_care_loop_schema.py")
text = path.read_text(encoding="utf-8")
old = '''    _ensure_column(db, "followup_tasks", "clinical_due_period", "TEXT")
'''
new = '''    # Context identity is owned by the encounter tranche, but copied pre-v2 or
    # partially migrated databases may reach the closed-care-loop installer first.
    # Install the prerequisite here as well so this migration is independently safe.
    _ensure_column(db, "followup_tasks", "clinical_context_hash", "TEXT")
    _ensure_column(db, "followup_tasks", "clinical_due_period", "TEXT")
'''
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise AssertionError("clinical_context_hash prerequisite insertion point missing")
path.write_text(text, encoding="utf-8")
