# Follow-up Orchestration & UX v1 — Canonical Implementation Plan

> **نام فایل مرجع:** `specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md`
>
> **کد برنامه:** `FOUX-V1`
>
> **نسخه:** `1.4.1`
>
> **آخرین بازبینی:** `2026-08-03`
>
> **وضعیت:** `FO_0_VALIDATED / FO_1_VALIDATED / FO_2_VALIDATED / FO_3_TECHNICALLY_VALIDATED / FO_3_LOCAL_UX_BLOCKED_BY_RUNTIME_DEFECT / FOCUSED_FIX_IN_PROGRESS`
>
> **مالک:** `Emad211`
>
> **دامنه:** فقط `specialist_clinic/`
>
> **طبقه‌بندی محیط فعلی:** `TEST_ONLY / SYNTHETIC_OR_RESETTABLE_DATA`
>
> **خارج از دامنه:** تغییر Rule بالینی، گسترش Hypoglycemia Shadow، تصمیم درمانی خودکار، Write به `clinic_new.db` و تغییر رفتار `webapp/`.

---

## 1. نقش و ترتیب اعتماد

این سند Source of Truth اجرایی برنامهٔ بازطراحی پیگیری است. ترتیب اعتماد:

1. وضعیت واقعی `main`، PRها، Issueها و CI؛
2. `PROJECT_STATE.json` و `PROJECT_STATE.md`؛
3. این سند و `specialist_clinic/AGENTS.md`؛
4. قراردادهای نزدیک به کد؛
5. متن PRهای تاریخی؛
6. حافظهٔ گفتگو یا ایجنت.

هر ادعای تکمیل، تست، push یا merge باید SHA و CI evidence داشته باشد. وجود branch یا کد محلی به معنی تکمیل نیست.

---

## 2. مسئلهٔ محصول

پیگیری بیمار میان چند Source of Truth پخش است:

```text
followup_tasks
clinical_task_events
clinical_outcome_events
care_plan_commitments
care_plan_commitment_events
followup_contact_events
engagement_approvals
sms_messages
appointments
```

هدف FOUX-V1 این است که بدون بازنویسی این منابع، یک Episode قابل‌ردیابی، Projection بازسازی‌پذیر و UI روشن بسازد تا کاربر بفهمد:

- چرا مورد ساخته شده؛
- وضعیت عملیاتی چیست؛
- مسئول یا صف پیشنهادی کدام است؛
- منتظر چه چیزی است؛
- اقدام بعدی چیست؛
- آخرین رویداد چه بوده است.

---

## 3. وضعیت قطعی trancheها

| Tranche | وضعیت | Evidence اصلی |
|---|---|---|
| FO-0 | `VALIDATED` | baseline و governance، PRهای #72/#73 |
| FO-1 | `VALIDATED` | Episode/Link/Event، PR #75 |
| FO-2 | `VALIDATED` | Projection/Policy/Parity، PR #78 |
| FO-3 | `TECHNICALLY_VALIDATED` | Unified Worklist خواندنی، PR #81 |
| FO-3 Local UX | `BLOCKED_BY_RUNTIME_DEFECT` | HTTP 500 در مرور واقعی مالک، Issue #84 |
| FO-4 و بعد | `BLOCKED` | نیازمند رفع defect، CI کامل و پذیرش UX جدید |

### 3.1 Evidence حاکم FO-3

```text
Tracking Issue       = #80
Implementation PR    = #81
Final head           = 14e8bf56782ead4ccef46db05eb8c4b6b034d263
Merge commit         = afed3545c0a90a1ed7ff7e0a892df89fffac00c2
Final CI run         = 30775348057
Specialist tests     = 754 passed
Accounting tests     = 54 passed
```

FO-3 از نظر cohort تستی و CI معتبر بود، اما مرور روی دیتابیس لوکال پایدارشده یک نقص runtime پیدا کرد؛ بنابراین پذیرش UX انجام نشده است.

---

## 4. Incident FO-3-UI-500

### 4.1 مشاهده

در مرور لوکال مالک روی دادهٔ تست، انتخاب «نمای یکپارچه» به صفحهٔ عمومی HTTP 500 منتهی شد. این رفتار ناقض قرارداد FO-3 است؛ صفحه باید یکی از این حالت‌ها را نشان دهد:

```text
Unified Worklist
Projection هنوز ساخته نشده
Projection قدیمی یا ناسازگار
Read schema ناقص
خواندن موقتاً ناموفق
```

هیچ schema drift شناخته‌شده نباید به generic 500 تبدیل شود.

### 4.2 Evidence و محدودیت تشخیص

- Screenshot صفحهٔ عمومی 500 توسط مالک ارائه شد؛
- traceback محلی در زمان ثبت نسخهٔ `1.4.1` در دسترس نبود؛
- بنابراین علت دقیق محلی نباید جعل شود؛
- یک gap طراحی قطعی وجود دارد: Read Model فقط وجود جدول را کنترل می‌کند و required-column/schema compatibility را پیش از query بررسی نمی‌کند؛
- SQLite با `CREATE TABLE IF NOT EXISTS` جدول موجود را ارتقا نمی‌دهد؛
- `followup_work_item_projection` cache disposable است و ممکن است از نسخهٔ آزمایشی قبلی باقی مانده باشد.

### 4.3 Issue و مجوز

```text
Focused repair issue = #84
Allowed work         = FO-3 defect repair only
FO-4 allowed         = false
```

---

## 5. معماری حاکم

```text
Authoritative Source Truths
        ↓
Episode / Link / Event              [FO-1]
        ↓
Deterministic Projection Cache      [FO-2]
        ↓
Read-only Unified Worklist/Timeline [FO-3]
        ↓
Deep-link to legacy action surfaces
```

Source Truthهای قبلی authoritative می‌مانند. Episode فقط lineage و Projection فقط cache است.

### 5.1 Storageهای موجود

FO-1:

```text
followup_episodes
followup_episode_links
followup_episode_events
```

FO-2:

```text
followup_work_item_projection
Projection version = 1.0
Policy version     = FOUX-NEXT-ACTION-V1
```

FO-3:

```text
GET /followups/unified/
GET /followups/unified/<episode_id>
```

FO-3 هیچ POST، mutation، rebuild در request یا action داخلی ندارد.

---

## 6. Invariantهای غیرقابل‌مذاکره

1. Source Truthهای قبلی authoritative می‌مانند.
2. Episode و Projection حقیقت بالینی نیستند.
3. relation، event، due date، target، outcome یا assignment جعل نمی‌شود.
4. هر Projection غیرنهایی دقیقاً action، wait یا block دارد.
5. completion بالینی فقط با Evidence معتبر انجام می‌شود.
6. Appointment به‌تنهایی Clinical Task را complete نمی‌کند.
7. FO-3 فقط GET/read است.
8. CTAهای FO-3 فقط deep-link هستند.
9. role proposal به معنی claim/assignment نیست.
10. Worklist قدیمی authority عملیاتی باقی می‌ماند.
11. Rule و Hypoglycemia Shadow خارج از scope هستند.
12. `clinic_new.db` فقط read-only است.
13. feature flag خاموش باید رفتار قبلی را بازگرداند.
14. generic 500 برای schema drift شناخته‌شده قابل‌قبول نیست.
15. فقط cache disposable می‌تواند خودکار recreate شود؛ Source Truth هرگز drop/rewrite نمی‌شود.
16. FO-4 و بعد بدون attestation جدید ممنوع است.

---

## 7. قرارداد Focused Repair نسخهٔ 1.4.1

### 7.1 Projection cache compatibility

`ensure_followup_projection_storage` باید required columnهای cache را کنترل کند. اگر جدول موجود incompatible باشد:

1. فقط `followup_work_item_projection` حذف شود؛
2. جدول با schema canonical دوباره ساخته شود؛
3. cache خالی بماند تا rebuild صریح اجرا شود؛
4. Episode/Link/Event و تمام Source Truthها بدون تغییر بمانند؛
5. عملیات idempotent باشد.

Recreate خودکار مجاز است چون Projection disposable cache است. انتقال یا حدس رکوردهای cache قدیمی ممنوع است.

### 7.2 Read-model preflight

پیش از query اصلی، Read Model باید وجود table و required columnهای زیر را بررسی کند:

```text
followup_work_item_projection
patient_links
followup_episode_links (برای source summaries)
```

خروجی readiness باید فقط codeهای غیرحساس داشته باشد:

```text
PROJECTION_NOT_BUILT
PROJECTION_SCHEMA_INCOMPATIBLE
PATIENT_IDENTITY_SCHEMA_INCOMPATIBLE
EPISODE_LINK_SCHEMA_INCOMPATIBLE
PROJECTION_READ_FAILED
READY
```

نام table/column و exception خام نباید در UI عمومی یا log PHI‌دار نمایش داده شود.

### 7.3 Controlled UX state

در خطاهای شناخته‌شده:

- route باید HTTP 200 با state کنترل‌شده یا 503 کنترل‌شده بدهد، نه generic 500؛
- Worklist قدیمی لینک اصلی باقی بماند؛
- UI توضیح دهد داده‌ای حدس زده نشده است؛
- remediation امن شامل restart روی نسخهٔ جدید و rebuild صریح Projection باشد؛
- raw exception نمایش داده نشود.

خطاهای برنامه‌نویسی ناشناخته نباید با `except Exception` پنهان شوند؛ فقط SQLite/schema/read errors طبقه‌بندی‌شده کنترل می‌شوند.

### 7.4 Test requirements

Focused tests باید ثابت کنند:

- legacy/incomplete projection cache safely recreated؛
- recreated cache خالی و schema canonical است؛
- Source Truth digest قبل/بعد برابر است؛
- migration rerun idempotent است؛
- missing/incompatible read schema generic 500 تولید نمی‌کند؛
- current canonical schema همچنان list/detail را render می‌کند؛
- feature OFF همچنان navigation hidden و route=404 است؛
- routeها GET-only و POST=405 هستند؛
- full Specialist و Accounting CI سبز است.

---

## 8. Feature Flags

همه default OFF:

```text
FOLLOWUP_EPISODES_ENABLED
FOLLOWUP_PROJECTION_SHADOW
FOLLOWUP_UNIFIED_WORKLIST_READONLY
FOLLOWUP_UNIFIED_WORKLIST_ACTIONS
FOLLOWUP_AUTO_ROUTING
FOLLOWUP_STRUCTURED_CONTACT
FOLLOWUP_SMS_AUTO_GUARDED
FOLLOWUP_APPOINTMENT_SYNC
FOLLOWUP_EVIDENCE_ASSIST
FOLLOWUP_AUTOMATION_HEALTH
```

در focused repair فقط `FOLLOWUP_UNIFIED_WORKLIST_READONLY` مصرف می‌شود. هیچ action flag فعال نمی‌شود.

---

## 9. Evidence trancheهای قبلی

### FO-0

```text
Issue #71
PR #72/#73
Merge 901dbfdf9c358ecc09d2a60a0680f6a4a8370d17
731 Specialist + 54 Accounting
```

### FO-1

```text
Issue #74 / PR #75
Merge 15ef1585c069a74c26fbc0ce859e03906e5f475a
736 Specialist + 54 Accounting
4 Episodes / 12 Links / second apply zero duplicates
```

### FO-2

```text
Issue #77 / PR #78
Merge 6c6e33203376a32165418e0d3c6f2a4a48253e7b
747 Specialist + 54 Accounting
100% legacy coverage / deterministic rebuild
```

### FO-3 initial implementation

```text
Issue #80 / PR #81
Merge afed3545c0a90a1ed7ff7e0a892df89fffac00c2
754 Specialist + 54 Accounting
```

### FO-3 runtime repair

```text
Issue #84
PR = pending
Merge = pending
Final CI = pending
Local UX re-review = pending
```

---

## 10. Local UX re-review after repair

پس از merge focused fix، روی commit جدید `main`:

```powershell
git checkout main
git pull origin main
cd specialist_clinic
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

برنامه یک بار بدون feature flag اجرا شود تا migration cache-compatible اعمال شود، سپس بسته شود. Projection صریح بازسازی شود:

```powershell
$env:FOLLOWUP_PROJECTION_SHADOW = "1"
.\.venv\Scripts\python.exe scripts\rebuild_followup_projection.py `
  --database specialist.db `
  --as-of "2026-08-03 12:00:00" `
  --apply
```

سپس UI خواندنی فعال شود:

```powershell
$env:FOLLOWUP_UNIFIED_WORKLIST_READONLY = "1"
.\.venv\Scripts\python.exe start.py
```

مرور باید شامل این موارد باشد:

1. بازشدن نمای یکپارچه بدون 500؛
2. جستجو و filter؛
3. action/wait/block copy؛
4. role proposal؛
5. action due و target؛
6. stale/overdue؛
7. detail Timeline؛
8. deep-linkهای حاکم؛
9. عرض کم و keyboard؛
10. flag OFF و ناپدیدشدن tab.

Attestation جدید باید commit repair را ثبت کند، نه commit قبلی FO-3.

---

## 11. Trancheهای آینده

### FO-4 — Claim, Assignment & Controlled Actions

**وضعیت: BLOCKED**

فقط پس از:

```text
focused repair merged
full CI green
FO3_UX_ACCEPTED=true
critical_ux_defects=0
governance PR مستقل
```

### FO-5 تا FO-10

**وضعیت: BLOCKED**

Routing/SLA، Structured Contact، SMS automation، Appointment reaction، Outbox، Evidence Assist و Automation Health هرکدام به Issue، contract، flag، CI و rollback مستقل نیاز دارند.

---

## 12. Rollback

### FO-3 UI

```powershell
$env:FOLLOWUP_UNIFIED_WORKLIST_READONLY = "0"
```

Worklist قبلی ادامه می‌دهد و data rollback لازم نیست.

### Projection cache repair

Recreate فقط cache را خالی می‌کند. بازسازی با CLI صریح انجام می‌شود. Source Truthها rollback یا تغییر نمی‌کنند.

### FO-1/FO-2 infrastructure

Schema additive retained-but-unused است. destructive rollback ممنوع است.

---

## 13. قواعد ایجنت

هر ایجنت باید:

1. `main` و Issue #84 را بخواند؛
2. این سند و Project State و AGENTS را تطبیق دهد؛
3. فقط branch focused repair را تغییر دهد؛
4. علت دقیق بدون traceback را جعل نکند؛
5. فقط cache disposable را repair کند؛
6. known SQLite/schema errors را fail-safe کند؛
7. خطاهای ناشناخته را پنهان نکند؛
8. focused و full CI را اجرا کند؛
9. FO-4 را مجاز نکند.

---

## 14. Progress Ledger

| تاریخ | رویداد | وضعیت |
|---|---|---|
| 2026-08-03 | محیط `specialist.db` به‌عنوان test-only ثبت شد | completed |
| 2026-08-03 | FO-0 validated | completed |
| 2026-08-03 | FO-1 PR #75 | validated |
| 2026-08-03 | FO-2 PR #78 | validated |
| 2026-08-03 | FO-3 PR #81 | technically validated |
| 2026-08-03 | Plan v1.4.0 / PR #82 | UX gate defined |
| 2026-08-03 | مالک generic 500 در نمای یکپارچه گزارش کرد | UX acceptance blocked |
| 2026-08-03 | Issue #84 و Plan v1.4.1 ایجاد شد | focused fix in progress |

---

## 15. تصمیم فعلی

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 = TECHNICALLY_VALIDATED
FO-3 LOCAL UX ACCEPTANCE = BLOCKED BY RUNTIME DEFECT
FOCUSED FO-3 FIX = IN PROGRESS
FO-4 AND LATER = BLOCKED
```

نقطهٔ ادامهٔ صحیح پروژه رفع Issue #84، CI کامل، merge، و تکرار مرور UX روی commit جدید است؛ نه آغاز claim، assignment، routing یا automation.