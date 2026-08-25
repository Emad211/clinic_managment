# دوزیهٔ راهنمای بالینی فشار خون بالا (HTN) — برای تبدیل مکانیکی به قواعد If/Then

> **نسخه:** v1.0.0 · **تاریخ:** 2026-08-23 · **وضعیت:** DRAFT برای بازبینی پزشک
> **مقصد:** موتور قواعد اپ specialist_clinic — تبدیل ۱:۱ به JSON rules
> **دامنه:** بزرگسالان ≥18 سال؛ **بارداری خارج از دامنه است** (راهنمای مستقل لازم دارد).
> **قاعدهٔ حاکم:** خروجی هر قاعده فقط «پیشنهاد به پزشک» است، نه ارسال خودکار (سازگار با governance FO).

---

## نگاشت DSL و قرارداد قواعد

هر قاعده = آرایهٔ `conditions` با منطق AND. شرط OR به دو قاعدهٔ جدا شکسته می‌شود (پسوند a/b).

```jsonc
{
  "id": "HTN-Rxx",
  "phase": "routine | safety | redflag",
  "severity": "critical | high | medium | low",
  "priority": 10,
  "conditions": [
    { "var": "indicator.bp_systolic.latest", "op": ">=", "value": 140 },
    { "var": "flag.diabetes", "op": "==", "value": true },
    { "var": "med.class", "op": "has", "value": "acei" },
    { "var": "age", "op": ">=", "value": 65 }
  ],
  "action": { "type": "...", "...": "..." }
}
```

| DSL | معادل بالینی |
|---|---|
| `indicator.<key>.latest` op `>=`,`<`,`between` | آخرین مقدار اندیکاتور |
| `flag.<key>` op `truthy`/`==`/`in` | پرچم جمعیت/بیماری |
| `med.class` op `has`/`not_has` | کلاس دارویی فعال بیمار |
| Actions | classify / set_target / suggest_med / create_followup / schedule_screening / vaccine / educate |

**فازها:** `redflag` = ارجاع فوری · `safety` = چک آزمایشگاهی/دارویی · `routine` = مدیریت معمول.
**اولویت:** عدد کوچک‌تر = زودتر اجرا.

---

# بخش ۱ — تشخیص و طبقه‌بندی

### ۱.۱ طبقه‌بندی دفتری (Office)

**ACC/AHA 2017** (Whelton PK et al., *Hypertension* 2018;71:e13–e115، جدول «Blood Pressure Categories»):

| دسته | سیستولیک (mmHg) | دیاستولیک (mmHg) |
|---|---|---|
| Normal | <120 **و** | <80 |
| Elevated | 120–129 **و** | <80 |
| Stage 1 HTN | 130–139 **یا** | 80–89 |
| Stage 2 HTN | ≥140 **یا** | ≥90 |

**ESH 2023** (Mancia G et al., *J Hypertens* 2023;41(12):1874–2071، §3.4):

| گرید | سیستولیک | دیاستولیک |
|---|---|---|
| Grade 1 | 140–159 | 90–99 |
| Grade 2 | 160–179 | 100–109 |
| Grade 3 | ≥180 | ≥110 |

- تشخیص نیازمند چند اندازه‌گیری در ≥2 ویزیت یا تأیید out-of-office (ESH 2023 §3.6).
- اگر فشار >20/10 mmHg بالاتر از هدف: شروع با **۲ دارو** (ACC/AHA 2017؛ ESH 2023 §7.2).

### ۱.۲ اندازه‌گیری خارج از مطب

| روش | ACC/AHA 2017 | ESH 2023 |
|---|---|---|
| HBPM (خانه) | ≥130/80 | ≥135/85 |
| ABPM بیداری | ≥130/80 | ≥135/85 |
| ABPM خواب | ≥110/65 | ≥120/70 |
| ABPM میانگین ۲۴ ساعت | ≥125/75 | ≥130/80 |

پروتکل HBPM (ESH 2023 §3.5): ۷ روز × ۲ قرائت (صبح قبل از دارو + شب)، حذف روز اول، میانگین ≥12 قرائت.

### قواعد پیشنهادی بخش ۱

#### HTN-R01a/b — Stage 2 (ACC/AHA)
```json
{"id":"HTN-R01a","phase":"routine","severity":"high","priority":10,
 "conditions":[{"var":"indicator.bp_systolic.latest","op":">=","value":140}],
 "action":{"type":"classify","label":"htn_stage_2_acc_aha"}}
{"id":"HTN-R01b","phase":"routine","severity":"high","priority":10,
 "conditions":[{"var":"indicator.bp_diastolic.latest","op":">=","value":90}],
 "action":{"type":"classify","label":"htn_stage_2_acc_aha"}}
```

#### HTN-R02a/b — Stage 1
```json
{"id":"HTN-R02a","phase":"routine","severity":"medium","priority":12,
 "conditions":[{"var":"indicator.bp_systolic.latest","op":"between","value":[130,139]}],
 "action":{"type":"classify","label":"htn_stage_1_acc_aha"}}
{"id":"HTN-R02b","phase":"routine","severity":"medium","priority":12,
 "conditions":[{"var":"indicator.bp_diastolic.latest","op":"between","value":[80,89]}],
 "action":{"type":"classify","label":"htn_stage_1_acc_aha"}}
```

#### HTN-R03 — Elevated (بدون دارو)
```json
{"id":"HTN-R03","phase":"routine","severity":"low","priority":14,
 "conditions":[
   {"var":"indicator.bp_systolic.latest","op":"between","value":[120,129]},
   {"var":"indicator.bp_diastolic.latest","op":"<","value":80}
 ],
 "action":{"type":"educate","topic":"lifestyle_elevated_bp",
   "note":"Non-pharmacologic + HBPM 7-day protocol"}}
```

#### HTN-R04 — Normal
```json
{"id":"HTN-R04","phase":"routine","severity":"low","priority":99,
 "conditions":[
   {"var":"indicator.bp_systolic.latest","op":"<","value":120},
   {"var":"indicator.bp_diastolic.latest","op":"<","value":80}
 ],
 "action":{"type":"classify","label":"bp_normal"}}
```

#### HTN-R05a/b — شدید کنترل‌نشده (دروازهٔ بخش ۷)
```json
{"id":"HTN-R05a","phase":"redflag","severity":"critical","priority":1,
 "conditions":[{"var":"indicator.bp_systolic.latest","op":">=","value":180}],
 "action":{"type":"create_followup","kind":"severe_htn_review","due_hours":24}}
{"id":"HTN-R05b","phase":"redflag","severity":"critical","priority":1,
 "conditions":[{"var":"indicator.bp_diastolic.latest","op":">=","value":110}],
 "action":{"type":"create_followup","kind":"severe_htn_review","due_hours":24}}
```
*(استناد: ESH 2023 §11 «Severe uncontrolled hypertension» — SBP≥180 یا DBP≥110)*

---

# بخش ۲ — اهداف درمانی بر اساس جمعیت

| جمعیت | هدف BP | استناد |
|---|---|---|
| بزرگسال عمومی تحت درمان | **<130/80** | ACC/AHA 2017 (Whelton 2018, Hypertension;71:e13) |
| رویکرد اروپایی (عمومی) | **<130/80 اگر تحمل شود؛ سیستولیک نه زیر 120** | ESH 2023 §7.4 (Mancia 2023, J Hypertens;41:1874)؛ مبنای شواهد: SPRINT (NEJM 2015;373:2103–16، PMID 26551272 — هدف <120 برتری ترکیبی CV با HR 0.75) |
| دیابت نوع ۱/۲ | **<130/80** | ADA Standards of Care 2025 §10.4a |
| CKD غیردیالیزی | **SBP <120** (اندازه‌گیری دفتری استانداردشده) | KDIGO 2021 BP Guideline Rec 3.4.1 Grade 2B (Kidney Int 2021;99:S1–S87) |
| CKD + احتیاط (سالمند/شکننده/کوموربیدی) | فردی‌سازی؛ افت سریع ممنوع | KDIGO 2021 Rec 3.4.1 (پیوست احتیاط) |
| سالمندان ≥65 سال | ابتدا به سمت <140 سپس <130 اگر تحمل شد؛ **سیستولیک <120 توصیه نمی‌شود** | ESH 2023 §7.4.2؛ HYVET (Beckett NS, NEJM 2008;358:1887–98 — هدف 150/80 در ≥80 سال) |
| شکننده / افت وضعیتی | شل‌کردن هدف تا 140–150 سیستولیک؛ بررسی افت فشار وضعیتی قبل از تشدید | ESH 2023 §7.5 |

### قواعد پیشنهادی بخش ۲

#### HTN-R06 — هدف عمومی
```json
{"id":"HTN-R06","phase":"routine","severity":"medium","priority":20,
 "conditions":[{"var":"flag.hypertension","op":"truthy"}],
 "action":{"type":"set_target","systolic":130,"diastolic":80,"population":"general",
   "citation":"ACC/AHA 2017"}}
```

#### HTN-R07 — هدف دیابت
```json
{"id":"HTN-R07","phase":"routine","severity":"high","priority":18,
 "conditions":[{"var":"flag.diabetes","op":"truthy"}],
 "action":{"type":"set_target","systolic":130,"diastolic":80,"population":"diabetes",
   "citation":"ADA Standards of Care 2025 §10.4a"}}
```

#### HTN-R08 — هدف CKD
```json
{"id":"HTN-R08","phase":"routine","severity":"high","priority":16,
 "conditions":[{"var":"flag.ckd","op":"truthy"}],
 "action":{"type":"set_target","systolic":120,"diastolic":null,"population":"ckd",
   "note":"KDIGO standardized-office SBP<120; individualize if frail",
   "citation":"KDIGO 2021 Rec 3.4.1"}}
```

#### HTN-R09 — سالمند ≥65 (هدف پله‌ای)
```json
{"id":"HTN-R09","phase":"routine","severity":"medium","priority":17,
 "conditions":[{"var":"age","op":">=","value":65}],
 "action":{"type":"set_target","systolic":140,"diastolic":90,"population":"elderly_step1",
   "note":"then toward 130 if tolerated; avoid SBP<120",
   "citation":"ESH 2023 §7.4.2"}}
```

#### HTN-R10 — شکننده/افت وضعیتی
```json
{"id":"HTN-R10","phase":"safety","severity":"high","priority":8,
 "conditions":[{"var":"flag.frail_or_orthostatic","op":"truthy"}],
 "action":{"type":"create_followup","kind":"orthostatic_bp_check_before_intensification",
   "due_days":14,"citation":"ESH 2023 §7.5"}}
```

---

# بخش ۳ — داروهای خط اول: دوز شروع، تیتراسیون، حداکثر

> همهٔ دوزها خوراکی، بزرگسال، بدون محدودیت شدید کبدی/کلیوی مگر ذکر شود.
> تیتراسیون عمومی: بازبینی هر **۲–۴ هفته**؛ اگر به هدف نرسید و دوز زیر max است → پلهٔ بعدی (ACC/AHA 2017؛ ESH 2023 §7.6).

### ۳.۱ مهارکنندهٔ ACE (ACEi)

| دارو | شروع | تیتراسیون | حداکثر روزانه | یادداشت |
|---|---|---|---|---|
| انالاپریل Enalapril | 5 mg یک‌بار/روز (2.5 اگر سن بالا یا eGFR<30) | دوبرابر هر ۲–۴ هفته | **40 mg** (در دوزهای بالا تقسیم ۲ نوبت) | ژنریک رایج ایران |
| رامیپریل Ramipril | 2.5–5 mg/روز | افزایش تدریجی هر ۲–۴ هفته | **10 mg** | شواهد ASCVD از HOPE |
| کاپتوپریل Captopril | 12.5–25 mg دو تا سه بار/روز | افزایش پله‌ای | **150 mg/روز عملی** (برچسب تا 450) | نیمه‌عمر کوتاه؛ TID |
| لیزینوپریل Lisinopril | 10 mg/روز (2.5–5 اگر eGFR<30) | دوبرابر هر ۲–۴ هفته | **40 mg** | |

هشدارهای کلاس ACEi/ARB: K⁺↑، افزایش کراتینین (**پذیرفتنی ≤30%**)، سرفه با ACEi (~۵–۲۰%)، آنژیوادم (نادر)، ممنوع در بارداری و تنگی دوطرفهٔ شریان کلیه.

### ۳.۲ بلوکر گیرندهٔ آنژیوتنسین (ARB)

| دارو | شروع | تیتراسیون | حداکثر روزانه |
|---|---|---|---|
| لوزارتان Losartan | 50 mg/روز (**25** اگر کم‌حجمی یا بیماری کبدی) | دوبرابر هر ۲–۴ هفته | **100 mg** |
| والزارتان Valsartan | 80 mg/روز | 160 → 320 | **320 mg** |
| تلمیزارتان Telmisartan | 40 mg/روز (20 در صورت نیاز) | 40 → 80 | **80 mg** |

### ۳.۳ مسدودکنندهٔ کانال کلسیم دی‌هیدروپیریدینی (CCB)

| دارو | شروع | تیتراسیون | حداکثر روزانه |
|---|---|---|---|
| آملودیپین Amlodipine | 5 mg/روز (**2.5** سالمند/شکننده/کم‌وزن) | 5 → 10 پس از ۲–۴ هفته | **10 mg** |
| نیفیدیپین آهسته‌رهش Nifedipine ER/OROS | 30 mg/روز | 30 → 60 → 90 | **90 mg** |

عارضهٔ اصلی: ادیم مچ (وابسته به دوز) — کاهش دوز یا تعویض، نه قطع کلاس.

### ۳.۴ دیورتیک تیازیدی/تیازیدمانند

| دارو | شروع | تیتراسیون | حداکثر روزانه |
|---|---|---|---|
| هیدروکلروتیازید HCTZ | 12.5–25 mg صبح | 12.5 → 25 | **25 mg توصیه‌شده** (برچسب تا 50؛ شواهد دوز بالا ضعیف) |
| اینداپامید Indapamide SR | 1.5 mg صبح (فرم معمولی 1.25–2.5) | ثابت | **1.5 mg (SR) / 2.5 mg (IR)** |
| کلرتالیدون Chlorthalidone | 12.5–25 mg صبح | 12.5 → 25 → 50 | **50 mg** |

تیازیدمانندها (chlorthalidone/indapamide) در شواهد پیامد مؤثرتر از HCTZ هستند. چک Na/K/Cr طی ۲–۴ هفته پس از شروع/تیتراسیون؛ احتیاط در نقرس.

### ۳.۵ خط چهارم / مقاوم

| دارو | شروع | تیتراسیون | حداکثر | یادداشت |
|---|---|---|---|---|
| اسپیرونولاکتون Spironolactone | 12.5–25 mg/روز | 25 → 50 پس از ۴ هفته | **50 mg** | PATHWAY-2: بهترین داروی چهارم (Lancet 2015;386:2059–68، PMID 26414968؛ بازوها: spironolactone 25→50، bisoprolol 5→10، doxazosin 4→8)؛ چک K در هفتهٔ ۱ و ۴؛ K>5.0 قطع؛ احتیاط eGFR<30 (آزمون eGFR≥45) |
| بیسوپرولول Bisoprolol | 2.5–5 mg/روز | دوبرابر هر ۲–۴ هفته | **10 mg** (برچسب تا 20) | بتابلاکر خط اول فقط با اندیکاسیون الزامی |
| متوپرولول سوکسینات Metoprolol succinate ER | 25–50 mg/روز | 50 → 100 → 200 | **200 mg** | |
| کارودیلول Carvedilol | 3.125 mg دو بار/روز | دوبرابر هر ۲ هفته | **25 mg BID** | |
| دوکسازوسین Doxazosin | 1–2 mg شب | 4 → 8 | **8 mg** | افت وضعیتی |
| فوروزماید Furosemide | 20–40 mg یک تا دو بار/روز | بر اساس حجم | متغیر | فقط eGFR<30 یا احتباس حجمی |
| تورسماید Torsemide | 5–10 mg/روز | — | **20 mg** | جذب بهتر از فوروزماید |
| فینرنون Finerenone | **10 mg/روز** (20 اگر eGFR≥60 و K≤5.0) | پس از ۴ هفته → 20 mg | **20 mg** | فقط CKD+دیابت نوع۲؛ ممنوع eGFR<25 یا K پایه >5.0؛ وقفه اگر K>5.5 (FIDELIO-DKD, NEJM 2020;383:2219–29، PMID 33264825) |

### قواعد پیشنهادی بخش ۳ (شروع/تیتراسیون)

#### HTN-R11 — شروع مونوتراپی Stage 2 بدون اندیکاسیون الزامی
```json
{"id":"HTN-R11","phase":"routine","severity":"high","priority":22,
 "conditions":[
   {"var":"flag.hypertension","op":"truthy"},
   {"var":"med.class","op":"not_has","value":"acei"},
   {"var":"med.class","op":"not_has","value":"arb"},
   {"var":"med.class","op":"not_has","value":"ccb"},
   {"var":"med.class","op":"not_has","value":"thiazide"}
 ],
 "action":{"type":"suggest_med","class":"acei","drug":"enalapril",
   "start_mg":5,"frequency":"daily","max_mg_per_day":40,
   "titration":{"interval_weeks":4,"step":"double until target or max"},
   "cautions":["k_up","creatinine_rise_le_30pct_acceptable"],
   "citation":"ACC/AHA 2017 first-line classes"}}
```

#### HTN-R12 — تیتراسیون داروی موجود زیر max
```json
{"id":"HTN-R12","phase":"routine","severity":"medium","priority":24,
 "conditions":[
   {"var":"indicator.bp_systolic.latest","op":">=","value":130},
   {"var":"flag.on_single_agent_below_max","op":"truthy"}
 ],
 "action":{"type":"suggest_med","class":"acei","drug":"enalapril",
   "titrate_to_mg":10,"max_mg_per_day":40,
   "note":"recheck BP in 2-4 weeks after each titration",
   "citation":"ACC/AHA 2017 titration cadence"}}
```

#### HTN-R13 — شروع CCB جایگزین (سرفه با ACEi)
```json
{"id":"HTN-R13","phase":"routine","severity":"medium","priority":23,
 "conditions":[
   {"var":"flag.acei_cough_intolerant","op":"truthy"},
   {"var":"med.class","op":"not_has","value":"ccb"}
 ],
 "action":{"type":"suggest_med","class":"ccb","drug":"amlodipine",
   "start_mg":5,"max_mg_per_day":10,
   "titration":{"interval_weeks":4,"step":"5->10"},
   "citation":"ACC/AHA 2017; ESH 2023 §7.6"}}
```

#### HTN-R14 — دیورتیک تیازیدمانند به‌عنوان داروی دوم/سوم
```json
{"id":"HTN-R14","phase":"routine","severity":"medium","priority":26,
 "conditions":[
   {"var":"flag.hypertension_uncontrolled","op":"truthy"},
   {"var":"med.class","op":"not_has","value":"thiazide"}
 ],
 "action":{"type":"suggest_med","class":"thiazide","drug":"indapamide_sr",
   "start_mg":1.5,"max_mg_per_day":1.5,
   "labs_after_weeks":4,
   "lab_keys":["sodium","potassium","creatinine"],
   "citation":"ESH 2023 §7.6 (thiazide-like preferred)"}}
```

#### HTN-R15 — Loop diuretic در CKD پیشرفته
```json
{"id":"HTN-R15","phase":"safety","severity":"high","priority":15,
 "conditions":[
   {"var":"indicator.egfr.latest","op":"<","value":30},
   {"var":"med.class","op":"has","value":"thiazide"}
 ],
 "action":{"type":"suggest_med","class":"loop_diuretic","drug":"furosemide",
   "start_mg":20,"frequency":"bid","replace_class":"thiazide",
   "citation":"KDIGO 2021; ESH 2023 (thiazides ineffective eGFR<30)"}}
```

---

# بخش ۴ — منطق ترکیب دارویی

### ۴.۱ قواعد ترکیب

1. **شروع با ترکیب دو دارویی تک‌قرص (SPC)** در اکثر بیماران، به‌ویژه Grade 2+ یا فشار >20/10 بالاتر از هدف (ESH 2023 §7.2؛ ACC/AHA 2017).
2. **ترکیب ارجح: ACEi (یا ARB) + CCB** — مبنای پیامد: ACCOMPLISH (Jamerson K et al., NEJM 2008;359:2417–28، PMID 19092151): بنازپریل+آملودیپین نسبت به بنازپریل+HCTZ کاهش ۲۰٪ رخداد CV (HR 0.80؛ 95%CI 0.72–0.90) با اختلاف BP ناچیز.
3. **ترکیب قابل‌قبول دوم: ACEi/ARB + تیازیدمانند.**
4. **ممنوع مطلق: ACEi + ARB همزمان** — ONTARGET (Yusuf S et al., NEJM 2008;358:1547–59، PMID 18378519): بدون کاهش پیامد + افزایش AKI، هایپرکالمی و افت وضعیتی.
5. سه‌گانهٔ استاندارد: **ACEi/ARB + CCB + تیازیدمانند**.
6. بتابلاکر فقط با اندیکاسیون الزامی (ASCVD/HFrEF/کنترل ضربان)، نه خط اول معمول.

### ۴.۲ مسیر مقاوم (Resistant HTN)

تعریف: کنترل‌نشده با **۳ دارو از ۳ کلاس شامل دیورتیک در دوز بهینه** (یا نیازمند ≥۴ دارو برای کنترل).

مسیر مبتنی بر PATHWAY-2 (Williams B et al., Lancet 2015;386:2059–68، PMID 26414968):
- **اسپیرونولاکتون 25→50 mg/روز = بهترین داروی چهارم** (برتری بر placebo، bisoprolol 5→10 و doxazosin 4→8).
- جایگزین‌ها: کلرتالیدون 12.5–25 mg یا آمیلورید 10–20 mg.
- اگر همچنان کنترل‌نشده → ارجاع برای بررسی HTN ثانویه (آلدوسترون/رنین، تنگی شریان کلیه، OSA، فئوکروموسیتوم) و ABPM.

### قواعد پیشنهادی بخش ۴

#### HTN-R16a/b — شروع SPC دو دارویی Grade 2
```json
{"id":"HTN-R16a","phase":"routine","severity":"high","priority":21,
 "conditions":[
   {"var":"indicator.bp_systolic.latest","op":">=","value":160},
   {"var":"med.class","op":"not_has","value":"acei"},
   {"var":"med.class","op":"not_has","value":"arb"}
 ],
 "action":{"type":"suggest_med","class":"acei","drug":"enalapril",
   "start_mg":5,"combo_with_class":"ccb","combo_drug":"amlodipine",
   "combo_start_mg":5,"form":"single_pill_preferred",
   "citation":"ESH 2023 §7.2; ACCOMPLISH NEJM 2008;359:2417"}}
{"id":"HTN-R16b","phase":"routine","severity":"high","priority":21,
 "conditions":[
   {"var":"indicator.bp_diastolic.latest","op":">=","value":100},
   {"var":"med.class","op":"not_has","value":"acei"},
   {"var":"med.class","op":"not_has","value":"arb"}
 ],
 "action":{"type":"suggest_med","class":"acei","drug":"enalapril",
   "start_mg":5,"combo_with_class":"ccb","combo_drug":"amlodipine",
   "combo_start_mg":5,"citation":"ESH 2023 §7.2"}}
```

#### HTN-R17 — ممنوعیت ACEi+ARB (حفاظت)
```json
{"id":"HTN-R17","phase":"safety","severity":"critical","priority":5,
 "conditions":[
   {"var":"med.class","op":"has","value":"acei"},
   {"var":"med.class","op":"has","value":"arb"}
 ],
 "action":{"type":"create_followup","kind":"physician_alert_dual_ras_blockade",
   "due_hours":24,
   "citation":"ONTARGET NEJM 2008;358:1547 — harm, never combine"}}
```

#### HTN-R18 — داروی چهارم: اسپیرونولاکتون (PATHWAY-2)
```json
{"id":"HTN-R18","phase":"routine","severity":"high","priority":19,
 "conditions":[
   {"var":"flag.resistant_htn_3drugs_with_diuretic","op":"truthy"},
   {"var":"med.class","op":"not_has","value":"mra"}
 ],
 "action":{"type":"suggest_med","class":"mra","drug":"spironolactone",
   "start_mg":25,"titrate_to_mg":50,"max_mg_per_day":50,
   "labs_weeks":[1,4],"lab_keys":["potassium","creatinine"],
   "stop_if_k_gt":5.0,
   "alternatives":[{"class":"thiazide","drug":"chlorthalidone","start_mg":12.5}],
   "citation":"PATHWAY-2 Lancet 2015;386:2059 (PMID 26414968)"}}
```

#### HTN-R19 — چک K پس از MRA (هفتهٔ ۱ و ۴)
```json
{"id":"HTN-R19","phase":"safety","severity":"critical","priority":6,
 "conditions":[
   {"var":"med.class","op":"has","value":"mra"},
   {"var":"flag.mra_started_or_titrated_within_4w","op":"truthy"}
 ],
 "action":{"type":"schedule_screening","panel":["potassium","creatinine","egfr"],
   "due_days":7,"repeat_due_days":28,
   "citation":"PATHWAY-2 protocol; ESH 2023 §7.9"}}
```

#### HTN-R20 — ارجاع مقاوم واقعی
```json
{"id":"HTN-R20","phase":"routine","severity":"high","priority":13,
 "conditions":[{"var":"flag.resistant_htn_on_4drugs_uncontrolled","op":"truthy"}],
 "action":{"type":"create_followup","kind":"specialist_referral_secondary_htn_workup",
   "due_days":30,
   "workup":["aldosterone_renin_ratio","renal_imaging","osa_screening","abpm"],
   "citation":"ESH 2023 §7.9; PATHWAY-2 post-trial guidance"}}
```

---

# بخش ۵ — اندیکاسیون‌های الزام‌آور (Compelling Indications)

| پرچم | توصیه | استناد |
|---|---|---|
| `flag.diabetes` | ACEi/ARB خط اول؛ هدف <130/80 | ADA Standards of Care 2025 §10.4b–c |
| `flag.diabetes` + UACR≥300 mg/g (یا eGFR 30–60) | ACEi/ARB **با حداکثر دوز تحمل‌شده** | ADA 2025 §10.4c؛ KDIGO 2021 Rec 3.7.1 |
| `flag.ckd` + UACR≥30 mg/g (A2/A3) | ACEi/ARB حداکثر تحمل‌شده؛ شروع وقتی SBP≥120 | KDIGO 2021 Rec 3.7.1 (Kidney Int 2021;99:S1–S87) |
| T2D + CKD (eGFR 25–75، K≤5.0) | افزودن **فینرنون** 10→20 mg | FIDELIO-DKD (NEJM 2020;383:2219–29، PMID 33264825 — HR 0.63 ترکیب کلیوی؛ قطع به‌علت هایپرکالمی 2.3% vs 0.9%)؛ FLOW (NEJM 2024 — کاهش ~۲۴٪ نارسایی کلیه؛ تأیید عدد دقیق در gaps) |
| `flag.ascvd` | استاتین (شدید اگر ≤75 سال) + آسپیرین پیشگیری ثانویه؛ بتابلاکر پس از MI | ACC/AHA Cholesterol Guideline 2018 (Circulation 2019;139:e1082)؛ ESH 2023 §8 |
| `flag.hf` (HFrEF) | بتابلاکر + ACEi/ARB/ARNI + MRA طبق راهنمای HF | خارج از دامنهٔ کامل این دوزیه — gap |

### قواعد پیشنهادی بخش ۵

#### HTN-R21 — دیابت → ACEi/ARB
```json
{"id":"HTN-R21","phase":"routine","severity":"high","priority":14,
 "conditions":[
   {"var":"flag.diabetes","op":"truthy"},
   {"var":"med.class","op":"not_has","value":"acei"},
   {"var":"med.class","op":"not_has","value":"arb"}
 ],
 "action":{"type":"suggest_med","class":"acei","drug":"enalapril",
   "start_mg":5,"max_mg_per_day":40,
   "note":"ARB (losartan 50->100) if ACEi cough",
   "citation":"ADA 2025 §10.4b"}}
```

#### HTN-R22 — آلبومینوری → RASi حداکثر دوز
```json
{"id":"HTN-R22","phase":"routine","severity":"high","priority":11,
 "conditions":[
   {"var":"indicator.uacr.latest","op":">=","value":300},
   {"var":"med.class","op":"not_has","value":"acei"},
   {"var":"med.class","op":"not_has","value":"arb"}
 ],
 "action":{"type":"suggest_med","class":"acei","drug":"enalapril",
   "start_mg":5,"target":"max_tolerated_dose","max_mg_per_day":40,
   "citation":"KDIGO 2021 Rec 3.7.1; ADA 2025 §10.4c"}}
```
*(نسخهٔ A2: همان قاعده با `uacr between [30,299]` و شرط `flag.diabetes`.)*

#### HTN-R23 — فینرنون برای T2D-CKD
```json
{"id":"HTN-R23","phase":"routine","severity":"medium","priority":27,
 "conditions":[
   {"var":"flag.diabetes","op":"truthy"},
   {"var":"flag.ckd","op":"truthy"},
   {"var":"indicator.egfr.latest","op":"between","value":[25,75]},
   {"var":"indicator.uacr.latest","op":">=","value":30},
   {"var":"med.class","op":"not_has","value":"finerenone"}
 ],
 "action":{"type":"suggest_med","class":"finerenone","drug":"finerenone",
   "start_mg":10,"start_mg_20_if_egfr_ge":60,
   "titrate_after_weeks":4,"target_mg":20,"max_mg_per_day":20,
   "hold_if_k_gt":5.5,"contraindicated_if":{"egfr_lt":25,"k_gt":5.0},
   "citation":"FIDELIO-DKD NEJM 2020;383:2219 (PMID 33264825); FLOW NEJM 2024"}}
```

#### HTN-R24 — ASCVD → لینک استاتین
```json
{"id":"HTN-R24","phase":"routine","severity":"high","priority":12,
 "conditions":[{"var":"flag.ascvd","op":"truthy"}],
 "action":{"type":"educate","topic":"statin_secondary_prevention",
   "note":"High-intensity statin if age<=75; aspirin secondary prevention — physician decision",
   "citation":"ACC/AHA Cholesterol 2018; ESH 2023 §8"}}
```

#### HTN-R25 — واکسن آنفلوانزا (بیماری مزمن)
```json
{"id":"HTN-R25","phase":"routine","severity":"low","priority":60,
 "conditions":[{"var":"flag.chronic_disease","op":"truthy"}],
 "action":{"type":"vaccine","vaccine":"influenza_annual",
   "citation":"ESC/ESH chronic-disease prevention practice; confirm with clinic policy"}}
```

---

# بخش ۶ — غربالگری آزمایشگاهی و پایش

### ۶.۱ زمان‌بندی

| زمان | آزمایش‌ها | استناد |
|---|---|---|
| **پایه** قبل از شروع هر داروی ضدفشار (به‌ویژه RASi/MRA/دیورتیک) | کراتینین/eGFR، K، UACR، گلوکز ناشتا/HbA1c، لیپیدها | ESH 2023 §4.5؛ KDIGO 2021 §3.7 |
| **۲–۴ هفته پس از شروع/تیتراسیون** ACEi/ARB/MRA/دیورتیک | K + کراتینین/eGFR؛ افزایش Cr تا **≤30% قابل قبول**؛ >30% → بررسی تنگی شریان کلیه/کاهش دوز | KDIGO 2021 §3.7.2؛ ESH 2023 §7.7 |
| **سالانه** در بیمار تحت درمان | کراتینین/eGFR، K، UACR (دیابت/CKD)، لیپیدها، گلوکز/HbA1c | ADA 2025 §10.4/§11؛ ESH 2023 §8.1.2 |
| HBPM پروتکل | ۷ روز × ۲ قرائت صبح/شب، حذف روز اول، میانگین ≥12 قرائت | ESH 2023 §3.5 |

### قواعد پیشنهادی بخش ۶

#### HTN-R26 — آزمایش پایه قبل از RASi
```json
{"id":"HTN-R26","phase":"safety","severity":"high","priority":9,
 "conditions":[
   {"var":"flag.rasi_about_to_start","op":"truthy"},
   {"var":"flag.baseline_labs_current","op":"==","value":false}
 ],
 "action":{"type":"schedule_screening",
   "panel":["creatinine","egfr","potassium","uacr","fbs","hba1c","ldl"],
   "due_days":0,"blocking":true,
   "citation":"ESH 2023 §4.5; KDIGO 2021 §3.7"}}
```

#### HTN-R27 — چک K/Cr پس از شروع/تیتراسیون RASi
```json
{"id":"HTN-R27","phase":"safety","severity":"critical","priority":7,
 "conditions":[
   {"var":"flag.rasi_started_or_titrated_within_4w","op":"truthy"},
   {"var":"flag.post_change_labs_done","op":"==","value":false}
 ],
 "action":{"type":"schedule_screening","panel":["potassium","creatinine","egfr"],
   "due_days":14,"window_days":[14,28],
   "accept_creatinine_rise_pct_max":30,
   "citation":"KDIGO 2021 §3.7.2"}}
```

#### HTN-R28 — UACR سالانه (دیابت)
```json
{"id":"HTN-R28","phase":"routine","severity":"medium","priority":30,
 "conditions":[
   {"var":"flag.diabetes","op":"truthy"},
   {"var":"flag.uacr_done_within_days","op":"<","value":365}
 ],
 "action":{"type":"schedule_screening","panel":["uacr"],"cadence":"annual",
   "citation":"ADA 2025 §11 (annual UACR in diabetes)"}}
```

#### HTN-R29 — پنل سالانهٔ بیمار HTN
```json
{"id":"HTN-R29","phase":"routine","severity":"low","priority":40,
 "conditions":[{"var":"flag.hypertension_on_treatment","op":"truthy"}],
 "action":{"type":"schedule_screening",
   "panel":["creatinine","egfr","potassium","uacr","ldl","fbs"],
   "cadence":"annual","citation":"ESH 2023 §8.1.2"}}
```

#### HTN-R30 — پروتکل HBPM
```json
{"id":"HTN-R30","phase":"routine","severity":"low","priority":45,
 "conditions":[{"var":"flag.bp_unconfirmed_or_white_coat_suspect","op":"truthy"}],
 "action":{"type":"educate","topic":"hbpm_protocol",
   "params":{"days":7,"readings_per_day":2,"discard_day1":true,"min_readings":12},
   "citation":"ESH 2023 §3.5"}}
```

---

# بخش ۷ — پرچم‌های سرخ: اورژانس و فوریت

### ۷.۱ تعاریف

- **اورژانس فشاری:** BP ≥180/**120** mmHg **با** آسیب اندام هدف جدید: آنسفالوپاتی، سکته/TIA، درد قفسهٔ سینه/سندرم حاد کرونری، دیسترس تنفسی/ادیم ریه، کاهش ادرار/AKI، افت بینایی/پاپیل‌ادم، تشنج، شکاف آئورت → **ارجاع فوری اورژانس**.
- **فوریت بدون علامت:** BP ≥180/110–120 بدون آسیب اندام → اندازه‌گیری مجدد پس از ۵ دقیقه استراحت ×۲؛ تنظیم داروی خوراکی؛ پیگیری طی **۲۴–۷۲ ساعت**؛ درمان وریدی ممنوع.
- استناد: ACC/AHA 2017 §7.4 («hypertensive crises» ≥180/120)؛ ESH 2023 §11.

### قواعد پیشنهادی بخش ۷

#### HTN-R31a/b/c — اورژانس فشاری
```json
{"id":"HTN-R31a","phase":"redflag","severity":"critical","priority":2,
 "conditions":[
   {"var":"indicator.bp_systolic.latest","op":">=","value":180},
   {"var":"indicator.bp_diastolic.latest","op":">=","value":120},
   {"var":"flag.end_organ_symptom","op":"in",
    "value":["chest_pain","dyspnea","neuro_deficit","vision_loss","seizure","oliguria"]}
 ],
 "action":{"type":"create_followup","kind":"emergency_referral_ed_now",
   "due_hours":0,
   "message_fa":"فشار بسیار بالا همراه با علامت خطر — مراجعهٔ فوری به اورژانس",
   "citation":"ACC/AHA 2017 §7.4; ESH 2023 §11"}}
{"id":"HTN-R31b","phase":"redflag","severity":"critical","priority":2,
 "conditions":[
   {"var":"indicator.bp_systolic.latest","op":">=","value":180},
   {"var":"flag.end_organ_symptom","op":"in",
    "value":["chest_pain","dyspnea","neuro_deficit","vision_loss","seizure","oliguria"]}
 ],
 "action":{"type":"create_followup","kind":"emergency_referral_ed_now","due_hours":0}}
{"id":"HTN-R31c","phase":"redflag","severity":"critical","priority":2,
 "conditions":[
   {"var":"indicator.bp_diastolic.latest","op":">=","value":120},
   {"var":"flag.end_organ_symptom","op":"in",
    "value":["chest_pain","dyspnea","neuro_deficit","vision_loss","seizure","oliguria"]}
 ],
 "action":{"type":"create_followup","kind":"emergency_referral_ed_now","due_hours":0}}
```

#### HTN-R32a/b — فوریت بدون علامت
```json
{"id":"HTN-R32a","phase":"redflag","severity":"high","priority":3,
 "conditions":[
   {"var":"indicator.bp_systolic.latest","op":">=","value":180},
   {"var":"flag.end_organ_symptom","op":"==","value":false}
 ],
 "action":{"type":"create_followup",
   "kind":"asymptomatic_severe_bp_recheck_and_oral_adjustment",
   "due_hours":24,"max_due_hours":72,
   "protocol":["repeat_after_rest_5min_x2","adjust_oral_meds","no_iv_therapy"],
   "citation":"ESH 2023 §11; ACC/AHA 2017 §7.4"}}
{"id":"HTN-R32b","phase":"redflag","severity":"high","priority":3,
 "conditions":[
   {"var":"indicator.bp_diastolic.latest","op":">=","value":110},
   {"var":"flag.end_organ_symptom","op":"==","value":false}
 ],
 "action":{"type":"create_followup",
   "kind":"asymptomatic_severe_bp_recheck_and_oral_adjustment",
   "due_hours":24,"max_due_hours":72}}
```

#### HTN-R33 — هایپرکالمی روی MRA/RASi
```json
{"id":"HTN-R33","phase":"safety","severity":"critical","priority":4,
 "conditions":[{"var":"flag.potassium_gt_5_5","op":"truthy"}],
 "action":{"type":"create_followup",
   "kind":"physician_alert_hyperkalemia_hold_raasi_mra",
   "due_hours":24,
   "citation":"KDIGO 2021 §3.7.2; FIDELIO-DKD protocol"}}
```

#### HTN-R34 — افت وضعیتی علامت‌دار
```json
{"id":"HTN-R34","phase":"safety","severity":"high","priority":10,
 "conditions":[{"var":"flag.symptomatic_orthostatic_hypotension","op":"truthy"}],
 "action":{"type":"create_followup","kind":"physician_review_deintensification",
   "due_days":7,
   "citation":"ESH 2023 §7.5 (avoid overtreatment in elderly/frail)"}}
```

---

# بخش ۸ — آموزش سبک زندگی (Educate)

| مداخله | عدد دقیق | اثر SBP تقریبی | استناد |
|---|---|---|---|
| رژیم DASH | میوه/سبزیجات/لبنیات کم‌چرب/غلات کامل | **−11 mmHg** | AHA Scientific Statement 2018؛ Filippou CD et al., Adv Nutr 2020 (meta) |
| سدیم | **<2300 mg/روز (~۵ گرم نمک)**؛ ایده‌آل 1500 mg | −5 تا −6 mmHg | ACC/AHA 2017 lifestyle؛ ESH 2023 §6.2 |
| کاهش وزن | ~**1 mmHg به‌ازای هر ۱ kg** کاهش وزن | متغیر | Neter JE et al., Hypertension 2003;42:878–84 (meta) |
| فعالیت هوازی | **90–150 دقیقه/هفته** شدت متوسط | −5 تا −8 mmHg | 2019 ACC/AHA Lifestyle Guideline (Circulation 2019;140:e796) |
| مقاومتی | ۲–۳ جلسه/هفته | −2 تا −4 mmHg | همان |
| الکل | ≤2 واحد/روز مردان، ≤1 زنان | −4 mmHg | ACC/AHA 2017 |
| پتاسیم غذایی | 3.5–5 g/روز **فقط اگر eGFR و K طبیعی** | −4 تا −5 mmHg | ACC/AHA 2017 lifestyle |

### قواعد پیشنهادی بخش ۸

#### HTN-R35 — DASH + سدیم
```json
{"id":"HTN-R35","phase":"routine","severity":"medium","priority":35,
 "conditions":[{"var":"flag.hypertension","op":"truthy"}],
 "action":{"type":"educate","topic":"dash_diet_sodium",
   "params":{"sodium_mg_per_day_max":2300,"ideal_mg_per_day":1500,
     "salt_g_per_day_max":5,"expected_sbp_reduction_mmhg":11},
   "citation":"AHA 2018 DASH advisory; ACC/AHA 2017 lifestyle"}}
```

#### HTN-R36 — وزن/BMI
```json
{"id":"HTN-R36","phase":"routine","severity":"medium","priority":36,
 "conditions":[{"var":"indicator.bmi.latest","op":">=","value":25}],
 "action":{"type":"educate","topic":"weight_loss",
   "params":{"sbp_mmhg_per_kg_lost":1,"target_bmi_lt":25},
   "citation":"Neter 2003 Hypertension;42:878 meta"}}
```

#### HTN-R37 — فعالیت بدنی
```json
{"id":"HTN-R37","phase":"routine","severity":"low","priority":38,
 "conditions":[{"var":"flag.hypertension","op":"truthy"}],
 "action":{"type":"educate","topic":"exercise_prescription",
   "params":{"aerobic_min_per_week":[90,150],"resistance_sessions_per_week":[2,3]},
   "citation":"2019 ACC/AHA Lifestyle Guideline"}}
```

#### HTN-R38 — ترک سیگار و محدودیت الکل
```json
{"id":"HTN-R38","phase":"routine","severity":"medium","priority":37,
 "conditions":[{"var":"flag.smoker_or_alcohol_excess","op":"truthy"}],
 "action":{"type":"educate","topic":"smoking_cessation_alcohol_limits",
   "params":{"alcohol_units_per_day":{"male_max":2,"female_max":1}},
   "citation":"ACC/AHA 2017 lifestyle"}}
```

---

# فهرست جامع قواعد پیشنهادی (Rule Index)

| ID | شرح | فاز | شدت | اولویت | Action |
|---|---|---|---|---|---|
| R01a/b | Stage 2 (≥140 یا ≥90) | routine | high | 10 | classify |
| R02a/b | Stage 1 (130–139/80–89) | routine | medium | 12 | classify |
| R03 | Elevated 120–129/<80 | routine | low | 14 | educate |
| R04 | Normal <120/<80 | routine | low | 99 | classify |
| R05a/b | SBP≥180 / DBP≥110 دروازهٔ red-flag | redflag | critical | 1 | create_followup(24h) |
| R06 | هدف عمومی <130/80 | routine | medium | 20 | set_target |
| R07 | هدف دیابت <130/80 | routine | high | 18 | set_target |
| R08 | هدف CKD SBP<120 | routine | high | 16 | set_target |
| R09 | سالمند ≥65 پله‌ای 140→130 | routine | medium | 17 | set_target |
| R10 | شکننده → چک افت وضعیتی قبل از تشدید | safety | high | 8 | create_followup |
| R11 | شروع مونوتراپی انالاپریل 5→40 | routine | high | 22 | suggest_med |
| R12 | تیتراسیون داروی زیر max | routine | medium | 24 | suggest_med |
| R13 | CCB جایگزین سرفهٔ ACEi (آملودیپین 5→10) | routine | medium | 23 | suggest_med |
| R14 | تیازیدمانند دوم/سوم (اینداپامید SR 1.5) | routine | medium | 26 | suggest_med |
| R15 | eGFR<30 → loop جایگزین تیازید | safety | high | 15 | suggest_med |
| R16a/b | Grade 2 → SPC دو دارویی ACEi+CCB | routine | high | 21 | suggest_med |
| R17 | ممنوعیت ACEi+ARB همزمان | safety | critical | 5 | create_followup(alert) |
| R18 | مقاوم → اسپیرونولاکتون 25→50 | routine | high | 19 | suggest_med |
| R19 | چک K هفتهٔ ۱ و ۴ پس از MRA | safety | critical | 6 | schedule_screening |
| R20 | مقاوم واقعی → ارجاع HTN ثانویه | routine | high | 13 | create_followup |
| R21 | دیابت → ACEi/ARB | routine | high | 14 | suggest_med |
| R22 | UACR≥300 → RASi حداکثر دوز | routine | high | 11 | suggest_med |
| R23 | T2D-CKD → فینرنون 10→20 | routine | medium | 27 | suggest_med |
| R24 | ASCVD → لینک استاتین/آسپیرین | routine | high | 12 | educate |
| R25 | واکسن آنفلوانزا سالانه | routine | low | 60 | vaccine |
| R26 | آزمایش پایه قبل از RASi | safety | high | 9 | schedule_screening |
| R27 | K/Cr در ۲–۴ هفته پس از تغییر RASi | safety | critical | 7 | schedule_screening |
| R28 | UACR سالانه دیابت | routine | medium | 30 | schedule_screening |
| R29 | پنل سالانهٔ HTN | routine | low | 40 | schedule_screening |
| R30 | پروتکل HBPM ۷روزه | routine | low | 45 | educate |
| R31a/b/c | اورژانس: ≥180/120 + علامت اندام → ED | redflag | critical | 2 | create_followup(now) |
| R32a/b | فوریت بدون علامت ≥180/110–120 → ۲۴–۷۲h | redflag | high | 3 | create_followup |
| R33 | K>5.5 → وقفهٔ RASi/MRA + هشدار پزشک | safety | critical | 4 | create_followup(alert) |
| R34 | افت وضعیتی علامت‌دار → بازبینی کاهش درمان | safety | high | 10 | create_followup |
| R35 | DASH + سدیم <2300 mg/d | routine | medium | 35 | educate |
| R36 | BMI≥25 → کاهش وزن ~1 mmHg/kg | routine | medium | 36 | educate |
| R37 | هوازی 90–150 min/wk + مقاومتی 2–3× | routine | low | 38 | educate |
| R38 | ترک سیگار/الکل ≤2/≤1 واحد | routine | medium | 37 | educate |

**مجموع: 38 قاعده (با شاخه‌های a/b/c = 51 گرهٔ اجرایی)** — در محدودهٔ هدف 25–40.

---

# شکاف‌های باز (Open Gaps)

1. **FLOW trial (NEJM 2024)** — عدد دقیق صفحه/DOI و HR نهایی تأیید نشد (جست‌وجوی PubMed خطا داد). قبل از انتشار، فقط FIDELIO-DKD (PMID 33264825) را استناد کن.
2. **فیلدهای fact snapshot ناموجود:** `flag.end_organ_symptom`، `flag.frail_or_orthostatic`، `flag.resistant_htn_*`، `flag.rasi_started_or_titrated_within_4w`، `flag.potassium_gt_5_5` — DSL فعلی فقط indicator/med.class/age دارد. یا پرچم‌ها را به snapshot اضافه کن یا این قواعد تا FO-7+ معلق بمانند.
3. **گرانولاریتی دوز:** `med.class` فقط has/not_has است؛ قواعد تیتراسیون (R11/R12/R18) به «دوز فعلی و max» نیاز دارند — نیاز به `med.dose_mg` و `med.at_max_dose` در snapshot.
4. **واحد UACR:** mg/g در برابر mg/mmol باید نرمال‌سازی شود (آستانه‌های این دوزیه همه mg/g هستند؛ A2=30–299، A3=≥300).
5. **eGFR فرمول:** CKD-EPI 2009 یا 2021؟ آستانه‌های دارویی مستقل از نسخه‌اند اما ثبت فرمول لازم است.
6. **HTN ثانویه:** غربالگری آلدوسترون/رنین، OSA، فئوکروموسیتوم با DSL فعلی مدل نمی‌شود — فقط ارجاع create_followup.
7. **بارداری:** صریحاً خارج از دامنه؛ قاعدهٔ fail-closed جداگانه لازم است (`flag.pregnant` → هیچ suggest_med).
8. **در دسترس بودن ژنریک ایران:** کلرتالیدون و فینرنون ممکن است رایج نباشند — جایگزین عملی ذکر شده ولی تصمیم با پزشک.
9. **ABPM/HBPM به‌عنوان داده:** آستانه‌های out-of-office (بخش ۱.۲) به کلیدهای جداگانه (`hbpm_systolic_avg` و…) نیاز دارند.
10. **استاتین:** کلاس `statin` در enum کلاس‌های دارویی نیست؛ R24 فقط educate است نه suggest_med.
11. **شماره بخش‌های ESH 2023:** بر اساس ساختار متن کامل است؛ قبل از production یک بار با PDF رسمی چک شود (scrape مستقیم به‌علت antibot انجام نشد).
12. **تعامل با governance FO-6:** این قواعد فقط «پیشنهاد به پزشک» تولید می‌کنند؛ هیچ مسیر auto-send ندارند و باید در allowlist CARE با policy MANUAL_APPROVAL قرار گیرند.

---

# منابع اصلی (Primary References)

1. Whelton PK, et al. 2017 ACC/AHA Guideline. Hypertension 2018;71:e13–e115 / JACC 2018;71:e127–e248.
2. Mancia G, et al. 2023 ESH Guidelines. J Hypertens 2023;41(12):1874–2071.
3. KDIGO 2021 BP in CKD Guideline. Kidney Int 2021;99(3S):S1–S87.
4. ADA Standards of Care 2025, Section 10. Diabetes Care 2025;48(Suppl 1).
5. Williams B, et al. PATHWAY-2. Lancet 2015;386:2059–68. PMID 26414968.
6. Bakris GL, et al. FIDELIO-DKD. NEJM 2020;383:2219–29. PMID 33264825.
7. Agarwal R, et al. FLOW. NEJM 2024 (finerenone kidney outcomes — عدد دقیق در gap #1).
8. Jamerson K, et al. ACCOMPLISH. NEJM 2008;359:2417–28. PMID 19092151.
9. Yusuf S, et al. ONTARGET. NEJM 2008;358:1547–59. PMID 18378519.
10. SPRINT Research Group. NEJM 2015;373:2103–16. PMID 26551272.
11. Beckett NS, et al. HYVET. NEJM 2008;358:1887–98.
12. Neter JE, et al. Influence of weight reduction on BP: meta-analysis. Hypertension 2003;42:878–84.
13. 2019 ACC/AHA Lifestyle Guideline. Circulation 2019;140:e796–e846.

*پایان دوزیه — نسخهٔ v1.0.0*

