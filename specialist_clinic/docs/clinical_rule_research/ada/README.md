# ADA 2026 Research Workstream

## وضعیت حاکم

- منبع مادر کاندیدا: نسخهٔ کامل `ADA Standards of Care in Diabetes—2026`
- گایدلاین خلاصه‌شده فقط برای navigation و context است.
- تمام Ruleهای قدیمی سامانه از نظر بالینی بی‌اعتبارند.
- Rule candidates: `0`
- Accepted Rules: `0`
- Licensing: `HOLD`
- Review model: دو Pass توسط همان ارزیاب؛ نه دو ارزیاب انسانی مستقل.

## مراحل

### ADA-00 — Protocol Freeze

Scope، no-pass gate، source boundaries، Drive/Excel workflow و ممنوعیت grandfathering قفل می‌شوند.

### ADA-01 — Guideline Identity and Appraisal

نسخه، methodology، search cutoff، evidence grading، disclosures، Living Standards و AGREE II بررسی می‌شوند. ADA 2026 برای پژوهش `USE WITH CONDITIONS` است، نه یک Rule Library اجرایی.

### ADA-02 — Recommendation Inventory

هر Recommendation با paraphrase مستقل، locator، Grade بندها، population، setting، dependencies، conflict و computability ثبت می‌شود. متن کامل محافظت‌شده در Git یا Drive مشترک کپی نمی‌شود.

### ADA-03 — Evidence Dossiers

برای هر Recommendation منتخب، citation chain، supplemental search، article screening، full-text extraction، Risk of Bias، directness، GRADE، cross-section dependencies، cross-guideline conflicts و conflict matrix ساخته می‌شود.

### ADA-04 — Formalization Readiness

فقط توصیه‌ای که evidence، conflict، licensing و Fact readiness را کامل کرده باشد می‌تواند Rule Candidate شود.

### ADA-05 — Validation and Governance

Golden cases، retrospective، SILENT، pilot، clinical approval و technical approval پیش از activation الزامی‌اند.

## وضعیت نسخه v0.7

- بخش ۶: `24` Recommendation Record دوپاسی
- Recommendation 6.19: نخستین Evidence Dossier
- مطالعات غربال‌شده: `16`
- استخراج متن کامل: `10`
- Article-level appraisal: `16`
- ارزیابی رسمی روش/نتیجه: `9`
- Post-cutoff evidence records: `5`
- GRADE Evidence Units: `10`
- KDIGO dependency records: `8`
- وابستگی بین‌بخشی ثبت‌شده: `14`
- تعارض باز: `23`
- Decision records: `48`
- Rule Candidate: `0`
- Accepted Rule: `0`

## ترمیم تاریخچه

نسخه‌های v0.3 تا v0.6 بر اساس IDهای canonical ادغام شدند. توالی Article، Full-text، Conflict، Decision و GRADE بدون gap یا duplicate کنترل شد. فرمول‌های Workbook و ZIP نیز بدون خطا تأیید شدند. جزئیات در `HISTORY_RECONCILIATION_V0_7_FA.md` ثبت شده است.

## نتیجهٔ رسمی فعلی برای Recommendation 6.19

- منابع 66 تا 70 ADA مستقیماً یک medication action استاندارد پس از رخداد تأییدشدهٔ Level 2/3 را آزمایش نمی‌کنند.
- Munshi 2016 feasibility evidence تک‌گروهی است و comparator هم‌زمان ندارد.
- IMPERIUM و CGM substudy آن به post-event action بسیار indirect هستند.
- Grant 2025 برای افزایش deprescribing process شواهد متوسط ایجاد می‌کند، نه برای کاهش severe hypoglycemia یا تعیین نوع تغییر دارو.
- Pilla 2023 evidence مربوط به values/preferences است، نه اثربخشی.
- Seidu 2019 برای سنتز اصلی سود–زیان `AMSTAR 2 CRITICALLY LOW` است و فقط citation map محسوب می‌شود.
- Christiaens 2025 یک safety-conflict signal مهم است، ولی `ROBINS-I CRITICAL` دارد و اثبات علی نیست.
- Rode 2024 شواهد مستقیم‌تری دربارهٔ گردش‌کار و recurrence ارائه می‌دهد، اما اثر علی تغییر دارو یا سطح مراقبت را ثابت نمی‌کند.
- Gilliam 2026 / HOAP شواهد randomized برای proactive pharmacist-led workflow و safer prescribing فراهم می‌کند؛ ولی الگوریتم HOAP، thresholdهای آن و قابلیت انتقالش به محصول مستقل اعتبارسنجی نشده‌اند.
- نتیجهٔ ED/IP در HOAP یک signal کم‌قطعیت و ثانویه است؛ رخدادها نادر بودند و اثر 12 ماهه پایدار نبود.
- PHT2 جمعیت بسیار مرتبطی دارد، اما متن کامل نتایج هنوز دریافت نشده است. این trial psychoeducation افزوده را با proactive care تنها مقایسه می‌کند، نه proactive care را با usual care.
- HypoPAP هنوز نتیجه منتشرشده ندارد و فقط horizon scanning است.
- مرور مدل‌های پیش‌بینی 2026 نشان داد تقریباً همهٔ مطالعات خطر سوگیری بالا دارند؛ هیچ risk model وارد پروژه نشده است.
- KDIGO نشان داد HbA1c در CKD پیشرفته ممکن است برای ایمنی کافی نباشد، insulin clearance تغییر کند و indication مستقل قلبی–کلیوی باید حفظ شود.
- KDIGO 2026 public-review draft تا انتشار نهایی فقط monitoring-only است.
- deintensification، dose reduction، complete cessation، class switching و regimen simplification interventionهای یکسان نیستند.
- کاهش، قطع، تعویض یا simplification خودکار دارو همچنان `BLOCKED` است.
- یک workflow برای مرور pharmacist/clinician اکنون evidence قوی‌تری دارد، اما همچنان Research Track است و Rule Candidate نیست.

## اسناد

- `ADA-01_AGREEII_DUAL_PASS_APPRAISAL_FA.md`
- `ADA-02_SECTION6_RECOMMENDATION_INVENTORY_FA.md`
- `ADA-03_REC_6_19_EVIDENCE_PROTOCOL_FA.md`
- `ADA-03_REC_6_19_INITIAL_EVIDENCE_MAP_FA.md`
- `ADA-03_REC_6_19_FORMAL_METHOD_APPRAISAL_FA.md`
- `ADA-03_REC_6_19_CROSS_SECTION_DEPENDENCY_REVIEW_FA.md`
- `ADA-03_REC_6_19_PRIMARY_CITATION_CHAIN_FA.md`
- `ADA-03_REC_6_19_GRADE_EVIDENCE_PROFILE_FA.md`
- `ADA-03_REC_6_19_KDIGO_CROSS_GUIDELINE_FA.md`
- `ADA-03_REC_6_19_POST_CUTOFF_UPDATE_FA.md`
- `ADA-03_REC_6_19_HOAP_RCT_APPRAISAL_FA.md`
- `ADA-03_REC_6_19_PHT2_PENDING_APPRAISAL_FA.md`
- `HISTORY_RECONCILIATION_V0_7_FA.md`
- `WORKSPACE_LINKS.md`
- `ADA_RESEARCH_STATUS_V0_3.json` تا `ADA_RESEARCH_STATUS_V0_7.json`
