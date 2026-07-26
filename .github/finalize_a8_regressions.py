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

test_path = ROOT / "specialist_clinic/tests/test_specialist_service_lineage_a8.py"
test_text = test_path.read_text(encoding="utf-8")
ux_test = '''


def test_patient_detail_renders_exact_service_lineage(a8_app):
    from src.services.specialist_financial_reconciliation_service import (
        SpecialistFinancialReconciliationService,
    )

    app, _accounting, _specialist = a8_app
    patient_id, _encounter = _enroll_and_complete(101)
    SpecialistFinancialReconciliationService().reconcile_invoice(101)
    client = app.test_client()
    login = client.post(
        "/auth/login", data={"username": "admin", "password": "admin"}
    )
    assert login.status_code in {302, 303}
    response = client.get(f"/patients/{patient_id}")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "خدمات دقیق" in html
    assert "تزریق عضلانی" in html
    assert "متصل به Encounter" in html
'''
if ux_test.strip() not in test_text:
    test_path.write_text(test_text + ux_test, encoding="utf-8")

Path(__file__).unlink()
