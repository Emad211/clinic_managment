# ADA 2026 Research Workstream

## وضعیت حاکم

- منبع مادر: نسخهٔ کامل `ADA Standards of Care in Diabetes—2026`
- تمام Ruleهای قدیمی از نظر بالینی بی‌اعتبارند.
- Rule candidates: `0`
- Accepted Rules: `0`
- Licensing: `HOLD`
- Runtime changes: `0`
- Clinical activation: `BLOCKED`
- Review model: دو Pass تحلیلی توسط همان ارزیاب؛ نه دو ارزیاب انسانی مستقل.

## مراحل

1. `ADA-00`: Protocol Freeze
2. `ADA-01`: Guideline Identity and AGREE II Appraisal
3. `ADA-02`: Recommendation Inventory
4. `ADA-03`: Evidence Dossiers, Risk of Bias, GRADE and conflicts
5. `ADA-04`: Formalization Readiness
6. `ADA-05`: Validation, SILENT, pilot and governed activation

## وضعیت نسخه v0.9.2

- بخش ۶: `24` Recommendation Record
- مطالعات غربال‌شده برای 6.19: `17`
- Full-text extractions: `10`
- Article-level appraisals: `16`
- Sealed formal method/result appraisals: `9`
- Provisional PHT2 appraisal: `1`
- GRADE Evidence Units: `10`
- KDIGO dependency records: `8`
- HOAP provenance domains: `8`
- Search Log records: `39`
- Open conflicts: `34`
- Decision records: `66`
- Rule Candidate: `0`
- Accepted Rule: `0`
- Runtime change: `0`

## منبع حقیقت Workbook

Native Google Sheet v0.9.2:

https://docs.google.com/spreadsheets/d/1p-ugp_yQ3pVqbSN1I-IwremZ4P65sSEi3AtReFeyVbc/edit

Parent v0.8 محفوظ مانده است:

https://docs.google.com/spreadsheets/d/1E99uz5cBc1vENqMMi6r25Sb2ZkeGCQf3MhJz0dZU90w/edit

Sheet `16_Version_History` lineage و KPIهای v0.8 و v0.9.2 را ثبت می‌کند.

## یافتهٔ اصلی Recommendation 6.19

ADA 6.19 یک trigger برای بازنگری clinician-owned طرح درمان است، نه یک medication action استاندارد و خودکار.

workflow مجاز:

`verified hypoglycemia event -> clinician-owned review trigger -> collect missing facts -> individualized decision`

هر formalization احتمالی باید داروی دقیق، indication، CKD stage، insulin clearance، قابلیت اعتماد HbA1c، cardiorenal benefit، frailty/cognition، caregiver capacity، treatment burden و ترجیح بیمار را بررسی کند.

## PHT2 — وضعیت v0.9.2

Protocol/SAP عمومی Version 7 بازیابی و ممیزی شد.

contrast صحیح:

- `PC`: proactive nurse care؛
- `PC+`: همان care به‌علاوهٔ psychoeducation.

این trial proactive care را با usual care مقایسه نکرده است.

Primary result:

- PC: 16.1%
- PC+: 11.6%
- aRR: 0.72، 95% CI: 0.39 تا 1.30
- aARD: -4.6 percentage points، 95% CI: -13.0 تا 3.7

گیت‌های باز:

- `92%` completion با `230/259 = 88.8%` سازگار نیست؛
- randomization design پس از first enrollment تغییر کرده است؛
- secondary/missing-data plan حین follow-up تغییر کرد؛
- clustering پس از completion روشن شد؛
- power assumption با event frequency واقعی فاصله داشت؛
- full results article/CONSORT و Final PCORI Report pending هستند.

RoB 2:

`SOME CONCERNS — PROVISIONAL / MAY ESCALATE`

GRADE:

`EU-6.19-10 = VERY LOW — PROVISIONAL / NOT FINAL`

## HOAP — وضعیت v0.9.2

Dedicated reporting/estimand audit انجام شد.

یافته‌های اصلی:

- 200 نفر randomize و 191 نفر پس از 9 post-allocation exclusion تحلیل شدند؛
- public registration پس از primary completion انجام شد؛
- assignment در مقاله 2023-06-01، trial start برابر 2023-07-20 و baseline برابر 2023-07-23 گزارش شده است؛
- فقط 73/96 نفر intervention initial visit کامل کردند؛
- 50/191 نفر از ابتدا primary safer-regimen state را داشتند؛
- target-drug subset شامل 141 نفر بود و prespecification آن هنوز ممیزی نشده است؛
- ED/IP result در شش ماه 0 در برابر 5 بود، اما secondary، sparse و در 12 ماه post hoc دیگر statistically clear نبود؛
- ED/IP data فقط بخش کوچکی از severe hypoglycemia را می‌گیرد؛
- Supplement 1 وجود دارد، ولی binary/date/version chronology هنوز audit نشده است؛
- internal HOAP guideline، evidence tables، Delphi details و reuse/software rights در دسترس نیستند.

GRADE canonical:

- `EU-6.19-08 = VERY LOW`؛ `PROCESS_WORKFLOW_EVIDENCE_ONLY`
- `EU-6.19-09 = VERY LOW`؛ `BLOCKED_REPLICATION_AND_PRECISION`

نقش مجاز HOAP:

`PROCESS_WORKFLOW_EVIDENCE_ONLY`

## مرزهای غیرقابل عبور

- کپی مستقیم HOAP به Rule Library
- استفاده از effect trial به‌عنوان تأیید تمام الگوریتم
- انتخاب restricted-subset effect به‌عنوان threshold
- کاهش/قطع/تعویض خودکار دارو
- حذف داروی organ-protective فقط بر اساس A1C یا hypoglycemia event
- `hypoglycemia_event -> reduce_all_diabetes_medications`
- `old_age -> deintensify`
- `low_eGFR -> stop_all_agents`
- `CGM_low -> assume_level_3_event`
- finalizing PHT2 بدون full article/CONSORT و analysis implementation
- فرض prespecification HOAP بدون audit Supplement 1
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
- `ADA-03_REC_6_19_HOAP_REPORTING_ESTIMAND_AUDIT_V0_9_2_FA.md`
- `ADA-03_REC_6_19_PHT2_PENDING_APPRAISAL_FA.md`
- `ADA-03_REC_6_19_PHT2_PROTOCOL_SAP_RECONCILIATION_V0_9_1_FA.md`
- `ADA-03_REC_6_19_GRADE_CONSISTENCY_AUDIT_FA.md`
- `ADA_REC_6_19_V0_9_2_WORKBOOK_DELTA.json`
- `ADA_RESEARCH_STATUS_V0_3.json` تا `ADA_RESEARCH_STATUS_V0_9_2.json`
- `HISTORY_RECONCILIATION_V0_7_FA.md`
- `WORKSPACE_LINKS.md`

## قدم بعدی حاکم

1. بازیابی و page-audit رسمی HOAP Supplement 1؛
2. بازیابی PHT2 full results article/CONSORT و Final PCORI Report؛
3. local computability assessment برای ایران؛
4. independent clinical/methodological review؛
5. فقط پس از بسته‌شدن تمام گیت‌ها، بررسی Formalization Readiness.

PR پژوهش باید همچنان Draft باقی بماند.
