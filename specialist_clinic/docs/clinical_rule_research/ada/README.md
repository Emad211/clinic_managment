# ADA 2026 Research Workstream

## وضعیت حاکم

- منبع مادر: نسخهٔ کامل `ADA Standards of Care in Diabetes—2026`
- تمام Ruleهای قدیمی از نظر بالینی بی‌اعتبارند.
- Rule candidates: `0`
- Accepted Rules: `0`
- Licensing: `HOLD`
- Runtime changes: `0`
- UI changes: `0`
- Clinical activation: `BLOCKED`
- Review model: دو Pass تحلیلی توسط همان ارزیاب؛ نه دو ارزیاب انسانی مستقل.

## مراحل

1. `ADA-00`: Protocol Freeze
2. `ADA-01`: Guideline Identity and AGREE II Appraisal
3. `ADA-02`: Recommendation Inventory
4. `ADA-03`: Evidence Dossiers, Risk of Bias, GRADE and conflicts
5. `ADA-04`: Formalization Readiness, Computability and Contract Freeze
6. `ADA-05`: Validation, SILENT, pilot and governed activation

## وضعیت نسخه v0.9.4

- Section 6 Recommendation records: `24`
- Studies screened for Recommendation 6.19: `17`
- Full-text extractions: `10`
- Article-level appraisals: `16`
- Sealed formal method/result appraisals: `9`
- Provisional PHT2 appraisal: `1`
- GRADE Evidence Units: `10`
- Search Log records: `48`
- Open conflicts: `43`
- Decision records: `82`
- Computability requirements audited: `28`
- Minimum Data Contract fields: `43`
- Event/Review Contract clauses: `38`
- Synthetic fixtures designed: `20`
- Rule Candidate: `0`
- Accepted Rule: `0`
- Runtime/UI change: `0`

## منبع حقیقت Workbook

Native Google Sheet v0.9.4:

https://docs.google.com/spreadsheets/d/1q344KGq1lUsncMofTtPSvEYKTmR2iJ0y6xSUnZsBDjY/edit

Parent v0.9.3 محفوظ است:

https://docs.google.com/spreadsheets/d/1x2tHD54tphkDXgmjQzmxHwHbA1CNXWTfzC236Z5j830/edit

Sheetهای اصلی جدید:

- `17_Computability_Audit`
- `18_Min_Data_Contract`
- `19_Event_Review_Contract`
- `20_Synthetic_Fixtures`
- `16_Version_History`

## Evidence boundary

ADA 6.19 یک trigger برای بازنگری clinician-owned طرح درمان است، نه medication action استاندارد و خودکار.

PHT2:

- proactive care را با usual care مقایسه نکرد؛
- Protocol/SAP عمومی استخراج شده است؛
- full results/CONSORT و Final PCORI Report باز هستند؛
- `EU-6.19-10 = VERY LOW — PROVISIONAL / NOT FINAL`.

HOAP:

- workflow فعال pharmacist/clinician را حمایت می‌کند؛
- comparator نیز passive HOAP access داشت؛
- post-allocation exclusions، chronology، subset estimand و Supplement 1 audit بازند؛
- internal guideline و reuse rights در دسترس نیست؛
- `EU-6.19-08/09 = VERY LOW` و فقط process/workflow evidence.

قاعده:

`DOCUMENT LISTED != DOCUMENT AUDITED`

## Computability v0.9.3 که در v0.9.4 حفظ شده است

```text
Verified clinician-review trigger = NOT_COMPUTABLE
Medication action                 = HARD_BLOCK
Minimum Data Contract             = DEFINED — RESEARCH ONLY
```

زیرساخت‌های قابل reuse:

- append-only medication/condition/allergy reconciliation؛
- time/source/unit/verification-aware observations؛
- canonical eGFR/UACR/HbA1c concepts؛
- conflict-aware Facts؛
- immutable clinician task contracts.

شکاف‌های hard:

- stable event identity و Level 2/3 evidence؛
- assistance و altered function؛
- event provenance/time/deduplication؛
- medication indication/actual exposure/causality؛
- renal trajectory، HbA1c reliability و CGM sufficiency؛
- cognition/function/frailty/nutrition/caregiver/preferences؛
- local access/cost/referral capacity؛
- structured clinician disposition.

## D0 Event and Review Contract Freeze v0.9.4

Contract پژوهشی شامل 38 clause است:

- immutable event root؛
- append-only event versions؛
- evidence links با نقش‌های مستقل؛
- correction و entered-in-error بدون UPDATE/DELETE؛
- duplicate candidate با human adjudication؛
- exact confirmed-version gate برای review case؛
- immutable review contract شامل required facts، verification و allowed outcomes؛
- append-only clinician disposition؛
- privacy/data-minimization و release gates.

Event states:

```text
CANDIDATE
PROVISIONAL
CONFIRMED
CONFLICT
REJECTED
ENTERED_IN_ERROR
```

Review states:

```text
OPEN
NEEDS_DATA
READY_FOR_CLINICIAN
IN_REVIEW
DISPOSITION_RECORDED
CLOSED
ENTERED_IN_ERROR
```

تنها یک event version دقیق `CONFIRMED` می‌تواند منبع review case باشد. candidate/provisional/conflict هیچ task بالینی تولید نمی‌کند.

## Synthetic fixtures

۲۰ fixture فقط با دادهٔ مصنوعی طراحی شده‌اند و هنوز executable نیستند. پوشش شامل:

- Level 2 و Level 3؛
- missing time/source؛
- duplicate و conflict؛
- late report و correction؛
- medication/renal/CGM/capacity gaps؛
- clinician-recorded no-change/change؛
- stale-head و cross-patient rejection؛
- ممنوعیت automatic medication action.

Global invariant:

```text
Expected automatic medication action = NONE / FORBIDDEN
```

## Fail-closed boundary

Fact مفقود، stale، provisional یا conflicting فقط می‌تواند این خروجی‌ها را بسازد:

```text
NEEDS_DATA
CONFLICT
EVIDENCE_INCOMPLETE
NOT_APPLICABLE_OR_REVIEW
CLINICIAN_REVIEW
```

ممنوع:

```text
missing -> false
one low observation -> verified event
glucose -> infer Level 3
medication class -> culprit medication
event -> automatic medication action
```

## مرزهای غیرقابل عبور

- کپی یا بازسازی HOAP به Rule Library؛
- finalizing PHT2 بدون full reporting؛
- کاهش/قطع/تعویض خودکار دارو؛
- حذف organ-protective agent فقط بر اساس A1C/event؛
- task بالینی از glucose observation منفرد؛
- automatic dedup merge؛
- UPDATE/DELETE رخداد؛
- اجرای prescription/order/referral از disposition؛
- استفاده از دادهٔ واقعی بیمار در D1 قبل از privacy approval؛
- schema migration بر اساس Research Contract Freeze؛
- SILENT/activation پیش از تمام گیت‌ها.

## اسناد کلیدی v0.9.4

- `ADA-04_REC_6_19_EVENT_REVIEW_CONTRACT_FREEZE_V0_9_4_FA.md`
- `ADA_RESEARCH_STATUS_V0_9_4.json`
- `ADA_REC_6_19_EVENT_REVIEW_CONTRACT_INDEX_V0_9_4.json`
- `ADA_REC_6_19_SYNTHETIC_FIXTURE_INDEX_V0_9_4.json`
- `ADA-04_REC_6_19_LOCAL_COMPUTABILITY_ASSESSMENT_V0_9_3_FA.md`
- `ADA_REC_6_19_MINIMUM_DATA_CONTRACT_INDEX_V0_9_3.json`
- `ADA_REC_6_19_COMPUTABILITY_GAP_INDEX_V0_9_3.json`
- `ADA-03_REC_6_19_PHT2_PROTOCOL_SAP_RECONCILIATION_V0_9_1_FA.md`
- `ADA-03_REC_6_19_HOAP_REPORTING_ESTIMAND_AUDIT_V0_9_2_FA.md`
- `WORKSPACE_LINKS.md`

## قدم بعدی حاکم

1. review چندتخصصی D0: پزشکی، پرستاری، داروسازی، معماری، privacy و terminology؛
2. اصلاح contract در صورت review، بدون schema migration؛
3. ساخت executable synthetic data-integrity tests فقط پس از approval؛
4. هیچ therapeutic expected output؛
5. ادامهٔ مستقل HOAP Supplement 1 و PHT2 full-report retrieval؛
6. Formalization Reassessment فقط پس از بسته‌شدن تمام گیت‌ها.

PR باید همچنان Draft باقی بماند.
