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
5. `ADA-04`: Formalization Readiness and Local Computability
6. `ADA-05`: Validation, SILENT, pilot and governed activation

## وضعیت نسخه v0.9.3

- Section 6 Recommendation records: `24`
- Studies screened for Recommendation 6.19: `17`
- Full-text extractions: `10`
- Article-level appraisals: `16`
- Sealed formal method/result appraisals: `9`
- Provisional PHT2 appraisal: `1`
- GRADE Evidence Units: `10`
- Search Log records: `45`
- Open conflicts: `43`
- Decision records: `74`
- Computability requirements audited: `28`
- Minimum Data Contract fields: `43`
- Rule Candidate: `0`
- Accepted Rule: `0`
- Runtime/UI change: `0`

## منبع حقیقت Workbook

Native Google Sheet v0.9.3:

https://docs.google.com/spreadsheets/d/1x2tHD54tphkDXgmjQzmxHwHbA1CNXWTfzC236Z5j830/edit

Parent v0.9.2 محفوظ مانده است:

https://docs.google.com/spreadsheets/d/1p-ugp_yQ3pVqbSN1I-IwremZ4P65sSEi3AtReFeyVbc/edit

Sheet `16_Version_History` lineage را ثبت می‌کند. دو Sheet جدید:

- `17_Computability_Audit`
- `18_Min_Data_Contract`

## یافتهٔ اصلی Recommendation 6.19

ADA 6.19 یک trigger برای بازنگری clinician-owned طرح درمان است، نه یک medication action استاندارد و خودکار.

workflow پژوهشی مجاز:

`capture/import source records -> construct candidate event -> resolve duplicates/conflicts -> clinician confirms/rejects event -> collect missing context -> clinician records disposition`

هیچ‌یک از مراحل فوق هنوز Rule فعال نیستند.

## PHT2

Protocol/SAP عمومی Version 7 بازیابی و ممیزی شد. contrast صحیح:

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
- amendment chronology و analysis implementation؛
- power assumption در برابر event frequency واقعی؛
- full results article/CONSORT؛
- Final PCORI Report.

RoB 2:

`SOME CONCERNS — PROVISIONAL / MAY ESCALATE`

GRADE:

`EU-6.19-10 = VERY LOW — PROVISIONAL / NOT FINAL`

## HOAP

- 200 نفر randomize و 191 نفر پس از 9 post-allocation exclusion تحلیل شدند؛
- public registration پس از primary completion بود؛
- assignment، trial start و baseline chronology هنوز تطبیق کامل ندارد؛
- comparator نیز passive HOAP access داشت؛
- target-drug subset prespecification ممیزی نشده است؛
- ED/IP signal secondary، sparse و غیرپایدار در 12 ماه بود؛
- Supplement 1 وجود دارد، ولی binary/date/version chronology هنوز page-audit نشده است؛
- internal HOAP guideline و reuse/software rights در دسترس نیستند.

GRADE canonical:

- `EU-6.19-08 = VERY LOW`؛ `PROCESS_WORKFLOW_EVIDENCE_ONLY`
- `EU-6.19-09 = VERY LOW`؛ `BLOCKED_REPLICATION_AND_PRECISION`

قاعدهٔ حاکم:

`DOCUMENT LISTED != DOCUMENT AUDITED`

## Local Computability v0.9.3

### نتیجهٔ رسمی

```text
Verified clinician-review trigger = NOT_COMPUTABLE
Medication action                 = HARD_BLOCK
Minimum Data Contract             = DEFINED — RESEARCH ONLY
Rule candidates                   = 0
```

### زیرساخت‌های قابل reuse

- reconciliation append-only برای medication/condition/allergy؛
- observations دارای value/unit/effective time/source/verification؛
- مفاهیم آزمایشگاهی eGFR، UACR و HbA1c؛
- conflict-aware Fact collections؛
- immutable clinician task contracts.

Reuse این زیرساخت‌ها هیچ Rule قدیمی را معتبر نمی‌کند.

### شکاف‌های Hard

- stable hypoglycemia event identity و Level 2/3 evidence؛
- external assistance و altered functioning؛
- event-level provenance، occurrence/recorded time و deduplication؛
- medication indication؛
- actual administration/adherence relative to event؛
- clinician-owned causality assessment؛
- renal trajectory/AKI/KRT و HbA1c reliability؛
- CGM data sufficiency و TBR window؛
- awareness، cognition، function، frailty، nutrition/illness و caregiver؛
- preferences، treatment burden و individualized goals؛
- local access/cost/formulary/referral/monitoring capacity؛
- structured clinician review disposition.

### Fail-closed boundary

Fact مفقود، stale، provisional یا conflicting فقط می‌تواند یکی از این خروجی‌ها را بسازد:

```text
NEEDS_DATA
CONFLICT
EVIDENCE_INCOMPLETE
NOT_APPLICABLE_OR_REVIEW
CLINICIAN_REVIEW
```

موارد زیر ممنوع‌اند:

```text
missing -> false
one low observation -> verified event
glucose value -> infer Level 3
medication class -> culprit medication
event -> automatic medication action
```

## مرزهای غیرقابل عبور

- کپی مستقیم HOAP به Rule Library
- استفاده از effect trial به‌عنوان تأیید تمام الگوریتم
- کاهش/قطع/تعویض خودکار دارو
- حذف داروی organ-protective فقط بر اساس A1C یا hypoglycemia event
- `hypoglycemia_event -> reduce_all_diabetes_medications`
- `old_age -> deintensify`
- `low_eGFR -> stop_all_agents`
- `CGM_low -> assume_level_3_event`
- finalizing PHT2 بدون full article/CONSORT
- فرض prespecification HOAP بدون audit Supplement 1
- ترجمه یا software encoding منبع محافظت‌شده بدون permission
- ساخت task از یک glucose reading منفرد

## اسناد کلیدی v0.9.3

- `ADA-04_REC_6_19_LOCAL_COMPUTABILITY_ASSESSMENT_V0_9_3_FA.md`
- `ADA_RESEARCH_STATUS_V0_9_3.json`
- `ADA_REC_6_19_MINIMUM_DATA_CONTRACT_INDEX_V0_9_3.json`
- `ADA_REC_6_19_COMPUTABILITY_GAP_INDEX_V0_9_3.json`
- `ADA-03_REC_6_19_PHT2_PROTOCOL_SAP_RECONCILIATION_V0_9_1_FA.md`
- `ADA-03_REC_6_19_HOAP_REPORTING_ESTIMAND_AUDIT_V0_9_2_FA.md`
- `ADA-03_REC_6_19_GRADE_EVIDENCE_PROFILE_FA.md`
- `ADA-03_REC_6_19_KDIGO_CROSS_GUIDELINE_FA.md`
- `ADA-03_REC_6_19_HOAP_PROVENANCE_TRANSFERABILITY_FA.md`
- `HISTORY_RECONCILIATION_V0_7_FA.md`
- `WORKSPACE_LINKS.md`

## قدم بعدی حاکم

1. `D0 Contract Freeze`: review پزشکی/پرستاری/داروسازی، terminology، privacy و correction/dedup policy؛
2. `D1 Synthetic Fixtures`: رخدادهای مصنوعی Level 2/3/ambiguous/duplicate/conflicting، بدون recommendation درمانی؛
3. `D2 Data Mapping Evaluation`: سنجش پوشش و missingness پرونده‌های فعلی بدون Rule یا alert؛
4. `D3 Human Review Validation`: بررسی misclassification و false merge/split؛
5. بازیابی مستقل HOAP Supplement 1 و PHT2 full reporting؛
6. فقط پس از بسته‌شدن تمام گیت‌ها، Formalization Reassessment.

PR پژوهش باید همچنان Draft باقی بماند.
