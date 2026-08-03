# ADA 2026 Research Workspace — Links

## وضعیت نسخهٔ v0.9.4

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
- Rule candidates: `0`
- Accepted clinical Rules: `0`
- Runtime/UI changes: `0`
- Licensing: `HOLD`
- Clinical activation: `BLOCKED`
- Review model: `two-pass same evaluator; not independent human appraisal`

## Google Drive

- Research root: https://drive.google.com/drive/folders/1UaeH0BiGTu_83m0sdoiNl_TpaY3lr37e
- ADA folder: https://drive.google.com/drive/folders/1O6HrtOl3oU6X4ceKCb-s6ATUD_Gu4wtc
- Workbook folder: https://drive.google.com/drive/folders/1hGafgckxY1KD5ScZdOaGYiLLfvX0I5QI
- **Native Google Sheet v0.9.4 — Event and Review Contract Freeze:** https://docs.google.com/spreadsheets/d/1q344KGq1lUsncMofTtPSvEYKTmR2iJ0y6xSUnZsBDjY/edit
- Parent v0.9.3 — preserved: https://docs.google.com/spreadsheets/d/1x2tHD54tphkDXgmjQzmxHwHbA1CNXWTfzC236Z5j830/edit
- Parent v0.9.2 — preserved: https://docs.google.com/spreadsheets/d/1p-ugp_yQ3pVqbSN1I-IwremZ4P65sSEi3AtReFeyVbc/edit
- Parent v0.8 — preserved: https://docs.google.com/spreadsheets/d/1E99uz5cBc1vENqMMi6r25Sb2ZkeGCQf3MhJz0dZU90w/edit
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

## Workbook lineage

`16_Version_History` اکنون این زنجیره را ثبت می‌کند:

```text
v0.8
→ v0.9.2
→ v0.9.3 Local Computability
→ v0.9.4 Event/Review Contract Freeze
```

Sheetهای پژوهش جدید:

- `17_Computability_Audit`: 28 نیاز code-to-evidence؛
- `18_Min_Data_Contract`: قرارداد 43فیلدی؛
- `19_Event_Review_Contract`: 38 clause برای event/evidence/dedup/review/disposition؛
- `20_Synthetic_Fixtures`: 20 fixture مصنوعی، غیرقابل‌اجرا در این مرحله.

## وضعیت رسمی D0

```text
Review trigger in current product = NOT_COMPUTABLE
Medication action                 = HARD_BLOCK
Event/Review Contract             = RESEARCH_FROZEN
Schema migration                  = NOT_APPROVED
Synthetic fixtures                = DESIGNED_NOT_EXECUTABLE
Rule candidates                   = 0
Runtime/UI changes                = 0
```

## Repository

- Repository: `Emad211/clinic_managment`
- Branch: `research/ada-2026-evidence-v0.2`
- Draft PR: `#60`
- Protected PDFs and binary workbooks are not committed.
- Git contains the Persian dossier، status JSON و compact indexes.
- Full contract/fixture rows remain in the Native Sheet and downloadable package.

## Local downloadable package

- Package: `clinic_rule_research_continuation_v0_9_4.zip`
- SHA-256: `a23832f5d387463cc34c1b8a23f9f5b3eb7cf7345e9e3eb4893c833898c104c8`
- Contents:
  - exported XLSX؛
  - Persian Contract Freeze dossier؛
  - status JSON؛
  - full 38-clause Event/Review Contract JSON؛
  - full 20-case Synthetic Fixture JSON؛
  - checksum manifest.

## Safety boundary

- event roots/versions/evidence/corrections append-only هستند؛
- automatic merge ممنوع است و human adjudication لازم است؛
- فقط exact CONFIRMED event version می‌تواند منبع review case باشد؛
- review contract immutable و fail-closed است؛
- clinician disposition فقط ثبت می‌شود و order/prescription/referral اجرا نمی‌کند؛
- تمام fixtureها synthetic هستند؛
- therapeutic expected output در fixtureها ممنوع است؛
- هیچ Rule Candidate وجود ندارد.

## Evidence holds

- PHT2 full results/CONSORT و Final PCORI Report بازند؛
- HOAP Supplement 1 binary/date/version chronology page-audit نشده است؛
- internal HOAP guideline و software reuse rights در دسترس نیستند؛
- licensing و independent human appraisal بازند.
