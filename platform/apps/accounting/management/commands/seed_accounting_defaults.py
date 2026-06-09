"""Seed sensible, EDITABLE accounting defaults for a clinic.

    python manage.py seed_accounting_defaults --clinic-slug demo

The legacy Flask app hard-coded one clinic's insurance list + service/procedure/
consumable catalogs in a seed script. Here those become per-clinic, editable rows
(InsurancePlan + Tariff), seeded with Iran-wide-typical starting values that ANY
clinic/مطب/کلینیک can then tune in the UI. Idempotent (get_or_create by name), so
re-running never duplicates and never overwrites a clinic's edits. The set is
tuned to ``clinic.clinic_type``: a single-doctor office (مطب) gets a lean catalog
(visits + a few procedures), a polyclinic (درمانگاه) gets the full nursing station.

Run AFTER bootstrap_clinic / etl_import (the clinic must already exist). Writes
RLS tables — on PostgreSQL run under a role allowed to write the tenant.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounting.models import InsurancePlan, Tariff
from apps.common.tenant import tenant_context
from apps.identity.models import Clinic

# Iran national payers — applicable to every Iranian clinic, hence safe defaults.
# (patient_share_percent is the patient's default out-of-pocket share.)
INSURANCE_DEFAULTS = [
    ("آزاد", 100, False),            # self-pay
    ("تأمین اجتماعی", 30, False),
    ("سلامت", 30, False),
    ("نیروهای مسلح", 20, False),
    ("بیمهٔ تکمیلی", 0, True),       # supplementary, stacks on a base payer
]

# (kind, name, amount_rial, category). Generic starting prices in Rial — editable.
VISIT_TARIFFS = [
    ("visit", "ویزیت پزشک عمومی", 3_000_000, ""),
    ("visit", "ویزیت پزشک متخصص", 6_000_000, ""),
]
NURSING_TARIFFS = [
    ("nursing", "تزریق عضلانی", 500_000, ""),
    ("nursing", "تزریق وریدی", 700_000, ""),
    ("nursing", "سرم‌تراپی", 1_500_000, ""),
    ("nursing", "پانسمان ساده", 800_000, ""),
]
PROCEDURE_TARIFFS = [
    ("procedure", "نوار قلب", 2_000_000, ""),
    ("procedure", "بخیه", 4_000_000, ""),
    ("procedure", "شستشوی گوش", 2_500_000, ""),
]
CONSUMABLE_TARIFFS = [
    ("consumable", "سرنگ ۵ سی‌سی", 80_000, "supply"),
    ("consumable", "آنژیوکت", 600_000, "supply"),
    ("consumable", "سرم نرمال سالین", 900_000, "drug"),
]


def _tariffs_for_type(clinic_type):
    """A مطب (single-doctor office) gets a lean catalog; clinics/polyclinics get
    the full nursing + consumables station. All rows are editable afterwards."""
    rows = list(VISIT_TARIFFS) + list(PROCEDURE_TARIFFS)
    if clinic_type != "office":
        rows += list(NURSING_TARIFFS) + list(CONSUMABLE_TARIFFS)
    return rows


class Command(BaseCommand):
    help = "Seed editable default insurance plans + tariffs for a clinic."

    def add_arguments(self, parser):
        parser.add_argument("--clinic-slug", required=True)

    @transaction.atomic
    def handle(self, *args, **opts):
        try:
            clinic = Clinic.objects.get(slug=opts["clinic_slug"])
        except Clinic.DoesNotExist:
            raise CommandError(f"clinic '{opts['clinic_slug']}' not found")

        n_ins = n_tar = 0
        with tenant_context(clinic.id):
            for name, share, supp in INSURANCE_DEFAULTS:
                _, created = InsurancePlan.objects.get_or_create(
                    clinic=clinic, name=name,
                    defaults={"patient_share_percent": share, "is_supplementary": supp},
                )
                n_ins += int(created)
            for kind, name, amount, category in _tariffs_for_type(clinic.clinic_type):
                _, created = Tariff.objects.get_or_create(
                    clinic=clinic, kind=kind, name=name,
                    defaults={"amount_rial": amount, "category": category},
                )
                n_tar += int(created)

        # ASCII-only output (Windows cp1252-safe); the data itself is Persian.
        self.stdout.write(self.style.SUCCESS(
            f"Clinic {clinic.slug} (type={clinic.clinic_type}): "
            f"+{n_ins} insurance plans, +{n_tar} tariffs (idempotent)."
        ))
