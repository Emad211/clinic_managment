# Follow-up Orchestration & UX v1 — Canonical Implementation Plan

> **نام فایل مرجع:** `specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md`
>
> **کد برنامه:** `FOUX-V1`
>
> **نسخه:** `1.4.0`
>
> **آخرین بازبینی:** `2026-08-03`
>
> **وضعیت:** `FO_0_VALIDATED / FO_1_VALIDATED / FO_2_VALIDATED / FO_3_TECHNICALLY_VALIDATED / FO_3_LOCAL_UX_ACCEPTANCE_PENDING`
>
> **مالک:** `Emad211`
>
> **دامنه:** فقط `specialist_clinic/`
>
> **طبقه‌بندی محیط فعلی:** `TEST_ONLY / SYNTHETIC_OR_RESETTABLE_DATA`
>
> **خارج از دامنه:** تغییر Rule بالینی، گسترش Hypoglycemia Shadow، تصمیم درمانی خودکار، Write به `clinic_new.db` و تغییر رفتار `webapp/`.

---

## 1. هدف سند

این سند Source of Truth اجرایی برنامهٔ بازطراحی پیگیری است. هدف برنامه این است که بدون جایگزین‌کردن Source of Truthهای موجود، داده‌های پراکندهٔ پیگیری به یک Episode قابل‌ردیابی، Projection بازسازی‌پذیر و تجربهٔ کاربری روشن تبدیل شوند.

این سند هم‌زمان تعیین می‌کند:

1. چه چیزی پیاده‌سازی شده است؛
2. چه چیزی فقط در حالت Shadow یا Read-only مجاز است؛
3. چه evidenceای برای عبور هر tranche لازم است؛
4. چه مواردی هنوز مسدود هستند؛
5. مسیر rollback چیست.

ترتیب اعتماد:

1. وضعیت واقعی `main`، PRها، Issues و CI؛
2. `PROJECT_STATE.json` و `PROJECT_STATE.md`؛
3. این سند و `specialist_clinic/AGENTS.md`؛
4. متن PRهای تاریخی؛
5. حافظهٔ گفتگو یا ایجنت.

---

## 2. وضعیت قطعی فعلی

| Tranche | وضعیت | Evidence اصلی |
|---|---|---|
| FO-0 | VALIDATED | baseline مصنوعی deterministic، CI و owner attestation محیط test-only |
| FO-1 | VALIDATED | Episode/Link/Event، backfill idempotent، PR #75 |
| FO-2 | VALIDATED | Projection/Policy/Parity، PR #78 |
| FO-3 | TECHNICALLY_VALIDATED | Unified Worklist و Timeline فقط‌خواندنی، PR #81 |
| FO-3 UX Acceptance | PENDING | مرور لوکال توسط مالک روی دادهٔ تست |
| FO-4 و بعد | BLOCKED | تا ثبت attestation مرور UX و تصمیم جدید در سند |

### 2.1 وضعیت Git حاکم

- FO-3 tracking issue: `#80`
- FO-3 implementation PR: `#81`
- FO-3 final head: `14e8bf56782ead4ccef46db05eb8c4b6b034d263`
- FO-3 merge commit: `afed3545c0a90a1ed7ff7e0a892df89fffac00c2`
- FO-3 final CI run: `30775348057`
- Specialist tests: `754 passed`
- Accounting tests: `54 passed`

### 2.2 تصحیح سابقه

در آغاز FO-3، branch با `main` یکسان و بدون commit بود. هر ادعای قبلی مبنی بر push شدن FO-3 پیش از PR #81 فاقد evidence Git بود و معتبر نیست. فقط commitها، PR و CI ثبت‌شده در بخش 2.1 مبنای وضعیت فعلی‌اند.

---

## 3. طبقه‌بندی داده و حدود ایمنی

`specialist.db` در محیط فعلی فقط دادهٔ تستی، مصنوعی یا resettable دارد. بنابراین:

- baseline و cohort تستی می‌توانند deterministic باشند؛
- ریسک PHI واقعی در این محیط انتظار نمی‌رود؛
- این فرض قبل از ورود هر دادهٔ واقعی باید لغو و production-readiness review انجام شود؛
- هیچ گزارش CI یا CLI نباید نام، تلفن، متن پیام، note آزاد یا مقدار بالینی خام را چاپ کند؛
- `clinic_new.db` برای Specialist همچنان read-only است.

این طبقه‌بندی مجوز کاهش کنترل‌های امنیتی، audit، authorization یا clinical safety نیست.

---

## 4. معماری حاکم

```text
Authoritative source tables
        │
        ▼
Follow-up Episode / Link / Event      [FO-1]
        │
        ▼
Deterministic Work Item Projection    [FO-2, cache only]
        │
        ▼
Read-only Unified Worklist/Timeline   [FO-3, feature gated]
        │
        └── deep-link only ──► Legacy authoritative action surfaces
```

### 4.1 Source of Truthهای موجود

منابع فعلی همچنان حاکم‌اند، از جمله:

- `followup_tasks`
- `clinical_task_events`
- `clinical_outcome_events`
- `care_plan_commitments`
- `care_plan_commitment_events`
- `engagement_approvals`
- `sms_messages` و delivery state
- `appointments`
- `followup_contact_events`

Episode و Projection جایگزین حقیقت بالینی یا عملیاتی نیستند.

### 4.2 قراردادهای ذخیره‌سازی پیاده‌شده

FO-1:

- `followup_episodes`
- `followup_episode_links`
- `followup_episode_events`
- Episode identity version: `1.0`
- backfill صریح، dry-run/apply و idempotent
- عدم ساخت رابطهٔ حدسی؛ موارد مبهم orphan می‌مانند

FO-2:

- `followup_work_item_projection`
- Projection version: `1.0`
- Policy version: `FOUX-NEXT-ACTION-V1`
- state classes: `ACTION_REQUIRED`, `WAITING`, `BLOCKED`, `TERMINAL`
- projection hash و source fingerprint deterministic
- cache قابل حذف و بازسازی
- role فقط proposal؛ `owner_user_id` تا FO-4 خالی است

FO-3:

- schema جدید ندارد؛
- Read Model محدود و صفحه‌بندی‌شده روی cache FO-2؛
- source-linkها batch خوانده می‌شوند و N+1 per item وجود ندارد؛
- Timeline از Episode Eventهای append-only و snapshot خواندنی Source State ساخته می‌شود؛
- متن پیام، note آزاد، raw clinical value و payload JSON وارد Timeline نمی‌شوند؛
- request هیچ Projection rebuild یا write انجام نمی‌دهد.

---

## 5. Invariantهای غیرقابل‌مذاکره

1. Source Truthهای قبلی authoritative می‌مانند.
2. Episode و Projection حقیقت بالینی نیستند.
3. هیچ relation، event، due date، target، outcome یا assignment جعل نمی‌شود.
4. هر Projection غیرنهایی دقیقاً یک explanation از نوع action، wait یا block دارد.
5. completion بالینی فقط با evidence معتبر در lifecycle حاکم انجام می‌شود.
6. رزرو نوبت به‌تنهایی task بالینی را complete نمی‌کند.
7. FO-3 فقط خواندنی است و هیچ endpoint جدید POST/mutation ندارد.
8. CTAهای FO-3 فقط deep-link به مسیرهای حاکم‌اند.
9. role proposal به معنی claim یا assignment نیست.
10. Worklist قدیمی تا تصمیم FO-4 authority عملیاتی باقی می‌ماند.
11. هیچ تغییر در Clinical Rules یا Hypoglycemia Shadow این برنامه مجاز نیست.
12. هیچ write به دیتابیس حسابداری مجاز نیست.
13. flag خاموش باید رفتار قابل‌مشاهدهٔ قبلی را بازگرداند.
14. FO-4 و بعد بدون attestation صریح سند ممنوع است.

---

## 6. Feature Flags

همهٔ flagها به‌صورت پیش‌فرض `OFF` هستند:

| Flag | وضعیت فعلی | کاربرد |
|---|---:|---|
| `FOLLOWUP_EPISODES_ENABLED` | OFF | گیت Episode runtime |
| `FOLLOWUP_PROJECTION_SHADOW` | OFF | rebuild صریح Projection سایه |
| `FOLLOWUP_UNIFIED_WORKLIST_READONLY` | OFF | نمایش FO-3 فقط‌خواندنی |
| `FOLLOWUP_UNIFIED_WORKLIST_ACTIONS` | OFF | FO-4؛ هنوز ممنوع |
| `FOLLOWUP_AUTO_ROUTING` | OFF | routing خودکار؛ ممنوع |
| `FOLLOWUP_STRUCTURED_CONTACT` | OFF | tranche بعدی؛ ممنوع |
| `FOLLOWUP_SMS_AUTO_GUARDED` | OFF | ارسال خودکار؛ ممنوع |
| `FOLLOWUP_APPOINTMENT_SYNC` | OFF | واکنش خودکار نوبت؛ ممنوع |
| `FOLLOWUP_EVIDENCE_ASSIST` | OFF | Evidence Assist؛ ممنوع |
| `FOLLOWUP_AUTOMATION_HEALTH` | OFF | health automation؛ ممنوع |

FO-3 فقط با `FOLLOWUP_UNIFIED_WORKLIST_READONLY=1` قابل مشاهده است. در حالت OFF:

- tab جدید مخفی است؛
- routeهای `/followups/unified/` و detail، `404` می‌دهند؛
- Worklist قدیمی بدون تغییر کار می‌کند.

---

## 7. Evidence trancheها

### 7.1 FO-0 — Baseline & Governance

- Issue `#71`
- plan PR `#70`
- implementation/attestation PRهای `#72` و `#73`
- merge evidence: `901dbfdf9c358ecc09d2a60a0680f6a4a8370d17`
- `731` تست Specialist و `54` تست Accounting در evidence ثبت‌شده
- baseline aggregate و PHI-free
- owner attestation: محیط test-only

### 7.2 FO-1 — Episode, Link & Event

- Issue `#74`
- PR `#75`
- merge: `15ef1585c069a74c26fbc0ce859e03906e5f475a`
- `736` تست Specialist و `54` تست Accounting
- cohort مصنوعی: `4` Episode و `12` Link
- اجرای دوم: صفر Episode/Link جدید
- source truth digest بدون تغییر

### 7.3 FO-2 — Projection, Policy & Parity

- Issue `#77`
- PR `#78`
- merge: `6c6e33203376a32165418e0d3c6f2a4a48253e7b`
- final CI: `30773195914`
- `747` تست Specialist و `54` تست Accounting
- `4` Projection در cohort canonical
- legacy coverage: `100%`
- hidden legacy sources: `0`
- explainable mismatch: `100%`
- hash deterministic و delete/rebuild equivalent
- missing source و patient drift به‌صورت fail-closed

### 7.4 FO-3 — Read-only Unified Worklist & Timeline

- Issue `#80`
- PR `#81`
- final head: `14e8bf56782ead4ccef46db05eb8c4b6b034d263`
- merge: `afed3545c0a90a1ed7ff7e0a892df89fffac00c2`
- final CI: `30775348057`
- `754` تست Specialist و `54` تست Accounting

گیت‌های فنی عبورکرده:

- تمام Projectionهای cohort از UI صفحه‌بندی‌شده قابل کشف‌اند؛
- state/role/SLA filterها whitelist-only هستند؛
- query count لیست bounded است و source linkها batch خوانده می‌شوند؛
- routeها GET-only هستند و POST برابر `405` است؛
- flag-off برابر `404` و navigation مخفی است؛
- GET routeها digest Source Truth و Projection را تغییر نمی‌دهند؛
- Timeline deterministic و provenance-aware است؛
- Timeline فاقد SMS body، note آزاد، raw clinical value و payload JSON است؛
- stale، overdue، empty و unavailable projection states متن روشن دارند؛
- role به‌صورت «پیشنهادی» نمایش داده می‌شود؛
- Worklist قدیمی authority اقدام باقی مانده است؛
- cache-control برابر private/no-store است.

اولین CI، پنج failure ناشی از fixture فشردهٔ FO-1 بدون ستون‌های واقعی هویت بیمار پیدا کرد. fixture به schema واقعی ارتقا یافت و query محصول تضعیف نشد. دور دوم کامل سبز شد.

---

## 8. FO-3 Local UX Acceptance Gate — گام جاری

FO-3 از نظر کد، تست و CI معتبر است؛ ولی تجربهٔ کاربری rendered باید روی اجرای لوکال و دادهٔ تست توسط مالک مشاهده شود. تا ثبت نتیجهٔ این مرور، FO-4 ممنوع است.

### 8.1 آماده‌سازی ویندوز

```powershell
cd specialist_clinic
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

در صورت نیاز، دادهٔ demo استاندارد بازسازی شود:

```powershell
.\.venv\Scripts\python.exe seed_demo_data.py
```

Projection فقط به‌صورت صریح ساخته شود:

```powershell
$env:FOLLOWUP_PROJECTION_SHADOW = "1"
.\.venv\Scripts\python.exe scripts\rebuild_followup_projection.py `
  --database specialist.db `
  --as-of "2026-08-03 12:00:00" `
  --apply
```

سپس UI فقط‌خواندنی فعال و برنامه اجرا شود:

```powershell
$env:FOLLOWUP_UNIFIED_WORKLIST_READONLY = "1"
.\.venv\Scripts\python.exe start.py
```

ورود توسعه طبق README فعلی: `admin / admin`؛ آدرس: `http://127.0.0.1:8090`.

### 8.2 مسیر مرور

1. ورود به «هاب پیام»؛
2. انتخاب «نمای یکپارچه»؛
3. تست جستجو و فیلترهای وضعیت، نقش و موعد؛
4. بررسی badgeهای stale و overdue؛
5. بازکردن detail هر چهار Episode تستی؛
6. بررسی خوانایی Timeline و audit details؛
7. بررسی deep-link به Worklist فعلی، پرونده و صف پیام؛
8. بررسی موبایل/عرض کم، keyboard focus و RTL؛
9. تأیید اینکه هیچ CTA حس «تکمیل داخل این صفحه» ایجاد نمی‌کند؛
10. خاموش‌کردن flag و تأیید ناپدیدشدن tab و `404` route.

### 8.3 معیار attestation مالک

برای عبور gate باید نتیجهٔ زیر ثبت شود:

```text
FO3_UX_ACCEPTED = true|false
reviewer = Emad211
reviewed_commit = afed3545c0a90a1ed7ff7e0a892df89fffac00c2
reviewed_on_test_data = true
critical_ux_defects = 0
notes = <خلاصه مشاهده یا نقص‌ها>
```

اگر نقص critical وجود داشته باشد، فقط patch محدود FO-3 مجاز است و FO-4 همچنان blocked می‌ماند.

---

## 9. Trancheهای آینده

### FO-4 — Controlled Actions, Claim & Assignment

**وضعیت: BLOCKED**

پس از attestation UX می‌تواند صرفاً برای طراحی و issue رسمی مجاز شود. دامنهٔ پیشنهادی:

- claim/assignment با optimistic concurrency؛
- append-only event و idempotency؛
- permission جداگانه؛
- stale projection recheck پیش از mutation؛
- بدون auto-routing یا تصمیم بالینی؛
- Worklist authority فقط پس از parity و rollback evidence تغییر می‌کند.

### FO-5 — Routing & SLA

**وضعیت: BLOCKED**

- queue policy نسخه‌دار؛
- SLA محاسباتی، نه clinical truth؛
- escalation event؛
- بدون واگذاری خودکار تا validation مستقل.

### FO-6 — Structured Contact

**وضعیت: BLOCKED**

- outcomeهای ساختاریافته؛
- idempotency؛
- note آزاد اختیاری و غیرحاکم؛
- عدم completion بالینی بدون evidence.

### FO-7 تا FO-10

**وضعیت: BLOCKED**

شامل SMS guarded automation، appointment reactions، Evidence Assist، outbox/retry و observability است. هر کدام به plan version، Issue، PR، flag، CI و rollback مستقل نیاز دارد.

---

## 10. Rollback

### FO-3

```powershell
$env:FOLLOWUP_UNIFIED_WORKLIST_READONLY = "0"
```

نتیجه:

- navigation جدید مخفی می‌شود؛
- routeهای جدید قابل مشاهده نیستند؛
- Worklist قدیمی ادامه می‌دهد؛
- هیچ data rollback لازم نیست؛
- Episode و Projection برای audit باقی می‌مانند.

### FO-2

`FOLLOWUP_PROJECTION_SHADOW=0` نگه داشته شود. Projection cache قابل حذف و rebuild است؛ Source Truth تغییر نمی‌کند.

### FO-1

Episode/Link/Event additive هستند. rollback رفتاری با خاموش نگه‌داشتن flags انجام می‌شود؛ حذف تاریخچه فقط با migration مستقل و تأییدشده مجاز است.

---

## 11. قواعد اجرای ایجنت

هر ایجنت پیش از کار باید:

1. `main` و open PR/Issueها را بخواند؛
2. این سند، `PROJECT_STATE.json`، `PROJECT_STATE.md` و `AGENTS.md` را تطبیق دهد؛
3. از branch تازهٔ `main` شروع کند؛
4. scope را به tranche مجاز محدود کند؛
5. CI کامل را پیش از merge اجرا کند؛
6. failure واقعی را از log اصلاح کند؛
7. ادعای push، merge یا test را فقط با SHA/run evidence مطرح کند؛
8. هیچ tranche بعدی را خودکار مجاز نکند.

در وضعیت نسخهٔ `1.4.0` تنها کارهای مجاز عبارت‌اند از:

- مرور لوکال FO-3؛
- patch محدود نقص FO-3؛
- مستندسازی attestation؛
- bug/security fix متمرکز.

FO-4 و بعد مجاز نیستند.

---

## 12. Progress Ledger

| تاریخ | رویداد | وضعیت |
|---|---|---|
| 2026-08-03 | owner طبقه‌بندی `specialist.db` را test-only اعلام کرد | ثبت شد |
| 2026-08-03 | FO-0 validated | بسته شد |
| 2026-08-03 | FO-1 در PR #75 merge شد | validated |
| 2026-08-03 | FO-2 در PR #78 merge شد | validated |
| 2026-08-03 | attestation v1.3.0 در PR #79 merge شد | FO-3 authorized |
| 2026-08-03 | branch FO-3 ابتدا خالی تشخیص داده شد | ادعای قبلی اصلاح شد |
| 2026-08-03 | FO-3 در PR #81 با CI کامل merge شد | technically validated |
| 2026-08-03 | Issue #80 با evidence بسته شد | completed |
| 2026-08-03 | Local UX Acceptance Gate تعریف شد | pending |

---

## 13. تصمیم فعلی

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 = TECHNICALLY_VALIDATED
FO-3 LOCAL UX ACCEPTANCE = PENDING
FO-4 AND LATER = BLOCKED
```

نقطهٔ ادامهٔ صحیح پروژه، اجرای مرور لوکال نسخهٔ merge‌شدهٔ FO-3 و ثبت attestation مالک است؛ نه آغاز mutation، assignment یا automation.
