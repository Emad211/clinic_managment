"""Reception + invoice pricing service (ACCOUNTING.md phase 2): pricing from
per-clinic tariffs, insurance share split, invoice totals, and payments."""
import datetime

import pytest

from apps.accounting import services
from apps.accounting.models import InsurancePlan, Tariff
from apps.accounting.services import (
    add_procedure, add_visit, close_invoice, open_invoice, record_payment,
    split_shares,
)

pytestmark = pytest.mark.django_db

WD = datetime.date(2026, 6, 9)


@pytest.fixture
def tameen(clinic):
    return InsurancePlan.objects.create(clinic=clinic, name="تأمین اجتماعی", patient_share_percent=30)


@pytest.fixture
def visit_tariff(clinic):
    return Tariff.objects.create(clinic=clinic, kind="visit", name="ویزیت متخصص", amount_rial=6_000_000)


def test_split_shares_self_pay_and_insured(tameen):
    assert split_shares(1_000, None) == (1_000, 0)        # no plan -> patient pays all
    assert split_shares(1_000, tameen) == (300, 700)       # 30% patient / 70% insurer
    assert split_shares(0, tameen) == (0, 0)


def test_add_visit_prices_and_splits(clinic, diabetic_patient, visit_tariff, tameen):
    inv = open_invoice(clinic, diabetic_patient, WD, "morning")
    v = add_visit(inv, tariff=visit_tariff, insurance_plan=tameen)
    assert v.amount_rial == 6_000_000                 # gross from tariff
    assert v.patient_share_rial == 1_800_000          # 30%
    inv.refresh_from_db()
    assert inv.total_rial == 1_800_000 and inv.status == "open"


def test_invoice_total_sums_patient_shares(clinic, diabetic_patient, visit_tariff, tameen):
    inv = open_invoice(clinic, diabetic_patient, WD, "morning")
    add_visit(inv, tariff=visit_tariff, insurance_plan=tameen)      # 1.8M patient
    add_procedure(inv, name="بخیه", amount_rial=2_000_000)          # self-pay 2.0M
    inv.refresh_from_db()
    assert inv.total_rial == 3_800_000


def test_payment_flow_partial_then_paid(clinic, diabetic_patient, visit_tariff):
    inv = open_invoice(clinic, diabetic_patient, WD, "evening")
    add_visit(inv, tariff=visit_tariff)  # self-pay 6.0M
    inv.refresh_from_db()
    assert inv.total_rial == 6_000_000

    record_payment(inv, 2_000_000, "cash")
    inv.refresh_from_db()
    assert inv.paid_rial == 2_000_000 and inv.status == "partial"

    record_payment(inv, 4_000_000, "card")
    inv.refresh_from_db()
    assert inv.paid_rial == 6_000_000 and inv.status == "paid"


def test_wallet_payment_debits_balance(clinic, diabetic_patient, visit_tariff):
    diabetic_patient.wallet_balance = 5_000_000
    diabetic_patient.save(update_fields=["wallet_balance"])
    inv = open_invoice(clinic, diabetic_patient, WD, "morning")
    add_visit(inv, tariff=visit_tariff)  # 6.0M

    # wallet only has 5.0M -> payment capped at the balance
    record_payment(inv, 6_000_000, "wallet")
    diabetic_patient.refresh_from_db()
    inv.refresh_from_db()
    assert diabetic_patient.wallet_balance == 0
    assert inv.paid_rial == 5_000_000 and inv.status == "partial"


def test_close_invoice_sets_status(clinic, diabetic_patient, visit_tariff):
    inv = open_invoice(clinic, diabetic_patient, WD, "night")
    add_visit(inv, tariff=visit_tariff)
    record_payment(inv, 6_000_000, "cash")
    close_invoice(inv)
    inv.refresh_from_db()
    assert inv.status == "paid"


def test_open_invoice_writes_activity_log(clinic, diabetic_patient):
    from apps.common.models import ActivityLog
    open_invoice(clinic, diabetic_patient, WD, "morning")
    assert ActivityLog.objects.filter(action="invoice.open").count() == 1
