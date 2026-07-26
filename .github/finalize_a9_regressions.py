from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A9 regression anchor missing in {relative}: {old[:220]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "specialist_clinic/tests/test_operational_security_hardening.py",
    '''        "service_lineage",
    }
''',
    '''        "service_lineage",
        "encounter_documentation",
    }
''',
)
replace_once(
    "specialist_clinic/tests/test_encounter_documentation_a9.py",
    '''    assert "کنترل فشار خون هنوز مطلوب نیست" in html
    assert "FOLLOWUP_REQUIRED" not in html
''',
    '''    assert "کنترل فشار خون هنوز مطلوب نیست" in html
    assert "پیگیری لازم است" in html
''',
)

test_path = ROOT / "specialist_clinic/tests/test_encounter_documentation_a9.py"
text = test_path.read_text(encoding="utf-8")
guard = '''


def test_a9_source_guard_has_no_direct_done_and_keeps_required_fields():
    root = Path(__file__).resolve().parents[1]
    queue = (root / "src/templates/doctor_queue/queue.html").read_text(
        encoding="utf-8"
    )
    visit = (root / "src/templates/doctor_queue/visit_quick.html").read_text(
        encoding="utf-8"
    )
    routes = (root / "src/api/doctor_queue.py").read_text(encoding="utf-8")
    assert "url_for('doctor_queue.done'" not in queue
    assert 'name="assessment"' in visit
    assert 'name="plan"' in visit
    assert 'name="outcome_code"' in visit
    assert 'name="action" value="sign"' in visit
    assert "permission_required(Permission.CLINICAL_DOCUMENT_WRITE)" in routes
    assert "permission_required(Permission.CLINICAL_DOCUMENT_AMEND)" in routes
'''
if guard.strip() not in text:
    test_path.write_text(text + guard, encoding="utf-8")

Path(__file__).unlink()
