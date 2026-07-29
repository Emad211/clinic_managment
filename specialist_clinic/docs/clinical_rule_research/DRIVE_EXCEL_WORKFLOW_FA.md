# گردش‌کار Google Drive و Excel برای پژوهش Rule Library

## ساختار Drive

```text
Clinical-Rules-Research/
├── 00_Governance
├── 01_Protocols
├── 02_Guidelines
├── 03_Search-Strategies
├── 04_Search-Results
├── 05_Full-Text-Papers
├── 06_Extraction
├── 07_Quality-Appraisal
├── 08_Conflict-Matrices
├── 09_Iranian-Context
├── 10_Rule-Dossiers
├── 11_Validation
└── 12_Archive
```

برای هر گایدلاین یک پوشهٔ نسخه‌دار ساخته می‌شود. فایل‌های محافظت‌شدهٔ ناشر بدون مجوز در Drive مشترک یا Git منتشر نمی‌شوند؛ به‌طور پیش‌فرض metadata، لینک رسمی، checksum و یادداشت مستقل نگهداری می‌شود.

## Workbook مرکزی

نام الگو: `Clinical_Rule_Evidence_Master.xlsx`

Sheetهای الزامی:

1. Guideline Registry
2. Guideline Appraisal
3. Recommendation Inventory
4. Search Log
5. Article Screening
6. Full-text Extraction
7. Risk of Bias
8. Evidence Mapping
9. Conflict Matrix
10. Iranian Context
11. Rule Candidate Registry
12. Computability Assessment
13. Validation Cases
14. Decision Log
15. Version History

## شناسه‌ها

- Guideline: `GDL-DM-001`
- Recommendation: `REC-DM-001`
- Article: `ART-DM-0001`
- Clinical Question: `CQ-DM-001`
- Evidence Unit: `EU-DM-001`
- Rule Candidate: `RULE-DM-001`
- Conflict: `CONFLICT-DM-001`
- Dossier: `DOS-DM-001-V1`

هیچ رکوردی بدون ID و provenance وارد وضعیت VERIFIED نمی‌شود.

## گردش‌کار مقاله

`IDENTIFIED → TITLE_ABSTRACT_INCLUDED → FULLTEXT_REQUESTED → FULLTEXT_INCLUDED → EXTRACTED_PASS1 → EXTRACTED_PASS2 → ROB_COMPLETE → EVIDENCE_MAPPED`

هر حذف نیازمند دلیل است. Abstract-only finalization ممنوع است، مگر متن کامل واقعاً غیرقابل دسترس باشد و مقاله نقش تعیین‌کننده نداشته باشد؛ این محدودیت باید صریح ثبت شود.

## دو Pass

- Pass 1: استخراج و appraisal اولیه.
- Pass 2: بازخوانی خصمانه با تمرکز بر subclause، population، directness، harm، missing data و تعارض.

هر دو Pass توسط همان ارزیاب انجام می‌شوند و هرگز به‌عنوان دو ارزیاب انسانی مستقل معرفی نمی‌شوند.

## منبع حقیقت

- متن کامل مقاله/گایدلاین: منبع حقیقت محتوا.
- Workbook: منبع حقیقت وضعیت و workflow.
- Git: منبع حقیقت اسناد مصوب، protocol، scope، dossier و decision history.
- Clinical Engine: فقط مصرف‌کنندهٔ Ruleهای approved و versioned.

## نسخه‌بندی

نسخهٔ جدید Workbook جایگزین یا حذف نسخهٔ قبلی نمی‌شود. هر نسخه در Drive نگهداری و در `WORKSPACE_LINKS.md` ثبت می‌شود. اسناد مصوب در Git commit می‌شوند. هر package دارای manifest و SHA-256 است.

## قواعد داده

- URL رسمی در ستون Source ذخیره شود.
- locator دقیق صفحه/جدول/Recommendation ثبت شود.
- نقل کامل متن محافظت‌شده در Sheet مشترک ممنوع است؛ paraphrase مستقل استفاده شود.
- Grade منبع، GRADE مستقل، directness و recommendation strength ستون‌های جدا هستند.
- تعارض و safety signal هیچ‌گاه با average یا حذف حل نمی‌شود.
- Rule count تا عبور تمام Gateها صفر می‌ماند.
