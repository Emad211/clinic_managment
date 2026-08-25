# یادداشت‌های تألیف — بستهٔ پیش‌نویس قواعد پرچم قرمز (`redflags-cross-v1` v0.1.0-draft)

```text
PACKAGE      = RULE_PACKAGE_RED_FLAGS_DRAFT_v0.1.json
SOURCE       = ACUTE_THRESHOLDS_DOSSIER_FA v1.0.0 (2026-08-23)
SCHEMA REF   = src/domain/clinical_engine/schemas/clinical-rule.schema.json (v2.0)
STATUS       = DRAFT — clinical_use = NOT_APPROVED_HISTORICAL_REGRESSION_ONLY
GENERATED    = 2026-08-23
```

> **هشدار حاکمیتی:** این بسته فقط یک پیش‌نویس داده‌ای است. به runtime، کامپایلر یا هیچ مسیر اجرایی **متصل نیست**.
> فعال‌سازی مستلزم (۱) اعتبارسنجی `package_contract`، (۲) بازبینی بالینی مستقل و (۳) **کلیک مالک** طبق تصمیم rollout مرحله‌ای (پرچم‌های قرمز = موج اول) است.

---

## ۱) جدول نگاشت داسیه → بسته

| داسیه | کد در بسته | فاز | اکشن اصلی | Severity | Priority (داسیه ×100) | due |
|---|---|---|---|---|---|---|
| §۱ RF-GLY-01 | RF-GLY-01 | PREFLIGHT | classify | CRITICAL | 9500 | — |
| §۱ RF-GLY-02 | RF-GLY-02 | PREFLIGHT | create_followup | URGENT | 8500 | 48h |
| §۱ RF-GLY-03 | RF-GLY-03 | PREFLIGHT | create_followup (+educate) | URGENT | 8800 | 24h |
| §۱ SF-GLY-04 | SF-GLY-04 | SAFETY | create_followup | URGENT | 7500 | 7d |
| §۱ SF-GLY-05 | SF-GLY-05 | SAFETY | create_followup | CRITICAL | 9000 | 24h + requires_acknowledgement=true |
| §۱ SF-GLY-06 | SF-GLY-06 | SAFETY | create_followup | WARN | 5500 | 14d |
| §۲ RF-BP-01 | RF-BP-01 | PREFLIGHT | classify (+create_followup هم‌روز) | CRITICAL | 9200 | 0h |
| §۲ RF-BP-02 | RF-BP-02 | PREFLIGHT | classify (+educate) | CRITICAL | 9600 | — |
| §۲ SF-BP-03 | SF-BP-03 | SAFETY | create_followup | WARN | 5000 | 30d |
| §۳ RF-REN-01 | RF-REN-01 | PREFLIGHT | create_followup (+classify) | URGENT | 8000 | 7d |
| §۳ SF-REN-02 | SF-REN-02 | SAFETY | create_followup | URGENT | 7800 | 14d — **SILENT** |
| §۳ SF-REN-03 | SF-REN-03 | SAFETY | create_followup | WARN | 6000 | 30d |
| §۴ SF-CM-01 | SF-CM-01 | SAFETY | create_followup (+educate) | WARN | 5200 | 14d — **SILENT** |
| §۴ SF-CM-02 | SF-CM-02 | SAFETY | create_followup | WARN | 5800 | 7d، عنوان: معاینهٔ پالس/ECG |
| §۵ SF-LAB-01 | SF-LAB-01 | SAFETY | create_followup | URGENT | 8200 | 72h؛ شرطی K+≥6→24h در params |
| §۵ SF-LAB-02 | SF-LAB-02 | SAFETY | create_followup (+educate) | WARN | 5600 | 14d |

جمع: **۱۶ قاعده** — ۶ redflag (PREFLIGHT) + ۱۰ safety (SAFETY). ترتیب آرایهٔ `rules[]` همان ترتیب بخش‌های داسیه است؛ رتبه‌بندی اجرایی با `priority` انجام می‌شود (جدول §۶ داسیه).

## ۲) تطبیق‌های ساختاری (Operator/DSL)

**عملگرها:** همهٔ عملگرهای داسیه (`has, in, between, >=, <=, >, <, ==`) زیرمجموعهٔ `SUPPORTED_OPERATORS` در `compiler_support.py` هستند — **هیچ جایگزینی عملگر لازم نشد.**

تطبیق‌های صرفاً ساختاری برای انطباق با اسکیمای v2 (طبق پیوست §۸ خود داسیه):

1. **`var` → `fact`:** `indicator.X.latest` → `lab.X` / `observation.X` با `selector.aggregation="latest"`؛ `med.class` → `medication.<class_key>`؛ `condition` → `condition.<code>`؛ `flag.<key>` → fact کاتالوگ فلگ.
2. **`node_id`:** اسکیما روی هر گرهٔ expression الزامی است؛ شناسه‌های قطعی `<CODE>-e*/c*` تولید شد.
3. **`op=has` روی condition:** به `op=truthy` روی `condition.<code>` تبدیل شد (معناشناسی برابر؛ truthy در SUPPORTED_OPERATORS).
4. **`med.class in [...]`:** به any-of از برگ‌های `medication.<class>` با `truthy` بسط یافت (SF-BP-03، SF-LAB-01، RF-GLY-03).
5. **Priority ×100:** طبق §۸ داسیه تا در بازهٔ 0–10000 اسکیما بگنجد.
6. **تریگرهای خام:** چون اسکیما `additionalProperties:false` دارد، تریگر عینیِ هر قاعده عیناً در کلید ریشهٔ `dossier_triggers` بسته حفظ شده است.

## ۳) موارد بیان‌ناپذیر در DSL 2.0 — قواعد SILENT

دو قاعده به aggregation نوع delta نیاز دارند که در DSL 2.0 وجود ندارد (enum مجاز: single/latest/all/count/within_days/count_within_days/recently_completed):

| قاعده | تریگر واقعی داسیه | وضعیت در بسته |
|---|---|---|
| SF-REN-02 | `indicator.egfr.delta_pct_12m <= -25` | `governance.status=SILENT` + condition جانشین `exists` + هشدار صریح در change_note |
| SF-CM-01 | `indicator.weight.delta_pct_180d <= -5` | همان الگو |

**SILENT هرگز اجرا نمی‌شود.** این دو قاعده تا افزودن پشتیبانی delta به evaluator v2 نباید از SILENT خارج شوند. برای این دو قاعده هیچ آستانهٔ عددی جایگزین اختراع نشده است.

## ۴) اقلام بخش «صداقت» (§۷ داسیه) که عمداً تبدیل نشدند

این موارد علائم وابسته به symptom دارند و دادهٔ ساختاریافته در اپ ندارند؛ ساخت قاعدهٔ ماشینی برای آنها تولید هشدار کاذب است:

- درد قفسهٔ سینه / نقص نورولوژیک / کاهش بینایی / کولیک کلیوی (تشخیص emergency vs urgency در BP بالا) → پوشش فقط از طریق متن educate در RF-BP-01/02؛ پیشنهاد فلگ آیندهٔ `acute_symptom_reported`.
- علائم کاتابولیک (پُرنوشی، پُرادراری، کاهش وزن ناخواسته) برای DKA/HHS → متن پیام RF-GLY-01/02؛ فلگ آیندهٔ `weight_loss_unintentional`.
- تهوع/استفراغ/درد شکم/تنفس کوسینال (DKA یوگلایسمیک) → متن آموزشی RF-GLY-03.
- ضربان نامنظم (غربالگری AF) → SF-CM-02 فقط «کار معاینهٔ پالس + ECG» می‌سازد؛ تشخیص با پزشک.
- هیپوگلیسمی سطح ۳ (اختلال هوشیاری) → ثبت دستی PATIENT_REPORTED؛ فلگ آیندهٔ `severe_hypo_history`.
- پایبندی دارویی (پیش‌نیاز تعریف دقیق HTN مقاوم) → SF-BP-03 نسخهٔ تقریبی است؛ یادداشت «تأیید پایبندی» در متن کار.
- تأیید پایداری افت eGFR (دو آزمایش فاصله‌دار) → SF-REN-02 منتظر aggregation `within_days`/delta.

قاعدهٔ طلایی داسیه رعایت شده: هرجا فاصلهٔ «داده ← تشخیص» هست، سیستم فقط `create_followup`/`educate` می‌سازد و تصمیم به پزشک برمی‌گردد.

## ۵) تصمیم‌های تألیفی که نیاز به تأیید مالک دارند

- `max_age_days` در required_facts عمداً خالی ماند (داسیه مقدار نداده؛ عدد جدید اختراع نمی‌شود).
- `task_contract` کامل فقط برای SF-GLY-05 (به‌دلیل requires_acknowledgement در داسیه)؛ سایر مقادیر آن (allowed_outcome_types و غیره) پیش‌فرض عملیاتی پیشنهادی‌اند.
- `review_due_date` پیش‌فرض ۹۰ روزه (2026-11-21).
- `source_url`ها فقط از DOI/PMID داخل ارجاع داسیه یا صفحهٔ فرود ژورنال ساخته شده‌اند؛ URL دقیق FDA در RF-GLY-03 باید در بازبینی تکمیل شود (در local_adaptation_note ثبت شده).
- `evidence_certainty`/`recommendation_strength` = NOT_GRADED برای همه (اطلاعات Class/LOE ESC داخل source_locator حفظ شده).
- مسیر شرطی K+≥6→24h در SF-LAB-01 به‌صورت متن در params حفظ شد، نه قاعدهٔ جداگانه، تا عدد جدید ساخته نشود.
- مرجع سبک: `git show da2956d~1:.../clinical_rules_seed.py` در هر دو ریویژن (~1 و ~2) stub بازنشستهٔ v1 است و واژگان میدانی قدیمی ارائه نمی‌دهد؛ واژگان این بسته مستقیماً از اسکیمای v2 و ثابت‌های compiler_support.py گرفته شده است.

## ۶) نتیجهٔ اعتبارسنجی jsonschema

```text
METHOD   = jsonschema.Draft202012Validator + FormatChecker
SCHEMA   = src/domain/clinical_engine/schemas/clinical-rule.schema.json
SCOPE    = هر عضو rules[] به‌عنوان RuleDefinition مستقل
$ref     = فقط ارجاع داخلی (#/$defs/expression) — نیازی به registry بیرونی نبود
RESULT   = ALL_VALID — 16/16 قاعده VALID (بدون خطا)
```

خروجی دقیق اجرا (2026-08-23): RF-GLY-01…SF-LAB-02 همگی `VALID`. نتیجه همچنین داخل خود JSON در کلید `validation` ثبت شده است.

## ۷) گام بعدی (خارج از محدودهٔ این تسک)

1. بازبینی بالینی مستقل هر ۱۶ قاعده (به‌ویژه دو قاعدهٔ SILENT و task_contract پیشنهادی SF-GLY-05).
2. اعتبارسنجی `package_contract` + گزارش v2 روی cohort ده‌تایی TEST0001–TEST0010.
3. کلیک فعال‌سازی مالک طبق rollout مرحله‌ای — پرچم‌های قرمز موج اول.
