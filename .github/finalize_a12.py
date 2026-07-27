from __future__ import annotations

import json
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
SPECIALIST = ROOT / "specialist_clinic"
ARTIFACTS = SPECIALIST / "src/domain/clinical_engine/rule_artifacts"
OLD_VERSION = "2026.1-draft.2"
NEW_VERSION = "2026.1-draft.3"
OLD_PACKAGE = ARTIFACTS / OLD_VERSION
NEW_PACKAGE = ARTIFACTS / NEW_VERSION


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def fact(
    key: str,
    value,
    *,
    fact_id: str,
    unit: str | None = None,
    days_before: int = 0,
    status: str = "PRESENT",
    verification: str = "CONFIRMED",
    conflict: str = "NONE",
) -> dict:
    item = {"key": key, "value": value, "fact_id": fact_id}
    if unit is not None:
        item["unit"] = unit
    if days_before:
        item["effective_days_before"] = days_before
        item["recorded_days_before"] = days_before
    if status != "PRESENT":
        item["status"] = status
    if verification != "CONFIRMED":
        item["verification"] = verification
    if conflict != "NONE":
        item["conflict"] = conflict
    return item


def context() -> dict:
    return {
        "evaluation_mode": "ENCOUNTER",
        "care_setting": "specialty_clinic",
        "encounter_type": "followup",
    }


def adult_diabetes_facts(*, age: int | None = 58) -> list[dict]:
    values = [fact("condition.codes", ["diabetes"], fact_id="condition")]
    if age is not None:
        values.append(fact("demographic.age_years", age, fact_id="age"))
    return values


def observation_keys(*values: str) -> dict:
    return fact("observation.keys", list(values), fact_id="observation-keys")


def blood_pressure(systolic: float = 130, diastolic: float = 80) -> list[dict]:
    return [
        fact(
            "observation.bp_systolic",
            systolic,
            unit="mm[Hg]",
            fact_id="sbp",
        ),
        fact(
            "observation.bp_diastolic",
            diastolic,
            unit="mm[Hg]",
            fact_id="dbp",
        ),
    ]


def lab(
    key: str,
    value: float,
    unit: str,
    *,
    days_before: int = 0,
    verification: str = "CONFIRMED",
) -> dict:
    return fact(
        f"observation.{key}",
        value,
        unit=unit,
        fact_id=f"lab-{key}",
        days_before=days_before,
        verification=verification,
    )


def medication(values: list[str]) -> dict:
    return fact("medication.classes", values, fact_id="medications")


def task_contract(required_fact: str) -> dict:
    return {
        "due_in_days": 30,
        "task_contract": {
            "urgency": "ROUTINE",
            "allowed_outcome_types": ["LAB_COMPLETED", "OBSERVATION"],
            "required_fact_keys": [required_fact],
            "minimum_verification": "CONFIRMED",
            "canonical_ingestion": "REQUIRED",
            "requires_acknowledgement": True,
        },
        "do_not_auto_message": True,
    }


def base_scope() -> dict:
    return {
        "population": "بزرگسال مبتلا به دیابت نوع ۲ در درمانگاه سرپایی",
        "age_min": 18,
        "age_max": None,
        "sex": ["any"],
        "care_settings": ["outpatient", "primary_care", "specialty_clinic"],
        "encounter_types": ["office_visit", "followup"],
        "condition_codes": ["diabetes"],
        "out_of_scope": ["inpatient care", "pregnancy-specific protocols"],
    }


def eligibility(prefix: str, *, require_metformin: bool = False) -> dict:
    items = [
        {
            "node_id": f"{prefix}-diabetes",
            "fact": "condition.codes",
            "selector": {"aggregation": "single"},
            "op": "has",
            "value": "diabetes",
            "unit": None,
        },
        {
            "node_id": f"{prefix}-adult",
            "fact": "demographic.age_years",
            "selector": {"aggregation": "single"},
            "op": ">=",
            "value": 18,
            "unit": None,
        },
    ]
    if require_metformin:
        items.append(
            {
                "node_id": f"{prefix}-metformin",
                "fact": "medication.classes",
                "selector": {"aggregation": "single"},
                "op": "has",
                "value": "metformin",
                "unit": None,
            }
        )
    return {"node_id": f"{prefix}-eligibility", "all": items}


def standard_required(*, observation_key: str | None = None, metformin: bool = False) -> list[dict]:
    required = [
        {
            "key": "condition.codes",
            "criticality": "CRITICAL",
            "max_age_days": None,
            "minimum_verification": "CONFIRMED",
            "on_unusable": "NEEDS_DATA",
            "prompt_fa": "فهرست تشخیص‌های فعال بیمار باید بازبینی و قابل استفاده باشد.",
        },
        {
            "key": "demographic.age_years",
            "criticality": "REQUIRED",
            "max_age_days": None,
            "minimum_verification": "CONFIRMED",
            "on_unusable": "NEEDS_DATA",
            "prompt_fa": "تاریخ تولد کامل برای احراز بزرگسال‌بودن لازم است.",
        },
    ]
    if metformin:
        required.append(
            {
                "key": "medication.classes",
                "criticality": "CRITICAL",
                "max_age_days": 30,
                "minimum_verification": "CONFIRMED",
                "on_unusable": "NEEDS_DATA",
                "prompt_fa": "فهرست داروهای فعال باید در ۳۰ روز اخیر تطبیق داده شود.",
            }
        )
    if observation_key:
        required.append(
            {
                "key": "observation.keys",
                "criticality": "CRITICAL",
                "max_age_days": None,
                "minimum_verification": "CONFIRMED",
                "on_unusable": "NEEDS_DATA",
                "prompt_fa": "فهرست داده‌های آزمایشگاهی ثبت‌شده باید قابل استفاده باشد.",
            }
        )
    return required


def monitoring_rule(
    *,
    code: str,
    semantic_key: str,
    title: str,
    test_key: str,
    max_days: int,
    prompt: str,
    text: str,
    source_title: str,
    source_locator: str,
    source_url: str,
    grade: str,
    priority: int,
) -> dict:
    prefix = code.lower().replace("_", "-")
    required = standard_required(observation_key=test_key)
    required.append(
        {
            "key": f"observation.{test_key}",
            "criticality": "OPTIONAL",
            "max_age_days": max_days,
            "minimum_verification": "CONFIRMED",
            "on_unusable": "CONTINUE_WITH_WARNING",
            "prompt_fa": prompt,
        }
    )
    return {
        "schema_version": "2.0",
        "dsl_version": "2.0",
        "rule_code": code,
        "version": "2.0.0-draft.3",
        "title": title,
        "phase": "ROUTINE",
        "action_type": "schedule_screening",
        "severity": "WARN",
        "priority": priority,
        "semantic_key": semantic_key,
        "scope": base_scope(),
        "required_facts": required,
        "eligibility": eligibility(prefix),
        "condition": {
            "node_id": f"{prefix}-due",
            "any": [
                {
                    "node_id": f"{prefix}-never-recorded",
                    "fact": "observation.keys",
                    "selector": {"aggregation": "single"},
                    "op": "not_has",
                    "value": test_key,
                    "unit": None,
                },
                {
                    "node_id": f"{prefix}-no-recent-result",
                    "fact": f"observation.{test_key}",
                    "selector": {
                        "aggregation": "count_within_days",
                        "within_days": max_days,
                    },
                    "op": "==",
                    "value": 0,
                    "unit": None,
                },
            ],
        },
        "safety": {
            "redflag_exclusions": [],
            "hard_exclusions": [],
            "on_safety_error": "BLOCK_ROUTINE_OUTPUTS",
        },
        "recommendation": {
            "text_fa": text,
            "suggestion_only": True,
            "requires_clinician_confirmation": True,
            "may_create_internal_task": True,
            "params": task_contract(f"observation.{test_key}"),
        },
        "evidence": {
            "source_title": source_title,
            "issuing_organization": "American Diabetes Association",
            "publication_date": "2026-01-01",
            "source_version": "2026",
            "source_locator": source_locator,
            "source_url": source_url,
            "evidence_certainty": grade,
            "recommendation_strength": "NOT_GRADED",
            "local_validation_status": "NOT_REVIEWED",
            "local_adaptation_note": (
                "پیش‌نویس فنی برای validation و shadow. سررسید فقط از Fact canonical، "
                "زمان as-of و نتیجهٔ تأییدشده محاسبه می‌شود؛ ساخت task منوط به تأیید پزشک است."
            ),
        },
        "governance": {
            "status": "DRAFT",
            "author": "clinical-engine-v2",
            "clinical_reviewer": None,
            "technical_reviewer": "pending",
            "review_due_date": "2026-09-30",
            "supersedes": None,
            "change_note": "First governed monitoring tranche; no active clinical rollout.",
        },
    }


def metformin_review_rule() -> dict:
    required = standard_required(metformin=True)
    required.append(
        {
            "key": "observation.egfr",
            "criticality": "CRITICAL",
            "max_age_days": 90,
            "minimum_verification": "CONFIRMED",
            "on_unusable": "NEEDS_DATA",
            "prompt_fa": "eGFR تأییدشده و حداکثر ۹۰ روزه برای بازبینی ایمنی متفورمین لازم است.",
        }
    )
    return {
        "schema_version": "2.0",
        "dsl_version": "2.0",
        "rule_code": "T2-SAFE-MET-REVIEW",
        "version": "2.0.0-draft.3",
        "title": "بازبینی فایده و خطر متفورمین در eGFR کمتر از ۴۵",
        "phase": "SAFETY",
        "action_type": "safety_alert",
        "severity": "WARN",
        "priority": 15,
        "semantic_key": "diabetes:safety:metformin-egfr-review",
        "scope": {
            **base_scope(),
            "population": "بزرگسال مبتلا به دیابت نوع ۲ و مصرف‌کنندهٔ متفورمین",
            "out_of_scope": [
                "inpatient care",
                "dialysis protocol",
                "acute kidney injury protocol",
            ],
        },
        "required_facts": required,
        "eligibility": eligibility("met-review", require_metformin=True),
        "condition": {
            "node_id": "met-review-range",
            "all": [
                {
                    "node_id": "met-review-lower",
                    "fact": "observation.egfr",
                    "selector": {"aggregation": "latest", "within_days": 90},
                    "op": ">=",
                    "value": 30,
                    "unit": "mL/min/{1.73_m2}",
                },
                {
                    "node_id": "met-review-upper",
                    "fact": "observation.egfr",
                    "selector": {"aggregation": "latest", "within_days": 90},
                    "op": "<",
                    "value": 45,
                    "unit": "mL/min/{1.73_m2}",
                },
            ],
        },
        "safety": {
            "redflag_exclusions": [],
            "hard_exclusions": [],
            "on_safety_error": "BLOCK_ROUTINE_OUTPUTS",
        },
        "recommendation": {
            "text_fa": (
                "فایده و خطر ادامهٔ متفورمین باید توسط پزشک بازبینی شود. "
                "این هشدار نسخه، تغییر دوز یا دستور قطع خودکار ایجاد نمی‌کند."
            ),
            "suggestion_only": True,
            "requires_clinician_confirmation": False,
            "may_create_internal_task": False,
            "params": {
                "do_not_modify_medication": True,
                "requires_medication_review": True,
                "do_not_auto_message": True,
            },
        },
        "evidence": {
            "source_title": "ADA Standards of Care in Diabetes — 2026: Chronic Kidney Disease and Risk Management",
            "issuing_organization": "American Diabetes Association",
            "publication_date": "2026-01-01",
            "source_version": "2026",
            "source_locator": (
                "Section 11, metformin/FDA eGFR guidance: reassess benefits and risks "
                "when eGFR falls below 45; contraindicated below 30."
            ),
            "source_url": (
                "https://diabetesjournals.org/care/article/49/Supplement_1/"
                "S246/163914/11-Chronic-Kidney-Disease-and-Risk-Management"
            ),
            "evidence_certainty": "NOT_GRADED",
            "recommendation_strength": "NOT_GRADED",
            "local_validation_status": "NOT_REVIEWED",
            "local_adaptation_note": (
                "پیش‌نویس ایمنی برای validation و shadow؛ هیچ تغییر دارویی خودکار مجاز نیست."
            ),
        },
        "governance": {
            "status": "DRAFT",
            "author": "clinical-engine-v2",
            "clinical_reviewer": None,
            "technical_reviewer": "pending",
            "review_due_date": "2026-09-30",
            "supersedes": None,
            "change_note": (
                "Add a non-prescriptive review band distinct from the existing eGFR<30 stop alert."
            ),
        },
    }


if NEW_PACKAGE.exists():
    shutil.rmtree(NEW_PACKAGE)
shutil.copytree(OLD_PACKAGE, NEW_PACKAGE)

ADA_GLYCEMIC_URL = (
    "https://diabetesjournals.org/care/article/49/Supplement_1/"
    "S132/163927/6-Glycemic-Goals-Hypoglycemia-and-Hyperglycemic"
)
ADA_CKD_URL = (
    "https://diabetesjournals.org/care/article/49/Supplement_1/"
    "S246/163914/11-Chronic-Kidney-Disease-and-Risk-Management"
)

a1c = monitoring_rule(
    code="T2-MON-A1C-DUE",
    semantic_key="diabetes:monitoring:hba1c-due",
    title="سررسید ارزیابی HbA1c در دیابت نوع ۲",
    test_key="hba1c",
    max_days=183,
    prompt="یک نتیجهٔ HbA1c تأییدشده در شش ماه اخیر لازم است.",
    text=(
        "ارزیابی HbA1c سررسید شده است. پس از تأیید پزشک، نتیجهٔ آزمایش باید "
        "به‌صورت canonical در پرونده ثبت شود."
    ),
    source_title=(
        "ADA Standards of Care in Diabetes — 2026: Glycemic Goals, "
        "Hypoglycemia, and Hyperglycemic Crises"
    ),
    source_locator=(
        "Recommendation 6.2: assess glycemic status at least twice yearly; evidence grade E."
    ),
    source_url=ADA_GLYCEMIC_URL,
    grade="LEGACY_ADA_E",
    priority=100,
)
egfr_due = monitoring_rule(
    code="T2-MON-EGFR-DUE",
    semantic_key="diabetes:monitoring:egfr-due",
    title="سررسید پایش eGFR در دیابت نوع ۲",
    test_key="egfr",
    max_days=365,
    prompt="یک نتیجهٔ eGFR تأییدشده در ۳۶۵ روز اخیر لازم است.",
    text=(
        "پایش eGFR سررسید شده است. پس از تأیید پزشک، نتیجهٔ آزمایش باید "
        "به‌صورت canonical در پرونده ثبت شود."
    ),
    source_title=(
        "ADA Standards of Care in Diabetes — 2026: Chronic Kidney Disease and Risk Management"
    ),
    source_locator=(
        "Recommendation 11.1a: assess eGFR at least annually in all people with "
        "type 2 diabetes; evidence grade B."
    ),
    source_url=ADA_CKD_URL,
    grade="LEGACY_ADA_B",
    priority=110,
)
uacr_due = monitoring_rule(
    code="T2-MON-UACR-DUE",
    semantic_key="diabetes:monitoring:uacr-due",
    title="سررسید پایش UACR در دیابت نوع ۲",
    test_key="uacr",
    max_days=365,
    prompt="یک نتیجهٔ UACR تأییدشده در ۳۶۵ روز اخیر لازم است.",
    text=(
        "پایش نسبت آلبومین به کراتینین ادرار سررسید شده است. پس از تأیید پزشک، "
        "نتیجه باید به‌صورت canonical در پرونده ثبت شود."
    ),
    source_title=(
        "ADA Standards of Care in Diabetes — 2026: Chronic Kidney Disease and Risk Management"
    ),
    source_locator=(
        "Recommendation 11.1a: assess urinary albumin-to-creatinine ratio at least "
        "annually in all people with type 2 diabetes; evidence grade B."
    ),
    source_url=ADA_CKD_URL,
    grade="LEGACY_ADA_B",
    priority=120,
)
met_review = metformin_review_rule()

dump(NEW_PACKAGE / "T2-MON-A1C-DUE.json", a1c)
dump(NEW_PACKAGE / "T2-MON-EGFR-DUE.json", egfr_due)
dump(NEW_PACKAGE / "T2-MON-UACR-DUE.json", uacr_due)
dump(NEW_PACKAGE / "T2-SAFE-MET-REVIEW.json", met_review)

manifest = {
    "ruleset_code": "general-outpatient",
    "version": NEW_VERSION,
    "status": "DRAFT",
    "clinical_use": "NOT_APPROVED",
    "rules": [
        {"file": "T2-REDFLAG-BP.json", "phase": "PREFLIGHT", "sort_order": 10},
        {"file": "T2-SAFE-MET-STOP.json", "phase": "SAFETY", "sort_order": 20},
        {"file": "T2-SAFE-MET-REVIEW.json", "phase": "SAFETY", "sort_order": 30},
        {"file": "T2-MON-A1C-DUE.json", "phase": "ROUTINE", "sort_order": 100},
        {"file": "T2-MON-EGFR-DUE.json", "phase": "ROUTINE", "sort_order": 110},
        {"file": "T2-MON-UACR-DUE.json", "phase": "ROUTINE", "sort_order": 120},
    ],
}
dump(NEW_PACKAGE / "manifest.json", manifest)

CODES = [
    "T2-REDFLAG-BP",
    "T2-SAFE-MET-STOP",
    "T2-SAFE-MET-REVIEW",
    "T2-MON-A1C-DUE",
    "T2-MON-EGFR-DUE",
    "T2-MON-UACR-DUE",
]


def expected(values: dict[str, str]) -> dict[str, str]:
    missing = set(CODES) - set(values)
    extra = set(values) - set(CODES)
    if missing or extra:
        raise RuntimeError(f"invalid expected outcome map missing={missing} extra={extra}")
    return values


cases = [
    {
        "case_id": "GC-GUARD-001",
        "title": "Active severe-pressure red flag suppresses due routine outputs",
        "categories": ["positive", "contraindication", "suppression"],
        "as_of_at": "2026-07-21 12:00:00",
        "context": context(),
        "facts": [
            *adult_diabetes_facts(),
            observation_keys("bp_systolic", "bp_diastolic", "egfr"),
            *blood_pressure(185, 92),
            medication(["metformin"]),
            lab("egfr", 24, "mL/min/{1.73_m2}"),
        ],
        "expected": {
            "outcomes": expected(
                {
                    "T2-REDFLAG-BP": "FIRED",
                    "T2-SAFE-MET-STOP": "FIRED",
                    "T2-SAFE-MET-REVIEW": "NOT_FIRED",
                    "T2-MON-A1C-DUE": "SUPPRESSED",
                    "T2-MON-EGFR-DUE": "NOT_FIRED",
                    "T2-MON-UACR-DUE": "SUPPRESSED",
                }
            ),
            "redflag_rule_codes": ["T2-REDFLAG-BP"],
            "suppression_reasons": {
                "T2-MON-A1C-DUE": "ACTIVE_REDFLAG",
                "T2-MON-UACR-DUE": "ACTIVE_REDFLAG",
            },
        },
    },
    {
        "case_id": "GC-NEG-001",
        "title": "All monitoring is current and no metformin safety population applies",
        "categories": ["negative"],
        "as_of_at": "2026-07-21 12:00:00",
        "context": context(),
        "facts": [
            *adult_diabetes_facts(),
            observation_keys("bp_systolic", "bp_diastolic", "hba1c", "egfr", "uacr"),
            *blood_pressure(),
            medication([]),
            lab("hba1c", 6.8, "%"),
            lab("egfr", 75, "mL/min/{1.73_m2}"),
            lab("uacr", 12, "mg/g"),
        ],
        "expected": {
            "outcomes": expected(
                {
                    "T2-REDFLAG-BP": "NOT_FIRED",
                    "T2-SAFE-MET-STOP": "NOT_APPLICABLE",
                    "T2-SAFE-MET-REVIEW": "NOT_APPLICABLE",
                    "T2-MON-A1C-DUE": "NOT_FIRED",
                    "T2-MON-EGFR-DUE": "NOT_FIRED",
                    "T2-MON-UACR-DUE": "NOT_FIRED",
                }
            ),
            "redflag_rule_codes": [],
        },
    },
    {
        "case_id": "GC-BORDER-001",
        "title": "Inclusive monitoring windows and exact metformin review lower boundary",
        "categories": ["borderline", "positive"],
        "as_of_at": "2026-07-21 12:00:00",
        "context": context(),
        "facts": [
            *adult_diabetes_facts(age=40),
            observation_keys("bp_systolic", "bp_diastolic", "hba1c", "egfr", "uacr"),
            *blood_pressure(180, 80),
            medication(["metformin"]),
            lab("hba1c", 7.1, "%", days_before=183),
            lab("egfr", 30, "mL/min/{1.73_m2}"),
            lab("uacr", 22, "mg/g", days_before=365),
        ],
        "expected": {
            "outcomes": expected(
                {
                    "T2-REDFLAG-BP": "FIRED",
                    "T2-SAFE-MET-STOP": "NOT_FIRED",
                    "T2-SAFE-MET-REVIEW": "FIRED",
                    "T2-MON-A1C-DUE": "NOT_FIRED",
                    "T2-MON-EGFR-DUE": "NOT_FIRED",
                    "T2-MON-UACR-DUE": "NOT_FIRED",
                }
            ),
            "redflag_rule_codes": ["T2-REDFLAG-BP"],
        },
    },
    {
        "case_id": "GC-A1C-DUE-001",
        "title": "Confirmed HbA1c older than 183 days is due",
        "categories": ["positive", "historical-as-of"],
        "as_of_at": "2026-07-21 12:00:00",
        "context": context(),
        "facts": [
            *adult_diabetes_facts(),
            observation_keys("bp_systolic", "bp_diastolic", "hba1c", "egfr", "uacr"),
            *blood_pressure(),
            medication([]),
            lab("hba1c", 7.4, "%", days_before=184),
            lab("egfr", 80, "mL/min/{1.73_m2}"),
            lab("uacr", 18, "mg/g"),
        ],
        "expected": {
            "outcomes": expected(
                {
                    "T2-REDFLAG-BP": "NOT_FIRED",
                    "T2-SAFE-MET-STOP": "NOT_APPLICABLE",
                    "T2-SAFE-MET-REVIEW": "NOT_APPLICABLE",
                    "T2-MON-A1C-DUE": "FIRED",
                    "T2-MON-EGFR-DUE": "NOT_FIRED",
                    "T2-MON-UACR-DUE": "NOT_FIRED",
                }
            )
        },
    },
    {
        "case_id": "GC-EGFR-DUE-001",
        "title": "Confirmed eGFR older than 365 days is due",
        "categories": ["positive", "historical-as-of"],
        "as_of_at": "2026-07-21 12:00:00",
        "context": context(),
        "facts": [
            *adult_diabetes_facts(),
            observation_keys("bp_systolic", "bp_diastolic", "hba1c", "egfr", "uacr"),
            *blood_pressure(),
            medication([]),
            lab("hba1c", 6.9, "%"),
            lab("egfr", 76, "mL/min/{1.73_m2}", days_before=366),
            lab("uacr", 11, "mg/g"),
        ],
        "expected": {
            "outcomes": expected(
                {
                    "T2-REDFLAG-BP": "NOT_FIRED",
                    "T2-SAFE-MET-STOP": "NOT_APPLICABLE",
                    "T2-SAFE-MET-REVIEW": "NOT_APPLICABLE",
                    "T2-MON-A1C-DUE": "NOT_FIRED",
                    "T2-MON-EGFR-DUE": "FIRED",
                    "T2-MON-UACR-DUE": "NOT_FIRED",
                }
            )
        },
    },
    {
        "case_id": "GC-UACR-DUE-001",
        "title": "Confirmed UACR older than 365 days is due",
        "categories": ["positive", "historical-as-of"],
        "as_of_at": "2026-07-21 12:00:00",
        "context": context(),
        "facts": [
            *adult_diabetes_facts(),
            observation_keys("bp_systolic", "bp_diastolic", "hba1c", "egfr", "uacr"),
            *blood_pressure(),
            medication([]),
            lab("hba1c", 6.9, "%"),
            lab("egfr", 76, "mL/min/{1.73_m2}"),
            lab("uacr", 11, "mg/g", days_before=366),
        ],
        "expected": {
            "outcomes": expected(
                {
                    "T2-REDFLAG-BP": "NOT_FIRED",
                    "T2-SAFE-MET-STOP": "NOT_APPLICABLE",
                    "T2-SAFE-MET-REVIEW": "NOT_APPLICABLE",
                    "T2-MON-A1C-DUE": "NOT_FIRED",
                    "T2-MON-EGFR-DUE": "NOT_FIRED",
                    "T2-MON-UACR-DUE": "FIRED",
                }
            )
        },
    },
    {
        "case_id": "GC-MISSING-AGE-001",
        "title": "Adult applicability cannot be established",
        "categories": ["missing-data"],
        "as_of_at": "2026-07-21 12:00:00",
        "context": context(),
        "facts": [
            *adult_diabetes_facts(age=None),
            observation_keys("bp_systolic", "bp_diastolic", "hba1c", "egfr", "uacr"),
            *blood_pressure(),
            medication(["metformin"]),
            lab("hba1c", 7.0, "%"),
            lab("egfr", 40, "mL/min/{1.73_m2}"),
            lab("uacr", 10, "mg/g"),
        ],
        "expected": {
            "outcomes": expected({code: "NEEDS_DATA" for code in CODES}),
            "required_missing_facts": {
                code: ["demographic.age_years"] for code in CODES
            },
        },
    },
    {
        "case_id": "GC-CONFLICT-001",
        "title": "Conflicting condition collection cannot establish diabetes eligibility",
        "categories": ["conflict"],
        "as_of_at": "2026-07-21 12:00:00",
        "context": context(),
        "facts": [
            fact(
                "condition.codes",
                None,
                fact_id="condition-conflict",
                status="UNKNOWN",
                verification="UNVERIFIED",
                conflict="PRESENT",
            ),
            fact("demographic.age_years", 63, fact_id="age"),
            observation_keys("bp_systolic", "bp_diastolic", "hba1c", "egfr", "uacr"),
            *blood_pressure(),
            medication(["metformin"]),
            lab("hba1c", 7.0, "%"),
            lab("egfr", 40, "mL/min/{1.73_m2}"),
            lab("uacr", 10, "mg/g"),
        ],
        "expected": {
            "outcomes": expected({code: "NEEDS_DATA" for code in CODES}),
            "required_missing_facts": {
                code: ["condition.codes"] for code in CODES
            },
        },
    },
    {
        "case_id": "GC-OBS-SOURCE-001",
        "title": "Unavailable observation collection blocks monitoring without false due tasks",
        "categories": ["missing-data"],
        "as_of_at": "2026-07-21 12:00:00",
        "context": context(),
        "facts": [*adult_diabetes_facts(), medication([])],
        "expected": {
            "outcomes": expected(
                {
                    "T2-REDFLAG-BP": "NEEDS_DATA",
                    "T2-SAFE-MET-STOP": "NOT_APPLICABLE",
                    "T2-SAFE-MET-REVIEW": "NOT_APPLICABLE",
                    "T2-MON-A1C-DUE": "NEEDS_DATA",
                    "T2-MON-EGFR-DUE": "NEEDS_DATA",
                    "T2-MON-UACR-DUE": "NEEDS_DATA",
                }
            ),
            "required_missing_facts": {
                "T2-MON-A1C-DUE": ["observation.keys"],
                "T2-MON-EGFR-DUE": ["observation.keys"],
                "T2-MON-UACR-DUE": ["observation.keys"],
            },
        },
    },
    {
        "case_id": "GC-SCOPE-001",
        "title": "Non-diabetic patient is outside the tranche population",
        "categories": ["negative"],
        "as_of_at": "2026-07-21 12:00:00",
        "context": context(),
        "facts": [
            fact("condition.codes", ["hypertension"], fact_id="condition"),
            fact("demographic.age_years", 58, fact_id="age"),
            observation_keys("bp_systolic", "bp_diastolic", "hba1c", "egfr", "uacr"),
            *blood_pressure(190, 120),
            medication(["metformin"]),
            lab("hba1c", 9.0, "%", days_before=400),
            lab("egfr", 20, "mL/min/{1.73_m2}", days_before=400),
            lab("uacr", 400, "mg/g", days_before=400),
        ],
        "expected": {
            "outcomes": expected({code: "NOT_APPLICABLE" for code in CODES}),
            "redflag_rule_codes": [],
        },
    },
    {
        "case_id": "GC-MINOR-001",
        "title": "Minor is outside the adult tranche population",
        "categories": ["negative"],
        "as_of_at": "2026-07-21 12:00:00",
        "context": context(),
        "facts": [
            *adult_diabetes_facts(age=17),
            observation_keys("bp_systolic", "bp_diastolic", "hba1c", "egfr", "uacr"),
            *blood_pressure(190, 120),
            medication(["metformin"]),
            lab("hba1c", 9.0, "%", days_before=400),
            lab("egfr", 20, "mL/min/{1.73_m2}", days_before=400),
            lab("uacr", 400, "mg/g", days_before=400),
        ],
        "expected": {
            "outcomes": expected({code: "NOT_APPLICABLE" for code in CODES}),
            "redflag_rule_codes": [],
        },
    },
    {
        "case_id": "GC-UNVERIFIED-A1C-001",
        "title": "Recent but unverified HbA1c cannot clear or trigger the due rule",
        "categories": ["missing-data"],
        "as_of_at": "2026-07-21 12:00:00",
        "context": context(),
        "facts": [
            *adult_diabetes_facts(),
            observation_keys("bp_systolic", "bp_diastolic", "hba1c", "egfr", "uacr"),
            *blood_pressure(),
            medication([]),
            lab("hba1c", 7.2, "%", verification="PROVISIONAL"),
            lab("egfr", 78, "mL/min/{1.73_m2}"),
            lab("uacr", 15, "mg/g"),
        ],
        "expected": {
            "outcomes": expected(
                {
                    "T2-REDFLAG-BP": "NOT_FIRED",
                    "T2-SAFE-MET-STOP": "NOT_APPLICABLE",
                    "T2-SAFE-MET-REVIEW": "NOT_APPLICABLE",
                    "T2-MON-A1C-DUE": "NEEDS_DATA",
                    "T2-MON-EGFR-DUE": "NOT_FIRED",
                    "T2-MON-UACR-DUE": "NOT_FIRED",
                }
            ),
            "required_missing_facts": {
                "T2-MON-A1C-DUE": ["observation.hba1c"]
            },
        },
    },
]

dump(
    NEW_PACKAGE / "validation-cases.json",
    {
        "schema_version": "1.0",
        "package_version": NEW_VERSION,
        "description": (
            "A12 technical golden matrix for the first governed diabetes monitoring "
            "tranche. Clinical approval remains a separate append-only gate."
        ),
        "cases": cases,
    },
)

release_path = SPECIALIST / "src/domain/clinical_engine/release.py"
release_text = release_path.read_text(encoding="utf-8")
old_line = f'CURRENT_BUNDLED_PACKAGE_VERSION = "{OLD_VERSION}"'
new_line = f'CURRENT_BUNDLED_PACKAGE_VERSION = "{NEW_VERSION}"'
if new_line not in release_text:
    if old_line not in release_text:
        raise RuntimeError("A12 release identity anchor is missing")
    release_path.write_text(
        release_text.replace(old_line, new_line, 1),
        encoding="utf-8",
    )

test_path = SPECIALIST / "tests/test_clinical_rule_library_tranche_a12.py"
test_path.write_text(
    '''# A12 governed diabetes monitoring tranche contract tests.
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.domain.clinical_engine.release import CURRENT_BUNDLED_PACKAGE_VERSION
from src.services.clinical_engine.package_contract import load_rule_package
from src.services.clinical_engine.validation_harness import (
    GoldenCaseValidationHarness,
    package_directory,
)


EXPECTED_CODES = {
    "T2-REDFLAG-BP",
    "T2-SAFE-MET-STOP",
    "T2-SAFE-MET-REVIEW",
    "T2-MON-A1C-DUE",
    "T2-MON-EGFR-DUE",
    "T2-MON-UACR-DUE",
}


def _package():
    return load_rule_package(
        package_directory(),
        expected_version=CURRENT_BUNDLED_PACKAGE_VERSION,
    )


def test_a12_package_is_current_complete_and_still_not_approved():
    package = _package()

    assert CURRENT_BUNDLED_PACKAGE_VERSION == "2026.1-draft.3"
    assert set(package.rule_codes) == EXPECTED_CODES
    assert package.manifest["status"] == "DRAFT"
    assert package.manifest["clinical_use"] == "NOT_APPROVED"
    assert all(
        rule.definition.evidence["local_validation_status"] == "NOT_REVIEWED"
        for rule in package.compiled_rules
    )


def test_a12_monitoring_rules_have_exact_confirmed_canonical_completion_contracts():
    package = _package()
    rules = {
        rule.definition.rule_code: rule.definition
        for rule in package.compiled_rules
    }
    expected = {
        "T2-MON-A1C-DUE": ("observation.hba1c", 183),
        "T2-MON-EGFR-DUE": ("observation.egfr", 365),
        "T2-MON-UACR-DUE": ("observation.uacr", 365),
    }

    for code, (fact_key, max_days) in expected.items():
        definition = rules[code]
        recommendation = definition.recommendation
        params = recommendation["params"]
        contract = params["task_contract"]

        assert definition.action_type.value == "schedule_screening"
        assert definition.phase.value == "ROUTINE"
        assert recommendation["requires_clinician_confirmation"] is True
        assert recommendation["may_create_internal_task"] is True
        assert params["due_in_days"] == 30
        assert contract["required_fact_keys"] == (fact_key,)
        assert contract["minimum_verification"] == "CONFIRMED"
        assert contract["canonical_ingestion"] == "REQUIRED"
        fact_policy = next(
            item for item in definition.required_facts
            if item["key"] == fact_key
        )
        assert fact_policy["max_age_days"] == max_days


def test_a12_metformin_review_is_non_prescriptive_and_distinct_from_stop_rule():
    package = _package()
    rules = {
        rule.definition.rule_code: rule.definition
        for rule in package.compiled_rules
    }
    review = rules["T2-SAFE-MET-REVIEW"]
    stop = rules["T2-SAFE-MET-STOP"]

    assert review.phase.value == "SAFETY"
    assert review.recommendation["may_create_internal_task"] is False
    assert review.recommendation["params"]["do_not_modify_medication"] is True
    assert review.semantic_key != stop.semantic_key
    assert review.priority > stop.priority


def test_a12_golden_matrix_passes_without_error_or_false_classification():
    report = GoldenCaseValidationHarness().run()

    assert report["status"] == "PASS"
    assert report["checks"]["all_cases_pass"] is True
    assert report["checks"]["zero_errors"] is True
    assert report["checks"]["zero_false_positive"] is True
    assert report["checks"]["zero_false_negative"] is True
    assert set(report["metrics"]) == EXPECTED_CODES
    assert all(
        values["true_positive"] > 0 and values["true_negative"] > 0
        for values in report["metrics"].values()
    )
''',
    encoding="utf-8",
)

docs = SPECIALIST / "docs/clinical_rule_library_tranche_a12.md"
docs.write_text(
    '''# A12 — اولین tranche کنترل‌شدهٔ کتابخانهٔ قواعد دیابت

## وضعیت انتشار

این tranche با شناسهٔ `2026.1-draft.3` فقط یک بستهٔ **DRAFT / NOT_APPROVED / NOT_REVIEWED** است. عبور تست فنی به‌معنی تأیید بالینی یا اجازهٔ نمایش به کاربر نیست.

## قواعد افزوده‌شده

- `T2-MON-A1C-DUE`: نبودن HbA1c یا نداشتن نتیجهٔ تأییدشده در ۱۸۳ روز اخیر.
- `T2-MON-EGFR-DUE`: نبودن eGFR یا نداشتن نتیجهٔ تأییدشده در ۳۶۵ روز اخیر.
- `T2-MON-UACR-DUE`: نبودن UACR یا نداشتن نتیجهٔ تأییدشده در ۳۶۵ روز اخیر.
- `T2-SAFE-MET-REVIEW`: بازبینی غیرتجویزی متفورمین در eGFR از ۳۰ تا کمتر از ۴۵.

## مرزهای ایمنی

- سررسیدها فقط با Factهای canonical و زمان `as_of_at` محاسبه می‌شوند.
- نتیجهٔ تازه اما تأییدنشده، وضعیت را به `NEEDS_DATA` می‌برد و task کاذب ایجاد نمی‌کند.
- Ruleهای سررسید فقط پس از تصمیم `ACCEPTED` پزشک task می‌سازند.
- تکمیل هر task به نتیجهٔ canonical، تأییدشده و دقیقاً هم‌نوع با آزمایش موردنیاز وابسته است.
- هشدار متفورمین هیچ نسخه، تغییر دوز یا قطع خودکار ایجاد نمی‌کند.
- هشدار فوری فعال، Ruleهای روتینِ درحال fire را با دلیل `ACTIVE_REDFLAG` suppress می‌کند.
- Rule هیپوگلیسمی تا زمانی که Factهای عمومی glucose/CGM و نیاز به کمک خارجی به‌صورت canonical ساخته نشوند، وارد بسته نمی‌شود.

## شواهد مبنا

- ADA Standards of Care in Diabetes — 2026، توصیهٔ 6.2 برای ارزیابی وضعیت قند حداقل دوبار در سال.
- ADA Standards of Care in Diabetes — 2026، توصیهٔ 11.1a برای UACR و eGFR حداقل سالانه در همهٔ افراد مبتلا به دیابت نوع ۲.
- همان بخش CKD برای مرز بازبینی فایده/خطر متفورمین زیر eGFR 45 و ممنوعیت زیر 30.

## گام‌های لازم پیش از shadow

1. بازبینی متن منبع و locator توسط پزشک مالک Rule.
2. تأیید مستقل Fact، unit، eligibility، threshold و exclusionها.
3. اجرای golden matrix و dependency analysis روی دادهٔ de-identified محلی.
4. امضای clinical و technical attestation به‌صورت append-only.
5. اجرای SILENT، تحلیل failure/NEEDS_DATA و سپس pilot محدود با seal دقیق.
''',
    encoding="utf-8",
)

print(
    f"A12 package {NEW_VERSION} generated with "
    f"{len(manifest['rules'])} rules and {len(cases)} cases"
)
