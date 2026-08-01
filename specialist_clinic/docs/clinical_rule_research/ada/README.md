# ADA 2026 Research Workstream

## وضعیت حاکم

- منبع مادر کاندیدا: نسخهٔ کامل `ADA Standards of Care in Diabetes—2026`
- تمام Ruleهای قدیمی سامانه از نظر بالینی بی‌اعتبارند.
- Rule candidates: `0`
- Accepted Rules: `0`
- Licensing: `HOLD`
- Clinical activation: `BLOCKED`
- Review model: دو Pass توسط همان ارزیاب؛ نه دو ارزیاب انسانی مستقل.

## مراحل

1. `ADA-00`: Protocol Freeze
2. `ADA-01`: Guideline Identity and AGREE II Appraisal
3. `ADA-02`: Recommendation Inventory
4. `ADA-03`: Evidence Dossiers, Risk of Bias, GRADE and conflicts
5. `ADA-04`: Formalization Readiness
6. `ADA-05`: Validation, SILENT, pilot and governed activation

## وضعیت نسخه v0.9.1

- بخش ۶: `24` Recommendation Record
- مطالعات غربال‌شده برای 6.19: `17`
- استخراج متن کامل مقالهٔ نتایج: `10`
- Article-level appraisal: `16`
- Formal method/result appraisal sealed: `9`
- Provisional result appraisal: `1` برای PHT2
- GRADE Evidence Units: `10`
- KDIGO dependency records: `8`
- HOAP provenance domains: `8`
- Search Log records: `35`
- تعارض باز: `29`
- Decision records: `59`
- Rule Candidate: `0`
- Accepted Rule: `0`
- Runtime change: `0`

## یافتهٔ اصلی Recommendation 6.19

ADA 6.19 یک trigger برای بازنگری clinician-owned طرح درمان است، نه یک medication action استاندارد و خودکار.

workflow مجاز فعلی:

`verified hypoglycemia event -> clinician-owned review trigger -> collect missing facts -> individualized decision`

منابع اصلی ADA برای 6.19 اثربخشی یک اقدام دارویی خودکار واحد را پس از Level 2/3 ثابت نمی‌کنند. هر formalization دارویی باید داروی دقیق، indication، CKD stage، insulin clearance، قابلیت اعتماد HbA1c، cardiorenal benefit، frailty/cognition، caregiver capacity، treatment burden و ترجیح بیمار را بررسی کند.

## PHT2 — وضعیت v0.9.1

Protocol و SAP عمومی PHT2 در ClinicalTrials.gov بازیابی و ممیزی شدند. نسخهٔ حاکم `Version 7 — 2025-04-14` است.

تصحیح مهم:

- عبارت قبلی «SAP در دسترس نیست» منسوخ شد؛
- full results article/CONSORT و Final PCORI Report همچنان روی HOLD هستند؛
- appraisal از `fully pending` به `provisional` ارتقا یافت، نه final.

contrast صحیح trial:

- `PC`: proactive nurse care؛
- `PC+`: همان care به‌علاوهٔ psychoeducation.

این trial proactive care را با usual care مقایسه نکرده است.

نتیجهٔ primary:

- PC: 16.1%
- PC+: 11.6%
- aRR: 0.72، 95% CI: 0.39 تا 1.30
- aARD: -4.6 percentage points، 95% CI: -13.0 تا 3.7

تعارض‌های باز:

- Abstract هم‌زمان `92%` completion و `230/259` را گزارش می‌کند؛ محاسبه برابر 88.8% است؛
- randomization design پس از first enrollment از cluster به individual تغییر کرده است؛
- secondary/missing-data plan حین follow-up تغییر کرده و clustering پس از completion روشن شده است؛
- power assumption نرخ رخداد بالاتری از event frequency واقعی داشت؛
- multiplicity statement در Protocol عمومی پیدا نشد.

RoB 2 موقت:

`SOME CONCERNS — PROVISIONAL / MAY ESCALATE`

GRADE موقت برای portability/actionability در Rule Library:

`EU-6.19-10 = VERY LOW — PROVISIONAL / NOT FINAL`

این قضاوت دربارهٔ قابلیت تبدیل به Rule است، نه نفی ارزش علمی trial.

## HOAP — وضعیت v0.9.1

Trial Protocol و SAP در JAMA Supplement 1 قرار دارند. با این حال:

- public registry posting بعد از primary completion انجام شده است؛
- تاریخ/نسخهٔ Supplement 1 نسبت به randomization هنوز مستقل ممیزی نشده است؛
- نسخهٔ frozen داخلی HOAP، evidence tables، Delphi details، clause-level grading و reuse/software rights در دسترس نیستند؛
- comparator نیز passive access به HOAP داشت؛
- primary outcome safer-prescribing process بود، نه severe hypoglycemia.

نقش مجاز HOAP:

`PROCESS_WORKFLOW_EVIDENCE_ONLY`

HOAP مجوز کپی thresholdها، actionهای دارویی یا الگوریتم داخلی نیست.

## مرزهای غیرقابل عبور

- کپی مستقیم HOAP به Rule Library
- استفاده از trial effect به‌عنوان تأیید تمام الگوریتم
- کاهش/قطع/تعویض خودکار دارو
- حذف داروی organ-protective فقط بر اساس A1C یا hypoglycemia event
- `hypoglycemia_event -> reduce_all_diabetes_medications`
- `old_age -> deintensify`
- `low_eGFR -> stop_all_agents`
- `CGM_low -> assume_level_3_event`
- استفاده از KDIGO 2026 draft به‌عنوان منبع normative
- finalizing PHT2 بدون متن کامل/CONSORT و analysis implementation
- ترجمه یا software encoding منبع محافظت‌شده بدون permission

## اسناد کلیدی

- `ADA-01_AGREEII_DUAL_PASS_APPRAISAL_FA.md`
- `ADA-02_SECTION6_RECOMMENDATION_INVENTORY_FA.md`
- `ADA-03_REC_6_19_EVIDENCE_PROTOCOL_FA.md`
- `ADA-03_REC_6_19_PRIMARY_CITATION_CHAIN_FA.md`
- `ADA-03_REC_6_19_GRADE_EVIDENCE_PROFILE_FA.md`
- `ADA-03_REC_6_19_KDIGO_CROSS_GUIDELINE_FA.md`
- `ADA-03_REC_6_19_POST_CUTOFF_UPDATE_FA.md`
- `ADA-03_REC_6_19_HOAP_RCT_APPRAISAL_FA.md`
- `ADA-03_REC_6_19_HOAP_PROVENANCE_TRANSFERABILITY_FA.md`
- `ADA-03_REC_6_19_PHT2_PENDING_APPRAISAL_FA.md`
- `ADA-03_REC_6_19_PHT2_PROTOCOL_SAP_RECONCILIATION_V0_9_1_FA.md`
- `ADA-03_REC_6_19_GRADE_CONSISTENCY_AUDIT_FA.md`
- `ADA_REC_6_19_V0_9_1_WORKBOOK_ROWS.json`
- `ADA_RESEARCH_STATUS_V0_3.json` تا `ADA_RESEARCH_STATUS_V0_9_1.json`
- `HISTORY_RECONCILIATION_V0_7_FA.md`
- `WORKSPACE_LINKS.md`

## وضعیت اجرایی

- Rule candidates: `0`
- Accepted Rules: `0`
- Licensing: `HOLD`
- Runtime changes: `0`
- Clinical activation: `BLOCKED`

PR پژوهش باید تا بسته‌شدن full-text/result reporting، HOAP access/method/licensing، local computability، independent review و validation در وضعیت Draft باقی بماند.
