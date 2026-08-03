# ADA-03 — ارزیابی کارآزمایی HOAP / Hypoglycemia Champion

**مقاله:** Gilliam et al., JAMA Network Open, 2026  
**DOI:** 10.1001/jamanetworkopen.2025.59946  
**Registry:** NCT06746714  
**وضعیت متن کامل مقاله:** کامل و CC-BY  
**وضعیت Supplement 1:** وجود Protocol/SAP تأیید شده؛ binary، تاریخ و version chronology هنوز ممیزی نشده‌اند

## طراحی و estimand واقعی

کارآزمایی open-label در Kaiser Permanente Northern California:

- 200 نفر randomize شدند؛
- 9 نفر پس از allocation حذف شدند؛
- cohort تحلیل‌شده 191 نفر بود: 96 intervention و 95 usual care؛
- intervention توسط یک pharmacist متخصص و به‌صورت multicomponent اجرا شد؛
- comparator، usual care پس از passive/system-wide availability of HOAP بود.

بنابراین contrast واقعی:

`active expert-pharmacist workflow using HOAP`

در برابر:

`usual care with passive HOAP availability`

است؛ نه اعتبار مستقل HOAP algorithm در برابر نبود الگوریتم.

## chronology باز

- مقاله: random selection/assignment در 2023-06-01؛
- registry و متن مقاله: trial start در 2023-07-20؛
- CONSORT footnote: baseline در 2023-07-23؛
- public registry posting پس از primary completion انجام شد.

این chronology بدون خواندن dated Supplement 1 نهایی نمی‌شود.

## Primary process outcome

Safer regimen در شش ماه:

- intervention: 27/96 = 28.1%؛
- control: 15/95 = 15.8%؛
- RD: 12.3 percentage points؛
- 95% CI: 0.6 تا 24.0.

اما 50 نفر از 191 نفر در randomization از قبل شرط primary outcome را داشتند و فقط 141 نفر sulfonylurea، bolus insulin یا mixed insulin دریافت می‌کردند.

در restricted target-drug subset:

- intervention: 27/68 = 40%؛
- control: 15/73 = 21%؛
- RD: 19.2 percentage points؛
- 95% CI: 4.0 تا 33.7.

تا ممیزی SAP مشخص نیست restricted subset همان estimand از پیش تعیین‌شده بوده یا تحلیل تکمیلی. هیچ‌یک از این estimateها به Rule دارویی تبدیل نمی‌شود.

## Acute-care hypoglycemia

در شش ماه:

- intervention: 0؛
- control: 5/95 = 5.3%؛
- RD: -5.3 percentage points؛
- 95% CI: -11.8 تا -1.3.

در 12 ماه که تحلیل post hoc بود:

- intervention: 1/48 = 2.1%؛
- control: 6/95 = 6.3%؛
- RD: -4.2 percentage points؛
- 95% CI: -11.3 تا 1.8.

این سیگنال secondary، sparse، multiplicity-unaudited و در 12 ماه statistically clear نبود. ED/IP data نیز طبق مقاله حدود 5% severe hypoglycemia را ثبت می‌کند.

## Intervention fidelity و transferability

- فقط 73 نفر از 96 نفر intervention یک initial visit کامل کردند؛
- یک pharmacist متخصص intervention را اجرا کرد؛
- تماس‌ها تکرارشونده و individualized بودند؛
- تیم درمان و زیرساخت integrated نقش اساسی داشتند؛
- comparator نیز passive HOAP access داشت.

بنابراین effect را نمی‌توان به یک clause یا threshold داخلی HOAP نسبت داد.

## RoB 2 پالایش‌شده

### Safer-regimen process outcome

Overall: **SOME CONCERNS — PROVISIONAL**

علل اصلی:

- post-randomization exclusions و نامشخص‌بودن handling از پیش تعیین‌شده؛
- public registration پس از primary completion؛
- assignment/start/baseline chronology باز؛
- open-label و intervention چندجزئی؛
- baseline outcome state برای 50/191؛
- restricted subset prespecification و multiplicity ممیزی‌نشده؛
- construct محدود EHR discontinuation order.

### ED/IP result

Overall: **SOME CONCERNS + VERY SERIOUS IMPRECISION — PROVISIONAL**

علل:

- secondary و rare؛
- فقط پنج event در شش ماه؛
- sensitivity پایین ED/IP برای تمام severe events؛
- 12-month analysis post hoc و غیرمعنی‌دار؛
- multiplicity ممیزی‌نشده.

## GRADE canonical

- `EU-6.19-08` safer-prescribing process: `VERY LOW`؛ Gate = `PROCESS_WORKFLOW_EVIDENCE_ONLY`.
- `EU-6.19-09` ED/IP signal: `VERY LOW`؛ Gate = `BLOCKED_REPLICATION_AND_PRECISION`.

## نتیجهٔ مجاز

این trial از پژوهش و local shadow evaluation یک workflow proactive، pharmacist/clinician-owned و team-based حمایت می‌کند.

## نتیجهٔ غیرمجاز

این trial اجازه نمی‌دهد:

- HOAP algorithm عیناً به Rule Library تبدیل شود؛
- restricted-subset estimate به threshold تبدیل شود؛
- medication discontinuation خودکار شود؛
- ED/IP signal اثبات پایدار severe-hypoglycemia prevention تلقی شود؛
- اثر به درمانگاه ایران بدون local computability، staffing و validation تعمیم داده شود؛
- internal guideline بدون access/method/licensing encode شود.

## Gate

`PROCESS_WORKFLOW_EVIDENCE_ONLY + SUPPLEMENT_VERSION_HOLD + INTERNAL_GUIDELINE_ACCESS_HOLD + LICENSING_HOLD`

- Rule Candidate = 0
- Accepted Rule = 0
- Runtime change = 0
- Clinical activation = BLOCKED
