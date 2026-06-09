"""Billing module: subscription plans, clinic subscriptions, payments.

Plan is a PLATFORM-level catalog (no clinic_id, no RLS — same for every tenant).
Subscription and Payment are tenant-owned (docs/DATA_MODEL.md §4). Payment gateway
is ZarinPal per TECH_STACK.
"""

from django.db import models

from apps.common.models import TenantModel, TimeStampedModel, UUIDModel


class Plan(UUIDModel, TimeStampedModel):
    """Platform-wide subscription plan (free | clinic | multi). NOT tenant-scoped."""

    PERIODS = [("monthly", "monthly"), ("yearly", "yearly")]

    code = models.SlugField(unique=True, max_length=32)  # free|clinic|multi
    name = models.TextField()
    price_rial = models.BigIntegerField(default=0)
    period = models.CharField(max_length=10, choices=PERIODS, default="yearly")
    features_json = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "plan"

    def __str__(self):
        return f"{self.code} ({self.price_rial} ﷼/{self.period})"


class Subscription(TenantModel):
    STATUS = [
        ("active", "active"),
        ("past_due", "past_due"),
        ("cancelled", "cancelled"),
    ]
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=16, choices=STATUS, default="active")
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "subscription"
        indexes = [models.Index(fields=["clinic", "status"])]


class Payment(TenantModel):
    STATUS = [("pending", "pending"), ("paid", "paid"), ("failed", "failed")]

    subscription = models.ForeignKey(
        Subscription, on_delete=models.SET_NULL, related_name="payments",
        null=True, blank=True,
    )
    amount_rial = models.BigIntegerField()
    gateway = models.TextField(default="zarinpal")
    authority = models.TextField(blank=True, default="")  # ZarinPal authority
    ref_id = models.TextField(blank=True, default="")
    status = models.CharField(max_length=10, choices=STATUS, default="pending")

    class Meta:
        db_table = "payment"
        indexes = [models.Index(fields=["clinic", "status", "-created_at"])]
