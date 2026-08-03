# ADA-03 — تطبیق پروتکل/SAP و نتایج PHT2 برای Recommendation 6.19
## بستهٔ اصلاحی پژوهش v0.9.1

**پروژه:** Specialist Clinic — Clinical Rule Library Rebuild  
**مبنای علمی:** ADA Standards of Care in Diabetes—2026  
**Recommendation جاری:** 6.19  
**مبنای داده:** `ADA_Clinical_Rule_Evidence_Master_v0.8.xlsx`  
**شاخهٔ حاکم:** `research/ada-2026-evidence-v0.2`  
**PR حاکم:** Draft PR #60  
**تاریخ ممیزی:** 2026-08-01  
**ماهیت خروجی:** پژوهش و کنترل شواهد؛ نه راهنمای درمان بیمار، نه Rule Specification و نه تغییر Runtime

---

## 1. Corrigendum اجباری نسبت به v0.9 پیشنهادی

بستهٔ v0.9 پیشنهادی قبلی نباید اعمال شود؛ زیرا وضعیت PHT2 را با عبارت «SAP در دسترس نیست» نگه داشته بود. اکنون یک فایل عمومی 28 صفحه‌ای در ClinicalTrials.gov شناسایی شده که Study Protocol و Statistical Analysis Plan را با هم در بر دارد. نسخهٔ جاری آن Version 7 و تاریخ آن 2025-04-14 است.

نتیجهٔ اصلاح:
- گیت «نبود Protocol/SAP» بسته شد؛
- گیت «متن کامل مقاله، CONSORT denominator، اجرای واقعی روش‌های missing data و Final Research Report» باز ماند؛
- patch قبلی superseded است.

در سرصفحهٔ PDF، شناسه به‌صورت `NCT0486387` دیده می‌شود و رقم پایانی افتاده است؛ URL رسمی سند، registry و عنوان مطالعه آن را به `NCT04863872` متصل می‌کنند. این مورد به‌عنوان خطای نمایشی provenance ثبت می‌شود، نه تعارض هویتی مطالعه.

---

## 2. سؤال علّی واقعی PHT2

PHT2 این دو بازو را مقایسه کرده است:

1. `PC`: proactive nurse care management؛
2. `PC+`: همان proactive care به‌علاوهٔ psychoeducation.

هر دو بازو می‌توانستند شامل بازبینی هدف قند، تغییر یا deintensification داروهای دارای ریسک هیپوگلیسمی، self-monitoring، glucagon و referral برای CGM باشند؛ اما این اقدامات clinician/provider-mediated بودند.

بنابراین:
- trial، proactive care را در برابر usual care آزمایش نکرده است؛
- کاهش درون‌گروهی رخدادها اثر علّی proactive care را ثابت نمی‌کند؛
- trial هیچ medication state transition ثابت و مستقلی را برای تبدیل مستقیم به Rule آزمایش نکرده است؛
- contrast تصادفی معتبر فقط «افزودن psychoeducation به proactive care» است.

---

## 3. chronology پروتکل

نقاط زمانی:
- registry اولیه: 2021-04-26؛
- original protocol: 2021-04-29؛
- first enrollment: 2022-01-26؛
- Version 4: 2022-07-01؛
- Version 5: 2023-11-29؛
- primary completion: 2024-04-24؛
- study completion: 2024-06-21؛
- Version 6: 2024-11-27؛
- Version 7: 2025-04-14؛
- registry results first posted: 2025-05-06؛
- publication: 2026-05-12.

### Version 4 پس از first enrollment
- cluster randomization به individual randomization تغییر کرد؛
- سن ورود از بالای 50 سال به 18 سال و بیشتر گسترش یافت؛
- recruitment pool افراد دریافت‌کنندهٔ insulin گسترش یافت.

این تغییرات اثبات bias نیستند؛ اما بدون متن کامل و CONSORT مشخص نیست آیا همهٔ شرکت‌کنندگان تحت روش نهایی تخصیص یافته‌اند. Domain 1 فعلاً نمی‌تواند `LOW` قطعی باشد.

### Version 5 حین follow-up
- secondary CGM outcomes اضافه شد؛
- mediation framework تغییر کرد؛
- missing-data trigger از 15% به 10% کاهش یافت.

### Version 6 پس از completion
- clustering در analysis به intervention training cohorts نسبت داده شد؛
- شکل قدیمی randomization اصلاح شد؛
- نام intervention پس از license agreement اصلاح شد.

این موارد outcome switching را ثابت نمی‌کنند، ولی اجرای نسخه‌دار SAP باید با full article یا analysis report تطبیق داده شود.

---

## 4. تطبیق outcome و analysis

Primary outcome از ابتدا severe hypoglycemia خوداظهاری در 12 ماه گذشته، در follow-up چهارده‌ماهه بود. روش برنامه‌ریزی‌شده شامل intention-to-treat، modified Poisson، adjustment برای age/sex/risk score/baseline events و GEE با robust variance بود. outcome collectors masked بودند، ولی participants، nurses و clinicians masked نبودند.

نتیجه:
- PC: 16.1%؛
- PC+: 11.6%؛
- aRR: 0.72، 95% CI: 0.39 تا 1.30؛
- aARD: -4.6 percentage points، 95% CI: -13.0 تا 3.7.

CI نتیجهٔ primary شامل no effect است. این نتیجه برتری آماری psychoeducation را نشان نمی‌دهد و برابر با اثبات equivalence یا بی‌اثری قطعی نیست.

### تعارض completion
Abstract هم‌زمان نوشته است:
- 92%؛
- n=230؛
- از 259 participant.

ولی `230 / 259 = 88.803%`.

اگر 259 denominator درست باشد، attrition برابر 11.197% است و از trigger ده‌درصدی Protocol عبور می‌کند. باید مشخص شود آیا responder/nonresponder check، multiple imputation یا IPW اجرا شده است. این تعارض با `CONFLICT-ADA-S06-027` ثبت می‌شود.

### Power
Protocol نرخ 60% severe hypoglycemia در بازوی PC را برای power model فرض کرده بود. event frequency واقعی در baseline و follow-up به‌مراتب پایین‌تر بود. نتیجهٔ عملی، information size کمتر و CI گسترده است. این مورد با `CONFLICT-ADA-S06-028` ثبت می‌شود.

### Level 2
- aRR = 0.46، 95% CI: 0.20 تا 1.03؛
- aARD = -11.3 pp، 95% CI: -21.7 تا -0.8.

مقیاس relative شامل no effect است، ولی absolute zero را شامل نمی‌شود. این secondary outcome است و عبارت روشنی دربارهٔ multiplicity adjustment در Protocol عمومی پیدا نشد؛ بنابراین قابل تبدیل مستقیم به threshold یا Rule نیست.

---

## 5. RoB 2 نتیجه‌محور — موقت

| Domain | قضاوت |
|---|---|
| D1 Randomization | SOME CONCERNS — تغییر روش پس از first enrollment نیازمند verification |
| D2 Deviations | SOME CONCERNS — unblinded و احتمال تفاوت cointervention/CGM |
| D3 Missing data | SOME CONCERNS — denominator hold |
| D4 Measurement | SOME CONCERNS — self-report 12-month recall در participantهای unblinded |
| D5 Selection | SOME CONCERNS — amendments، multiplicity نامشخص و full-text hold |
| Overall | SOME CONCERNS — PROVISIONAL, MAY ESCALATE |

این appraisal outcome-specific است، توسط همان ارزیاب در دو پاس تحلیلی انجام شده و independent human review نیست. قضاوت نهایی محسوب نمی‌شود.

---

## 6. GRADE برای استفاده در Rule Library

سؤال محصولی:

> آیا PHT2 برای ساخت یک Rule قابل‌انتقال و actionable پس از hypoglycemia در Recommendation 6.19 کفایت می‌کند؟

- Starting certainty: HIGH؛
- Risk of bias: SERIOUS — provisional؛
- Inconsistency: قابل‌برآورد نیست؛ یک trial؛
- Indirectness: SERIOUS؛ trial psychoeducation افزوده‌شده به proactive nurse care را می‌سنجد، نه medication action مستقل؛
- Imprecision: SERIOUS؛ primary CI گسترده و event frequency پایین؛
- Proposed final: **VERY LOW — PROVISIONAL / NOT FINAL**.

این downgrade دربارهٔ portability/actionability در محصول است و به معنای بی‌ارزش‌بودن علمی trial نیست.

---

## 7. وضعیت HOAP

JAMA Supplement 1 شامل trial protocol و SAP است؛ بنابراین عبارت «هیچ protocol/SAP وجود ندارد» باید اصلاح شود.

اما گیت‌های زیر بازند:
1. registry عمومی بعد از primary completion منتشر شده است؛
2. تاریخ و نسخهٔ Supplement 1 هنوز به‌صورت مستقل با randomization تطبیق داده نشده است؛
3. خود HOAP guideline/algorithm، evidence tables، Delphi report، clause-level grading و حقوق reuse/software encoding عمومی و قابل‌ممیزی نیستند.

HOAP trial یک process outcome را سنجیده است: safer regimen در شش ماه. severe hypoglycemia primary outcome نبود و رخدادهای acute-care اندک بودند. نقش مجاز HOAP در این dossier فقط `PROCESS_WORKFLOW_EVIDENCE_ONLY` است، نه اثبات مستقل thresholdها و actionهای الگوریتم داخلی.

---

## 8. تغییرات پیشنهادی Workbook

- Search Log: `SEA-ADA-0032` تا `SEA-ADA-0035`؛
- Conflict Matrix: `CONFLICT-ADA-S06-027` تا `029` و refinement برای `025`؛
- Decision Log: `DEC-ADA-054` تا `059`؛
- RoB 2: `ROB2-PHT2-V0.9.1` به‌صورت provisional؛
- GRADE: update پیشنهادی `EU-6.19-10` به `VERY LOW — PROVISIONAL`.

KPI پیشنهادی:
- Search records: 35؛
- Open conflicts: 29؛
- Decision records: 59؛
- Rule candidates: 0؛
- Accepted Rules: 0؛
- Runtime changes: 0.

---

## 9. مرز محصول

این یافته‌ها اجازه نمی‌دهند سیستم:
- insulin یا sulfonylurea را خودکار قطع/کاهش دهد؛
- target قند یا HbA1c را خودکار تغییر دهد؛
- glucagon یا CGM را خودکار تجویز کند؛
- action sequence داخلی HOAP را encode کند؛
- یک رخداد hypoglycemia را بدون factual prerequisites به اقدام دارویی وصل کند.

تنها workflow مجاز:

`verified hypoglycemia event -> clinician-owned review trigger -> collect missing facts -> individualized decision`

---

## 10. نتیجهٔ v0.9.1

Protocol/SAP عمومی یک گیت واقعی را بست و appraisal را از «کاملاً pending» به «provisional» ارتقا داد. هم‌زمان سه محدودیت مهم روشن شد:
1. amendmentهای substantive پس از شروع و analysis clarification پس از completion؛
2. ناسازگاری completion statement؛
3. فاصلهٔ زیاد power assumption با event frequency واقعی.

وضعیت نهایی توسعه‌ای:
- `Rule candidates = 0`
- `Accepted Rules = 0`
- `Licensing = HOLD`
- `Runtime changes = 0`
- `Clinical activation = BLOCKED`

این بسته پژوهش را جلو می‌برد، ولی Rule بالینی شتاب‌زده نمی‌سازد.
