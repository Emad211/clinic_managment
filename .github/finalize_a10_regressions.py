from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# A9 tests validate documentation lifecycle, not plan semantics. Keep them stable/no-task;
# A10 owns FOLLOWUP_REQUIRED semantic tests with explicit commitments.
a9 = ROOT / "specialist_clinic/tests/test_encounter_documentation_a9.py"
text = a9.read_text(encoding="utf-8")
text = text.replace(
    '"outcome_code": "FOLLOWUP_REQUIRED",',
    '"outcome_code": "STABLE_CONTINUE",',
    1,
)
text = text.replace(
    'assert current["outcome_code"] == "FOLLOWUP_REQUIRED"',
    'assert current["outcome_code"] == "STABLE_CONTINUE"',
    1,
)
text = text.replace(
    'assert "پیگیری لازم است" in html',
    'assert "پایدار؛ ادامه برنامه" in html',
    1,
)
a9.write_text(text, encoding="utf-8")

health = ROOT / "specialist_clinic/tests/test_operational_security_hardening.py"
text = health.read_text(encoding="utf-8")
old = '''        "encounter_documentation",
    }
'''
new = '''        "encounter_documentation",
        "encounter_plan_commitments",
    }
'''
if new not in text:
    if old not in text:
        raise AssertionError("A10 health regression anchor missing")
    text = text.replace(old, new, 1)
health.write_text(text, encoding="utf-8")

# Static guard: no mutable resolve surface for Plan tasks and the planner fields stay present.
a10 = ROOT / "specialist_clinic/tests/test_encounter_plan_commitments_a10.py"
text = a10.read_text(encoding="utf-8")
guard = '''


def test_a10_source_guard_keeps_structured_planner_and_event_route():
    root = Path(__file__).resolve().parents[1]
    visit = (root / "src/templates/doctor_queue/visit_quick.html").read_text(encoding="utf-8")
    worklist = (root / "src/templates/followups/worklist.html").read_text(encoding="utf-8")
    routes = (root / "src/api/followups.py").read_text(encoding="utf-8")
    followups = (root / "src/adapters/sqlite/followups_repo.py").read_text(encoding="utf-8")
    for field in (
        "commitment_client_key", "commitment_type", "commitment_instruction",
        "commitment_due_date", "commitment_due_time", "commitment_fulfillment",
    ):
        assert f'name="{field}"' in visit
    assert "followups.plan_transition" in worklist
    assert "FOLLOWUP_PLAN_TRANSITION" in routes
    assert "encounter_plan" in followups
'''
if guard.strip() not in text:
    text += guard
a10.write_text(text, encoding="utf-8")

Path(__file__).unlink()
