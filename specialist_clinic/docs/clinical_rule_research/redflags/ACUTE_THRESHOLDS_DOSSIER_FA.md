# پروندهٔ پژوهشی — پرچم‌های قرمز حاد و آستانه‌های ایمنی (Cross-Domain Red Flags)

```text
DOC_ID        = ACUTE_THRESHOLDS_DOSSIER_FA
VERSION       = 1.0.0
DATE          = 2026-08-23
SCOPE         = دیابت / فشار خون / چربی خون / کلیه — فقط با داده‌های موجود در اپ
DOWNSTREAM    = تبدیل مستقیم به قاعدهٔ موتور بالینی (trigger JSON → RuleDefinition)
DSL_REF       = docs/treatment_engine_plan.md §۳ + src/domain/clinical_engine/schemas/clinical-rule.schema.json
STATUS        = DRAFT_FOR_CLINICAL_REVIEW (هیچ قاعده‌ای بدون بازبینی پزشک فعال نمی‌شود)
```

---

## ۰) قرارداد تریگر — فقط متغیرهای واقعاً موجود

هر تریگر با همان DSL پروژه نوشته شده است (`{"all":[...]}` / `{"any":[...]}`):

| نوع var | مقادیر موجود در اپ | منبع داده |
|---|---|---|
| `condition` | `diabetes`, `hypertension`, `hyperlipidemia`, `ckd` | `patient_conditions` |
| `indicator.<key>.latest` | `bp_systolic`, `bp_diastolic`, `fbs`, `bs_2hpp`, `hba1c`, `pulse`, `weight`, `bmi`, `egfr`, `uacr`, `potassium`, `triglyceride`, `creatinine` | `vital_readings` + `lab_results` |
| `flag.<key>` | `hypo_risk(low/atrisk/high)`, `ckd_stage_g(G1..G5)`, `ckd_stage_a(A1..A3)`, `hf`, `hf_symptomatic`, `ascvd`, `cvd_high_risk`, `frailty`, `pregnancy`, `smoking`, `masld` | `flag_catalog` |
| `med.class` | `metformin, sglt2i, glp1_ra, su, insulin_basal, insulin_bolus, acei, arb, ccb, thiazide, mra, finerenone, fibrate, loop_diuretic, ...` | `drug_classes` |
| `age` | عدد سال | `patients.birth_date` |

عملگرها: `>=, <=, >, <, ==, between, in, has, not_has, exists`.
فازها: `redflag` (ارائهٔ وقفه‌ای، توجه فوری پزشک) / `safety` (هشدار ایمنی در جریان کار) / `routine`.
اکشن‌های مجاز: `classify` / `create_followup` / `educate`. **هیچ قاعده‌ای دارو قطع یا شروع نمی‌کند؛ همه پیشنهاد + تأیید پزشک.**

> **قاعدهٔ طراحی پرچم قرمز:** تریگر باید تک‌متغیره یا AND ساده باشد تا ابهام‌زدایی شود. هرجا علامت بالینی لازم است ولی ثبت ساختاریافته نداریم، نسخهٔ flag-based یا `create_followup` دستی پیشنهاد شده (بخش ۷).

---

## ۱) گلیسمی

### RF-GLY-01 — FBS ≥ 400 (بحران هیپرگلیسمیک محتمل)
- **منطق:** قند ≥400 همراه زمینهٔ دیابت = احتمال DKA/HHS؛ نیاز به ارزیابی هم‌روز (کتون، الکترولیت، وضعیت ذهنی).
- **Trigger:**
```json
{"all": [
  {"var": "condition", "op": "has", "value": "diabetes"},
  {"var": "indicator.fbs.latest", "op": ">=", "value": 400}
]}
```
- **Action:** `classify` (redflag) — **Severity: CRITICAL** — Priority **95**
- **message_fa:** «قند خون بسیار بالا (≥۴۰۰). بررسی فوری کتواسیدوز/سندرم هیپراسمولار امروز: آزمایش کتون ادرار/خون، الکترولیت و گاز خون. اگر تهوع، استفراغ، درد شکم، تنفس عمیق یا کاهش هوشیاری دارد، همین حالا اورژانس.»
- **Citation:** ADA Standards of Care 2025, §9 Pharmacologic Approaches to Glycemic Treatment (Diabetes Care 2025;48(Suppl.1):S181), Fig 9.4 — glucose ≥300 mg/dL/A1C >10% به‌عنوان آستانهٔ «خیلی بالا»؛ آستانهٔ HHS ≥600 در ADA Hyperglycemic Crises Consensus Report (Diabetes Care 2024;47(10):1637–1654).

### RF-GLY-02 — FBS 300–399 (شدید/نیازمند تشدید)
- **منطق:** شدیداً خارج هدف؛ مسیر تشدید درمان + تکرار آزمایش در ۲۴–۷۲ ساعت.
- **Trigger:**
```json
{"all": [
  {"var": "condition", "op": "has", "value": "diabetes"},
  {"var": "indicator.fbs.latest", "op": "between", "value": [300, 399]}
]}
```
- **Action:** `create_followup` (due_in_hours=48) — **Severity: URGENT** — Priority **85**
- **message_fa:** «قند ناشتا ≥۳۰۰ ثبت شده است. تکرار آزمایش و مرور رژیم/دارو ظرف ۴۸ ساعت لازم است؛ در صورت بروز علائم تخریب کاتابولیک (کاهش وزن ناخواسته، پُرنوشی/پُرادراری شدید) تماس فوری.»
- **Citation:** ADA SOC 2025 §9 (S181) — BG ≥300 mg/dL به‌عنوان آستانهٔ ورود انسولین/تشدید.

### RF-GLY-03 — SGLT2i + هیپرگلیسمی نسبی (خطر DKA یوگلایسمیک)
- **منطق:** روی SGLT2i کتواسیدوز می‌تواند با قند <200 رخ دهد؛ آستانهٔ هشدار پایین‌تر می‌آید.
- **Trigger:**
```json
{"all": [
  {"var": "condition", "op": "has", "value": "diabetes"},
  {"var": "med.class", "op": "in", "value": ["sglt2i"]},
  {"var": "indicator.fbs.latest", "op": ">=", "value": 250}
]}
```
- **Action:** `create_followup` (due_in_hours=24) + متن آموزشی — **Severity: URGENT** — Priority **88**
- **message_fa:** «بیمار روی مهارکنندهٔ SGLT2 است. حتی با قند نسبتاً پایین‌تر، خطر کتواسیدوز یوگلایسمیک وجود دارد؛ در صورت تهوع/استفراغ/درد شکم/بی‌حالی، اندازه‌گیری کتون و مراجعهٔ فوری. بررسی موقت قطع دارو با پزشک.»
- **Citation:** FDA Drug Safety Communication 2015 (به‌روزرسانی دسامبر ۲۰۱۵) — SGLT2i و کتواسیدوز با قند <250؛ ADA SOC 2025 §9 (بحث ایمنی SGLT2i).

### SF-GLY-04 — A1c ≥ 10٪ (فوریت تشدید درمان)
- **Trigger:**
```json
{"all": [
  {"var": "condition", "op": "has", "value": "diabetes"},
  {"var": "indicator.hba1c.latest", "op": ">=", "value": 10}
]}
```
- **Action:** `create_followup` (due_in_days=7) — **Severity: URGENT** — Priority **75**
- **message_fa:** «هموگلوبین A1c بالای ۱۰٪ است. جلسهٔ تشدید درمان (احتمال شروع/تشدید انسولین) ظرف یک هفته برنامه‌ریزی شود.»
- **Citation:** ADA SOC 2025 §9 (S181), Fig 9.4 — A1C >10% یا BG ≥300 → در نظر گرفتن انسولین زودهنگام.

### SF-GLY-05 — هیپوگلیسمی سطح ۲ (<54) هر قرائت
- **منطق:** هر مقدار <54 = Level 2؛ الزام بازنگری دارو (انسولین/SU).
- **Trigger:**
```json
{"all": [
  {"var": "condition", "op": "has", "value": "diabetes"},
  {"any": [
    {"var": "indicator.fbs.latest", "op": "<", "value": 54},
    {"var": "indicator.bs_2hpp.latest", "op": "<", "value": 54}
  ]}
]}
```
- **Action:** `create_followup` (due_in_hours=24, task_contract.requires_acknowledgement=true) — **Severity: CRITICAL** — Priority **90**
- **message_fa:** «قرائت قند زیر ۵۴ ثبت شده (هیپوگلیسمی سطح ۲). بازنگری فوری رژیم دارویی — به‌ویژه انسولین/سولفونیل‌اوره — و آموزش مدیریت هیپو لازم است.»
- **Citation:** ADA SOC 2025, §6 Glycemic Goals and Hypoglycemia (Diabetes Care 2025;48(Suppl.1):S128) — تعریف Level 2: <54 mg/dL؛ توصیهٔ بازنگری طرح درمان پس از L2/L3.

### SF-GLY-06 — هیپوگلیسمی سطح ۱ مکرر (54–69) با ریسک بالا
- **Trigger:**
```json
{"all": [
  {"var": "condition", "op": "has", "value": "diabetes"},
  {"var": "indicator.fbs.latest", "op": "between", "value": [54, 69]},
  {"var": "flag.hypo_risk", "op": "in", "value": ["atrisk", "high"]}
]}
```
- **Action:** `create_followup` (due_in_days=14) — **Severity: WARN** — Priority **55**
- **message_fa:** «قند در محدودهٔ ۵۴–۶۹ با سابقهٔ ریسک هیپوگلیسمی. بررسی الگوی قرائت‌ها و امکان deintensification در ویزیت بعدی.»
- **Citation:** ADA SOC 2025 §6 (S128) — Level 1: <70 و ≥54؛ توصیهٔ پایش در افراد پرخطر.

---

## ۲) فشار خون

### RF-BP-01 — BP ≥180/110 بدون علامت ثبت‌شده (مسیر مدیریتی هم‌روز)
- **Trigger:**
```json
{"all": [
  {"var": "condition", "op": "has", "value": "hypertension"},
  {"any": [
    {"var": "indicator.bp_systolic.latest", "op": ">=", "value": 180},
    {"var": "indicator.bp_diastolic.latest", "op": ">=", "value": 110}
  ]}
]}
```
- **Action:** `classify` (redflag) + `create_followup` (due_in_hours=0/هم‌روز) — **Severity: CRITICAL** — Priority **92**
- **message_fa:** «فشار ≥۱۸۰ سیستول یا ≥۱۱۰ دیاستول ثبت شده. اندازه‌گیری مجدد پس از ۵ دقیقه استراحت، ارزیابی هم‌روزِ آسیب حاد اندام هدف و تنظیم فوری درمان لازم است. اگر درد قفسهٔ سینه، ضعف اندام، اختلال تکلم/بینایی یا درد شدید پهلو دارید، اورژانس.»
- **Citation:** ESC 2024 Guidelines for the management of elevated blood pressure and hypertension (Eur Heart J 2024;45(38):3912–4018, doi:10.1093/eurheartj/ehae178), Diagnostic Confirmation Algorithm (Fig 10): Screening BP ≥180/110 → exclude hypertensive emergency؛ در نبود اورژانس، تأیید و شروع سریع درمان (Class 1, LOE C).

### RF-BP-02 — BP ≥180/110 + نشانگر ریسک قلبی-عروقی ثبت‌شده (نسخهٔ flag-based علائم)
- **منطق:** درد قفسهٔ سینه/نقص نورولوژیک/کاهش بینایی/کولیک کلیوی قابل تشخیص ماشینی نیست؛ تنها proxy ثبت‌شدهٔ فعلی `hf_symptomatic`/`ascvd`/`cvd_high_risk` است. این قاعده پیام را به «ارجاع اورژانسی» ارتقا می‌دهد و educate می‌کند.
- **Trigger:**
```json
{"all": [
  {"any": [
    {"var": "indicator.bp_systolic.latest", "op": ">=", "value": 180},
    {"var": "indicator.bp_diastolic.latest", "op": ">=", "value": 110}
  ]},
  {"any": [
    {"var": "flag.hf_symptomatic", "op": "==", "value": "1"},
    {"var": "flag.ascvd", "op": "==", "value": "1"},
    {"var": "flag.cvd_high_risk", "op": "==", "value": "1"}
  ]}
]}
```
- **Action:** `educate` + `classify` (redflag) — **Severity: CRITICAL** — Priority **96**
- **message_fa:** «فشار خیلی بالا در بیمار با بیماری قلبی/عروقی شناخته‌شده. احتمال فوریت فشار خون بالاست. اگر درد قفسهٔ سینه، تنگی نفس، ضعف/بی‌حسی، اختلال بینایی یا هوشیاری دارید بی‌درنگ اورژانس. ارزیابی پزشکی امروز الزامی است.»
- **Citation:** ESC 2024 (ehae178), بخش Hypertensive emergencies — تعریف اورژانس = BP بالا + آسیب حاد اندام هدف (HMOD حاد)؛ تشخیص آن فقط بالینی است (بخش ۷).

### SF-BP-03 — فشار خون مقاوم (≥140/90 با ۳ دارو شامل دیورتیک)
- **منطق:** شمارش تعداد دارو در DSL فعلی نیست؛ معادل ماشین‌پذیر: حضور هم‌زمان thiazide + CCB + (ACEi یا ARB) با کنترل‌نشدن فشار.
- **Trigger:**
```json
{"all": [
  {"var": "condition", "op": "has", "value": "hypertension"},
  {"any": [
    {"var": "indicator.bp_systolic.latest", "op": ">=", "value": 140},
    {"var": "indicator.bp_diastolic.latest", "op": ">=", "value": 90}
  ]},
  {"var": "med.class", "op": "in", "value": ["thiazide"]},
  {"var": "med.class", "op": "in", "value": ["ccb"]},
  {"var": "med.class", "op": "in", "value": ["acei", "arb"]}
]}
```
- **Action:** `create_followup` (due_in_days=30) — **Severity: WARN** — Priority **50**
- **message_fa:** «فشار با ترکیب سه‌دارویی (شامل دیورتیک) کنترل نشده است — الگوی فشار خون مقاوم. بررسی پایبندی، ABPM، غربالگری علل ثانویه (آلدوسترون‌اولیه، آپنه خواب) و مسیر تخصصی/اسپیرونولاکتون با پزشک مطرح شود.»
- **Citation:** ESC 2024 (ehae178), Resistant Hypertension section — تعریف: office BP ≥140/90 با ≥3 دارو در حداکثر دوز قابل تحمل شامل دیورتیک با تأیید پایبندی؛ ACC/AHA 2017 Guideline (Hypertension 2018;71:e13–e115), §8 نیز همین تعریف را دارد.

---

## ۳) کلیوی

### RF-REN-01 — eGFR <30 (ارجاع نفرولوژی + بازنگری متفورمین)
- **Trigger:**
```json
{"all": [
  {"var": "indicator.egfr.latest", "op": "<", "value": 30}
]}
```
- **Action:** `create_followup` (due_in_days=7) + `classify` — **Severity: URGENT** — Priority **80**
- **message_fa:** «eGFR زیر ۳۰ است. ارجاع به نفرولوژی و بازنگری فوری داروها ضروری است: متفورمین در eGFR<30 منع مصرف دارد (قطع با تصمیم پزشک)؛ در ۳۰–۴۴ فقط با نصف دوز. دوز داروهای دیگر نیز بازبینی شود.»
- **Citation:** KDIGO 2024 CKD Guideline (Kidney Int 2024;105(4S):S117–S314, PMID 38490803), Chapter 5 Practice Point — refer most people with eGFR <30 to nephrology services؛ Chapter 3 Practice Points (متفورمین بر اساس FDA label): عدم شروع <45، نصف دوز 30–44، قطع <30؛ FDA Metformin label (contraindicated eGFR <30 mL/min/1.73m²).

### SF-REN-02 — افت eGFR >25٪ نسبت به baseline (مشروط به محاسبه‌پذیری delta)
- **منطق:** فقط اگر موتور `delta` روی egfr را محاسبه کند فعال شود؛ در غیر این صورت قاعده SILENT.
- **Trigger:**
```json
{"all": [
  {"var": "indicator.egfr.delta_pct_12m", "op": "<=", "value": -25}
]}
```
- **Action:** `create_followup` (due_in_days=14) — **Severity: URGENT** — Priority **78**
- **message_fa:** «افت بیش از ۲۵٪ در eGFR نسبت به مقدار پایه ثبت شده است. بررسی علت (داروهای نفروتوکسیک، دهیدراتاسیون، انسداد)، تکرار آزمایش و مشاورهٔ نفرولوژی توصیه می‌شود.»
- **Citation:** KDIGO 2024 (S117–S314), Chapter 1/2 — «sustained decline in GFR category» به‌عنوان معیار پیشرفت؛ تعریف کلاسیک پیشرفت سریع KDIGO: افت ≥25٪ از baseline.
- **⚠️ شرط فعال‌سازی:** نیازمند پشتیبانی aggregation `within_days/delta` در evaluator (schema v2 از selector `aggregation` پشتیبانی می‌کند).

### SF-REN-03 — UACR ≥300 (ماکروآلبومینوری/A3 — تشدید محافظت کلیوی)
- **Trigger:**
```json
{"all": [
  {"var": "indicator.uacr.latest", "op": ">=", "value": 300}
]}
```
- **Action:** `create_followup` (due_in_days=30) — **Severity: WARN** — Priority **60**
- **message_fa:** «آلبومین ادرار شدیداً بالا (A3). بهینه‌سازی مهارکنندهٔ RAS، بررسی کاندیداتوری SGLT2i/فینرنون، تکرار UACR برای تأیید پایداری و پایش پتاسیم لازم است.»
- **Citation:** KDIGO 2024 (S117–S314), Table 2 — A3: UACR >300 mg/g؛ Rec 3.7.x — شروع RASi در A2/A3؛ Rec 3.11.x — SGLT2i با eGFR≥20 و ACR≥200؛ nsMRA (فینرنون) با شرایط پتاسیم نرمال.

---

## ۴) قلبی-متابولیک

### SF-CM-01 — کاهش وزن ناخواسته >5٪ (پنجرهٔ ~۶ ماه)
- **منطق:** «ناخواسته» بودن را ماشین نمی‌فهمد؛ سیستم افت وزن را فلگ می‌کند و تأیید ناخواسته‌بودن + workup به کار دستی پزشک می‌رود.
- **Trigger:**
```json
{"all": [
  {"var": "indicator.weight.delta_pct_180d", "op": "<=", "value": -5}
]}
```
- **Action:** `create_followup` (due_in_days=14) + `educate` — **Severity: WARN** — Priority **52**
- **message_fa:** «کاهش وزن بیش از ۵٪ در بازهٔ اخیر ثبت شده است. اگر این کاهش عمدی (رژیم/ورزش) نبوده، ارزیابی پزشک برای علل ثانویه (بدخیمی، پرکاری تیروئید، افسردگی، سوءجذب) لازم است.»
- **Citation:** Endocrine Society Clinical Practice Guideline — Unintentional Weight Loss in Older Adults (J Clin Endocrinol Metab 2021;106(3), doi:10.1210/clinem/dgaa726) — تعریف: کاهش >5٪ وزن طی 6–12 ماه = clinically significant involuntary weight loss؛ ارزیابی برای بدخیمی/تیروئید/افسردگی.
- **⚠️ شرط فعال‌سازی:** نیازمند محاسبهٔ درصد تغییر وزن در پنجرهٔ زمانی (delta aggregation).

### SF-CM-02 — پالس خارج محدودهٔ امن + وظیفهٔ معاینهٔ دستی ریتم (غربالگری AF)
- **منطق:** اپ ECG ندارد؛ «ضربان نامنظم» قابل تشخیص نیست. این قاعده فقط مقادیر عددی غیرعادی را می‌گیرد و غربالگری AF را به‌صورت **کار معاینهٔ دستی** ایجاد می‌کند (ESC: لمس پالس برای کشف آریتمی Class 1C).
- **Trigger:**
```json
{"any": [
  {"var": "indicator.pulse.latest", "op": ">", "value": 120},
  {"var": "indicator.pulse.latest", "op": "<", "value": 50}
]}
```
- **Action:** `create_followup` (due_in_days=7, عنوان: معاینهٔ پالس/ECG) — **Severity: WARN** — Priority **58**
- **message_fa:** «ضربان قلب خارج محدودهٔ معمول (<۵۰ یا >۱۲۰) ثبت شده است. معاینهٔ پالس توسط پزشک و در صورت نامنظم بودن، نوار قلب (ECG) برای غربالگری فیبریلاسیون دهلیزی انجام شود.»
- **Citation:** ESC 2024 HTN (ehae178), BP Measurement section — «All patients should have pulse palpation at rest to detect arrhythmias such as AF» (Class 1, LOE C)؛ ESC 2024 AF guideline (Eur Heart J 2024;45(36):3314–3414) — تشخیص AF نیازمند ECG است.

---

## ۵) ایمنی آزمایشگاهی

### SF-LAB-01 — K⁺ ≥5.5 روی ACEi/ARB/MRA/فینرنون (مسیر hold/recheck)
- **منطق:** قطع خودکار ممنوع؛ سیستم مسیر «تکرار K+، مرور دوز، تصمیم پزشک» را می‌سازد. K+ ≥6.0 = فوری.
- **Trigger:**
```json
{"all": [
  {"var": "indicator.potassium.latest", "op": ">=", "value": 5.5},
  {"var": "med.class", "op": "in", "value": ["acei", "arb", "mra", "finerenone"]}
]}
```
- **Action:** `create_followup` (due_in_hours=72؛ اگر K+≥6.0 → due_in_hours=24) — **Severity: URGENT** — Priority **82**
- **message_fa:** «پتاسیم ≥۵٫۵ در بیمار روی داروی مؤثر بر RAS/مینرالوکورتیکوئید. تکرار پتاسیم (کنترل همولیز نمونه)، مرور دوز/تعلیق موقت دارو و پرهیز از NSAID فقط با تصمیم پزشک. در صورت K+≥6 یا تغییرات ECG، اقدام فوری.»
- **Citation:** KDIGO 2024 (S117–S314), Recommendation 3.7.2 (1B) — ادامهٔ RASi مگر K+ >5.5 mmol/L؛ FDA Kerendia (finerenone) Prescribing Information 2021 — قطع دائم در K+ >5.5 mEq/L؛ FIDELIO-DKD (NEJM 2020;383:2219–2229) — پروتکل پایش پتاسیم.

### SF-LAB-02 — تری‌گلیسرید ≥500 (ریسک پانکراتیت)
- **Trigger:**
```json
{"all": [
  {"var": "indicator.triglyceride.latest", "op": ">=", "value": 500}
]}
```
- **Action:** `create_followup` (due_in_days=14) + `educate` — **Severity: WARN** — Priority **56**
- **message_fa:** «تری‌گلیسرید ≥۵۰۰ ثبت شده است. کنترل شدید قند، قطع الکل، بررسی علل ثانویه و بحث دربارهٔ درمان دارویی (فیبرات) برای کاهش خطر پانکراتیت حاد با پزشک مطرح شود.»
- **Citation:** ADA SOC 2025, §10 Cardiovascular Disease and Risk Management (Diabetes Care 2025;48(Suppl.1)) — TG fasting ≥500 mg/dL → بررسی علل ثانویه و درمان دارویی برای کاهش خطر پانکراتیت؛ AHA Scientific Statement (Miller M et al., Circulation 2011;123:2292–2333) — آستانهٔ ≥500 برای شروع دارو جهت پیشگیری از پانکراتیت؛ Yang AL & McNabb-Baltar J, Pancreatology 2020;20:795–800 — HTG سومین علت شایع پانکراتیت حاد.

---

## ۶) جدول رتبه‌بندی اولویت (rationale)

| Rank | Code | Severity | Priority | منطق رتبه‌بندی |
|---|---|---|---|---|
| 1 | RF-BP-02 | CRITICAL | 96 | فشار بحرانی + بیماری CV شناخته‌شده = بالاترین احتمال فوریت واقعی |
| 2 | RF-GLY-01 | CRITICAL | 95 | قند ≥400 = خطر DKA/HHS با مرگ‌ومیر معنادار، پنجرهٔ زمانی ساعت‌ها |
| 3 | RF-BP-01 | CRITICAL | 92 | آستانهٔ severe HTN؛ خطر حادثهٔ قلبی-مغزی در روزهای آینده |
| 4 | SF-GLY-05 | CRITICAL | 90 | هیپو L2 = رویداد ایمنی فوری با خطر اختلال هوشیاری |
| 5 | RF-GLY-03 | URGENT | 88 | DKA یوگلایسمیک با ارائهٔ فریبنده (قند تقریباً نرمال) |
| 6 | RF-GLY-02 | URGENT | 85 | هیپرگلیسمی شدید؛ فوریت کمتر از ≥400 |
| 7 | SF-LAB-01 | URGENT | 82 | هایپرکالمی ≥5.5 روی RAASi/MRA = خطر آریتمی؛ مسیر ۷۲ ساعته |
| 8 | RF-REN-01 | URGENT | 80 | eGFR<30 = مرحلهٔ ارجاع + منع دارویی فعال |
| 9 | SF-REN-02 | URGENT | 78 | افت سریع eGFR = سیگنال آسیب فعال (مشروط به delta) |
| 10 | SF-GLY-04 | URGENT | 75 | A1c≥10 = فوریت تشدید اما نه بحران حاد |
| 11 | SF-REN-03 | WARN | 60 | A3 = تسریع محافظت کلیوی، افق هفته‌ها |
| 12 | SF-CM-02 | WARN | 58 | پالس غیرعادی → معاینهٔ دستی؛ AF خودش اورژانس نیست |
| 13 | SF-LAB-02 | WARN | 56 | TG≥500 = ریسک پانکراتیت، افق روزها-هفته‌ها |
| 14 | SF-GLY-06 | WARN | 55 | هیپو L1 مکرر = تنظیم مزمن درمان |
| 15 | SF-CM-01 | WARN | 52 | کاهش وزن ناخواسته = workup مهم اما غیرفوری |
| 16 | SF-BP-03 | WARN | 50 | HTN مقاوم = مسیر تخصصی، افق ماه |

**اصل رتبه‌بندی:** (۱) تهدید حیات در ساعت‌ها > (۲) خطر آسیب اندام در روزها > (۳) تصحیح مسیر درمان در هفته‌ها > (۴) بهینه‌سازی در ماه‌ها. داخل هر لایه، قطعیت تشخیصی تریگر (تک‌متغیره > چندشرطی) و برگشت‌پذیری عارضه وزن می‌گیرد.

---

## ۷) صداقت — چه پرچم‌هایی قابل اتوماسیون نیستند

این موارد **عمداً قاعده ندارند** چون دادهٔ ساختاریافته‌شان در اپ وجود ندارد. ساخت قاعدهٔ ماشینی برای آنها تولید هشدار کاذب/گمراه‌کننده است:

| علامت بالینی | چرا نمی‌شود؟ | جایگزین پیشنهادی |
|---|---|---|
| درد قفسهٔ سینه، نقص نورولوژیک، کاهش بینایی، کولیک کلیوی (تشخیص emergency vs urgency در BP بالا) | هیچ فیلد symptom/intake ساختاریافته‌ای وجود ندارد | (الف) متن educate در RF-BP-01/02 که بیمار را به اورژانس هدایت کند؛ (ب) فلگ جدید `acute_symptom_reported` که فقط پزشک/پرسنل ثبت کند → نسخهٔ flag-based |
| علائم کاتابولیک (پُرنوشی، پُرادراری، کاهش وزن ناخواسته) برای DKA/HHS | ثبت ساختاریافته ندارد | متن پیام RF-GLY-01/02 + فلگ `weight_loss_unintentional` پس از تأیید پزشک (SF-CM-01 فقط «افت وزن» را می‌بیند) |
| تهوع/استفراغ/درد شکم/تنفس کوسینال (DKA یوگلایسمیک) | ثبت ندارد | متن هشدار RF-GLY-03 صرفاً آموزشی است |
| ضربان نامنظم (غربالگری AF) | اپ ECG ندارد؛ `pulse` فقط عدد است | SF-CM-02 فقط کارِ «معاینهٔ پالس + ECG» می‌سازد؛ تشخیص با پزشک |
| سطح ۳ هیپوگلیسمی (اختلال هوشیاری نیازمند کمک دیگران) | رویداد بیرون از سیستم ثبت می‌شود | ثبت دستی به‌عنوان PATIENT_REPORTED outcome؛ سپس فلگ `severe_hypo_history` |
| پایبندی دارویی (پیش‌نیاز تعریف دقیق HTN مقاوم) | اپ adherence ساختاریافته ندارد | SF-BP-03 نسخهٔ تقریبی است؛ یادداشت «تأیید پایبندی» در متن کار |
| تأیید پایداری افت eGFR (دو آزمایش فاصله‌دار) | evaluator فعلی فقط latest را می‌سنجد | SF-REN-02 پس از افزودن aggregation `within_days` به evaluator v2 |

**قاعدهٔ طلایی:** هر جا بین «داده» و «تشخیص» فاصلهٔ بالینی هست، سیستم فقط `create_followup`/`educate` می‌سازد و تصمیم را به پزشک برمی‌گرداند.

---

## ۸) پیوست — نگاشت به اسکیمای v2 (clinical-rule.schema.json)

هر trigger این سند هنگام تبدیل به `RuleDefinition` باید:
- `var` → `fact` نگاشت شود: `indicator.X.latest` → `lab.X`/`observation.X` با `selector.aggregation="latest"` (+ `max_age_days` در required_facts)؛ `med.class` → `medication.<class_key>`؛ `condition` → `condition.<code>`؛ `flag.<key>` → fact کاتالوگ فلگ.
- `phase`: redflag rules → `PREFLIGHT`؛ safety rules → `SAFETY` (طبق enum اسکیما).
- `action_type`: `classify`/`create_followup`/`educate` (enum موجود).
- `severity`: INFO/WARN/URGENT/CRITICAL طبق جدول بالا؛ `priority` عدد صحیح 0–10000 (اعداد این سند ×100).
- `safety.on_safety_error = "BLOCK_ROUTINE_OUTPUTS"` و `recommendation.suggestion_only=true`، `requires_clinician_confirmation=true` برای همهٔ قواعد دارویی (SF-LAB-01, RF-REN-01, SF-BP-03).
- دو قاعدهٔ delta-dependent (SF-REN-02, SF-CM-01) تا آماده شدن delta aggregation با `governance.status=SILENT` وارد شوند.

## ۹) منابع اصلی

1. American Diabetes Association. *Standards of Care in Diabetes—2025*. Diabetes Care 2025;48(Suppl.1) — §6 (S128–S145): طبقه‌بندی هیپوگلیسمی؛ §9 (S181–S204): آستانه‌های تشدید/انسولین؛ §10: TG≥500.
2. Kidney Disease: Improving Global Outcomes (KDIGO) CKD Work Group. *KDIGO 2024 Clinical Practice Guideline for the Evaluation and Management of CKD*. Kidney Int 2024;105(4S):S117–S314 (PMID 38490803) — Table 2 (A3)، Rec 3.7.2 (K+>5.5)، Practice Points متفورمین/ارجاع.
3. *2024 ESC Guidelines for the management of elevated blood pressure and hypertension*. Eur Heart J 2024;45(38):3912–4018 (doi:10.1093/eurheartj/ehae178) — Fig 10 (BP≥180/110)، Resistant HTN، pulse palpation.
4. Whelton PK, et al. *2017 ACC/AHA High Blood Pressure Guideline*. Hypertension 2018;71:e13–e115 — تعریف resistant HTN.
5. U.S. FDA. Drug Safety Communication 2015 — SGLT2i و ketoacidosis؛ Metformin & Kerendia (finerenone) Prescribing Labels.
6. Bakris GL, et al. *FIDELIO-DKD*. N Engl J Med 2020;383:2219–2229.
7. Endocrine Society. *Unintentional Weight Loss in Older Adults* CPG. J Clin Endocrinol Metab 2021;106(3) (doi:10.1210/clinem/dgaa726).
8. Miller M, et al. *Triglycerides and Cardiovascular Disease: AHA Scientific Statement*. Circulation 2011;123:2292–2333.
9. Yang AL, McNabb-Baltar J. *Hypertriglyceridemia and acute pancreatitis*. Pancreatology 2020;20:795–800.
10. Dhatariya KK, et al. *ADA Consensus Report on Hyperglycemic Crises in Adults With Diabetes*. Diabetes Care 2024;47(10):1637–1654.
