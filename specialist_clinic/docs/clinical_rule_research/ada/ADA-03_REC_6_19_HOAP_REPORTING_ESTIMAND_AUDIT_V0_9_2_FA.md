# ADA-03 — ممیزی Reporting، Estimand و قابلیت انتقال HOAP
## بستهٔ پژوهشی v0.9.2 برای Recommendation 6.19

**پروژه:** Specialist Clinic — Clinical Rule Library Rebuild  
**گایدلاین مادر:** ADA Standards of Care in Diabetes—2026  
**Recommendation جاری:** 6.19  
**شاخهٔ پژوهش:** `research/ada-2026-evidence-v0.2`  
**PR:** Draft PR #60  
**تاریخ:** 2026-08-01  
**ماهیت سند:** ممیزی پژوهشی؛ نه دستور درمان، نه Rule Specification و نه تغییر Runtime

---

## 1. هدف v0.9.2

نسخهٔ v0.9.1 گیت Protocol/SAP عمومی PHT2 را اصلاح کرد. نسخهٔ v0.9.2 روی HOAP متمرکز است و چهار پرسش را به‌صورت مستقل بررسی می‌کند:

1. جمعیت واقعاً randomize‌شده و جمعیت واقعاً تحلیل‌شده چه تفاوتی دارند؟
2. estimand نتیجهٔ «safer regimen» دقیقاً چیست؟
3. سیگنال ED/inpatient تا چه حد patient-important، پایدار و قابل‌انتقال است؟
4. وجود Supplement 1 تا چه حد prespecification را ثابت می‌کند؟

منبع حقیقت workflow اکنون Native Google Sheet v0.9.2 است. نسخهٔ v0.8 حذف یا بازنویسی نشده و lineage در Sheet مستقل `16_Version_History` ثبت شده است.

## 2. سؤال علّی واقعی HOAP

HOAP trial این contrast را آزمود:

`active outreach by one expert clinical pharmacist using HOAP`

در برابر:

`usual care after system-wide passive availability/dissemination of HOAP`

بنابراین trial، «HOAP algorithm در برابر نبود HOAP» را جدا نمی‌کند. اثر مشاهده‌شده می‌تواند حاصل ترکیبی از شناسایی proactive افراد پرخطر، بازبینی پرونده توسط pharmacist متخصص، مشارکت تیم درمان، تماس‌های تکرارشونده، individualized target setting، medication optimization، education، CGM/glucagon، referral و زیرساخت integrated باشد.

پس trial برای **workflow فعال و متخصص‌محور** مستقیم‌تر از اعتبار clause-by-clause الگوریتم داخلی است.

## 3. جمعیت randomize‌شده در برابر جمعیت تحلیل‌شده

مقاله 200 فرد را randomize‌شده گزارش می‌کند، اما پس از تخصیص 9 فرد حذف شدند:

- intervention: چهار نفر؛
- usual care: پنج نفر؛
- cohort تحلیل‌شده: 191 نفر، شامل 96 intervention و 95 usual care.

مقاله این 191 نفر را ITT cohort می‌نامد. با این حال، تا زمانی که Supplement 1 و handling از پیش تعیین‌شدهٔ ineligibility پس از randomization ممیزی نشود، تعبیر محافظه‌کارانهٔ پروژه این است:

`post-randomization-exclusion / modified-ITT population — provisional`

این یافته اثبات نمی‌کند حذف‌ها outcome-driven بوده‌اند؛ فقط اجازه نمی‌دهد عبارت strict all-randomized ITT بدون قید پذیرفته شود.

**Conflict:** `CONFLICT-ADA-S06-030`

## 4. تعارض chronology تخصیص، شروع trial و baseline

مقاله می‌گوید cohort در 2023-06-01 randomly selected و assigned شد. در عین حال:

- ClinicalTrials.gov: study start = 2023-07-20؛
- مقاله: trial conducted from 2023-07-20؛
- CONSORT footnote: baseline = 2023-07-23.

این اختلاف زمانی الزاماً خطا یا تخلف نیست؛ ممکن است assignment، eligibility refresh، operational start و baseline تعاریف متفاوتی داشته باشند. اما بدون dated Protocol/SAP نمی‌توان chronology را قطعی بازسازی کرد.

**Conflict:** `CONFLICT-ADA-S06-031`

## 5. primary outcome و مسئلهٔ estimand

Primary outcome در شش ماه عبارت بود از تجویز regimen کم‌خطرتر، تعریف‌شده با discontinuation یکی یا چند مورد زیر:

- sulfonylurea؛
- bolus/mealtime insulin؛
- mixed insulin.

نتیجهٔ full cohort:

- intervention: 27/96 = 28.1%؛
- usual care: 15/95 = 15.8%؛
- RD = 12.3 percentage points؛ 95% CI: 0.6 تا 24.0.

اما در baseline، فقط 141 نفر از 191 نفر یکی از داروهای هدف را دریافت می‌کردند؛ یعنی 50 نفر از ابتدا در state تعریف‌شدهٔ «safer regimen» قرار داشتند یا opportunity مستقیم برای discontinuation تعریف‌شده نداشتند. مقاله restricted target-drug subset را نیز گزارش می‌کند و effect آن بزرگ‌تر است.

این موضوع دو سؤال ایجاد می‌کند:

- estimand اصلی full cohort بوده یا افراد دارای opportunity واقعی برای discontinuation؟
- restricted subset prespecified بوده یا تحلیل تکمیلی/انتخابی؟

تا ممیزی SAP، هیچ‌یک از دو estimate به medication Rule تبدیل نمی‌شود. Full-cohort result یک process contrast است و subset نتیجهٔ بزرگ‌تری دارد، اما انتخاب آن بدون prespecification audit مجاز نیست.

**Conflict:** `CONFLICT-ADA-S06-032`

## 6. محدودیت construct «safer regimen»

EHR discontinuation order نسبتاً objective است، اما dose reduction، adherence یا مصرف واقعی، علت ادامه یا قطع دارو، indicationهای هم‌زمان، جایگزینی دارویی، hyperglycemia علامت‌دار و net clinical benefit را کامل اندازه‌گیری نمی‌کند.

خود مقاله گزارش می‌کند که uniform deprescribing برای همه ممکن نبود و تصمیم به comorbidity، هدف درمان، ترجیح بیمار، readiness و shared decision-making وابسته بود.

نتیجهٔ مجاز:

> proactive pharmacist-led team review می‌تواند process تجویز را در یک integrated system تغییر دهد.

نتیجهٔ غیرمجاز:

> هر فرد flagged باید یک داروی مشخص را قطع کند.

## 7. سیگنال ED/inpatient و patient-important outcome

در شش ماه:

- intervention: صفر رخداد ED/IP؛
- usual care: پنج رخداد؛
- RD = -5.3 percentage points؛ 95% CI: -11.8 تا -1.3.

با وجود اهمیت بالینی ظاهری، این endpoint:

- secondary بود؛
- فقط پنج event داشت؛
- multiplicity handling آن از Supplement 1 ممیزی نشده؛
- در 12 ماه که post hoc بود، دیگر تفاوت آماری روشن نداشت؛
- تنها رویدادهایی را می‌گیرد که به ED یا بستری رسیده‌اند؛
- طبق مقاله، چنین داده‌هایی حدود 5% severe hypoglycemia را پوشش می‌دهند.

در نتیجه، این یافته یک **replication signal** است، نه اثبات prevention پایدار severe hypoglycemia یا اثر یک medication action مشخص.

`EU-6.19-09 = VERY LOW`  
`Rule gate = BLOCKED_REPLICATION_AND_PRECISION`

**Conflict:** `CONFLICT-ADA-S06-033`

## 8. Supplement 1 و prespecification

JAMA و PMC وجود Supplement 1 را به‌عنوان Trial Protocol/SAP نشان می‌دهند، اما binary رسمی در این محیط به‌صورت قابل‌اعتماد بازیابی و page-audit نشد. بنابراین signature/date نسخهٔ اولیه، تاریخ نهایی‌شدن پیش از randomization، amendment history، handling از پیش تعیین‌شدهٔ post-randomization exclusions، primary estimand، restricted subset، multiplicity و 12-month analyses تأیید نشده‌اند.

قاعدهٔ پروژه:

`DOCUMENT LISTED != DOCUMENT AUDITED`

وجود Supplement 1 یک پیشرفت واقعی نسبت به «نبود سند» است، اما prespecification نهایی را ثابت نمی‌کند.

**Conflicts:** `CONFLICT-ADA-S06-025` و `CONFLICT-ADA-S06-034`

## 9. RoB 2 پالایش‌شدهٔ HOAP

### Safer-prescribing process outcome

- D1 Randomization: SOME CONCERNS — post-allocation exclusions، public registration دیرهنگام و chronology باز؛
- D2 Deviations: SOME CONCERNS — open-label، یک pharmacist متخصص، تماس ناقص و intervention چندجزئی؛
- D3 Missing outcome: LOW برای EHR outcome در cohort 191نفره، با جداسازی concern مربوط به exclusions در D1؛
- D4 Measurement: LOW برای order construct، ولی indirect به adherence و net benefit؛
- D5 Selection: SOME CONCERNS — baseline outcome state، restricted subset و multiplicity/SAP hold.

**Overall:** `SOME CONCERNS — PROVISIONAL`

### ED/IP outcome

همهٔ concernهای بالا همراه با sparse events، sensitivity پایین و 12-month post hoc باقی می‌مانند.

**Overall:** `SOME CONCERNS + VERY SERIOUS IMPRECISION — PROVISIONAL`

## 10. GRADE canonical

### EU-6.19-08 — safer-prescribing process

- Final: **VERY LOW**؛
- Gate: `PROCESS_WORKFLOW_EVIDENCE_ONLY`.

### EU-6.19-09 — ED/IP signal

- Final: **VERY LOW**؛
- Gate: `BLOCKED_REPLICATION_AND_PRECISION`.

### EU-6.19-10 — PHT2

- Final: **VERY LOW — PROVISIONAL / NOT FINAL**؛
- Gate: `FULL_RESULTS_ARTICLE_CONSORT_AND_FINAL_REPORT_PENDING`.

هیچ Evidence Unit به Rule Candidate تبدیل نشد.

## 11. قابلیت انتقال به ایران و مطب تخصصی

HOAP در بستری اجرا شده که integrated EHR و registry، risk-stratification، clinical pharmacist متخصص، physician-approved protocols، repeated outreach، CGM/glucagon/referral و داده‌های utilization را در اختیار داشت.

پیش از هر local workflow باید staffing، medication reconciliation، دسترسی و هزینه، referral/monitoring، language/caregiver needs، reuse rights، local shadow evaluation و independent clinical review جداگانه ارزیابی شوند.

## 12. مرز Runtime و UI

در v0.9.2 هیچ تغییر Runtime، UI یا Rule Registry انجام نشده است. سیستم مجاز نیست:

- sulfonylurea یا insulin را خودکار قطع یا کاهش دهد؛
- restricted-subset effect را به threshold تبدیل کند؛
- HOAP internal algorithm را بازسازی یا encode کند؛
- ED/IP signal را اثبات severe-hypoglycemia prevention بداند؛
- target قند، CGM یا glucagon را خودکار تجویز کند.

workflow مجاز همچنان:

`verified hypoglycemia event -> clinician-owned review trigger -> collect missing facts -> individualized decision`

## 13. وضعیت منبع حقیقت v0.9.2

- Native Sheet مستقل از v0.8 ساخته شد؛
- Search Log: 39؛
- Open conflicts: 34؛
- Decision records: 66؛
- Rule candidates: 0؛
- Accepted Rules: 0؛
- Runtime changes: 0؛
- Licensing: HOLD؛
- Clinical activation: BLOCKED.

Native Sheet:
https://docs.google.com/spreadsheets/d/1p-ugp_yQ3pVqbSN1I-IwremZ4P65sSEi3AtReFeyVbc/edit

Parent v0.8 preserved:
https://docs.google.com/spreadsheets/d/1E99uz5cBc1vENqMMi6r25Sb2ZkeGCQf3MhJz0dZU90w/edit

## 14. منابع رسمی

- HOAP trial article: https://jamanetwork.com/journals/jamanetworkopen/fullarticle/2845169
- HOAP registry: https://clinicaltrials.gov/study/NCT06746714
- PHT2 registry: https://clinicaltrials.gov/study/NCT04863872
- PHT2 Protocol/SAP: https://cdn.clinicaltrials.gov/large-docs/72/NCT04863872/Prot_SAP_000.pdf
- PHT2 results: https://www.pcori.org/research-results/2020/comparing-two-approaches-preventing-dangerously-low-blood-sugar-adults-type-2-diabetes-pht2-study

## 15. نتیجهٔ نهایی

v0.9.2 شواهد HOAP را رد نمی‌کند؛ نقش درست آن را محدود و دقیق می‌کند:

- شواهد قابل‌استفاده: workflow فعال، team-based و clinician-owned؛
- شواهد غیرکافی: الگوریتم portable، threshold دارویی، automatic action و اثبات patient-outcome پایدار.

وضعیت حاکم:

- `Rule candidates = 0`
- `Accepted Rules = 0`
- `Licensing = HOLD`
- `Runtime changes = 0`
- `Clinical activation = BLOCKED`
