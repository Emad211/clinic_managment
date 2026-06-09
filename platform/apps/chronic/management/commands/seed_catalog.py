"""Idempotently seed the GLOBAL clinical catalogs (clinic IS NULL).

Mirrors specialist_clinic's startup re-seed (clinical_rules_seed): safe to run on
every deploy; manager per-clinic overrides are never touched (they have a
non-null clinic_id). ADA thresholds here must stay in sync with
specialist_clinic vitals_service.THRESHOLDS / analytics_service.TARGETS
(CLAUDE.md rule).

PostgreSQL note: global rows have clinic_id NULL, which the catalog RLS WITH
CHECK (own-only) rejects for a tenant role. Run this under the platform
owner/BYPASSRLS role (the ops/migration role), NOT the app's tenant role.
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

# (code, name_fa, name_en)
DRUG_CLASSES = [
    ("metformin", "متفورمین", "Biguanide"),
    ("sulfonylurea", "سولفونیل‌اوره", "Sulfonylurea"),
    ("dpp4", "مهارکنندهٔ DPP-4", "DPP-4 inhibitor"),
    ("sglt2", "مهارکنندهٔ SGLT2", "SGLT2 inhibitor"),
    ("glp1", "آگونیست GLP-1", "GLP-1 RA"),
    ("tzd", "تیازولیدین‌دیون", "Thiazolidinedione"),
    ("insulin", "انسولین", "Insulin"),
    ("acei", "مهارکنندهٔ ACE", "ACE inhibitor"),
    ("arb", "مسدودکنندهٔ گیرندهٔ آنژیوتانسین", "ARB"),
    ("ccb", "مسدودکنندهٔ کانال کلسیم", "Calcium channel blocker"),
    ("thiazide", "دیورتیک تیازیدی", "Thiazide diuretic"),
    ("beta_blocker", "بتابلوکر", "Beta blocker"),
    ("statin", "استاتین", "Statin"),
    ("aspirin", "آسپرین", "Antiplatelet"),
]

# (code, name_fa, name_en)
CONDITIONS = [
    ("dm_t2", "دیابت نوع ۲", "Type 2 diabetes"),
    ("htn", "فشار خون بالا", "Hypertension"),
    ("dyslipidemia", "اختلال چربی خون", "Dyslipidemia"),
    ("ckd", "بیماری مزمن کلیه", "Chronic kidney disease"),
    ("obesity", "چاقی", "Obesity"),
]

# (key, name_fa, unit, warn_high, danger_high, target_text)  -- higher is worse
INDICATORS = [
    ("hba1c", "HbA1c", "%", 7.0, 8.0, "<۷٪ (هدفِ عمومی ADA)"),
    ("fbs", "قند ناشتا", "mg/dL", 130.0, 180.0, "۸۰–۱۳۰"),
    ("bp_systolic", "فشار سیستولیک", "mmHg", 130.0, 140.0, "<۱۳۰"),
    ("bp_diastolic", "فشار دیاستولیک", "mmHg", 80.0, 90.0, "<۸۰"),
    ("ldl", "LDL کلسترول", "mg/dL", 100.0, 130.0, "<۱۰۰ (یا <۷۰ پرخطر)"),
    ("egfr", "eGFR", "mL/min/1.73m²", None, None, ">۶۰ (پایین‌تر بدتر)"),
]

# (code, label_fa, severity, color)
FLAGS = [
    ("hba1c_uncontrolled", "HbA1c خارج از کنترل", "warning", "amber"),
    ("bp_uncontrolled", "فشار خون کنترل‌نشده", "warning", "amber"),
    ("severe_hyperglycemia", "هیپرگلیسمی شدید", "red_flag", "red"),
    ("hypoglycemia_risk", "خطر افت قند", "red_flag", "red"),
    ("ckd_progression", "پیشرفت بیماری کلیه", "warning", "amber"),
    ("missed_followup", "پیگیریِ عقب‌افتاده", "info", "blue"),
    ("no_statin_indicated", "نبودِ استاتین با اندیکاسیون", "suggestion", "indigo"),
]

# (code, title, category, severity, trigger_json, message_fa, source_ref)
RULES = [
    (
        "hba1c_above_target",
        "HbA1c بالاتر از هدف",
        "glycemic",
        "suggestion",
        {"any": [{"field": "hba1c", "op": ">", "value": 7.0}]},
        "HbA1c بالاتر از هدفِ ۷٪ است؛ تشدید/تعدیلِ درمان را با پزشک بررسی کنید. (پیشنهاد — تأیید با پزشک)",
        "ADA Standards of Care — Glycemic Targets",
    ),
    (
        "severe_hyperglycemia",
        "هیپرگلیسمی شدید",
        "glycemic",
        "red_flag",
        {"any": [{"field": "fbs", "op": ">=", "value": 300.0}, {"field": "hba1c", "op": ">=", "value": 10.0}]},
        "قندِ بسیار بالا — ارزیابیِ فوری لازم است.",
        "ADA — Hyperglycemic crises",
    ),
    (
        "bp_above_target",
        "فشار خون بالاتر از هدف",
        "blood_pressure",
        "suggestion",
        {"any": [{"field": "bp_systolic", "op": ">=", "value": 140.0}, {"field": "bp_diastolic", "op": ">=", "value": 90.0}]},
        "فشار خون بالاتر از هدف است؛ شروع/تشدیدِ درمانِ فشار را بررسی کنید. (پیشنهاد — تأیید با پزشک)",
        "ADA — Cardiovascular Disease and Risk Management",
    ),
    (
        "statin_indicated_diabetes",
        "اندیکاسیونِ استاتین در دیابت",
        "lipid",
        "suggestion",
        {"all": [{"field": "age", "op": ">=", "value": 40}, {"field": "has_condition", "op": "==", "value": "dm_t2"}, {"not": {"field": "on_statin", "op": "==", "value": True}}]},
        "بیمارِ دیابتیِ ≥۴۰ سال بدونِ استاتین — شروعِ استاتین طبق ADA را بررسی کنید. (پیشنهاد — تأیید با پزشک)",
        "ADA — Lipid management (statin therapy)",
    ),
    (
        "ckd_screen_due",
        "زمانِ غربالگریِ کلیه",
        "renal",
        "info",
        {"any": [{"field": "months_since_egfr", "op": ">=", "value": 12}]},
        "بیش از ۱۲ ماه از آخرین eGFR/آلبومینِ ادرار گذشته — غربالگریِ سالانهٔ کلیه را برنامه‌ریزی کنید.",
        "ADA — CKD screening (annual eGFR + uACR)",
    ),
]


class Command(BaseCommand):
    help = "Idempotently seed global clinical catalogs (drug classes, conditions, indicators, flags, rules)."

    @transaction.atomic
    def handle(self, *args, **options):
        n = {"drug_class": 0, "condition": 0, "indicator": 0, "flag": 0, "rule": 0}

        for code, fa, en in DRUG_CLASSES:
            _, created = DrugClass.objects.update_or_create(
                clinic=None, code=code, defaults={"name_fa": fa, "name_en": en}
            )
            n["drug_class"] += 1

        for code, fa, en in CONDITIONS:
            Condition.objects.update_or_create(
                clinic=None, code=code, defaults={"name_fa": fa, "name_en": en}
            )
            n["condition"] += 1

        for key, fa, unit, warn_high, danger_high, target in INDICATORS:
            ClinicalIndicator.objects.update_or_create(
                clinic=None,
                key=key,
                defaults={
                    "name_fa": fa,
                    "unit": unit,
                    "warn_high": warn_high,
                    "danger_high": danger_high,
                    "target_text": target,
                },
            )
            n["indicator"] += 1

        for code, label, severity, color in FLAGS:
            FlagCatalog.objects.update_or_create(
                clinic=None,
                code=code,
                defaults={"label_fa": label, "severity": severity, "color": color},
            )
            n["flag"] += 1

        for code, title, category, severity, trigger, message, ref in RULES:
            ClinicalRule.objects.update_or_create(
                clinic=None,
                code=code,
                defaults={
                    "title": title,
                    "category": category,
                    "severity": severity,
                    "trigger_json": trigger,
                    "message_fa": message,
                    "source_ref": ref,
                    "is_active": True,
                },
            )
            n["rule"] += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Seeded global catalogs: "
                f"{n['drug_class']} drug classes, {n['condition']} conditions, "
                f"{n['indicator']} indicators, {n['flag']} flags, {n['rule']} rules."
            )
        )
