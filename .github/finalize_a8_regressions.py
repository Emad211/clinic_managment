from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A8 regression anchor missing in {relative}: {old[:220]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "specialist_clinic/tests/test_operational_security_hardening.py",
    '''        "payer_adjustments",
    }
''',
    '''        "payer_adjustments",
        "service_lineage",
    }
''',
)
replace_once(
    "specialist_clinic/tests/test_specialist_service_lineage_a8.py",
    '''    current = repository.current_lines_for_patient(patient_id)
    assert current[2]["description"] == "تعویض پانسمان"
''',
    '''    current = repository.current_lines_for_patient(patient_id)
    current_procedure = next(
        row for row in current if row["item_type"] == "PROCEDURE"
    )
    assert current_procedure["description"] == "تعویض پانسمان"
''',
)

Path(__file__).unlink()
