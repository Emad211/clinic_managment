"""Reception + invoicing service (ACCOUNTING.md phase 2).

The business logic for the desk workflow: open an invoice, add revenue items
(visit / injection / procedure) priced from the per-clinic Tariff and split by the
patient's InsurancePlan, record payments (cash/card/wallet/insurance), and close.

Generalised — nothing here is specific to one clinic: prices come from the
clinic's editable Tariff rows and insurance shares from its editable InsurancePlan
rows (see seed_accounting_defaults). Money is BIGINT Rial; every row carries the
invoice's explicit work_date+shift (a night shift can cross midnight).

Call inside the clinic's tenant context (the web request already is).
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from apps.accounting.models import (
    Injection, Invoice, InvoiceItemPayment, Procedure, Visit,
)
from apps.common.activity import log_activity

# revenue = visits + injections + procedures (consumables are NOT revenue) —
# preserved from the legacy app's definition.
REVENUE_RELATIONS = ("visits", "injections", "procedures")


def split_shares(amount_rial: int, plan) -> tuple:
    """(patient_share, insurer_share) for a gross amount under an InsurancePlan.
    No plan => self-pay (patient pays 100%). Rounded to whole Rial, never negative,
    never more than the gross."""
    amount_rial = int(amount_rial or 0)
    if amount_rial <= 0:
        return 0, 0
    if plan is None:
        return amount_rial, 0
    pct = Decimal(plan.patient_share_percent) / Decimal(100)
    patient = int((Decimal(amount_rial) * pct).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    patient = max(0, min(patient, amount_rial))
    return patient, amount_rial - patient


def _price(tariff, amount_rial):
    if amount_rial is not None:
        return int(amount_rial)
    return int(tariff.amount_rial) if tariff else 0


def _derive_status(total, paid):
    if paid <= 0:
        return "open"
    return "paid" if paid >= total else "partial"


def open_invoice(clinic, patient, work_date, shift, created_by=None):
    inv = Invoice.objects.create(
        clinic=clinic, patient=patient, work_date=work_date, shift=shift,
        status="open", created_by=created_by,
    )
    log_activity(
        clinic, created_by, "invoice.open",
        summary=f"باز کردن فاکتور برای {patient.full_name}",
        entity_type="invoice", entity_id=inv.id,
    )
    return inv


@transaction.atomic
def add_visit(invoice, *, tariff=None, amount_rial=None, doctor=None, insurance_plan=None):
    amount = _price(tariff, amount_rial)
    patient_share, _ins = split_shares(amount, insurance_plan)
    v = Visit.objects.create(
        clinic=invoice.clinic, invoice=invoice, patient=invoice.patient, doctor=doctor,
        tariff=tariff, amount_rial=amount, insurance_plan=insurance_plan,
        patient_share_rial=patient_share, work_date=invoice.work_date, shift=invoice.shift,
    )
    recompute_invoice(invoice)
    return v


@transaction.atomic
def add_injection(invoice, *, name=None, tariff=None, amount_rial=None, insurance_plan=None):
    amount = _price(tariff, amount_rial)
    patient_share, _ins = split_shares(amount, insurance_plan)
    obj = Injection.objects.create(
        clinic=invoice.clinic, invoice=invoice, patient=invoice.patient,
        name=name or (tariff.name if tariff else ""), amount_rial=amount,
        insurance_plan=insurance_plan, patient_share_rial=patient_share,
        work_date=invoice.work_date, shift=invoice.shift,
    )
    recompute_invoice(invoice)
    return obj


@transaction.atomic
def add_procedure(invoice, *, name=None, tariff=None, amount_rial=None, insurance_plan=None):
    amount = _price(tariff, amount_rial)
    patient_share, _ins = split_shares(amount, insurance_plan)
    obj = Procedure.objects.create(
        clinic=invoice.clinic, invoice=invoice, patient=invoice.patient,
        name=name or (tariff.name if tariff else ""), amount_rial=amount,
        insurance_plan=insurance_plan, patient_share_rial=patient_share,
        work_date=invoice.work_date, shift=invoice.shift,
    )
    recompute_invoice(invoice)
    return obj


def recompute_invoice(invoice):
    """Total = sum of patient shares across revenue items (what the patient owes)."""
    if invoice.status == "void":
        return invoice
    total = 0
    for rel in REVENUE_RELATIONS:
        for row in getattr(invoice, rel).all():
            total += row.patient_share_rial or 0
    invoice.total_rial = total
    invoice.status = _derive_status(total, invoice.paid_rial or 0)
    invoice.save(update_fields=["total_rial", "status", "updated_at"])
    return invoice


@transaction.atomic
def record_payment(invoice, amount_rial, method="cash", actor=None):
    """Record a payment against the invoice. ``wallet`` debits the patient's
    wallet (capped at the balance) and appends a WalletTransaction. Returns the
    payment row, or None if nothing was charged."""
    amount = int(amount_rial or 0)
    if amount <= 0:
        return None

    if method == "wallet":
        from apps.chronic.models import WalletTransaction
        from apps.patients.models import Patient

        p = Patient.objects.select_for_update().get(id=invoice.patient_id)
        amount = min(amount, p.wallet_balance or 0)
        if amount <= 0:
            return None
        p.wallet_balance -= amount
        p.save(update_fields=["wallet_balance", "updated_at"])
        WalletTransaction.objects.create(
            clinic=invoice.clinic, patient=p, kind="debit", amount=amount,
            balance_after=p.wallet_balance, reason="پرداخت فاکتور", created_by=actor,
        )

    pay = InvoiceItemPayment.objects.create(
        clinic=invoice.clinic, invoice=invoice, amount_rial=amount, method=method,
    )
    invoice.paid_rial = (invoice.paid_rial or 0) + amount
    invoice.status = _derive_status(invoice.total_rial or 0, invoice.paid_rial)
    invoice.save(update_fields=["paid_rial", "status", "updated_at"])
    log_activity(
        invoice.clinic, actor, "invoice.payment",
        summary=f"پرداخت {amount} ریال ({method}) فاکتور {invoice.patient.full_name}",
        entity_type="invoice", entity_id=invoice.id,
        metadata={"method": method, "amount": amount},
    )
    return pay


@transaction.atomic
def close_invoice(invoice, actor=None):
    """Finalise the invoice: recompute the total and freeze its paid/unpaid state."""
    recompute_invoice(invoice)
    invoice.refresh_from_db(fields=["total_rial", "paid_rial"])
    invoice.status = _derive_status(invoice.total_rial or 0, invoice.paid_rial or 0)
    invoice.save(update_fields=["status", "updated_at"])
    log_activity(
        invoice.clinic, actor, "invoice.close",
        summary=f"بستن فاکتور {invoice.patient.full_name} (وضعیت {invoice.status})",
        entity_type="invoice", entity_id=invoice.id,
        metadata={"status": invoice.status, "total": invoice.total_rial,
                  "paid": invoice.paid_rial},
    )
    return invoice
