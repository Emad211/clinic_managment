# ADA-04 — Research Contract Freeze برای رخداد و بازبینی هیپوگلیسمی
## نسخهٔ v0.9.4

**پروژه:** Specialist Clinic — Clinical Rule Library Rebuild  
**گایدلاین مادر:** ADA Standards of Care in Diabetes—2026  
**Recommendation جاری:** 6.19  
**مرحله:** ADA-04 / D0 Contract Freeze  
**تاریخ:** 2026-08-01  
**شاخه:** `research/ada-2026-evidence-v0.2`  
**PR:** Draft #60  
**ماهیت:** قرارداد پژوهشی داده و workflow؛ نه schema migration، نه Rule بالینی و نه تغییر Runtime/UI

---

## 1. نتیجهٔ حاکم

v0.9.3 ثابت کرد که رخداد قابل‌اعتماد و medication action در مدل فعلی computable نیستند. v0.9.4 این شکاف را با کدنویسی عجولانه پر نکرد؛ بلکه قرارداد پژوهشی لازم برای بررسی معماری، بالینی، privacy و validation را freeze کرد.

```text
Event/Review Contract clauses = 38
Synthetic fixtures            = 20
Schema migration              = NOT_APPROVED
Executable fixtures           = NOT_IMPLEMENTED
Review trigger in product     = NOT_COMPUTABLE
Medication action             = HARD_BLOCK
Rule candidates               = 0
Runtime/UI changes            = 0
Clinical activation           = BLOCKED
```

---

## 2. معماری رخداد

### Root identity

هر episode یک `event_id` پایدار دارد. patient identity، creator و creation time غیرقابل‌ویرایش‌اند. merge یا correction هیچ identity و provenance قبلی را حذف نمی‌کند.

### Version chain

تمام تغییرها نسخهٔ جدید می‌سازند:

```text
root version
→ superseding version
→ corrected / confirmed / rejected / conflict / entered-in-error version
```

- UPDATE و DELETE ممنوع‌اند؛
- transition علیه head قدیمی atomically رد می‌شود؛
- occurrence time و recorded time جدا هستند؛
- reporter و recorder جدا هستند؛
- verification و classification basis برای هر version traceable است.

### Event status

```text
CANDIDATE
PROVISIONAL
CONFIRMED
CONFLICT
REJECTED
ENTERED_IN_ERROR
```

تنها یک **نسخهٔ دقیق CONFIRMED** می‌تواند منبع یک review case governed باشد. candidate، provisional و conflict فقط به data-quality/adjudication مسیر می‌روند و task بالینی تولید نمی‌کنند.

---

## 3. Evidence links

شاهدها به event لینک می‌شوند و داخل event کپی نمی‌شوند. نقش‌های مجاز:

```text
GLUCOSE
ASSISTANCE
ALTERED_FUNCTION
SYMPTOM
TREATMENT
SETTING
ENCOUNTER
OTHER
```

این نقش‌ها قابل‌جایگزینی نیستند. glucose به‌تنهایی assistance یا altered function را ثابت نمی‌کند. source system، source record identity، device/method، observed value/unit و verification نگه‌داری می‌شوند.

---

## 4. Duplicate و correction

Duplicate fingerprint فقط candidate تولید می‌کند. score الگوریتم هرگز merge نهایی انجام نمی‌دهد.

تصمیم‌های dedup:

```text
MERGE
SPLIT
DISTINCT
NEEDS_MORE_DATA
```

تصمیم انسانی accountable و append-only است. original IDs و source links باقی می‌مانند. correction نیز نسخهٔ جدید یا `ENTERED_IN_ERROR` می‌سازد و هیچ ردیفی حذف نمی‌شود.

---

## 5. Clinician review contract

Review case به یک event version دقیق متصل است و contract immutable دارد:

- contract version و content hash؛
- required Fact keys؛
- minimum verification؛
- allowed outcome types؛
- owner و urgency؛
- append-only state transitions.

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

فقدان یا conflict هر Fact الزامی، readiness را fail closed می‌کند.

---

## 6. Clinician disposition

سیستم در آینده ممکن است فقط تصمیم clinician را ثبت کند:

```text
NO_CHANGE
MEDICATION_CHANGE
EDUCATION
DEVICE_REVIEW
REFERRAL
FOLLOWUP
OTHER
```

اما این contract:

- تصمیم دارویی تولید نمی‌کند؛
- prescription یا order اجرا نمی‌کند؛
- referral خارجی ایجاد نمی‌کند؛
- patient-facing treatment directive نمی‌سازد؛
- guideline wording محافظت‌شده را وارد payload نمی‌کند.

یک `MEDICATION_CHANGE` ثبت‌شده فقط گزارش تصمیم independently authored clinician است، نه recommendation موتور.

---

## 7. Privacy و data minimization

قرارداد پژوهشی مجوز جمع‌آوری نامحدود داده نیست. اصول:

- reference و coded essentials به‌جای کپی source payload؛
- actor/device IDs به‌اندازهٔ نیاز audit؛
- محدودکردن narrative؛
- versioned access/retention policy؛
- privacy/security approval پیش از prototype؛
- synthetic-only برای D1.

---

## 8. Synthetic fixture catalog

۲۰ fixture طراحی شد. هیچ fixture دادهٔ واقعی بیمار ندارد و هیچ therapeutic expected output مجاز نیست.

پوشش:

- measured Level 2 evidence؛
- Level 3 بدون glucose؛
- missing occurrence time؛
- patient-reported provisional evidence؛
- duplicate CGM/EMS records؛
- conflicting assistance reports؛
- late reporting؛
- correction و entered-in-error؛
- medication indication/exposure gaps؛
- stale renal context؛
- incomplete CGM pattern؛
- cognition/support gap؛
- local availability gap؛
- clinician-recorded no-change/change؛
- forbidden automatic medication action؛
- stale-head transition؛
- cross-patient source mismatch.

Global fixture invariant:

```text
Expected automatic medication action = NONE / FORBIDDEN
```

---

## 9. Reuse از معماری موجود

قابل reuse:

- immutable clinical task contracts؛
- append-only task event chains؛
- source system/record uniqueness؛
- content hashes؛
- canonical outcome links؛
- conflict-aware reconciliation؛
- fail-loud completion evidence.

نیازمند domain جدا:

- hypoglycemia event identity/version؛
- evidence roles؛
- Level 3 assistance/function semantics؛
- duplicate candidate/adjudication؛
- structured review disposition.

Reuse زیرساخت هیچ Rule یا schema قدیمی را grandfather نمی‌کند.

---

## 10. Release gates

پیش از هر implementation:

1. clinical review؛
2. nursing/pharmacy review؛
3. architecture review؛
4. privacy/security/data-minimization review؛
5. terminology review؛
6. independent human methodological review؛
7. executable synthetic integrity tests؛
8. migration/rollback plan؛
9. evidence/licensing/local applicability gates؛
10. explicit approval for prototype stage.

Failure هر گیت، مرحلهٔ بعد را BLOCK می‌کند.

---

## 11. وضعیت Workbook v0.9.4

- Search Log: 48؛
- Open conflicts: 43؛
- Decision records: 82؛
- Minimum Data Contract: 43 fields؛
- Event/Review Contract: 38 clauses؛
- Synthetic fixtures: 20؛
- Rule candidates: 0؛
- Accepted Rules: 0؛
- Runtime/UI changes: 0.

Native Sheet:

https://docs.google.com/spreadsheets/d/1q344KGq1lUsncMofTtPSvEYKTmR2iJ0y6xSUnZsBDjY/edit

Parent v0.9.3 preserved:

https://docs.google.com/spreadsheets/d/1x2tHD54tphkDXgmjQzmxHwHbA1CNXWTfzC236Z5j830/edit

---

## 12. نتیجهٔ نهایی

```text
Contract status        = RESEARCH_FROZEN
Implementation         = NOT_APPROVED
Synthetic fixtures     = DESIGNED_NOT_EXECUTABLE
Rule candidates        = 0
Medication automation  = FORBIDDEN
Runtime/UI changes     = 0
Licensing              = HOLD
Clinical activation    = BLOCKED
```

قدم بعدی فقط review چندتخصصی D0 و سپس پیاده‌سازی testهای synthetic data-integrity است؛ نه clinical action coding.
