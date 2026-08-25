# یادداشت‌های تألیف — بستهٔ پیش‌نویس قواعد دوز/تیتراسیون T2D (`t2d-dosing-v1` v0.1.0-draft)

```text
PACKAGE      = RULE_PACKAGE_T2D_DOSING_DRAFT_v0.1.json
SOURCE       = DOSING_REFRESH_VS_FROZEN_DOC_FA (راستی‌آزمایی ada_t2_rules.md v0.9.4، 2026-08-23)
SCHEMA REF   = src/domain/clinical_engine/schemas/clinical-rule.schema.json (v2.0)
STATUS       = DRAFT — clinical_use = NOT_APPROVED_HISTORICAL_REGRESSION_ONLY
GENERATED    = 2026-08-23
```

> **هشدار حاکمیتی:** این بسته فقط پیش‌نویس داده‌ای است و به runtime/compiler **متصل نیست**.
> فعال‌سازی مستلزم (۱) اعتبارسنجی `package_contract`، (۲) بازبینی بالینی مستقل و (۳) کلیک مالک طبق rollout مرحله‌ای است.

---

## ۱) شمارش قواعد به تفکیک کلاس (۳۵ قاعده)

| کلاس | IDs | تعداد |
|---|---|---|
| متفورمین | T2-DOS-MET-01..04 | ۴ |
| SGLT2i | T2-DOS-SGLT2-01..05 | ۵ |
| GLP-1/dual | T2-DOS-GLP1-01..07 | ۷ |
| DPP-4i | T2-DOS-DPP4-01..03 | ۳ |
| TZD | T2-DOS-TZD-01..02 | ۲ |
| SU | T2-DOS-SU-01..03 | ۳ |
| انسولین basal | T2-INS-BASAL-01..05 | ۵ |
| انسولین prandial | T2-INS-PRANDIAL-01..02 | ۲ |
| Correction/ISF | T2-INS-CORR-01 | ۱ |
| هیپوگلیسمی درمان | T2-HYPO-TX-01..02 | ۲ |
| روز بیماری | T2-SICKDAY-01 | ۱ |

فازها: **۳۱ ROUTINE + ۴ SAFETY** (CORR-01، HYPO-TX-01/02، SICKDAY-01 طبق دستور کار).
اکشن‌ها: 32 suggest_med + 2 safety_alert + 1 flag_risk (BASAL-05/SILENT).
وضعیت: 34 DRAFT + **1 SILENT** (T2-INS-BASAL-05).

## ۲) اعداد DELTA حمل‌شده (از ستون CURRENT با citation همان سطر)

1. **DELTA-1 — Empagliflozin max = 25 mg** با گیت tolerance؛ گیت گلایسمی eGFR≥30 در شرط ماشینی (Jardiance PI rev 10/2025 §2.2). فرض «10 mg» منقضی.
2. **DELTA-2 — Semaglutide خوراکی شروع 3 mg** (نه 0.25)؛ مسیر 3→7→14؛ R2 (1.5/4/9) علامت‌گذاری out-of-scope (Rybelsus PI §2.2).
3. **DELTA-3 — Sitagliptin eGFR 30–<45 → 50 mg**؛ 25 فقط <30/HD (Januvia PI §2.2).
4. **DELTA-4 — ISF استاندارد 1800/TDD (آنالوگ سریع) و 1500/TDD (regular)**؛ «1700» غیراستاندارد؛ کل قاعده NON-GUIDELINE خارج از ADA با تأیید پزشک (§۲.۴ داسیه).

همچنین NOTEهای داسیه حفظ شد: canagliflozin سقف 100 در 30–<60 (200 فقط UGT-inducer)، heuristic بودن آستانهٔ overbasalization، سقف رسمی Trulicity 4.5 mg.

## ۳) شکاف‌های DSL/داده (غیربیان‌پذیرها)

1. **زمان‌بندی فواصل تیتراسیون** (+500 هفتگی، q3d، q4w، ×30d): aggregation زمانی برای schedule در DSL 2.0 نیست؛ همهٔ فواصل verbatim در متن/params.
2. **محاسبهٔ دوز وزن‌محور در runtime** (0.1–0.2 U/kg/day، >0.5 U/kg/day، 10% دوز basal): fact وزن/دوز ساختاریافته وجود ندارد → T2-INS-BASAL-05 با الگوی SILENTِ SF-REN-02 بستهٔ redflags وارد شد (condition جانشین exists + هشدار change_note؛ هرگز اجرا نمی‌شود).
3. **ISF وابسته به TDD**: TDD fact نیست؛ فرمول فقط متن estimate با تأیید پزشک (T2-INS-CORR-01).
4. **ALT >2.5×ULN** (TZD-02): lab.alt در فهرست facts این موج نیست → کارت یادآور با gap صریح.
5. **مهارکنندهٔ قوی CYP3A4/5** (DPP4-02 saxa): fact تداخل دارویی نیست → متن.
6. **NYHA class** (TZD-01): flag HF در فهرست facts این موج نیست → متن.
7. **تفکیک agent درون کلاس** (glyburide در SU؛ lixi/exenatide در GLP-1؛ empa/dapa/cana در SGLT2i؛ sema SC vs PO): fact سطح کلاس است؛ نام agent در عنوان/متن/params و بازبینی دستی لیست دارو لازم است.
8. **«هیپوی بدون علت مشخص»** (BASAL-04): علت‌یابی بیان‌پذیر نیست؛ تریگر fbs<70 (آستانهٔ L1) + متن.
9. **علائم sick-day / DKA یوگلایسمیک** (تهوع/استفراغ + کتون): symptom fact نیست → متن آموزشی (الگوی §۴ notes بستهٔ redflags).
10. **initiation واقعی انسولین/متفورمین**: fact «insulin-naïve/dose-in-flight» نیست؛ همهٔ کارت‌ها در زمینهٔ تحت‌درمان fire می‌کنند.

## ۴) تصمیم‌های تألیفی نیازمند تأیید مالک

- **PRIORITY (3000–9400)**: داسیه ستون priority نداشت؛ تخصیص دستی (SAFETY > گیت‌های کلیوی > کارت‌های مرجع).
- **آستانهٔ eGFR<60 برای SU-03 (glyburide)**: داسیه عدد CKD نداده؛ <60 (مرز G3a) authored operationalization است.
- **تریگر egfr<60 برای سه قاعدهٔ DPP4**: باندهای sita/saxa/alo از <60 به پایین relevance دارند؛ ≥60 دوز نرمال است (در متن ذکر شده).
- **may_create_internal_task=true فقط MET-04** (داسیه صراحتاً «+B12 monitoring followup» داده)؛ due_in_* عمداً خالی چون داسیه عدد نداده.
- **source_urlها**: ADA → صفحهٔ فرود Diabetes Care 49(Suppl.1)؛ FDA PIها → نمایهٔ Drugs@FDA/DailyMed با local_adaptation_note (در داسیه DOI/PMID نبود). CORR-01 عمداً به صفحهٔ ADA اشاره می‌کند تا «نبودِ ISF در ADA» مستند بماند.
- requires_clinician_confirmation=true برای هر ۳۵ قاعده؛ NOT_GRADED/NOT_REVIEWED برای همه؛ review_due_date=2026-11-21.

## ۵) نتیجهٔ اعتبارسنجی jsonschema

```text
METHOD   = jsonschema.Draft202012Validator + FormatChecker
SCHEMA   = src/domain/clinical_engine/schemas/clinical-rule.schema.json
SCOPE    = هر عضو rules[] به‌عنوان RuleDefinition مستقل
$ref     = فقط ارجاع داخلی (#/$defs/expression)
RESULT   = ALL_VALID — 35/35 قاعده VALID (۰ خطا) — دو گذر (قبل و بعد از patch بلوک validation)
```

نتیجه همچنین داخل خود JSON در کلید `validation` ثبت شده است (validated_at به وقت تهران).

## ۶) گام بعدی (خارج از محدودهٔ این تسک)

1. بازبینی بالینی مستقل هر ۳۵ قاعده (به‌ویژه SILENT بودن BASAL-05، NON-GUIDELINE بودن CORR-01 و آستانهٔ تألیفی SU-03).
2. اعتبارسنجی `package_contract` + گزارش v2 روی cohort ده‌تایی TEST0001–TEST0010.
3. تصمیم مالک دربارهٔ افزودن facts آینده: lab.alt، weight، structured dose، insulin-naïve، symptom flags.
