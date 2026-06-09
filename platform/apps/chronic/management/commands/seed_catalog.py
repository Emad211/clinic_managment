"""Idempotently seed a MINIMAL set of GLOBAL clinical catalogs (clinic IS NULL).

This is the fresh-install fallback for deployments with no legacy data. When the
legacy `specialist.db` exists, prefer `etl_catalog` — it ports the full 57 ADA
rules / 13 indicators / 18 flags with their complete clinical fields. ADA
thresholds here must stay in sync with specialist_clinic vitals_service.THRESHOLDS
/ analytics_service.TARGETS (CLAUDE.md rule).

PostgreSQL note: global rows have clinic_id NULL, which the catalog RLS WITH
CHECK (own-only) rejects for a tenant role. Run under the platform owner /
BYPASSRLS ops role, not the app's tenant role.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.chronic.models import (
    ClinicalIndicator,
    ClinicalRule,
    Condition,
    DrugClass,
    FlagCatalog,
)

# (code, label, glucose_lowering)
DRUG_CLASSES = [
    ("metformin", "متفورمین", True),
    ("sulfonylurea", "سولفونیل‌اوره", True),
    ("dpp4", "مهارکنندهٔ DPP-4", True),
    ("sglt2", "مهارکنندهٔ SGLT2", True),
    ("glp1", "آگونیست GLP-1", True),
    ("insulin", "انسولین", True),
    ("acei", "مهارکنندهٔ ACE", False),
    ("arb", "مسدودکنندهٔ گیرندهٔ آنژیوتانسین", False),
    ("statin", "استاتین", False),
]

# (code, name)
CONDITIONS = [
    ("dm_t2", "دیابت نوع ۲"),
    ("htn", "فشار خون بالا"),
    ("dyslipidemia", "اختلال چربی خون"),
    ("ckd", "بیماری مزمن کلیه"),
    ("obesity", "چاقی"),
]

# (key, label, unit, direction, warn, danger, target)
INDICATORS = [
    ("hba1c", "HbA1c", "%", "high_bad", 7.0, 8.0, "<۷٪"),
    ("fbs", "قند ناشتا", "mg/dL", "high_bad", 130.0, 180.0, "۸۰–۱۳۰"),
    ("bp_systolic", "فشار سیستولیک", "mmHg", "high_bad", 130.0, 140.0, "<۱۳۰"),
    ("bp_diastolic", "فشار دیاستولیک", "mmHg", "high_bad", 80.0, 90.0, "<۸۰"),
    ("ldl", "LDL کلسترول", "mg/dL", "high_bad", 100.0, 130.0, "<۱۰۰"),
    ("egfr", "eGFR", "mL/min/1.73m²", "low_bad", 60.0, 30.0, ">۶۰"),
]

# (code, label, flag_type, category)
FLAGS = [
    ("hba1c_uncontrolled", "HbA1c خارج از کنترل", "warning", "glycemic"),
    ("bp_uncontrolled", "فشار خون کنترل‌نشده", "warning", "blood_pressure"),
    ("severe_hyperglycemia", "هیپرگلیسمی شدید", "red_flag", "glycemic"),
    ("hypoglycemia_risk", "خطر افت قند", "red_flag", "glycemic"),
    ("ckd_progression", "پیشرفت بیماری کلیه", "warning", "renal"),
    ("missed_followup", "پیگیریِ عقب‌افتاده", "info", "operational"),
]

# (code, title, category, severity, trigger_json, recommendation, source_ref)
RULES = [
    (
        "hba1c_above_target", "HbA1c بالاتر از هدف", "glycemic", "suggestion",
        {"any": [{"field": "hba1c", "op": ">", "value": 7.0}]},
        "HbA1c بالاتر از هدفِ ۷٪ است؛ تشدید/تعدیلِ درمان را با پزشک بررسی کنید. (پیشنهاد — تأیید با پزشک)",
        "ADA Standards of Care — Glycemic Targets",
    ),
    (
        "severe_hyperglycemia", "هیپرگلیسمی شدید", "glycemic", "red_flag",
        {"any": [{"field": "fbs", "op": ">=", "value": 300.0}, {"field": "hba1c", "op": ">=", "value": 10.0}]},
        "قندِ بسیار بالا — ارزیابیِ فوری لازم است.",
        "ADA — Hyperglycemic crises",
    ),
    (
        "bp_above_target", "فشار خون بالاتر از هدف", "blood_pressure", "suggestion",
        {"any": [{"field": "bp_systolic", "op": ">=", "value": 140.0}, {"field": "bp_diastolic", "op": ">=", "value": 90.0}]},
        "فشار خون بالاتر از هدف است؛ شروع/تشدیدِ درمانِ فشار را بررسی کنید. (پیشنهاد — تأیید با پزشک)",
        "ADA — Cardiovascular Disease and Risk Management",
    ),
]


class Command(BaseCommand):
    help = "Idempotently seed a minimal set of global clinical catalogs (fresh-install fallback)."

    @transaction.atomic
    def handle(self, *args, **options):
        for i, (code, label, gl) in enumerate(DRUG_CLASSES):
            DrugClass.objects.update_or_create(
                clinic=None, code=code,
                defaults={"label": label, "glucose_lowering": gl, "display_order": i},
            )
        for code, name in CONDITIONS:
            Condition.objects.update_or_create(
                clinic=None, code=code, defaults={"name": name}
            )
        for i, (key, label, unit, direction, warn, danger, target) in enumerate(INDICATORS):
            ClinicalIndicator.objects.update_or_create(
                clinic=None, key=key,
                defaults={
                    "label": label, "unit": unit, "direction": direction,
                    "warn": warn, "danger": danger, "target": target,
                    "display_order": i, "is_vital": True,
                },
            )
        for i, (code, label, flag_type, category) in enumerate(FLAGS):
            FlagCatalog.objects.update_or_create(
                clinic=None, code=code,
                defaults={"label": label, "flag_type": flag_type, "category": category, "display_order": i},
            )
        for code, title, category, severity, trigger, recommendation, ref in RULES:
            ClinicalRule.objects.update_or_create(
                clinic=None, code=code,
                defaults={
                    "title": title, "category": category, "severity": severity,
                    "trigger_json": trigger, "recommendation": recommendation,
                    "source_ref": ref, "is_active": True,
                },
            )

        self.stdout.write(self.style.SUCCESS(
            f"Seeded minimal global catalogs: {len(DRUG_CLASSES)} drug classes, "
            f"{len(CONDITIONS)} conditions, {len(INDICATORS)} indicators, "
            f"{len(FLAGS)} flags, {len(RULES)} rules. "
            f"(For the full ADA set, run etl_catalog against specialist.db.)"
        ))
