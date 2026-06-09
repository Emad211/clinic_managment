"""Idempotently seed the platform subscription plans (global, not tenant-scoped).

Prices are placeholders (Rial/year) — tune from MASTER_PLAN pricing once set.
"""

from django.core.management.base import BaseCommand

from apps.billing.models import Plan

# (code, name, price_rial, period, features)
PLANS = [
    ("free", "رایگان", 0, "yearly",
     {"patients": 50, "eprescription": False, "sms": False, "decision_support": True}),
    ("clinic", "کلینیک", 60_000_000, "yearly",
     {"patients": 2000, "eprescription": True, "sms": True, "decision_support": True}),
    ("multi", "چندمطبی", 150_000_000, "yearly",
     {"patients": None, "eprescription": True, "sms": True, "decision_support": True, "multi_clinic": True}),
]


class Command(BaseCommand):
    help = "Seed/refresh the global subscription plans (idempotent)."

    def handle(self, *args, **options):
        for code, name, price, period, features in PLANS:
            Plan.objects.update_or_create(
                code=code,
                defaults={"name": name, "price_rial": price, "period": period,
                          "features_json": features, "is_active": True},
            )
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(PLANS)} plans."))
