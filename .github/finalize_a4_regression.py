from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A4 regression anchor missing in {relative}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "specialist_clinic/tests/test_operational_security_hardening.py",
    '''        "worker",
        "revenue_scope",
    }
''',
    '''        "worker",
        "revenue_scope",
        "finance_projection",
    }
''',
)

replace_once(
    "specialist_clinic/tests/test_specialist_revenue_boundary.py",
    '''    # This write simulates the independent accounting app, not the specialist app.
    _close_and_pay_specialist_invoice(accounting, work_date=work_date)
    after_accounting_write = _sha256(accounting)
    dashboard = RevenueService().dashboard()
''',
    '''    # Service completion is independent from accounting closure and is required
    # before a financial observation may enter specialist revenue.
    DoctorQueueService(work_date_provider=lambda: work_date).end_visit(
        {"accounting_invoice_id": 2},
        "pytest-doctor",
        notes="خدمت تخصصی تکمیل شد",
    )
    # This write simulates the independent accounting app, not the specialist app.
    _close_and_pay_specialist_invoice(accounting, work_date=work_date)
    after_accounting_write = _sha256(accounting)
    from src.services.specialist_financial_reconciliation_service import (
        SpecialistFinancialReconciliationService,
    )
    reconciled = SpecialistFinancialReconciliationService().reconcile_all()
    assert reconciled["issues"] == []
    dashboard = RevenueService().dashboard()
''',
)

Path(__file__).unlink()
