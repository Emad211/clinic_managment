# ADA-04 — ارزیابی قابلیت محاسبهٔ محلی Recommendation 6.19
## نسخهٔ پژوهشی v0.9.3

**پروژه:** Specialist Clinic — Clinical Rule Library Rebuild  
**گایدلاین مادر:** ADA Standards of Care in Diabetes—2026  
**Recommendation جاری:** 6.19  
**مرحله:** ADA-04 — Formalization Readiness / Local Computability  
**تاریخ:** 2026-08-01  
**شاخه:** `research/ada-2026-evidence-v0.2`  
**PR:** Draft #60  
**ماهیت سند:** ممیزی پژوهشی و قرارداد داده؛ نه Rule بالینی، نه schema migration تأییدشده و نه تغییر Runtime/UI

---

## 1. نتیجهٔ حاکم

پس از تطبیق Recommendation 6.19، شواهد PHT2/HOAP، وابستگی‌های ADA/KDIGO و مدل دادهٔ واقعی سامانه، نتیجهٔ Formalization Readiness چنین است:

```text
Verified clinician-review trigger = NOT_COMPUTABLE
Medication action                 = HARD_BLOCK
Rule candidates                   = 0
Accepted Rules                    = 0
Runtime/UI changes                = 0
Licensing                         = HOLD
Clinical activation               = BLOCKED
```

این نتیجه به معنی شکست موتور نیست. موتور و قراردادهای فنی پایه وجود دارند؛ اما Factهایی که برای فهم درست «یک رخداد»، علت احتمالی، داروی مرتبط و توانایی اجرای تصمیم لازم‌اند هنوز کامل و قابل‌اعتماد نیستند. ساخت Rule پیش از حل این شکاف‌ها، missing را به false یا یک observation را به event تبدیل می‌کرد.

---

## 2. مبنای بالینی

ADA 2026 در Recommendation 6.19 می‌گوید رخداد Level 2 یا Level 3 باید باعث بازبینی طرح درمان شود و هر deintensification یا switch فقط در صورت مناسب‌بودن انجام شود.

مرزهای داده‌ای مهم:

- Level 2 با glucose کمتر از 54 mg/dL تعریف می‌شود؛
- Level 3 به تغییر عملکرد ذهنی یا جسمی و نیاز به کمک شخص دیگر وابسته است و به وجود عدد glucose وابسته نیست؛
- Level 2 و Level 3 دو مسیر شواهد متفاوت‌اند؛
- یک low reading، یک event deduplicated نیست؛
- CGM pattern با یک event واحد یک مفهوم نیست؛
- cognition، function، frailty، support، kidney function، medication indication و preferences روی بازبینی اثر می‌گذارند.

منابع رسمی:

- https://pmc.ncbi.nlm.nih.gov/articles/PMC12690178/
- https://diabetesjournals.org/care/article/49/Supplement_1/S277/163921/13-Older-Adults-Standards-of-Care-in-Diabetes-2026

شرایط reuse و software adaptation ADA همچنان روشن نشده و Licensing روی HOLD است.

---

## 3. زیرساخت‌های قابل‌استفادهٔ موجود

### 3.1 Reconciliation

سامانه برای condition، medication و allergy یک تاریخچهٔ append-only، snapshot hash، completeness، conflict و patient confirmation دارد. Medication projection فعلی شامل نام، class، dose، schedule و interval است و concept مبهم را fail closed نگه می‌دارد.

### 3.2 Observations

vital و lab observationها value، unit، effective time، source و verification دارند. eGFR، UACR و HbA1c نیز در lab catalog وجود دارند.

### 3.3 Conflict و uncertainty

مدل Fact موجود می‌تواند `CONFIRMED`، `PROVISIONAL`، `UNVERIFIED`، `UNKNOWN` و conflict را حفظ کند. این پایه باید در event contract جدید نیز باقی بماند.

### 3.4 Clinician task

Task contractهای immutable، urgency، acknowledgement، required fact keys و minimum verification را پشتیبانی می‌کنند. اما ingestion canonical آن‌ها عمدتاً numeric observation/lab است و برای review disposition ساختاریافته کافی نیست.

نتیجه: این اجزا باید reuse شوند، ولی هیچ Rule قدیمی یا منطق بالینی قبلی grandfather نمی‌شود.

---

## 4. شکاف اول — هویت رخداد هیپوگلیسمی

مدل فعلی observation دارد ولی hypoglycemia event مستقل ندارد. یک event ایمن حداقل باید این موارد را داشته باشد:

- stable event ID؛
- event level و basis آن؛
- glucose value/unit/method در صورت وجود؛
- occurrence time جدا از recorded time؛
- reporter، recorder، device و source record links؛
- verification؛
- external assistance؛
- altered mental/physical functioning؛
- symptoms، treatment و setting؛
- duplicate fingerprint؛
- merge/split adjudication history.

بدون این قرارداد:

- یک low ممکن است چندبار شمرده شود؛
- Level 3 ممکن است از glucose حدس زده شود؛
- نبود assistance ممکن است به false تبدیل شود؛
- زمان رخداد با زمان ثبت اشتباه شود؛
- recurrence قابل‌اعتماد محاسبه نمی‌شود.

بنابراین حتی clinician-review trigger فعلاً `NOT_COMPUTABLE` است.

---

## 5. شکاف دوم — زمینهٔ دارویی

Medication list فعلی یک پایهٔ مفید است، ولی برای action کافی نیست.

### Factهای مفقود یا ناقص

- indication هر medication؛
- actual administration time و dose؛
- adherence، missed/extra dose و meal mismatch؛
- reason برای start/stop/dose change؛
- suspected contributor و causality certainty؛
- event-time medication snapshot بدون approximation؛
- active cardiorenal indication؛
- shared decision و rationale.

Prescription با administration یکسان نیست. وجود insulin یا sulfonylurea در medication list ثابت نمی‌کند که دارو در زمان مرتبط مصرف شده یا علت رخداد بوده است.

FHIR R5 فقط به‌عنوان design reference استفاده شد:

- MedicationStatement برای reason/adherence و بازهٔ مصرف؛
- MedicationAdministration برای occurrence/performer/dose؛
- AdverseEvent برای suspected agent و causality؛
- Provenance برای who/what/when.

منابع رسمی:

- https://hl7.org/fhir/medicationstatement.html
- https://hl7.org/fhir/medicationadministration.html

استفاده از این semantics به معنی الزام به پیاده‌سازی کامل FHIR نیست.

---

## 6. شکاف سوم — زمینهٔ کلیه، اندازه‌گیری و CGM

سامانه eGFR، UACR و HbA1c را می‌تواند ذخیره کند؛ اما موارد زیر هنوز canonical/validated نیستند:

- renal trajectory؛
- AKI state؛
- dialysis/KRT؛
- HbA1c reliability؛
- CGM dataset identity؛
- wear percentage و valid days؛
- TBR calculation window و algorithm version.

یک eGFR منفرد نمی‌تواند chronic stage را از acute decline جدا کند. A1C در بعضی contextهای کلیوی/خونی قابل‌اعتماد نیست. یک CGM low نیز pattern پایدار را ثابت نمی‌کند.

---

## 7. شکاف چهارم — ظرفیت بیمار و زمینهٔ رخداد

برای individualized review، این profileها باید versioned و زمان‌دار باشند:

- hypoglycemia awareness و fear؛
- cognition، function و frailty؛
- meal intake، fasting، illness، vomiting و dehydration؛
- caregiver/support capacity؛
- self-management ability؛
- preferences، burden و goals؛
- cost، formulary و device access؛
- referral و monitoring capacity.

Generic flag catalog به‌تنهایی کافی نیست؛ instrument/version، authored time، author، source، interpretation و expiry لازم‌اند.

---

## 8. Minimum Data Contract v0.9.3

یک قرارداد 43فیلدی پژوهشی ساخته شد و در Sheet `18_Min_Data_Contract` و JSON همراه ثبت شد. گروه‌های آن:

- Event: 17 فیلد؛
- Medication/exposure/causality: 11 فیلد؛
- Renal/cardiorenal: 3 فیلد؛
- Glycemic goals/validity/CGM: 3 فیلد؛
- Patient capacity/context/support: 5 فیلد؛
- Local applicability: 2 فیلد؛
- Workflow ownership/disposition: 2 فیلد.

این قرارداد یک schema migration نیست. پیش از implementation باید architecture، privacy، clinical review، terminology، validation و migration plan مستقل تصویب شوند.

---

## 9. Fail-closed behavior

برای هر Fact الزامی، خروجی نبود/ابهام فقط یکی از این موارد است:

```text
NEEDS_DATA
CONFLICT
EVIDENCE_INCOMPLETE
NOT_APPLICABLE_OR_REVIEW
CLINICIAN_REVIEW
```

خروجی‌های ممنوع:

```text
missing -> false
provisional -> confirmed
one low observation -> one verified event
medication class -> culprit medication
event -> automatic medication action
```

`UNKNOWN` یک وضعیت درجه‌اول است و نباید حذف شود.

---

## 10. وضعیت HOAP Supplement 1

بازیابی binary رسمی Supplement 1 دوباره امتحان شد. وجود و نام فایل تأیید است، اما content، signature، original date و amendment chronology هنوز page-audit نشده‌اند.

قاعده همچنان:

```text
DOCUMENT LISTED != DOCUMENT AUDITED
```

این hold مستقل از Computability Assessment است و بسته نشده است.

---

## 11. طراحی مرحلهٔ بعد — بدون کدنویسی بالینی

### D0 — Contract Freeze

- review پزشکی/پرستاری/داروسازی روی 43 فیلد؛
- تعریف terminology؛
- privacy/data minimization؛
- event correction و duplicate adjudication؛
- source/verification policy.

### D1 — Synthetic Fixtures

- ساخت fixtureهای مصنوعی Level 2، Level 3، ambiguous، duplicate و conflicting؛
- هیچ دادهٔ واقعی بیمار و هیچ recommendation درمانی.

### D2 — Data Mapping Evaluation

- سنجش اینکه پرونده‌های فعلی چه درصدی از contract را پر می‌کنند؛
- missingness و source reliability؛
- بدون اجرای Rule یا alert.

### D3 — Human Review Validation

- مقایسهٔ event construction و missing-fact checklist با clinician review؛
- inter-rater agreement؛
- false merge/split و misclassification.

### D4 — Formalization Reassessment

فقط پس از بسته‌شدن Evidence، Licensing، Local Applicability، Independent Review و validation می‌توان بررسی کرد که clinician-review concept به C2/SILENT candidate برسد یا خیر.

Medication action حتی در آن مرحله نیز به evidence unit و validation مستقل نیاز دارد.

---

## 12. Workbook و KPIهای v0.9.3

- Search Log: 45؛
- Open conflicts: 43؛
- Decision records: 74؛
- Computability requirements: 28؛
- Minimum data fields: 43؛
- Rule candidates: 0؛
- Accepted Rules: 0؛
- Runtime/UI changes: 0.

Native Google Sheet:

https://docs.google.com/spreadsheets/d/1x2tHD54tphkDXgmjQzmxHwHbA1CNXWTfzC236Z5j830/edit

Parent v0.9.2 preserved:

https://docs.google.com/spreadsheets/d/1p-ugp_yQ3pVqbSN1I-IwremZ4P65sSEi3AtReFeyVbc/edit

---

## 13. نتیجهٔ نهایی

v0.9.3 یک Rule نساخت؛ دقیقاً مشخص کرد برای ساخت امن چه چیزی وجود دارد و چه چیزی هنوز وجود ندارد.

```text
Clinical evidence role     = clinician-owned workflow research only
Review trigger             = NOT_COMPUTABLE
Medication action          = HARD_BLOCK
Minimum data contract      = DEFINED — RESEARCH ONLY
Rule candidates            = 0
Accepted Rules             = 0
Runtime/UI changes         = 0
Licensing                  = HOLD
Clinical activation        = BLOCKED
```
