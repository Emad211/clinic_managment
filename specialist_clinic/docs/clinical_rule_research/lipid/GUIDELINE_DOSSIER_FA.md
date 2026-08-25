# دوزیهٔ پژوهشی قواعد مدیریت لیپید (LIPID) — نسخهٔ قابل تبدیل مکانیکی به JSON

```text
SCOPE = lipid management rules for specialist_clinic clinical engine v2
TARGET_CONVERSION = 15-25 JSON rules (24 sketches provided)
UNITS = mg/dL primary; mmol/L in parentheses
LANGUAGE = fa (Persian output strings)
STATUS = RESEARCH DOSSIER - not a runtime artifact; no FO-6 executor surface touched
DATE = 2026-08-23
```

**منابع حاکم (hierarchy):**

1. **[1]** Mach F, Baigent C, Catapano AL, et al. *2019 ESC/EAS Guidelines for the management of dyslipidaemias.* Eur Heart J. 2020;41(1):111-188. PMID: 31504418. doi:10.1093/eurheartj/ehz455
2. **[2]** Visseren FLJ, Mach F, Smulders YM, et al. *2021 ESC Guidelines on cardiovascular disease prevention in clinical practice.* Eur Heart J. 2021;42(34):3227-3337. PMID: 34458905. doi:10.1093/eurheartj/ehab484
3. **[3]** Grundy SM, Stone NJ, Bailey AL, et al. *2018 AHA/ACC/Multisociety Guideline on the Management of Blood Cholesterol.* Circulation. 2019;139(25):e1082-e1143. doi:10.1161/CIR.0000000000000625
4. **[4]** AACE Dyslipidemia Guideline Task Force. *AACE Clinical Practice Guideline: Pharmacologic Management of Adults with Dyslipidemia.* Endocr Pract. 2025 (انتشار آنلاین دسامبر ۲۰۲۴). Article ID: S1530-891X(24)00691-8 — https://www.endocrinepractice.org/article/S1530-891X(24)00691-8/fulltext
5. **[5]** KDIGO Lipid Work Group. *KDIGO Clinical Practice Guideline for Lipid Management in Chronic Kidney Disease.* Kidney Int Suppl. 2013;3(3):259-305.
6. **[6]** Tonelli M, Wanner C. *Lipid management in CKD: synopsis of the KDIGO 2013 guideline.* Ann Intern Med. 2014;160(3):182. PMID: 24323134. doi:10.7326/M13-2453
7. **[7]** Wanner C, Tonelli M. *KDIGO Lipid Guideline: summary of recommendation statements.* Kidney Int. 2014;85(6):1303-1309. PMID: 24552851. doi:10.1038/ki.2014.31
8. **[8]** Cannon CP, Blazing MA, Giugliano RP, et al. *Ezetimibe Added to Statin Therapy after Acute Coronary Syndromes (IMPROVE-IT).* N Engl J Med. 2015;372(25):2387-2397. PMID: 26039521. doi:10.1056/NEJMoa1410489
9. **[9]** Bhatt DL, Steg PG, Miller M, et al. *Cardiovascular Risk Reduction with Icosapent Ethyl for Hypertriglyceridemia (REDUCE-IT).* N Engl J Med. 2019;380(1):11-22. PMID: 30415628. doi:10.1056/NEJMoa1812792
10. **[10]** Nissen SE, Lincoff AM, Brennan D, et al. *Bempedoic Acid and Cardiovascular Outcomes in Statin-Intolerant Patients (CLEAR Outcomes).* N Engl J Med. 2023;388(15):1353-1364. PMID: 36876740. doi:10.1056/NEJMoa2215024
11. **[11]** Nissen SE, Menon V, Nicholls SJ, et al. *Bempedoic Acid for Primary Prevention of CV Events in Statin-Intolerant Patients.* JAMA. 2023;330(2):131-140. PMID: 37354546. doi:10.1001/jama.2023.9696
12. **[12]** ADA Professional Practice Committee. *Standards of Care in Diabetes—2025.* Diabetes Care. 2025;48(Suppl 1). PMID: 39651989 (بخش ۱۰: مدیریت ریسک قلبی‌عروقی)
13. **[13]** FDA Drug Safety Communication (June 2011): *Simvastatin dose limits with interacting drugs* (سقف دوز سیمواستاتین با داروهای تداخل‌دار).
14. **[14]** Blumenthal RS, Morris PB, Gaudino M, et al. *2026 ACC/AHA/AACVPR Guideline on the Management of Dyslipidemia* (جایگزین راهنمای ۲۰۱۸). JACC. 2026;87(19):2624-2757. PMID: 41824590. doi:10.1016/j.jacc.2025.11.016
15. **[15]** KDIGO CKD Work Group. *KDIGO 2024 Clinical Practice Guideline for the Evaluation and Management of CKD.* Kidney Int. 2024;105(4S):S117-S314. PMID: 38490803. doi:10.1016/j.kint.2023.10.018

> ⚠️ **یادداشت نسخه:** راهنمای ۲۰۲۶ ACC/AHA [14] راهنمای ۲۰۱۸ را رسماً بازنشسته کرده است؛ اعداد این دوزیه بر ESC/EAS 2019 + ACC/AHA 2018 + AACE 2025 + KDIGO استوارند و بازبینی تطبیقی با [14] در «شکاف‌های باز» ثبت شده است.

---

## ۰) قراردادهای تبدیل به قاعده (DSL Contract)

### ۰.۱ اتم‌های مجاز trigger (طبق DSL فعلی)

| اتم | شکل | مثال |
|---|---|---|
| شرط بیماری | `condition(has)` | `{"condition": "diabetes", "op": "has"}` |
| شاخص آزمایشگاهی | `indicator.<key>.latest(op, val)` | `{"indicator": "ldl", "latest": ">=", "value": 55}` |
| فلگ ریسک | `flag.<key>(truthy/in)` | `{"flag": "ascvd", "op": "truthy"}` |
| کلاس دارو | `med.class(has/not_has)` | `{"med_class": "statin", "op": "not_has"}` |

کلیدهای indicator مجاز: `ldl, trig, hdl, hba1c, bp_systolic, bp_diastolic, egfr`
کلیدهای flag مجاز: `ascvd, cvd_high_risk, hf, ckd_stage_g, ckd_stage_a, masld` (+ `diabetes` از طریق condition)

### ۰.۲ اکشن‌ها، فازها، شدت، اولویت

| فیلد | مقادیر | معنا |
|---|---|---|
| `action` | `classify / set_target / suggest_med / schedule_screening / create_followup / educate` | طبق DSL |
| `phase` | `redflag / safety / routine` | redflag=نیاز توجه فوری پزشک؛ safety=ایمنی دارو/آزمایش؛ routine=مدیریت استاندارد |
| `severity` | `critical / high / medium / low` | critical=خطر پانکراتیت یا تداخل خطرناک دارویی |
| `priority` | `1..5` | ۱=بالاترین |

**قاعدهٔ fail-closed:** هر قاعده‌ای که دادهٔ ورودی‌اش نامعلوم یا قدیمی باشد اجرا نمی‌شود (مطابق حاکمیت FO-6). هر `ext_*` در trigger یعنی «نیازمند توسعهٔ DSL» و تا پیاده‌سازی، rule غیرفعال است.

---

## ۱) طبقه‌بندی ریسک و اهداف LDL-C

### ۱.۱ جدول اهداف ESC/EAS 2019 [1]

| طبقهٔ ریسک | هدف LDL-C | کاهش ≥۵۰٪ از baseline | تعریف خلاصه |
|---|---|---|---|
| **very-high** | **<55 mg/dL (<1.4 mmol/L)** | ✅ الزامی | ASCVD مستند، آسیب اندام هدف با DM/CKD G3-G5، FH با ASCVD یا با عامل خطر بزرگ |
| **high** | **<70 mg/dL (<1.8 mmol/L)** | ✅ الزامی | یک عامل خطر بزرگ (TC≥310 mg/dL، HTN grade 3)، DM نوع ۱ با آسیب اندام، CKD G3-G5 بدون آسیب اندام، DM نوع ۲ با آسیب اندام/طولانی/≥۳ عامل خطر، SCORE ≥10% |
| **moderate** | **<100 mg/dL (<2.6 mmol/L)** | ❌ | SCORE 5-10%، DM نوع ۲ بدون آسیب اندام/بدون عامل خطر بزرگ، CKD G1-G2 |
| **low** | **<116 mg/dL (<3.0 mmol/L)** | ❌ | SCORE <5% |

> 🔧 **اصلاح نگاشت ورودی:** در صورت‌کار اولیه نوشته شده بود «low/moderate <116 mg/dL (2.6)». صحیحِ راهنمای [1]: **116 mg/dL = 3.0 mmol/L (ریسک low)** و **100 mg/dL = 2.6 mmol/L (ریسک moderate)**. جدول بالا مرجع نهایی است.

ESC 2021 Prevention [2] همین اهداف را حفظ و برای دیابت، CKD و risk enhancers جزئیات بیشتری می‌دهد.

### ۱.۲ نگاشت به فلگ‌های اپ ما

| فلگ/شرط ما | طبقهٔ ریسک | هدف LDL |
|---|---|---|
| `flag.ascvd = truthy` | very-high | <55 (1.4) + ≥50% کاهش |
| `flag.cvd_high_risk = truthy` **یا** (`diabetes` ∧ سن ≥40) | high | <70 (1.8) + ≥50% کاهش |
| دیابت سن <40 با عامل خطر افزاینده، MASLD با سندرم متابولیک، CKD G1-G2 | moderate | <100 (2.6) |
| سایر | low | <116 (3.0) |

### ۱.۳ قواعد پیشنهادی

#### LIPID_R01 — هدف LDL برای ASCVD (very-high)
- توصیه: هر بیمار با ASCVD مستند باید LDL-C <55 mg/dL (1.4) **و** کاهش ≥۵۰٪ نسبت به baseline داشته باشد.
- اعداد: 55 mg/dL / 1.4 mmol/L / pct_reduction_min=50
- استناد: [1] جدول اهداف؛ [2]
- ⚠️ ارزیابی «کاهش ≥50%» نیازمند baseline LDL است که در DSL فعلی (`indicator.latest`) قابل بیان نیست → شکاف G1.

```json
{
  "id": "LIPID_R01",
  "phase": "routine",
  "severity": "high",
  "priority": 1,
  "trigger": { "all": [ { "flag": "ascvd", "op": "truthy" } ] },
  "action": "set_target",
  "params": { "ldl_mgdl_max": 55, "ldl_mmoll_max": 1.4, "pct_reduction_min": 50 },
  "citation": "[1] ESC/EAS 2019"
}
```

#### LIPID_R02 — هدف LDL برای ریسک بالا (cvd_high_risk یا دیابت ≥40 سال)
- توصیه: LDL-C <70 mg/dL (1.8) و کاهش ≥۵۰٪.
- استناد: [1]؛ [2]
- ⚠️ اتم سن در DSL فعلی نیست → شکاف G2.

```json
{
  "id": "LIPID_R02",
  "phase": "routine",
  "severity": "high",
  "priority": 1,
  "trigger": {
    "any": [
      { "flag": "cvd_high_risk", "op": "truthy" },
      { "all": [
        { "condition": "diabetes", "op": "has" },
        { "ext_patient_attr": { "age_gte": 40 }, "note": "G2: نیاز به اتم سن در DSL" }
      ]}
    ]
  },
  "action": "set_target",
  "params": { "ldl_mgdl_max": 70, "ldl_mmoll_max": 1.8, "pct_reduction_min": 50 },
  "citation": "[1] ESC/EAS 2019; [2] ESC 2021"
}
```

#### LIPID_R03 — هدف LDL برای ریسک متوسط
- توصیه: LDL-C <100 mg/dL (2.6).
- استناد: [1]

```json
{
  "id": "LIPID_R03",
  "phase": "routine",
  "severity": "medium",
  "priority": 2,
  "trigger": {
    "note": "دیابت بدون ASCVD - first-match-wins پس از R01/R02"
  },
  "action": "set_target",
  "params": { "ldl_mgdl_max": 100, "ldl_mmoll_max": 2.6 },
  "citation": "[1] ESC/EAS 2019"
}
```

> نکتهٔ پیاده‌سازی: ترتیب ارزیابی R01→R02→R03→R04 باید first-match-wins باشد تا نیازی به NOT نباشد (DSL فعلی op منفی برای condition ندارد).

#### LIPID_R04 — هدف LDL برای ریسک پایین + آموزش سبک زندگی
- توصیه: LDL-C <116 mg/dL (3.0)؛ مداخلهٔ lifestyle خط اول.
- استناد: [1]؛ [2]

```json
{
  "id": "LIPID_R04",
  "phase": "routine",
  "severity": "low",
  "priority": 4,
  "trigger": {
    "note": "fallback نهایی پس از R01-R03 (first-match-wins)"
  },
  "action": "educate",
  "params": { "topic_fa": "تغذیهٔ سالم، فعالیت بدنی منظم، ترک سیگار", "target_ldl_mgdl": 116 },
  "citation": "[1]; [2]"
}
```

---

## ۲) شدت استاتین و دوزهای دقیق

### ۲.۱ جدول شدت‌ها (ACC/AHA 2018 [3] Table 5؛ سازگار با ESC/EAS 2019 [1])

| شدت | کاهش LDL مورد انتظار | دارو و دوز دقیق (mg/day) |
|---|---|---|
| **High-intensity** | ≥50% | **آتورواستاتین 40-80** · **روزوواستاتین 20-40** |
| **Moderate-intensity** | 30-49% | **آتورواستاتین 10-20** · **روزوواستاتین 5-10** · **سیمواستاتین 20-40** · پراواستاتین 40-80 · فلوواستاتین XL 80 (یا 40 دو بار در روز) · پیتاواستاتین 2-4 · لوواستاتین 40 |
| **Low-intensity** | <30% | سیمواستاتین 10 · پراواستاتین 10-20 · روزوواستاتین 5 · فلوواستاتین 20-40 · لوواستاتین 20 |

⛔ **سیمواستاتین 80 mg:** شروع یا افزایش به این دوز ممنوع (خطر میوپاتی) — FDA 2011 [13].

### ۲.۲ انتخاب شدت بر اساس طبقهٔ ریسک

| طبقه | شدت اولیه | استناد |
|---|---|---|
| very-high (ASCVD) | High-intensity؛ اگر LDL هنوز بالای هدف روی max tolerated → افزودن ezetimibe | [1] Class I؛ [3] |
| high (cvd_high_risk / DM≥40 با RF) | High-intensity | [1]؛ [12] |
| T2D سن 40-75 بدون RF افزاینده | Moderate-intensity (پیش‌فرض) | [12] ADA SoC |
| moderate | Moderate-intensity پس از شکست lifestyle (۳ ماه) | [1]؛ [4] |
| CKD ≥50 سال eGFR<60 | استاتین (یا استاتین+ezetimibe دوز ثابت) | [5][6][7] |

### ۲.۳ قواعد پیشنهادی

#### LIPID_R05 — استاتین پرشدت برای ASCVD
```json
{
  "id": "LIPID_R05",
  "phase": "routine",
  "severity": "high",
  "priority": 1,
  "trigger": { "all": [ { "flag": "ascvd", "op": "truthy" }, { "med_class": "statin", "op": "not_has" } ] },
  "action": "suggest_med",
  "params": {
    "drug_class": "statin",
    "intensity": "high",
    "options_mg_day": [ { "drug": "atorvastatin", "range": [40, 80] }, { "drug": "rosuvastatin", "range": [20, 40] } ],
    "note_fa": "حداکثر دوز قابل تحمل؛ تصمیم نهایی با پزشک"
  },
  "citation": "[1] ESC/EAS 2019 Class I; [3] ACC/AHA 2018"
}
```

#### LIPID_R06 — استاتین پرشدت برای ریسک بالا
```json
{
  "id": "LIPID_R06",
  "phase": "routine",
  "severity": "high",
  "priority": 1,
  "trigger": { "flag": "cvd_high_risk", "op": "truthy" },
  "action": "suggest_med",
  "params": {
    "drug_class": "statin",
    "intensity": "high",
    "options_mg_day": [ { "drug": "atorvastatin", "range": [40, 80] }, { "drug": "rosuvastatin", "range": [20, 40] } ]
  },
  "citation": "[1]; [12]"
}
```

#### LIPID_R07 — استاتین متوسط پیش‌فرض برای T2D سن 40-75
```json
{
  "id": "LIPID_R07",
  "phase": "routine",
  "severity": "medium",
  "priority": 2,
  "trigger": {
    "all": [
      { "condition": "diabetes", "op": "has" },
      { "ext_patient_attr": { "age_between": [40, 75] }, "note": "G2" },
      { "med_class": "statin", "op": "not_has" }
    ]
  },
  "action": "suggest_med",
  "params": {
    "drug_class": "statin",
    "intensity": "moderate",
    "options_mg_day": [
      { "drug": "atorvastatin", "range": [10, 20] },
      { "drug": "rosuvastatin", "range": [5, 10] },
      { "drug": "simvastatin", "range": [20, 40], "note": "80mg ممنوع [13]" }
    ]
  },
  "citation": "[12] ADA SoC 2025; [3]"
}
```

#### LIPID_R08 — استاتین متوسط برای ریسک متوسط پس از شکست lifestyle
```json
{
  "id": "LIPID_R08",
  "phase": "routine",
  "severity": "medium",
  "priority": 3,
  "trigger": {
    "all": [
      { "indicator": "ldl", "latest": ">=", "value": 100 },
      { "med_class": "statin", "op": "not_has" }
    ],
    "note": "first-match-wins بعد از R01-R04؛ lifestyle 3 ماهه ناموفق"
  },
  "action": "suggest_med",
  "params": {
    "drug_class": "statin",
    "intensity": "moderate",
    "options_mg_day": [ { "drug": "atorvastatin", "range": [10, 20] }, { "drug": "rosuvastatin", "range": [5, 10] }, { "drug": "simvastatin", "range": [20, 40] } ]
  },
  "citation": "[1]; [4] AACE 2025"
}
```

#### LIPID_R09 — استاتین برای CKD (سن ≥50، eGFR<60، غیر دیالیزی)
- توصیهٔ KDIGO 2013 [5][6][7]: بزرگسالان ≥50 سال با eGFR<60 و غیر دیالیزی → استاتین یا استاتین/ezetimibe با دوز ثابت (بدون تیتراسیون بر اساس LDL). دیالیز: شروع جدید توصیه نمی‌شود؛ ادامهٔ درمان موجود بلامانع. KDIGO 2024 [15] چارچوب را تأیید می‌کند.

```json
{
  "id": "LIPID_R09",
  "phase": "routine",
  "severity": "high",
  "priority": 2,
  "trigger": {
    "all": [
      { "indicator": "egfr", "latest": "<", "value": 60 },
      { "flag": "ckd_stage_g", "op": "in", "values": ["G3a", "G3b", "G4", "G5nd"] },
      { "ext_patient_attr": { "age_gte": 50 }, "note": "G2" },
      { "med_class": "statin", "op": "not_has" }
    ]
  },
  "action": "suggest_med",
  "params": {
    "drug_class": "statin",
    "mode": "fixed_dose_no_titration",
    "options_mg_day": [ { "drug": "atorvastatin", "dose": 20 }, { "drug": "rosuvastatin", "dose": 10 } ],
    "combo_option": { "drug": "simvastatin", "dose": 20, "plus_ezetimibe": 10 }
  },
  "citation": "[5] KDIGO 2013; [6]; [7]; [15] KDIGO 2024"
}
```

---

## ۳) تیتراسیون و پایش مجدد

- **ACC/AHA 2018 [3]:** پنل لیپید **۴ تا ۱۲ هفته** پس از شروع یا تغییر دوز استاتین تکرار شود؛ سپس هر ۳–۱۲ ماه.
- **ESC/EAS 2019 [1]:** تکرار لیپید و آنزیم کبدی **8±4 هفته** پس از شروع/تغییر (معادل همان پنجرهٔ ۴–۱۲ هفته)، سپس هر ۶–۱۲ ماه.
- **قبل از هر escalation:** بررسی پایبندی (adherence) الزامی است [1] §treatment adherence؛ عدم پایبندی رایج‌ترین دلیل عدم رسیدن به هدف است.

#### LIPID_R10 — پایش ۴–۱۲ هفته پس از شروع/تغییر استاتین
```json
{
  "id": "LIPID_R10",
  "phase": "routine",
  "severity": "medium",
  "priority": 2,
  "trigger": { "all": [ { "med_class": "statin", "op": "has" }, { "ext_statin_changed_within_weeks": 12, "note": "G5: نیاز به رویداد تغییر دارو" } ] },
  "action": "schedule_screening",
  "params": { "test": "lipid_panel", "window_weeks": [4, 12], "fasting_required": false },
  "citation": "[3] ACC/AHA 2018 (4-12wk); [1] ESC/EAS 2019 (8±4wk)"
}
```

#### LIPID_R11 — عدم رسیدن به هدف روی استاتین فعلی (با تأیید پایبندی)
```json
{
  "id": "LIPID_R11",
  "phase": "routine",
  "severity": "high",
  "priority": 2,
  "trigger": {
    "all": [
      { "med_class": "statin", "op": "has" },
      { "indicator": "ldl", "latest": ">=", "value": 70 },
      { "ext_adherence_confirmed": true, "note": "G6: منبع دادهٔ پایبندی تعریف نشده" }
    ]
  },
  "action": "create_followup",
  "params": {
    "title_fa": "بررسی تیتراسیون استاتین",
    "steps_fa": ["تأیید پایبندی", "افزایش شدت تا max tolerated", "در صورت عدم دستیابی: افزودن ezetimibe"],
    "due_days": 30
  },
  "citation": "[1]; [3]"
}
```

#### LIPID_R12 — پایش سالانه در صورت رسیدن به هدف
```json
{
  "id": "LIPID_R12",
  "phase": "routine",
  "severity": "low",
  "priority": 4,
  "trigger": { "all": [ { "med_class": "statin", "op": "has" }, { "indicator": "ldl", "latest": "<", "value": 70 } ] },
  "action": "create_followup",
  "params": { "title_fa": "پنل لیپید سالانه", "interval_months": 12 },
  "citation": "[3] (every 3-12 months); [1] (6-12 months)"
}
```

---

## ۴) درمان‌های افزودنی (Add-ons)

### ۴.۱ Ezetimibe 10 mg
- وقتی با **حداکثر دوز قابل تحمل استاتین** به هدف نرسید → افزودن ezetimibe 10 mg روزانه (Class I برای very-high/high در ESC/EAS 2019 [1]).
- شواهد: IMPROVE-IT [8] — افزودن ezetimibe به سیمواستاتین 40 پس از ACS، رویدادهای قلبی‌عروقی را کاهش داد (HR 0.936).

#### LIPID_R13 — افزودن ezetimibe
```json
{
  "id": "LIPID_R13",
  "phase": "routine",
  "severity": "high",
  "priority": 2,
  "trigger": {
    "all": [
      { "med_class": "statin", "op": "has" },
      { "med_class": "ezetimibe", "op": "not_has" },
      { "indicator": "ldl", "latest": ">=", "value": 55 },
      { "ext_on_max_tolerated_statin": true, "note": "G4: DSL دوز دارو را نمی‌بیند" }
    ]
  },
  "action": "suggest_med",
  "params": { "drug": "ezetimibe", "dose_mg_day": 10 },
  "citation": "[1] Class I; [8] IMPROVE-IT"
}
```

### ۴.۲ Bempedoic acid
- گزینه برای بیماران **عدم تحمل استاتین**: CLEAR Outcomes [10] — bempedoic acid 180 mg روزانه در بیماران ناتوان از تحمل استاتین، MACE را کاهش داد (HR 0.87). زیرگروه پیشگیری اولیه نیز سود نشان داد [11]. فراهمی محلی محدود → تصمیم پزشک.

#### LIPID_R14 — bempedoic acid در عدم تحمل استاتین
```json
{
  "id": "LIPID_R14",
  "phase": "routine",
  "severity": "medium",
  "priority": 3,
  "trigger": {
    "all": [
      { "flag": "statin_intolerance_documented", "op": "truthy", "note": "فلگ جدید پیشنهادی - G13" },
      { "indicator": "ldl", "latest": ">=", "value": 70 }
    ]
  },
  "action": "suggest_med",
  "params": { "drug": "bempedoic_acid", "dose_mg_day": 180, "decision_owner": "physician", "availability_check_fa": "فراهمی دارو در ایران بررسی شود" },
  "citation": "[10] CLEAR Outcomes; [11]"
}
```

### ۴.۳ تری‌گلیسرید ≥500 mg/dL — فیبرات اول (redflag)
- TG ≥500 mg/dL (5.6 mmol/L) → خطر پانکراتیت حاد؛ **هدف اولیه TG<500** با فیبرات/اصلاح lifestyle، نه استاتین به‌تنهایی [4] AACE 2025؛ [3].
- فیبرات ترجیحی: **فنوفیبرات 145-160 mg روزانه** (gemfibrozil با استاتین تداخل میوپاتی دارد — پرهیز همزمان [3][13]).

#### LIPID_R15 — TG≥500 (redflag)
```json
{
  "id": "LIPID_R15",
  "phase": "redflag",
  "severity": "critical",
  "priority": 1,
  "trigger": { "all": [ { "indicator": "trig", "latest": ">=", "value": 500 } ] },
  "action": "suggest_med",
  "params": {
    "drug": "fenofibrate",
    "dose_mg_day": [145, 160],
    "goal_fa": "کاهش سریع TG به زیر 500 برای پیشگیری از پانکراتیت",
    "escalate_fa": "ارجاع فوری به پزشک؛ بررسی علل ثانویه (دیابت کنترل‌نشده، الکل، هیپوتیروئیدی، داروها)"
  },
  "citation": "[4] AACE 2025; [3] ACC/AHA 2018"
}
```

### ۴.۴ TG 200-499 با ASCVD — Icosapent ethyl (اختیاری)
- REDUCE-IT [9]: icosapent ethyl 2 g دو بار در روز (مجموع 4 g/day) در بیماران ASCVD (یا DM با RF) با TG 200-499 تحت درمان استاتین → کاهش ۲۵٪ رویدادهای ایسکمیک (HR 0.75).
- فقط فراوردهٔ EPA خالص؛ ترکیبات omega-3 عمومی جایگزین نیستند ([3]).

#### LIPID_R16 — icosapent ethyl اختیاری
```json
{
  "id": "LIPID_R16",
  "phase": "routine",
  "severity": "medium",
  "priority": 3,
  "trigger": {
    "all": [
      { "flag": "ascvd", "op": "truthy" },
      { "indicator": "trig", "latest": "between", "values": [200, 499] },
      { "med_class": "statin", "op": "has" }
    ]
  },
  "action": "suggest_med",
  "params": { "drug": "icosapent_ethyl", "dose": "2 g BID (4 g/day)", "optional": true, "decision_owner": "physician", "evidence": "REDUCE-IT HR 0.75" },
  "citation": "[9] REDUCE-IT; [3]"
}
```

> PCSK9 inhibitors (evolocumab FOURIER؛ alirocumab ODYSSEY OUTCOMES) مرحلهٔ سوم ESC/EAS هستند اما خارج از دامنهٔ DSL فعلی و فراهمی محلی → شکاف G8.

---

## ۵) دیابت (Diabetes-specific)

- **ADA Standards of Care 2025 [12] (بخش ۱۰):**
  - T2D سن **40-75** بدون ASCVD → **استاتین متوسط** پیش‌فرض.
  - وجود **عوامل خطر افزاینده** → ارتقا به **پرشدت**: مدت طولانی دیابت (T2D ≥10 سال)، آلبومینوری (ACR ≥30 mg/g)، eGFR <60، رتینوپاتی، نوروپاتی، ABI <0.9، چند عامل خطر دیگر.
  - سن 20-39 با عوامل خطر → استاتین معقول (reasonable).
  - سن >75 → ادامهٔ درمان موجود در صورت تحمل.
- **CKD در دیابت:** KDIGO 2013 [5][6] — دیابتی ≥50 سال با eGFR<60 → استاتین (R09 پوشش می‌دهد).

#### LIPID_R17 — ارزیابی استاتین در T2D سن 20-39 با عامل خطر
```json
{
  "id": "LIPID_R17",
  "phase": "routine",
  "severity": "medium",
  "priority": 3,
  "trigger": {
    "all": [
      { "condition": "diabetes", "op": "has" },
      { "ext_patient_attr": { "age_between": [20, 39] }, "note": "G2" },
      { "ext_any_risk_enhancer": ["diabetes_duration_gte_10y", "acr_gte_30", "retinopathy", "neuropathy"], "note": "G9" },
      { "med_class": "statin", "op": "not_has" }
    ]
  },
  "action": "create_followup",
  "params": { "title_fa": "ارزیابی شروع استاتین در دیابت جوان با عامل خطر", "owner": "physician" },
  "citation": "[12] ADA SoC 2025"
}
```

#### LIPID_R18 — ارتقای شدت در دیابت با CKD/آلبومینوری
```json
{
  "id": "LIPID_R18",
  "phase": "routine",
  "severity": "high",
  "priority": 2,
  "trigger": {
    "all": [
      { "condition": "diabetes", "op": "has" },
      { "any": [ { "indicator": "egfr", "latest": "<", "value": 60 }, { "flag": "ckd_stage_a", "op": "in", "values": ["A2", "A3"] } ] },
      { "med_class": "statin", "op": "has" },
      { "ext_current_intensity_lt_high": true, "note": "G4: شدت فعلی از دوز قابل استخراج نیست" }
    ]
  },
  "action": "suggest_med",
  "params": { "intensity_upgrade_to": "high", "options_mg_day": [ { "drug": "atorvastatin", "range": [40, 80] }, { "drug": "rosuvastatin", "range": [20, 40] } ] },
  "citation": "[12]; [5] KDIGO 2013"
}
```

---

## ۶) ایمنی (Safety)

### ۶.۱ آزمایش پایه و پایش
- **ALT پایه قبل از شروع استاتین** [3]؛ پایش روتین ALT لازم نیست — فقط در صورت علائم (خستگی، بی‌اشتهایی، تهوع، زردی، ادرار تیره).
- **CK فقط در صورت علائم عضلانی** (میالژی، ضعف، ادرار تیره) درخواست شود؛ پایش روتین CK بی‌فایده است [3][1].

### ۶.۲ تداخلات دارویی — سقف دوز سیمواستاتین (FDA 2011 [13])

| داروی همراه | حداکثر سیمواستاتین |
|---|---|
| **آملودیپین** | **20 mg/day** |
| دیلتیازم / وراپامیل / دروندارون | 10 mg/day |
| آمیودارون | 20 mg/day |
| Gemfibrozil | پرهیز همزمان با استاتین (خطر میوپاتی ↑) — فنوفیبرات جایگزین شود [3] |

### ۶.۳ مسیر عدم تحمل استاتین (statin intolerance pathway) [1][3][4]
1. تأیید واقعی بودن علائم (کنار گذاشتن هیپوتیروئیدی، کوفتگی، درد مفصلی) ± CK.
2. کاهش دوز همان استاتین و rechallenge.
3. دوزگذاری یک‌روزدرمیان با روزوواستاتین 5-10 یا آتورواستاتین.
4. تعویض مولکول (pravastatin/rosuvastatin/fluvastatin).
5. افزودن درمان غیراستاتینی (ezetimibe ± bempedoic acid [10]).

### ۶.۴ MASLD و HF
- **MASLD:** استاتین‌ها در NAFLD/MASLD ایمن‌اند و نباید قطع شوند [4].
- **HF:** استاتین برای کاهش مرگ‌ومیر در HF اندیکاسیون ندارد اما در بیمار HF با ASCVD، استاتین برای اندیکاسیون ASCVD ادامه یابد [1][2].

#### LIPID_R19 — ALT پایه قبل از شروع استاتین
```json
{
  "id": "LIPID_R19",
  "phase": "safety",
  "severity": "medium",
  "priority": 2,
  "trigger": { "all": [ { "med_class": "statin", "op": "not_has" }, { "ext_statin_start_planned": true, "note": "G5: رویداد پیشنهاد دارو" } ] },
  "action": "schedule_screening",
  "params": { "test": "alt_baseline", "gate_fa": "شروع استاتین پس از ثبت ALT پایه" },
  "citation": "[3] ACC/AHA 2018"
}
```

#### LIPID_R20 — علائم عضلانی روی استاتین → CK
```json
{
  "id": "LIPID_R20",
  "phase": "safety",
  "severity": "high",
  "priority": 1,
  "trigger": { "all": [ { "med_class": "statin", "op": "has" }, { "ext_symptom_reported": "muscle_pain_weakness_dark_urine", "note": "G10: منبع گزارش علامت تعریف نشده" } ] },
  "action": "schedule_screening",
  "params": { "test": "ck", "action_fa": "در صورت CK>10x ULN یا علائم شدید: قطع موقت استاتین و ارجاع فوری" },
  "citation": "[3]; [1]"
}
```

#### LIPID_R21 — سقف سیمواستاتین با آملودیپین (critical)
```json
{
  "id": "LIPID_R21",
  "phase": "safety",
  "severity": "critical",
  "priority": 1,
  "trigger": {
    "all": [
      { "med_class": "statin", "op": "has" },
      { "ext_active_molecule": "amlodipine", "note": "G11: DSL فقط med.class دارد، مولکول نمی‌بیند" },
      { "ext_simvastatin_dose_gt": 20, "note": "G4" }
    ]
  },
  "action": "create_followup",
  "params": { "title_fa": "تداخل سیمواستاتین/آملودیپین", "fix_fa": "کاهش سیمواستاتین به ≤20 mg یا تعویض به آتورواستاتین/روزوواستاتین", "owner": "physician" },
  "citation": "[13] FDA 2011; [3]"
}
```

#### LIPID_R22 — مسیر گام‌به‌گام عدم تحمل استاتین
```json
{
  "id": "LIPID_R22",
  "phase": "safety",
  "severity": "medium",
  "priority": 2,
  "trigger": { "all": [ { "flag": "statin_intolerance_documented", "op": "truthy", "note": "G13" } ] },
  "action": "create_followup",
  "params": {
    "pathway_fa": ["تأیید علائم و علل ثانویه (TSH، کوفتگی)", "کاهش دوز + rechallenge", "دوز یک‌روزدرمیان روزوواستاتین 5-10", "تعویض مولکول", "افزودن ezetimibe ± bempedoic acid"],
    "owner": "physician"
  },
  "citation": "[1]; [3]; [4]; [10]"
}
```

---

## ۷) غربالگری و دورهٔ پایش (Screening cadence)

- **پنل لیپید ناشتا الزامی نیست** — non-fasting قابل قبول است [3][1][2]؛ در صورت TG غیرناشتا >400 mg/dL، ناشتا تکرار شود.
- تشخیص جدید دیابت/فشار خون/ASCVD یا بیمار جدید → پنل لیپید اولیه.
- on-target → سالانه؛ off-target → طبق برنامهٔ تیتراسیون (R10/R11).

#### LIPID_R23 — پنل لیپید اولیه هنگام تشخیص
```json
{
  "id": "LIPID_R23",
  "phase": "routine",
  "severity": "medium",
  "priority": 2,
  "trigger": {
    "any": [
      { "ext_newly_diagnosed_condition": ["diabetes", "hypertension"], "note": "G12: op جدید" },
      { "flag": "ascvd", "op": "truthy" }
    ]
  },
  "action": "schedule_screening",
  "params": { "test": "lipid_panel_full", "fasting_required": false, "includes": ["ldl", "hdl", "trig", "total_cholesterol"] },
  "citation": "[3]; [1]; [2]"
}
```

#### LIPID_R24 — دورهٔ پایش بر اساس وضعیت هدف
```json
{
  "id": "LIPID_R24",
  "phase": "routine",
  "severity": "low",
  "priority": 4,
  "trigger": { "all": [ { "ext_last_lipid_panel_months_ago": 12, "note": "G5" } ] },
  "action": "schedule_screening",
  "params": { "test": "lipid_panel", "fasting_required": false, "cadence_rule_fa": "on-target: سالانه؛ off-target: طبق R10/R11" },
  "citation": "[3]; [1]"
}
```

---

## ۸) جدول خلاصهٔ ۲۴ قاعده

| ID | Phase | Action | Trigger (خلاصه) | Severity | P | استناد |
|---|---|---|---|---|---|---|
| R01 | routine | set_target | ascvd → LDL<55 + ≥50% | high | 1 | [1] |
| R02 | routine | set_target | cvd_high_risk ∨ (DM∧age≥40) → LDL<70 + ≥50% | high | 1 | [1][2] |
| R03 | routine | set_target | DM بدون ASCVD (متوسط) → LDL<100 | medium | 2 | [1] |
| R04 | routine | educate | ریسک پایین → LDL<116 + lifestyle | low | 4 | [1][2] |
| R05 | routine | suggest_med | ascvd ∧ ¬statin → پرشدت (atva 40-80 / rosuva 20-40) | high | 1 | [1][3] |
| R06 | routine | suggest_med | cvd_high_risk → پرشدت | high | 1 | [1][12] |
| R07 | routine | suggest_med | T2D 40-75 → متوسط (atva 10-20 / rosuva 5-10 / simva 20-40) | medium | 2 | [12][3] |
| R08 | routine | suggest_med | متوسط ∧ LDL≥100 ∧ ¬statin → متوسط | medium | 3 | [1][4] |
| R09 | routine | suggest_med | CKD G3-G5nd ∧ age≥50 ∧ ¬statin → دوز ثابت | high | 2 | [5][6][7][15] |
| R10 | routine | schedule_screening | شروع/تغییر استاتین → لیپید 4-12wk | medium | 2 | [3][1] |
| R11 | routine | create_followup | statin ∧ LDL≥70 ∧ پایبند → تیتراسیون | high | 2 | [1][3] |
| R12 | routine | create_followup | statin ∧ LDL<70 → سالانه | low | 4 | [3][1] |
| R13 | routine | suggest_med | max statin ∧ LDL≥55 ∧ ¬ezetimibe → ezetimibe 10mg | high | 2 | [1][8] |
| R14 | routine | suggest_med | عدم تحمل استاتین ∧ LDL≥70 → bempedoic 180mg | medium | 3 | [10][11] |
| R15 | redflag | suggest_med | trig≥500 → فنوفیبرات 145-160 + ارجاع فوری | critical | 1 | [4][3] |
| R16 | routine | suggest_med | ascvd ∧ trig 200-499 ∧ statin → icosapent ethyl 2g BID (اختیاری) | medium | 3 | [9][3] |
| R17 | routine | create_followup | T2D 20-39 ∧ RF → ارزیابی استاتین | medium | 3 | [12] |
| R18 | routine | suggest_med | DM ∧ (eGFR<60 ∨ A2-A3) → ارتقا به پرشدت | high | 2 | [12][5] |
| R19 | safety | schedule_screening | پیش از شروع استاتین → ALT پایه | medium | 2 | [3] |
| R20 | safety | schedule_screening | statin ∧ علائم عضلانی → CK | high | 1 | [3][1] |
| R21 | safety | create_followup | simva+amlodipine ∧ دوز>20 → اصلاح فوری | critical | 1 | [13][3] |
| R22 | safety | create_followup | عدم تحمل استاتین → مسیر گام‌به‌گام | medium | 2 | [1][3][4][10] |
| R23 | routine | schedule_screening | تشخیص جدید DM/HTN/ASCVD → پنل اولیه non-fasting | medium | 2 | [3][1][2] |
| R24 | routine | schedule_screening | 12 ماه از آخرین پنل → تکرار بر اساس وضعیت هدف | low | 4 | [3][1] |

---

## ۹) شکاف‌های باز (Open Gaps)

| # | شکاف | اثر | پیشنهاد |
|---|---|---|---|
| G1 | **baseline LDL در DSL نیست** (`indicator.latest` فقط آخرین مقدار) | قواعد «کاهش ≥50%» (R01/R02) کامل قابل پیاده‌سازی نیستند | افزودن `indicator.baseline` یا snapshot اولین مقدار ثبت‌شده |
| G2 | **اتم سن/ویژگی بیمار در DSL تعریف نشده** (`condition(has)` فقط بیماری) | R02/R07/R09/R17/R23 به `ext_patient_attr` نیاز دارند | افزودن atom `patient.age(op,val)` |
| G3 | **واحد canonical نامشخص** (mg/dL vs mmol/L) | مقایسهٔ thresholdها شکننده | تعهد به mg/dL در engine + تبدیل در ingest |
| G4 | **`med.class(has)` دوز مولکول را نمی‌بیند** | R13 (max tolerated)، R18 (شدت فعلی)، R21 (سقف simva) قابل ارزیابی نیستند | افزودن `med.molecule_dose` یا فیلد dose در medication record |
| G5 | **رویدادهای زمانی** (شروع/تغییر دارو، تاریخ آخرین پنل) در DSL نیستند | R10/R19/R24 | افزودن `event.within_weeks` |
| G6 | **منبع دادهٔ پایبندی (adherence) تعریف نشده** | R11 gate پایبندی دارد | قرارداد: refill data یا self-report ساختاریافته |
| G7 | **فراهمی ایران**: icosapent ethyl و bempedoic acid در فرمولاری محلی نامطمئن | R14/R16 عملیاتی بودن | بررسی داروخانه‌های مرجع؛ در غیاب، rule فقط educate تولید کند |
| G8 | **PCSK9i** (FOURIER/ODYSSEY) مرحلهٔ سوم ESC/EAS است ولی خارج از DSL و فراهمی | تکمیل مسیر very-high refractory | فاز بعدی |
| G9 | **عوامل خطر افزایندهٔ ADA** (duration، ACR، retinopathy، neuropathy) کلید flag ندارند | R17/R18 دقیق نمی‌شود | افزودن flags یا استخراج از lab/exam records |
| G10 | **ورودی علائم بیمار** (myalgia) در DSL نیست | R20 | اتصال به followup responses یا symptom log |
| G11 | **مولکول فعال** (amlodipine) — منبع medication list باید مولکول‌محور تأیید شود | R21 | بررسی medication model اپ specialist |
| G12 | **op های جدید** (`newly_diagnosed`) در DSL فعلی نیستند | R23 | افزودن یا بازطراحی trigger |
| G13 | **فلگ `statin_intolerance_documented`** جدید است و باید به schema اضافه شود | R14/R22 | additive migration + governance |
| G14 | **AACE 2025**: شماره صفحات/volume دقیق journal هنوز ثبت نشده (صفحهٔ fulltext توسط antibot مسدود شد) | استناد کتاب‌شناختی کامل | تکمیل از PubMed در جلسهٔ بعد |
| G15 | **راهنمای 2026 ACC/AHA [14]** رسماً 2018 را بازنشسته کرده | اعداد ممکن است در بازنگری بعدی تغییر کنند | بازبینی تطبیقی اختصاصی [14] پیش از freeze ruleset |
| G16 | **بارداری/شیردهی**: قاعدهٔ exclusion استاتین در زنان بارور ثبت نشده | ایمنی | قاعدهٔ safety جداگانه در نسخهٔ بعد |
| G17 | **علل ثانویهٔ هایپرلیپیدمی** (TSH) — کلید indicator نداریم | R15/R22 کامل نیست | افزودن tsh به indicator keys |
| G18 | **پیام‌های فارسی educate** (R04/R15) به templateهای SMS governed نیاز دارند | خروجی کاربر-رو | هم‌راستا با محدودیت‌های FO-6 (بدون auto-send؛ فقط manual/CARE) |

---

## ۱۰) یادداشت حاکمیتی

این سند صرفاً **مادهٔ پژوهشی** برای تبدیل مکانیکی به JSON rules است. هیچ تغییری در runtime، schema، feature flag یا مسیرهای FO-6 ایجاد نمی‌کند. هر rule پیش از فعال‌سازی باید از فیلترهای معمول موتور v2 (evaluator، safety kernel، owner review) عبور کند. تمام thresholds با واحد mg/dL ذخیره شوند؛ mmol/L فقط نمایشی است.
