# ADA 2026 Research Workspace — Links

## وضعیت نسخهٔ v0.9.3

- Section 6 Recommendation records: `24`
- Studies screened for Recommendation 6.19: `17`
- Full-text extractions: `10`
- Article-level appraisals: `16`
- Sealed formal method/result appraisals: `9`
- Provisional PHT2 result appraisal: `1`
- GRADE Evidence Units: `10`
- Search Log records: `45`
- Open conflicts: `43`
- Decision records: `74`
- Computability requirements audited: `28`
- Minimum Data Contract fields: `43`
- Rule candidates: `0`
- Accepted clinical Rules: `0`
- Runtime changes: `0`
- UI changes: `0`
- Licensing: `HOLD`
- Clinical activation: `BLOCKED`
- Review model: `two-pass same evaluator; not independent human appraisal`

## Google Drive

- Research root: https://drive.google.com/drive/folders/1UaeH0BiGTu_83m0sdoiNl_TpaY3lr37e
- ADA folder: https://drive.google.com/drive/folders/1O6HrtOl3oU6X4ceKCb-s6ATUD_Gu4wtc
- Workbook folder: https://drive.google.com/drive/folders/1hGafgckxY1KD5ScZdOaGYiLLfvX0I5QI
- **Native Google Sheet v0.9.3 — Local Computability Gap Assessment:** https://docs.google.com/spreadsheets/d/1x2tHD54tphkDXgmjQzmxHwHbA1CNXWTfzC236Z5j830/edit
- Parent Native Google Sheet v0.9.2 — preserved: https://docs.google.com/spreadsheets/d/1p-ugp_yQ3pVqbSN1I-IwremZ4P65sSEi3AtReFeyVbc/edit
- Parent Native Google Sheet v0.8 — preserved: https://docs.google.com/spreadsheets/d/1E99uz5cBc1vENqMMi6r25Sb2ZkeGCQf3MhJz0dZU90w/edit
- Evidence Dossier folder: https://drive.google.com/drive/folders/1V00DWnlQDCeYTSVjAQy6oN4bZfmTTxRt
- GRADE/HOAP v0.8 folder: https://drive.google.com/drive/folders/1ySaa4cyqbc6V5JN7L1sUuwbDZy8w8u_j
- GRADE consistency audit: https://docs.google.com/document/d/1A8I4pIJ4gtsp2nCrQLcolZKZAfYSFKg9pNvugjOjxZc
- HOAP provenance and transferability: https://docs.google.com/document/d/1hYd4fN3FKOrqAmyBVWT80VIqjIkyTgSZXgN2U2bsEKI
- Post-cutoff update v0.7: https://docs.google.com/document/d/1r_EEWHzw1bSIPf1CGQ7jTPEmK0xWQLqAM1AO8hLsJP4
- HOAP RCT appraisal v0.7: https://docs.google.com/document/d/1hf9pehL2sTOt4YVWe7h-bpu4cWL9G9zGAQsjDJ6vtE0
- PHT2 preliminary appraisal v0.7: https://docs.google.com/document/d/1Mwe_kZSiYrH27GPc-3ZMBriIiKgMNlZprb20cIWkOh0
- Primary citation chain: https://docs.google.com/document/d/1o7dcRVzFL4nTBJMtOWCMPMmdF3tVfq8EES_OfLFxA94
- GRADE evidence profile: https://docs.google.com/document/d/1e_1clvoRnCdKxOiQJ5JeN3uXY5p9iWcI5D5W2MZPDrw
- KDIGO cross-guideline review: https://docs.google.com/document/d/1dCQ4Xq33fAzZT7XgJKepPUNqNKr6QuE1zMkNLDEmPVg

## Workbook v0.9.3

Sheetهای جدید:

- `17_Computability_Audit`: 28 نیاز code-to-evidence و وضعیت availability/gap/fail-closed behavior؛
- `18_Min_Data_Contract`: قرارداد پژوهشی 43فیلدی برای event، medication، renal/CGM، patient context، local applicability و clinician disposition؛
- `16_Version_History`: lineage میان v0.8، v0.9.2 و v0.9.3.

وضعیت رسمی:

```text
Review trigger          = NOT_COMPUTABLE
Medication action       = HARD_BLOCK
Minimum Data Contract   = DEFINED — RESEARCH ONLY
Rule Candidate          = 0
Runtime/UI changes      = 0
```

## Repository

- Repository: `Emad211/clinic_managment`
- Branch: `research/ada-2026-evidence-v0.2`
- Draft PR: `#60`
- Protected PDFs and binary workbooks are not committed.
- Native Sheet v0.9.2 is preserved; v0.9.3 is a separate versioned copy.
- Git contains the detailed Persian assessment, status JSON and compact machine-readable indexes. The full matrices remain in the Native Sheet and downloadable package.

## Local downloadable package

- Package: `clinic_rule_research_continuation_v0_9_3.zip`
- SHA-256: `3ae7cafb35e6a1f8f7531719f9f0f7e796034755781fa00c86fa47240119e795`
- Contents:
  - exported XLSX;
  - Persian local-computability assessment؛
  - status JSON؛
  - full 43-field Minimum Data Contract JSON؛
  - full 28-row Computability Gap Matrix JSON؛
  - checksum manifest.

## Current evidence and computability boundary

PHT2 Protocol/SAP is available but final reporting/CONSORT and the Final PCORI Report remain pending. HOAP supports research into an active clinician/pharmacist-owned workflow, but its Supplement 1 date/version chronology and internal guideline/reuse rights remain unaudited.

The current product has reusable reconciliation, observation, conflict and clinician-task foundations. It does not yet have a governed hypoglycemia-event identity/level contract, Level 3 assistance/function facts, event deduplication, medication indication/actual exposure/causality, validated renal/CGM/patient-capacity profiles, local capability registry or structured clinician review disposition.

Therefore:

- one low observation is not a verified event؛
- glucose does not establish Level 3؛
- missing assistance is not `false`؛
- medication class is not a culprit medication؛
- no medication action is computable or authorized؛
- no Rule Candidate exists.
