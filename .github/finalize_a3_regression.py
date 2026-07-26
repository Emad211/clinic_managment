from pathlib import Path

# Trigger revision: align the legacy expectation and run explicit decision-state tests.
ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "specialist_clinic/tests/test_clinical_engine_v2_followups.py"
text = path.read_text(encoding="utf-8")
old = '''        (
            {"requires_clinician_confirmation": True},
            "TASK_POLICY_REJECTED",
        ),
'''
new = '''        (
            {"requires_clinician_confirmation": True},
            "CLINICIAN_DECISION_REQUIRED",
        ),
'''
if new not in text:
    if old not in text:
        raise AssertionError("legacy clinician-confirmation expectation anchor missing")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
Path(__file__).unlink()
