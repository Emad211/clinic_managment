# Follow-up Orchestration & UX v1 — Canonical Implementation Plan

> **نام فایل مرجع:** `specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md`
>
> **کد برنامه:** `FOUX-V1`
>
> **نسخه:** `1.5.1`
>
> **آخرین بازبینی:** `2026-08-03`
>
> **وضعیت:** `FO_0_VALIDATED / FO_1_VALIDATED / FO_2_VALIDATED / FO_3_VALIDATED_WITH_OWNER_ACCEPTANCE / FO_4_TECHNICALLY_VALIDATED_LOCAL_UX_ACCEPTANCE_PENDING / FO_5_AND_LATER_BLOCKED`
>
> **مالک:** `Emad211`
>
> **دامنه:** فقط `specialist_clinic/`
>
> **طبقه‌بندی محیط فعلی:** `TEST_ONLY / SYNTHETIC_OR_RESETTABLE_DATA`
>
> **خارج از دامنه:** تغییر Rule بالینی، گسترش Hypoglycemia Shadow، تصمیم درمانی خودکار، Write به `clinic_new.db` و تغییر رفتار `webapp/`.

---

## 1. ترتیب اعتماد

1. وضعیت واقعی `main`، PRها، Issueها و CI؛
2. `PROJECT_STATE.json` و `PROJECT_STATE.md`؛
3. این سند و `specialist_clinic/AGENTS.md`؛
4. قراردادهای نزدیک به کد؛
5. متن PRهای تاریخی؛
6. حافظهٔ گفتگو یا ایجنت.

هر ادعای تکمیل، تست، push یا merge باید SHA و CI evidence داشته باشد.

---

## 2. هدف محصول

Task، SMS، Contact، Appointment، Clinical Outcome و Encounter Commitment بدون بازنویسی Source of Truthهای فعلی در Episode و Projection بازسازی‌پذیر دیده شوند تا کاربر فوراً بداند:

- چرا مورد ساخته شده؛
- وضعیت و موعد چیست؛
- صف مسئول کدام است؛
- مسئول واقعی چه کسی است؛
- اقدام بعدی و آخرین رویداد چیست.

---

## 3. وضعیت trancheها

| Tranche | وضعیت | Evidence |
|---|---|---|
| FO-0 | `VALIDATED` | Issue #71، PR #72/#73 |
| FO-1 | `VALIDATED` | Issue #74، PR #75 |
| FO-2 | `VALIDATED` | Issue #77، PR #78 |
| FO-3 | `VALIDATED_WITH_OWNER_ACCEPTANCE` | Issue #83، PR #81/#85/#88 |
| FO-4 | `TECHNICALLY_VALIDATED / LOCAL_UX_PENDING` | Issue #94، PR #95 |
| FO-5 و بعد | `BLOCKED` | validation، owner acceptance و governance مستقل لازم است |

---

## 4. معماری حاکم

```text
Authoritative Source Truths
        ↓
Episode / Link / append-only Event       [FO-1]
        ↓
Deterministic Projection Cache           [FO-2]
        ↓
Unified Worklist / Timeline              [FO-3]
        ↓
Ownership / Routing / SLA events         [FO-4]
```

Source Truthهای قبلی authoritative می‌مانند. Episode حقیقت بالینی نیست و Projection فقط cache است.

### Storageهای معتبر

```text
followup_episodes
followup_episode_links
followup_episode_events
followup_work_item_projection
```

FO-4 جدول Source Truth جدیدی نساخت؛ ownership از event stream موجود بازسازی می‌شود.

---

## 5. Evidence معتبر

### FO-0

```text
Merge 901dbfdf9c358ecc09d2a60a0680f6a4a8370d17
731 Specialist + 54 Accounting
```

### FO-1

```text
Merge 15ef1585c069a74c26fbc0ce859e03906e5f475a
736 Specialist + 54 Accounting
```

### FO-2

```text
Merge 6c6e33203376a32165418e0d3c6f2a4a48253e7b
CI 30773195914
747 Specialist + 54 Accounting
100% legacy coverage / deterministic rebuild
```

### FO-3

```text
Initial PR #81
Runtime repair Issue #84 / PR #85
Operator-copy repair Issue #87 / PR #88
Runtime/UI commit 020803868e1c2755f7669d52da92cb8050a46018
Governance merge f6fb9f87c7fe302c6e18d7f5909aed4128a7f5ca
Latest FO-3 CI 30828272752
762 Specialist + 54 Accounting
```

Owner acceptance در Issue #83:

```text
FO3_UX_ACCEPTED = true
reviewer = Emad211
reviewed_commit = 020803868e1c2755f7669d52da92cb8050a46018
reviewed_on_test_data = true
critical_ux_defects = 0
```

### FO-4 — Claim, Assignment, Routing & SLA

```text
Authorization Issue #90 / PR #91
Implementation Issue #94 / PR #95
Final head ec98140fc262f26089e5a05b3e24a2b9647882ff
Merge 27ccb992f2cb43c78bfe98549c3f0414b88fd1d8
Final CI 30844075841
773 Specialist + 54 Accounting
```

قابلیت‌های معتبر:

- eventهای append-only از نوع `ROUTED`، `CLAIMED` و `ASSIGNED`؛
- atomic claim با `BEGIN IMMEDIATE` و دقیقاً یک winner؛
- exact replay idempotent و conflict detection؛
- stale expected-event guard؛
- release توسط owner یا مدیر؛
- assign/reassign و route با permission سازگار؛
- terminal mutation rejection پیش از role/owner checks؛
- actual queue و actual owner در list/detail؛
- role filter براساس صف مؤثر بعد از routing؛
- ownership overlay به‌صورت batch و بدون N+1؛
- حفظ ownership پس از Projection rebuild؛
- routeهای mutation با feature flag خاموش = 404؛
- Source Truth digest بدون تغییر.

### اصلاحات کشف‌شده توسط CI

اجرای اول fixture قدیمی terminal را ناقص می‌ساخت و schema به‌درستی آن را رد کرد؛ fixture به قرارداد کامل ارتقا یافت و policy ضعیف نشد.

اجرای بعدی نشان داد Claim روی terminal قبل از terminal check به `OWNER_ROLE_MISSING` می‌رسید. سرویس اصلاح شد تا Claim، Release، Assign و Route همگی ابتدا terminal بودن را fail closed رد کنند.

---

## 6. Invariantهای غیرقابل‌مذاکره

1. Source Truthهای قبلی authoritative می‌مانند.
2. Episode و Projection حقیقت بالینی نیستند.
3. relation، event، due date، target، outcome یا assignment جعل نمی‌شود.
4. Clinical completion فقط با Evidence و transition معتبر انجام می‌شود.
5. Appointment به‌تنهایی Clinical Task را complete نمی‌کند.
6. Worklist قدیمی تا cutover مستقل authority بالینی باقی می‌ماند.
7. Rule و Hypoglycemia Shadow خارج از scope هستند.
8. `clinic_new.db` فقط read-only است.
9. feature flag خاموش رفتار FO-3 read-only را بازمی‌گرداند.
10. ownership mutationها append-only، idempotent و audit‌شده‌اند.
11. claim هم‌زمان دقیقاً یک winner دارد.
12. reassignment پنهان ممنوع است.
13. stale form/current-head mismatch fail closed است.
14. owner role و owner user دو مفهوم جدا هستند.
15. نقش پیشنهادی FO-2 به‌تنهایی assignment واقعی نیست.
16. terminal item قابل دریافت، آزادکردن، route یا assignment نیست.
17. FO-5 و بعد بدون owner acceptance و governance جدید ممنوع است.

---

## 7. Feature Flags

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

برای مرور FO-4:

```text
FOLLOWUP_UNIFIED_WORKLIST_READONLY=1
FOLLOWUP_UNIFIED_WORKLIST_ACTIONS=1
FOLLOWUP_AUTO_ROUTING=1
```

خاموش‌کردن Actions باید همهٔ mutation routeها و controlها را مخفی و unavailable کند. خاموش‌کردن Auto Routing فقط تغییر صف مدیریتی را غیرفعال می‌کند.

---

## 8. قدم مجاز فعلی — FO-4 Local UX Acceptance

Issue حاکم: `#94`

هیچ توسعهٔ FO-5 یا اتوماسیون جدیدی پیش از نتیجهٔ این مرور مجاز نیست. فقط defect متمرکز FO-4 می‌تواند اصلاح شود.

### اجرای لوکال

```powershell
git checkout main
git pull origin main
cd specialist_clinic
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

در صورت نیاز Projection را بازسازی کنید:

```powershell
$env:FOLLOWUP_PROJECTION_SHADOW = "1"
.\.venv\Scripts\python.exe scripts\rebuild_followup_projection.py `
  --database specialist.db `
  --as-of "2026-08-03 12:00:00" `
  --apply
```

FO-4 را فعال و برنامه را اجرا کنید:

```powershell
$env:FOLLOWUP_UNIFIED_WORKLIST_READONLY = "1"
$env:FOLLOWUP_UNIFIED_WORKLIST_ACTIONS = "1"
$env:FOLLOWUP_AUTO_ROUTING = "1"
.\.venv\Scripts\python.exe start.py
```

### Checklist پذیرش

- در لیست، «صف مسئول» و «مسئول فعلی» جدا باشند؛
- مورد بدون مسئول با متن روشن نمایش داده شود؛
- «دریافت برای رسیدگی» نام کاربر فعلی را ثبت کند؛
- «آزادکردن و بازگرداندن به صف» مسئول فردی را حذف ولی صف را حفظ کند؛
- مدیر بتواند کاربر سازگار را assign/reassign کند؛
- مدیر بتواند صف را تغییر دهد و مسئول ناسازگار حذف شود؛
- Timeline تغییر صف و مسئول را نشان دهد؛
- کلیک تکراری event تکراری نسازد؛
- فرم stale پیام «صفحه را تازه کنید» بدهد و mutation نکند؛
- terminal item هیچ control عملیاتی نداشته باشد؛
- action due و target همچنان جدا باشند؛
- با Actions=0 صفحه دقیقاً read-only شود و POSTها 404 باشند؛
- Worklist قدیمی، SMS، Appointment و Clinical behavior تغییر نکرده باشند.

### Attestation لازم

```text
FO4_UX_ACCEPTED = true|false
reviewer = Emad211
reviewed_commit = 27ccb992f2cb43c78bfe98549c3f0414b88fd1d8
reviewed_on_test_data = true
critical_ux_defects = <number>
notes = <observations or defects>
```

---

## 9. Exit Gate برای FO-5

```text
FO-4 PR #95 merged                    = PASS
Final CI 30844075841 green            = PASS
Atomic one-winner claim               = PASS
Stale/permission/terminal fail closed = PASS
Projection rebuild preserves owner    = PASS
Source Truth unchanged                = PASS
FO4_UX_ACCEPTED=true                  = PENDING
critical_ux_defects=0                 = PENDING
governance authorization PR merged    = PENDING
```

تا آن زمان Structured Contact automation، Retry/Escalation، SMS automation، Appointment reaction، Outbox/Dead-letter، Evidence Assist و FO-5+ مسدودند.

---

## 10. Rollback

```powershell
$env:FOLLOWUP_UNIFIED_WORKLIST_ACTIONS = "0"
$env:FOLLOWUP_AUTO_ROUTING = "0"
```

نتیجه:

- action controlها و mutation routeها unavailable می‌شوند؛
- FO-3 read-only باقی می‌ماند؛
- eventهای audit حذف یا rewrite نمی‌شوند؛
- Source Truth rollback لازم ندارد؛
- Projection قابل rebuild است.

---

## 11. قواعد ایجنت

1. `main`، Issue #94 و plan v1.5.1 خوانده شوند؛
2. فقط local UX review یا focused FO-4 defect fix مجاز است؛
3. ownership eventها append-only باقی بمانند؛
4. Source Truth، Rule، SMS و Appointment behavior تغییر نکند؛
5. هر mutation permission، stale guard، terminal guard و idempotency داشته باشد؛
6. هر fix جدید full CI و owner re-review می‌خواهد؛
7. بدون FO-4 owner acceptance وارد FO-5 نشود.

---

## 12. تصمیم فعلی

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 = VALIDATED WITH OWNER ACCEPTANCE
FO-4 = TECHNICALLY VALIDATED / LOCAL UX ACCEPTANCE PENDING
FO-5 AND LATER = BLOCKED
```
