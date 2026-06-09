"""Accounting module (from webapp): invoices, visits, injections, procedures,
consumables, tariffs, payroll.

Conventions preserved from the Flask app: money is BIGINT (Rial, not float), and
every operational row carries an explicit ``work_date`` + ``shift`` (a night
shift can cross midnight, so the calendar date is NOT used to attribute activity
to a work day). See CLAUDE.md "Manual shifts".
"""

from django.db import models

from apps.common.models import TenantModel

SHIFTS = [("morning", "morning"), ("evening", "evening"), ("night", "night")]


class Tariff(TenantModel):
    """Per-clinic price list (visit/service/nursing/procedure/consumable)."""

    KIND = [
        ("visit", "visit"),
        ("service", "service"),
        ("nursing", "nursing"),
        ("procedure", "procedure"),
        ("consumable", "consumable"),
        ("injection", "injection"),
    ]
    kind = models.CharField(max_length=16, choices=KIND)
    name = models.TextField()
    amount_rial = models.BigIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "tariff"
        indexes = [models.Index(fields=["clinic", "kind", "is_active"])]


class Invoice(TenantModel):
    STATUS = [("open", "open"), ("paid", "paid"), ("partial", "partial"), ("void", "void")]

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="invoices"
    )
    work_date = models.DateField()
    shift = models.CharField(max_length=10, choices=SHIFTS)
    total_rial = models.BigIntegerField(default=0)
    paid_rial = models.BigIntegerField(default=0)
    status = models.CharField(max_length=10, choices=STATUS, default="open")
    created_by = models.ForeignKey(
        "identity.AppUser", on_delete=models.SET_NULL, related_name="+",
        null=True, blank=True,
    )

    class Meta:
        db_table = "invoice"
        indexes = [models.Index(fields=["clinic", "work_date", "shift"])]


class Visit(TenantModel):
    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name="visits", null=True, blank=True
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="visits"
    )
    doctor = models.ForeignKey(
        "identity.AppUser", on_delete=models.SET_NULL, related_name="+",
        null=True, blank=True,
    )
    tariff = models.ForeignKey(
        Tariff, on_delete=models.SET_NULL, related_name="+", null=True, blank=True
    )
    amount_rial = models.BigIntegerField(default=0)
    work_date = models.DateField()
    shift = models.CharField(max_length=10, choices=SHIFTS)

    class Meta:
        db_table = "visit"
        indexes = [models.Index(fields=["clinic", "work_date", "shift"])]


class VisitItem(TenantModel):
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="items")
    name = models.TextField()
    quantity = models.IntegerField(default=1)
    amount_rial = models.BigIntegerField(default=0)

    class Meta:
        db_table = "visit_item"
        indexes = [models.Index(fields=["clinic", "visit"])]


class Injection(TenantModel):
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="injections"
    )
    invoice = models.ForeignKey(
        Invoice, on_delete=models.SET_NULL, related_name="injections",
        null=True, blank=True,
    )
    name = models.TextField()
    amount_rial = models.BigIntegerField(default=0)
    work_date = models.DateField()
    shift = models.CharField(max_length=10, choices=SHIFTS)

    class Meta:
        db_table = "injection"
        indexes = [models.Index(fields=["clinic", "work_date", "shift"])]


class Procedure(TenantModel):
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="procedures"
    )
    invoice = models.ForeignKey(
        Invoice, on_delete=models.SET_NULL, related_name="procedures",
        null=True, blank=True,
    )
    name = models.TextField()
    amount_rial = models.BigIntegerField(default=0)
    work_date = models.DateField()
    shift = models.CharField(max_length=10, choices=SHIFTS)

    class Meta:
        db_table = "procedure"
        indexes = [models.Index(fields=["clinic", "work_date", "shift"])]


class ConsumableLedger(TenantModel):
    name = models.TextField()
    quantity = models.IntegerField(default=0)
    amount_rial = models.BigIntegerField(default=0)
    direction = models.CharField(
        max_length=8, choices=[("in", "in"), ("out", "out")], default="out"
    )
    work_date = models.DateField()
    shift = models.CharField(max_length=10, choices=SHIFTS)

    class Meta:
        db_table = "consumable_ledger"
        indexes = [models.Index(fields=["clinic", "work_date", "shift"])]


class InvoiceItemPayment(TenantModel):
    METHOD = [("cash", "cash"), ("card", "card"), ("wallet", "wallet"), ("insurance", "insurance")]

    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name="payments"
    )
    amount_rial = models.BigIntegerField()
    method = models.CharField(max_length=12, choices=METHOD, default="cash")

    class Meta:
        db_table = "invoice_item_payment"
        indexes = [models.Index(fields=["clinic", "invoice"])]


class PayrollSetting(TenantModel):
    user = models.ForeignKey(
        "identity.AppUser", on_delete=models.CASCADE, related_name="+"
    )
    base_rial = models.BigIntegerField(default=0)
    share_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    config_json = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "payroll_setting"
        indexes = [models.Index(fields=["clinic", "user"])]
