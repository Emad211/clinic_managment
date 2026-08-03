# ADA-03 — ارزیابی PHT2 با Protocol/SAP عمومی

**مقاله:** Ralston et al., 2026  
**DOI:** 10.1007/s11606-026-10491-7  
**Registry:** NCT04863872  
**وضعیت حاکم:** Protocol/SAP استخراج شده؛ متن کامل مقاله، CONSORT denominator و Final PCORI Report همچنان pending

## Corrigendum نسبت به v0.8

فایل عمومی `PHT2 Protocol/SAP Version 7` با تاریخ 2025-04-14 در ClinicalTrials.gov بازیابی شد. بنابراین عبارت قبلی «SAP در دسترس نیست» دیگر معتبر نیست.

گزارش کامل تطبیق در این سند ثبت شده است:

- `ADA-03_REC_6_19_PHT2_PROTOCOL_SAP_RECONCILIATION_V0_9_1_FA.md`
- `ADA_REC_6_19_V0_9_1_WORKBOOK_ROWS.json`
- `ADA_RESEARCH_STATUS_V0_9_1.json`

## جمعیت

بزرگسالان مبتلا به T2D که:

- insulin یا sulfonylurea دریافت می‌کردند؛ و
- severe hypoglycemia در 12 ماه قبل داشتند یا impaired awareness داشتند.

این جمعیت برای Recommendation 6.19 بسیار مرتبط است، اما باز هم تمام factual prerequisites لازم برای یک medication action مستقل را تعیین نمی‌کند.

## مقایسهٔ صحیح

- `PC`: proactive nurse care management
- `PC+`: همان proactive care به‌علاوهٔ psychoeducation

این trial **proactive care را با usual care مقایسه نکرده است**. بنابراین کاهش رخداد در هر دو بازو را نمی‌توان اثر علّی proactive care دانست.

## نتیجهٔ primary

Severe hypoglycemia در 14 ماه:

- PC: 16.1%
- PC+: 11.6%
- aRR: 0.72، 95% CI: 0.39 تا 1.30
- aARD: -4.6 percentage points، 95% CI: -13.0 تا 3.7

افزودن psychoeducation برتری آماری مشخصی برای نتیجهٔ primary نشان نداد. این نتیجه equivalence یا بی‌اثری قطعی را اثبات نمی‌کند.

## تعارض‌های باز جدید

### Completion denominator

Abstract هم‌زمان `92%` و `n=230 of 259` را گزارش می‌کند؛ در حالی که:

`230 / 259 = 88.803%`

اگر denominator برابر 259 باشد، attrition حدود 11.2% است و از trigger ده‌درصدی Protocol عبور می‌کند. اجرای responder/nonresponder comparison، MI یا IPW باید با متن کامل/CONSORT تأیید شود.

### Amendment chronology

- Version 4 پس از first enrollment، cluster randomization را به individual randomization تغییر داد.
- Version 5 حین follow-up، secondary CGM outcomes و missing-data plan را تغییر داد.
- Version 6 پس از study completion، clustering analysis را روشن کرد.

وجود این amendmentها به‌تنهایی bias را ثابت نمی‌کند، ولی D1 و D5 را تا بررسی اجرای نسخه‌دار analysis باز نگه می‌دارد.

### Power and imprecision

Protocol برای power model نرخ 60% رخداد در بازوی PC را فرض کرده بود، در حالی که event frequency واقعی کمتر بود. CI نتیجهٔ primary همچنان گسترده است.

## RoB 2 موقت

`SOME CONCERNS — PROVISIONAL / MAY ESCALATE`

علت‌ها:

- randomization-method chronology هنوز به CONSORT flow نیاز دارد؛
- participants/providers unblinded بودند؛
- completion denominator ناسازگار است؛
- outcome اصلی self-reported 12-month recall بود؛
- اجرای دقیق missing-data methods و multiplicity از اسناد عمومی کامل نشده است.

این ارزیابی outcome-specific، دوپاسی توسط همان ارزیاب و غیرنهایی است.

## GRADE موقت برای Rule Library

برای سؤال «آیا PHT2 یک Rule قابل‌انتقال و actionable برای Recommendation 6.19 ایجاد می‌کند؟»:

`EU-6.19-10 = VERY LOW — PROVISIONAL / NOT FINAL`

علت اصلی: serious provisional RoB، serious indirectness و serious imprecision.

این certainty دربارهٔ portability/actionability در محصول است، نه ارزش علمی خود trial.

## Gate

`PROTOCOL_SAP_EXTRACTED + FULL_RESULTS_ARTICLE_AND_FINAL_REPORT_PENDING + PROVISIONAL_ROB2_GRADE`

- Rule Candidate = 0
- Accepted Rule = 0
- Runtime change = 0
- Clinical activation = BLOCKED
