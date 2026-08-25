# یادداشت‌های تألیف — بستهٔ پیش‌نویس قواعد فشار خون (`htn-core-v1` v0.1.0-draft)

```text
PACKAGE      = RULE_PACKAGE_HTN_DRAFT_v0.1.json
SOURCE       = GUIDELINE_DOSSIER_FA v1.0.0 (2026-08-23)
SCHEMA REF   = src/domain/clinical_engine/schemas/clinical-rule.schema.json (v2.0)
PATTERN REF  = docs/clinical_rule_research/redflags/package/RULE_PACKAGE_RED_FLAGS_DRAFT_v0.1.json (+AUTHORING_NOTES_FA.md)
STATUS       = DRAFT — clinical_use = NOT_APPROVED_HISTORICAL_REGRESSION_ONLY
GENERATED    = 2026-08-23
```

> **هشدار حاکمیتی:** این بسته فقط یک پیش‌نویس داده‌ای است. به runtime، کامپایلر یا هیچ مسیر اجرایی **متصل نیست**.
> فعال‌سازی مستلزم (۱) اعتبارسنجی `package_contract`، (۲) بازبینی بالینی مستقل و (۳) کلیک مالک است.
> تعامل با governance FO-6 طبق شکاف #۱۲ داسیه: همهٔ قواعد فقط «پیشنهاد به پزشک» تولید می‌کنند؛ هیچ مسیر auto-send ندارند.

---

## ۱) جدول نگاشت داسیه → بسته

| داسیه | کد در بسته | فاز | اکشن | Severity | Priority (×100) | due |
|---|---|---|---|---|---|---|
| §۱ R01a/b | HTN-R01A/B | ROUTINE | classify | URGENT | 1000 | — |
| §۱ R02a/b | HTN-R02A/B | ROUTINE | classify | WARN | 1200 | — |
| §۱ R03 | HTN-R03 | ROUTINE | educate | INFO | 1400 | — |
| §۱ R04 | HTN-R04 | ROUTINE | classify | INFO | 9900 | — |
| §۱ R05a/b | HTN-R05A/B | PREFLIGHT | create_followup | CRITICAL | 100 | 24h |
| §۲ R06 | HTN-R06 | ROUTINE | set_target | WARN | 2000 | — |
| §۲ R07 | HTN-R07 | ROUTINE | set_target | URGENT | 1800 | — |
| §۲ R08 | HTN-R08 | ROUTINE | set_target | URGENT | 1600 | — |
| §۲ R09 | HTN-R09 | ROUTINE | set_target | WARN | 1700 | — |
| §۲ R10 | HTN-R10 | SAFETY | create_followup | URGENT | 800 | 14d |
| §۳ R11 | HTN-R11 | ROUTINE | suggest_med | URGENT | 2200 | — |
| §۳ R12 | HTN-R12 | ROUTINE | suggest_med | WARN | 2400 | — |
| §۳ R13 | HTN-R13 | ROUTINE | suggest_med | WARN | 2300 | — |
| §۳ R14 | HTN-R14 | ROUTINE | suggest_med | WARN | 2600 | — |
| §۳ R15 | HTN-R15 | SAFETY | suggest_med | URGENT | 1500 | — |
| §۴ R16a/b | HTN-R16A/B | ROUTINE | suggest_med | URGENT | 2100 | — |
| §۴ R17 | HTN-R17 | SAFETY | create_followup | CRITICAL | 500 | 24h |
| §۴ R18 | HTN-R18 | ROUTINE | suggest_med | URGENT | 1900 | — |
| §۴ R19 | HTN-R19 | SAFETY | schedule_screening | CRITICAL | 600 | 7d + repeat 28d |
| §۴ R20 | HTN-R20 | ROUTINE | create_followup | URGENT | 1300 | 30d |
| §۵ R21 | HTN-R21 | ROUTINE | suggest_med | URGENT | 1400 | — |
| §۵ R22 | HTN-R22 | ROUTINE | suggest_med | URGENT | 1100 | — |
| §۵ R23 | HTN-R23 | ROUTINE | suggest_med | WARN | 2700 | — |
| §۵ R24 | HTN-R24 | ROUTINE | educate | URGENT | 1200 | — |
| §۵ R25 | HTN-R25 | ROUTINE | vaccine | INFO | 6000 | — |
| §۶ R26 | HTN-R26 | SAFETY | schedule_screening | URGENT | 900 | 0d (blocking) |
| §۶ R27 | HTN-R27 | SAFETY | schedule_screening | CRITICAL | 700 | 14d (window 14–28) |
| §۶ R28 | HTN-R28 | ROUTINE | schedule_screening | WARN | 3000 | annual |
| §۶ R29 | HTN-R29 | ROUTINE | schedule_screening | INFO | 4000 | annual |
| §۶ R30 | HTN-R30 | ROUTINE | educate | INFO | 4500 | — |
| §۷ R31a/b/c | HTN-R31A/B/C | PREFLIGHT | create_followup | CRITICAL | 200 | 0h (ED now) |
| §۷ R32a/b | HTN-R32A/B | PREFLIGHT | create_followup | URGENT | 300 | 24h (max 72h) |
| §۷ R33 | HTN-R33 | SAFETY | create_followup | CRITICAL | 400 | 24h |
| §۷ R34 | HTN-R34 | SAFETY | create_followup | URGENT | 1000 | 7d |
| §۸ R35 | HTN-R35 | ROUTINE | educate | WARN | 3500 | — |
| §۸ R36 | HTN-R36 | ROUTINE | educate | WARN | 3600 | — |
| §۸ R37 | HTN-R37 | ROUTINE | educate | INFO | 3800 | — |
| §۸ R38 | HTN-R38 | ROUTINE | educate | WARN | 3700 | — |

جمع: **۴۵ قاعدهٔ اجرایی** (۳۸ شناسهٔ داسیه با شاخه‌های a/b/c). ترتیب آرایهٔ `rules[]` همان ترتیب بخش‌های داسیه است؛ رتبه‌بندی اجرایی با `priority`.

### فکت‌های استفاده‌شده در هر قاعده

| کد(ها) | فکت‌ها |
|---|---|
| R01A/R05A/R12/R16A/R31A/R31B/R32A | `observation.bp_systolic` |
| R01B/R02B/R05B/R16B/R31C/R32B | `observation.bp_diastolic` |
| R02A/R03/R04 | `observation.bp_systolic` + `observation.bp_diastolic` |
| R06/R11/R35/R37 | `condition.hypertension` (+ داروها در R11) |
| R07/R21/R28 | `condition.diabetes` (+ داروها در R21، `flag.uacr_done_within_days` در R28) |
| R08/R23 | `condition.ckd` (+ `lab.egfr`, `lab.uacr`, `medication.finerenone` در R23) |
| R09 | `patient.age` (+ `scope.age_min=65`) |
| R10 | `flag.frail_or_orthostatic` |
| R13 | `flag.acei_cough_intolerant` + `medication.ccb` |
| R14 | `flag.hypertension_uncontrolled` + `medication.thiazide` |
| R15 | `lab.egfr` + `medication.thiazide` |
| R17 | `medication.acei` + `medication.arb` |
| R18 | `flag.resistant_htn_3drugs_with_diuretic` + `medication.mra` |
| R19 | `medication.mra` + `flag.mra_started_or_titrated_within_4w` |
| R20 | `flag.resistant_htn_on_4drugs_uncontrolled` |
| R22 | `lab.uacr` + `medication.acei` + `medication.arb` |
| R24 | `flag.ascvd` |
| R25 | `flag.chronic_disease` |
| R26 | `flag.rasi_about_to_start` + `flag.baseline_labs_current` |
| R27 | `flag.rasi_started_or_titrated_within_4w` + `flag.post_change_labs_done` |
| R29 | `flag.hypertension_on_treatment` |
| R30 | `flag.bp_unconfirmed_or_white_coat_suspect` |
| R31*/R32* | BP + `flag.end_organ_symptom` |
| R33 | `flag.potassium_gt_5_5` |
| R34 | `flag.symptomatic_orthostatic_hypotension` |
| R36 | `observation.bmi` |
| R38 | `flag.smoker_or_alcohol_excess` |

## ۲) تطبیق‌های ساختاری (Operator/DSL)

1. **عملگرها:** همهٔ عملگرهای داسیه (`has, not_has, in, between, >=, <, ==, truthy`) زیرمجموعهٔ `SUPPORTED_OPERATORS` در `compiler_support.py` هستند — **هیچ عملگر جدیدی لازم نشد.**
2. **`var` → `fact`:** `indicator.X.latest` → `observation.X` / `lab.X` / `observation.bmi` با `selector.aggregation="latest"`؛ `age` → `patient.age` (داسیه در شکاف #۲ تأیید می‌کند age در DSL فعلی موجود است)؛ `flag.<key>` → fact کاتالوگ فلگ.
3. **`med.class has X` →** برگ `medication.X truthy`. **`med.class not_has X` →** گرهٔ `not{medication.X truthy}` (اسکیما not-expression دارد؛ op=not_has روی فکت بولی medication مبهم بود).
4. **`node_id`:** شناسه‌های قطعی `<CODE>-e*/c*` روی هر گره — ۱۶۹ node_id یکتا (بررسی خودکار شد).
5. **Priority ×100** تا در بازهٔ 0–10000 اسکیما بگنجد (بیشینه: R04 = 9900).
6. **تریگرهای خام:** عیناً (آرایهٔ `conditions` داسیه) در کلید ریشهٔ `dossier_triggers` — ۴۵/۴۵ پوشش کامل.
7. **پسوندهای a/b/c → A/B/C:** الگوی `rule_code` اسکیما (`^[A-Z0-9][A-Z0-9._-]+$`) حروف کوچک نمی‌پذیرد؛ نرمال‌سازی case انجام شد و در change_note هر قاعده ثبت است.
8. **FLAG→FACT نگاشت:** پرچم‌های حضور بیماری (`flag.hypertension`/`flag.diabetes`/`flag.ckd`) → `condition.hypertension`/`condition.diabetes`/`condition.ckd` (سازگار با RED FLAGS)؛ `flag.ascvd` مطابق قرارداد RED FLAGS به‌صورت flag fact ماند؛ سایر پرچم‌های عملیاتی عیناً `flag.<key>`.

## ۳) تفاوت‌های آگاهانه با بستهٔ RED FLAGS

- **encounter_types = `['chronic_followup']`** طبق دستور کار این بسته (RED FLAGS: `outpatient_chronic_care`).
- **author = `research-dossier-conversion`** طبق دستور کار (RED FLAGS: `clinical_rule_research/redflags pipeline`).
- **may_create_internal_task=true فقط برای action_type=create_followup** (۱۰ قاعده: R05A/B، R10، R17، R20، R31A/B/C، R32A/B، R33، R34). این **محدودتر از** `INTERNAL_TASK_ACTIONS` کامپایلر است که `schedule_screening`/`vaccine` را هم شامل می‌شود — تصمیم عمدی طبق دستور کار («true iff create_followup»)؛ مالک می‌تواند هنگام بازبینی تغییر دهد.
- **قاعدهٔ SILENT ساخته نشد.** برخلاف RED FLAGS (SF-REN-02/SF-CM-01 با aggregation delta)، هیچ تریگری از این داسیه بیان‌ناپذیر مطلق نیست — همهٔ تریگرها با flag-based جایگزینِ خودِ داسیه بیان شدند. محدودیت‌ها به‌صورت DSL gap ثبت شده‌اند (بخش ۴).

## ۴) شکاف‌های DSL/داده که اختراع نشدند (طبق Open Gaps داسیه)

1. **ماشین حالت تیتراسیون (R12/R18/R19/R27):** «دوز فعلی زیر max» و «تغییر دوز در ۴ هفتهٔ اخیر» به `med.dose_mg`، `med.at_max_dose` و **timestamp آخرین تغییر دوز** نیاز دارند — در DSL 2.0 وجود ندارد (شکاف #۳ داسیه). شرط جانشین flag-based عیناً از خود داسیه آمده؛ هیچ فکت عددی جایگزین ساخته نشد.
2. **پرچم‌های ناموجود در snapshot (شکاف #۲ داسیه):** `end_organ_symptom`، `frail_or_orthostatic`، `resistant_htn_*`، `rasi_started_or_titrated_within_4w`، `potassium_gt_5_5` — قواعد وابسته با change_note ⚠️ علامت خورده‌اند و نباید قبل از تأمین پرچم‌ها فعال شوند (DRAFT خودش مانع است).
3. **واحد UACR (شکاف #۴):** mg/g در برابر mg/mmol باید نرمال‌سازی شود — در local_adaptation_note ثبت شد.
4. **نسخهٔ A2 قاعدهٔ R22** (uacr between [30,299] + دیابت) در متن داسیه ذکر شده ولی قاعدهٔ جداگانه ساخته نشد تا عدد/قاعدهٔ جدید اختراع نشود.
5. **HTN ثانویه (شکاف #۶):** غربالگری آلدوسترون/رنین/OSA فقط به‌صورت آرایهٔ workup داخل params قاعدهٔ ارجاع (R20) حفظ شده.
6. **بارداری (شکاف #۷):** fail-closed جداگانه (`flag.pregnant` → هیچ suggest_med) خارج از دامنهٔ این تبدیل است — باید در لایهٔ policy/governance پیاده شود.
7. **FLOW (NEJM 2024) (شکاف #۱):** فقط با هشدار «عدد دقیق تأییدنشده» ذکر شده؛ استناد اصلی FIDELIO-DKD (PMID 33264825) است.
8. **استاتین (شکاف #۱۰):** کلاس statin در enum نیست → R24 عمداً educate است نه suggest_med.
9. **ABPM/HBPM به‌عنوان داده (شکاف #۹):** آستانه‌های out-of-office به کلیدهای جداگانه نیاز دارند — فقط پروتکل HBPM در params آموزشی R30 حفظ شده.

## ۵) موارد نیازمند تصمیم/تأیید مالک

- **HTN-R28 — تریگر ظاهراً وارونه:** داسیه شرط `uacr_done_within_days < 365` (یعنی «UACR اخیراً انجام شده») را برای زمان‌بندی UACR سالانه گذاشته؛ منطقاً انتظار می‌رود NOT-done باشد. **عیناً حفظ شد** و در change_note برای بازبینی پزشک علامت خورد — هیچ اصلاح منطقی انجام نشد.
- **شرایط منفی دارویی fail-closed:** `not_has` ها REQUIRED/NEEDS_DATA گرفتند تا در نبود دادهٔ دارو، پیشنهاد شروع دارو داده نشود (R11/R13/R14/R16A/B/R18/R21/R22/R23). شرایط مثبت AND مطابق RED FLAGS (SF-BP-03) با REQUIRED/NOT_APPLICABLE.
- **max_age_days عمداً خالی** (داسیه مقدار نداده؛ عدد جدید اختراع نمی‌شود).
- **review_due_date** پیش‌فرض ۹۰ روزه (2026-11-21).
- **source_urlها:** فقط DOI/PMID داخل ارجاع داسیه یا صفحهٔ فرود ژورنال؛ موارد بدون DOI/PMID با local_adaptation_note علامت خورده‌اند (ACC/AHA، ESH، KDIGO 2021، HYVET، Neter، Circulation 2019، R25).
- **evidence_certainty/recommendation_strength = NOT_GRADED** برای همه (اطلاعات Class/LOE داخل source_locator حفظ شده).

## ۶) نتیجهٔ اعتبارسنجی jsonschema

```text
METHOD   = jsonschema.Draft202012Validator + FormatChecker
SCHEMA   = src/domain/clinical_engine/schemas/clinical-rule.schema.json
SCOPE    = هر عضو rules[] به‌عنوان RuleDefinition مستقل
$ref     = فقط ارجاع داخلی (#/$defs/expression) — نیازی به registry بیرونی نبود
RESULT   = ALL_VALID — 45/45 قاعده VALID (بدون خطا)
CHECKS   = 169 node_id یکتا · بدون rule_code تکراری · dossier_triggers 45/45
```

نتیجه همچنین داخل خود JSON در کلید `validation` ثبت شده است (validated_at = 2026-08-23T18:45:39+03:30).

## ۷) گام بعدی (خارج از محدودهٔ این تسک)

1. بازبینی بالینی مستقل هر ۴۵ قاعده — به‌ویژه: تریگر وارونهٔ R28، شرایط منفی fail-closed، پرچم‌های ناموجود (بخش ۴).
2. تأمین پرچم‌های شکاف #۲ و فکت‌های دوز/timestamp شکاف #۳ در fact snapshot قبل از هرگونه فعال‌سازی.
3. اعتبارسنجی `package_contract` + گزارش v2 روی cohort ده‌تایی TEST0001–TEST0010.
4. کلیک فعال‌سازی مالک طبق rollout مرحله‌ای.
