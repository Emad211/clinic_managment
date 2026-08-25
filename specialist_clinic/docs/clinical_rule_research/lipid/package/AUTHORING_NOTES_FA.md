# یادداشت‌های تألیف — بستهٔ پیش‌نویس قواعد مدیریت لیپید (`lipid-core-v1` v0.1.0-draft)

```text
PACKAGE      = RULE_PACKAGE_LIPID_DRAFT_v0.1.json
SOURCE       = GUIDELINE_DOSSIER_FA (lipid) — docs/clinical_rule_research/lipid/GUIDELINE_DOSSIER_FA.md (2026-08-23)
SCHEMA REF   = src/domain/clinical_engine/schemas/clinical-rule.schema.json (v2.0)
STATUS       = DRAFT — clinical_use = NOT_APPROVED_HISTORICAL_REGRESSION_ONLY
GENERATED    = 2026-08-23
```

> **هشدار حاکمیتی:** این بسته فقط یک پیش‌نویس داده‌ای است. به runtime، کامپایلر یا هیچ مسیر اجرایی **متصل نیست**.
> فعال‌سازی مستلزم (۱) اعتبارسنجی `package_contract`، (۲) بازبینی بالینی مستقل و (۳) کلیک مالک است.
> راهنمای ۲۰۲۶ ACC/AHA [14] رسماً راهنمای ۲۰۱۸ را بازنشسته کرده (G15)؛ اعداد این بسته بر ESC/EAS 2019 + ACC/AHA 2018 + AACE 2025 + KDIGO 2013/2024 استوارند و بازبینی تطبیقی با [14] پیش از freeze لازم است.

---

## ۱) شمارش قواعد بر حسب دسته

**بر حسب فاز:**

| فاز | تعداد | قواعد |
|---|---|---|
| ROUTINE | ۱۹ | R01–R14، R16–R18، R23، R24 |
| SAFETY | ۴ | R19 (ALT پایه)، R20 (CK علائم عضلانی)، R21 (سقف سیمواستاتین/آملودیپین)، R22 (مسیر عدم تحمل) |
| PREFLIGHT | ۱ | R15 (TG≥500 — redflag داسیه) |

**بر حسب action_type:**

| action | تعداد | قواعد |
|---|---|---|
| set_target | ۴ | R01، R02، R03، R04 |
| suggest_med | ۱۰ | R05، R06، R07، R08، R09، R13، R14، R15، R16، R18 |
| create_followup | ۵ | R11، R12، R17، R21، R22 |
| schedule_screening | ۴ | R10، R19، R23، R24 |
| educate | ۱ | R04 |

جمع: **۲۴ قاعده** (LIPID-R01 … LIPID-R24؛ کد داسیه با زیرخط `LIPID_Rxx` بود، در بسته با خط تیره). ترتیب آرایهٔ `rules[]` همان ترتیب بخش‌های داسیه است.

**سایر نگاشت‌ها:** severity داسیه critical/high/medium/low → CRITICAL/URGENT/WARN/INFO؛ priority داسیه ۱..۵ → ×100 (100..500)؛ `may_create_internal_task=true` فقط برای create_followup/schedule_screening (۱۰ قاعده)؛ `requires_clinician_confirmation=true` برای همهٔ ۲۴ قاعده.

## ۲) تطبیق‌های ساختاری (Operator/DSL)

1. **`var` → `fact`:** `indicator.X.latest` → `lab.X` با `selector.aggregation="latest"`؛ `med.class` → `medication.<class_key>`؛ `condition` → `condition.<code>`؛ `flag.<key>` → fact کاتالوگ فلگ.
2. **`op=has`:** → `truthy`. **`op=not_has`:** → گرهٔ `not{truthy}` (نه عملگر not_has) تا معنا بدون ابهامِ value کامپایل شود (R05, R07, R08, R09, R13, R17, R19).
3. **`node_id`:** شناسه‌های قطعی `<CODE>-e*/c*` روی هر گرهٔ expression (الزام اسکیما + کامپایلر).
4. **تریگرهای خام:** عیناً در کلید ریشهٔ `dossier_triggers` حفظ شده‌اند (شامل اتم‌های `ext_*` و noteها)، چون اسکیما `additionalProperties:false` دارد.
5. **Priority ×100:** ۱..۵ داسیه → 100..500 (قرارداد redflags).
6. **Severity mapping:** critical→CRITICAL، high→URGENT، medium→WARN، low→INFO.
7. **واژگان facts طبق دستور کار:** lab.ldl / lab.triglyceride / lab.hdl / lab.egfr، condition.diabetes / condition.hyperlipidemia، flag.ascvd / flag.cvd_high_risk / flag.masld، medication.statin / medication.ezetimibe / medication.fibrate (+ کلیدهای قراردادی §۳). دوزهای suggest_med به‌صورت رشتهٔ عیناً حفظ شده‌اند: «atorvastatin 40–80» پرشدت، «ezetimibe 10 mg»، «icosapent ethyl 2 g BID» با optional=true، «bempedoic acid 180 mg»، «fenofibrate 145–160 mg».

## ۳) شکاف DSL و الگوی «قرارداد fact-key» (مهم‌ترین تطبیق)

DSL 2.0 اتم سن ندارد (G2) و چند تریگر داسیه (`ext_*`) را نمی‌بیند. طبق دستور صریح کار:

- **هیچ placeholder تریگری که بتواند misfire کند ساخته نشد.**
- الزام سن به `required_facts` منتقل شد: کلید **`patient.age_years`** با `criticality=CRITICAL` و `on_unusable=NEEDS_DATA` (fail-closed — بدون تأمین سن از سوی evaluator، قاعده اجرا نمی‌شود) و مقایسهٔ واقعی سن (`>=`, `between`) عیناً در شرط نوشته شد. `scope.age_min/age_max` فقط فرادادهٔ اعلامی است.
- همین الگو برای سایر ورودی‌های بیان‌ناپذیر تعمیم یافت — کلید آینده در required_facts (NEEDS_DATA یا OPTIONAL/CONTINUE_WITH_WARNING برای شاخه‌های اختیاری) + شرط واقعی روی همان کلید:

| کلید قراردادی | قواعد | شکاف داسیه | on_unusable |
|---|---|---|---|
| `patient.age_years` | R02, R07, R09, R17 | G2 (اتم سن) | NEEDS_DATA |
| `medication.statin_change_weeks_ago` | R10 | G5 (رویداد تغییر دارو) | NEEDS_DATA |
| `patient.adherence_confirmed` | R11 | G6 (منبع پایبندی) | NEEDS_DATA |
| `medication.statin_max_tolerated_confirmed` | R13 | G4 (دید دوز مولکول) | NEEDS_DATA |
| `flag.statin_intolerance_documented` | R14, R22 | G13 (فلگ جدید) | NEEDS_DATA |
| `patient.diabetes_risk_enhancer_present` | R17 | G9 (عوامل خطر ADA) | NEEDS_DATA |
| `patient.albuminuria_a2_a3_present` | R18 | G9 (ckd_stage_a خارج واژگان) | CONTINUE_WITH_WARNING |
| `medication.current_intensity_below_high` | R18 | G4 (شدت فعلی) | NEEDS_DATA |
| `medication.statin_start_planned` | R19 | G5 (رویداد پیشنهاد دارو) | NEEDS_DATA |
| `symptom.muscle_pain_weakness_dark_urine` | R20 | G10 (ورودی علائم) | NEEDS_DATA |
| `medication.amlodipine` | R21 | G11 (مولکول فعال) | NEEDS_DATA |
| `medication.simvastatin_dose_mg` | R21 | G4 (دوز مولکول) | NEEDS_DATA |
| `patient.newly_diagnosed_dm_or_htn` | R23 | G12 (op جدید) | CONTINUE_WITH_WARNING |
| `screening.last_lipid_panel_months_ago` | R24 | G5 (تاریخ آخرین پنل) | NEEDS_DATA |

- تفاوت عمدی با الگوی SILENT بستهٔ redflags: آنجا condition جانشینِ `exists` می‌توانست misfire کند؛ اینجا تریگر واقعی عیناً در شرط نوشته شده و فقط «تأمین داده» به evaluator واگذار شده است. تا تأمین هر کلید، قاعدهٔ مربوط fail-closed اجرا نمی‌شود.
- **G1 (baseline LDL):** الزام «کاهش ≥50٪ از baseline» در R01/R02 قابل ارزیابی نیست؛ عدد 50 عیناً در `params.pct_reduction_min` حفظ شده و به‌عنوان شکاف DSL ثبت شده است — هیچ شرط جانشین ساخته نشد.
- **R04 (fallback):** trigger داسیه «سایر/else» بود که بیان‌پذیر نیست؛ gate واقعی `condition.hyperlipidemia` گذاشته شد و صحت آن به ترتیب **first-match-wins R01→R02→R03→R04** وابسته است (نکتهٔ خود داسیه).
- **R09 (دیالیز):** حذف بیماران دیالیزی نیازمند `flag.ckd_stage_g` است که خارج واژگان مجاز این بسته است؛ هشدار دیالیز در متن توصیه حمل می‌شود و افزودن فلگ پیش از فعال‌سازی لازم است.

## ۴) تصمیم‌های تألیفی که نیاز به تأیید مالک دارند

- `may_create_internal_task=true` فقط برای create_followup/schedule_screening (R10,R11,R12,R17,R19,R20,R21,R22,R23,R24)؛ بقیه false.
- `requires_clinician_confirmation=true` برای همهٔ ۲۴ قاعده (فراتر از CONFIRMATION_REQUIRED کامپایلر).
- `review_due_date = 2026-11-21` (۹۰ روزه؛ مالک می‌تواند تغییر دهد).
- Evidence URLs فقط از DOI/PMID ارجاع داسیه یا Article ID خود داسیه ([4] AACE) مکانیکی ساخته شده‌اند؛ مورد FDA [13] به بخش عمومی Drug Safety اشاره دارد و نشانی دقیق باید تکمیل شود (`local_adaptation_note` در R21).
- `evidence_certainty`/`recommendation_strength` = NOT_GRADED؛ `local_validation_status` = NOT_REVIEWED برای همه (اطلاعات Class I/LOE داخل source_locator حفظ شده).
- واحدها mg/dL (تعهد G3)؛ mmol/L فقط نمایشی.
- همپوشانی R15 با SF-LAB-02 بستهٔ redflags-cross-v1 — dedupe با مالک.
- خارج از دامنهٔ عمدی: PCSK9i (G8)، exclusion بارداری (G16)، TSH علل ثانویه (G17)، خروجی SMS governed (G18)، بازبینی تطبیقی ACC/AHA 2026 (G15)، کتاب‌شناسی کامل AACE (G14).

## ۵) نتیجهٔ اعتبارسنجی jsonschema

```text
METHOD   = jsonschema.Draft202012Validator + FormatChecker
SCHEMA   = src/domain/clinical_engine/schemas/clinical-rule.schema.json
SCOPE    = هر عضو rules[] به‌عنوان RuleDefinition مستقل
$ref     = فقط ارجاع داخلی (#/$defs/expression) — نیازی به registry بیرونی نبود
RESULT   = ALL_VALID — 24/24 قاعده VALID (صفر خطا)
```

خروجی دقیق اجرا (2026-08-23): LIPID-R01…LIPID-R24 همگی `VALID`. نتیجه همچنین داخل خود JSON در کلید `validation` ثبت شده است.

## ۶) گام بعدی (خارج از محدودهٔ این تسک)

1. بازبینی بالینی مستقل هر ۲۴ قاعده — به‌ویژه قواعد وابسته به کلیدهای قراردادی §۳ و دو مسیر first-match-wins/fallback.
2. تصمیم دربارهٔ کلیدهای قراردادی (افزودن additive به کاتالوگ فلگ‌ها/فکت‌ها یا تعریف evaluator) و dedupe با SF-LAB-02.
3. اعتبارسنجی `package_contract` + گزارش v2 روی cohort ده‌تایی TEST0001–TEST0010 و سپس کلیک مالک.
