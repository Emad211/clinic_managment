# Follow-up Orchestration & UX v1 — Canonical Implementation Plan

> **نام فایل مرجع:** `specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md`
>
> **کد برنامه:** `FOUX-V1`
>
> **نسخه:** `1.4.4`
>
> **آخرین بازبینی:** `2026-08-03`
>
> **وضعیت:** `FO_0_VALIDATED / FO_1_VALIDATED / FO_2_VALIDATED / FO_3_RUNTIME_REPAIR_TECHNICALLY_VALIDATED / FO_3_OPERATOR_COPY_REPAIR_TECHNICALLY_VALIDATED / FO_3_POST_FIX_LOCAL_UX_ACCEPTANCE_PENDING`
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

هر ادعای تکمیل، تست، push یا merge باید SHA و CI evidence داشته باشد.

---

## 2. هدف محصول

بدون بازنویسی Source of Truthهای فعلی، Task، SMS، Contact، Appointment، Clinical Outcome و Encounter Commitment باید در یک Episode قابل‌ردیابی و Projection بازسازی‌پذیر دیده شوند تا کاربر فوراً بفهمد:

- چرا این مورد ساخته شده؛
- وضعیت عملیاتی چیست؛
- صف پیشنهادی کدام است؛
- منتظر چه چیزی است؛
- اقدام بعدی چیست؛
- آخرین رویداد چه بوده است.

---

## 3. وضعیت trancheها

| Tranche | وضعیت | Evidence اصلی |
|---|---|---|
| FO-0 | `VALIDATED` | baseline/governance، PRهای #72/#73 |
| FO-1 | `VALIDATED` | Episode/Link/Event، PR #75 |
| FO-2 | `VALIDATED` | Projection/Policy/Parity، PR #78 |
| FO-3 | `TECHNICALLY_VALIDATED` | Unified Worklist خواندنی، PR #81 |
| FO-3 Runtime Repair | `TECHNICALLY_VALIDATED` | Issue #84 / PR #85 |
| FO-3 Operator Copy Repair | `TECHNICALLY_VALIDATED` | Issue #87 / PR #88 |
| FO-3 Post-fix UX | `PENDING_OWNER_ACCEPTANCE` | Issue #83 |
| FO-4 و بعد | `BLOCKED` | پذیرش UX صریح و governance PR مستقل لازم است |

---

## 4. معماری حاکم

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

### Storageهای موجود

```text
followup_episodes
followup_episode_links
followup_episode_events
followup_work_item_projection
```

### Routeهای FO-3

```text
GET /followups/unified/
GET /followups/unified/<episode_id>
```

FO-3 هیچ POST، mutation، request-time rebuild یا action داخلی ندارد.

---

## 5. Evidence trancheهای معتبر

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
CI 30773195914
747 Specialist + 54 Accounting
100% legacy coverage / deterministic rebuild
```

### FO-3 initial implementation

```text
Issue #80 / PR #81
Final head 14e8bf56782ead4ccef46db05eb8c4b6b034d263
Merge afed3545c0a90a1ed7ff7e0a892df89fffac00c2
CI 30775348057
754 Specialist + 54 Accounting
```

### FO-3 runtime repair

```text
Issue #84
PR #85
Final head 8809252b2ca25fb55f200d783016d30ec10134d7
Merge 8f851c90da5a81f4b7ffce43eaa5bf6010d58fa2
Root-cause CI 30808217800
Final CI 30809363219
761 Specialist + 54 Accounting
```

### FO-3 operator copy repair

```text
Issue #87
PR #88
Final head 39ebef3b70470f39292faaa7d986e2f1a90a0e80
Merge 020803868e1c2755f7669d52da92cb8050a46018
Final CI 30827033618
762 Specialist + 54 Accounting
5 changed files / copy and regression test only
```

---

## 6. Incident FO3_UI_500 — RESOLVED TECHNICALLY

### مشاهده

مالک هنگام مرور لوکال روی دادهٔ تست، generic HTTP 500 را پس از کلیک «نمای یکپارچه» گزارش کرد. Issue #84 ایجاد و FO-4 متوقف شد.

### علت قطعی

تست integration با Flask و Jinja واقعی در CI run `30808217800` ثبت کرد:

```text
TypeError: 'builtin_function_or_method' object is not iterable
{% for item in model.items %}
```

Jinja، `model.items` را به متد داخلی `dict.items` resolve کرده بود، نه mapping key `items`.

اصلاح:

```jinja2
model['items']
timeline['items']
```

`timeline.items` نیز همان ریسک را داشت و پیشگیرانه اصلاح شد. guard static بازگشت این dot notationها را رد می‌کند.

### Hardening ثانویه

- required-column contract برای cache Projection؛
- recreate فقط برای `followup_work_item_projection` ناسازگار؛
- cache جدید خالی و نیازمند rebuild صریح؛
- عدم انتقال رکورد حدسی؛
- ثابت‌ماندن Source Truth و Episode digests؛
- Read Model preflight؛
- readiness codeهای PHI-free؛
- صفحهٔ فارسی کنترل‌شده برای خطاهای SQLite/schema شناخته‌شده؛
- عدم پنهان‌کردن خطاهای برنامه‌نویسی ناشناخته با `except Exception`.

این hardening علت screenshot نبود؛ علت قطعی همان Jinja collision بود.

### 6.1. FO3_OPERATOR_PROJECTION_JARGON — RESOLVED TECHNICALLY

مرور ایستای `main` روی commit `b977fe5be5683f9d46fccf0e102d0a6dc97d79c7` نشان داد که رابط خواندنی هنوز اصطلاح فنی `Projection` را مستقیماً به کاربر درمانگاه نمایش می‌دهد، از جمله:

```text
Projection قدیمی
سن Projection
Projection هنوز ساخته نشده است
```

این مورد با معیار پذیرش «stale/overdue قابل‌فهم باشد» سازگار نبود. Issue `#87` و PR `#88` repair متمرکز زیر را انجام دادند:

- `Projection قدیمی` → `اطلاعات نما قدیمی است`؛
- `سن Projection` → `آخرین بازسازی نما`؛
- readiness copyهای فنی → متن عملیاتی فارسی؛
- حفظ machine readiness codeها و نام‌های داخلی؛
- حفظ `Projection version/hash` فقط در audit جمع‌شونده؛
- افزودن regression test برای جلوگیری از بازگشت jargon.

مرز repair:

```text
Route/query change       = none
Schema/cache behavior    = none
Source Truth mutation    = none
Clinical rule change     = none
Claim/assignment/routing = none
SMS/appointment behavior = none
Accounting write         = none
Feature defaults         = unchanged / OFF
```

این repair از نظر فنی با CI `30827033618` و `762 Specialist + 54 Accounting` معتبر است، اما owner acceptance را جعل یا تکمیل نمی‌کند. Issue #83 باید روی merge commit `020803868e1c2755f7669d52da92cb8050a46018` مرور شود.

---

## 7. Invariantهای غیرقابل‌مذاکره

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
14. mapping keyهای متعارض با متدهای dict در Jinja باید bracket notation داشته باشند.
15. known schema drift نباید generic 500 تولید کند.
16. فقط cache disposable می‌تواند recreate شود؛ Source Truth هرگز drop/rewrite نمی‌شود.
17. FO-4 و بعد بدون owner acceptance و governance PR جدید ممنوع است.
18. اصطلاح‌های فنی cache/projection نباید در کپی اصلی اپراتوری نمایش داده شوند؛ audit جمع‌شونده استثنا است.

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

در مرور فعلی فقط Read-only flag مصرف می‌شود. Action flags ممنوع‌اند.

---

## 9. قدم مجاز فعلی — Post-fix Local UX Acceptance

Issue حاکم: `#83`

Repairهای فنی #84 و #87 بسته شده‌اند. هیچ توسعهٔ جدیدی پیش از نتیجهٔ این مرور مجاز نیست، مگر defect متمرکز جدیدی در خود FO-3 پیدا شود.

### اجرای لوکال

```powershell
git checkout main
git pull origin main
cd specialist_clinic
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

برنامه را یک‌بار اجرا و ببندید تا cache migration اعمال شود:

```powershell
.\.venv\Scripts\python.exe start.py
```

سپس Projection را صریح بازسازی کنید:

```powershell
$env:FOLLOWUP_PROJECTION_SHADOW = "1"
.\.venv\Scripts\python.exe scripts\rebuild_followup_projection.py `
  --database specialist.db `
  --as-of "2026-08-03 12:00:00" `
  --apply
```

و UI خواندنی را فعال کنید:

```powershell
$env:FOLLOWUP_UNIFIED_WORKLIST_READONLY = "1"
.\.venv\Scripts\python.exe start.py
```

### Checklist پذیرش

- نمای یکپارچه بدون 500 باز شود؛
- list و Timeline هر دو render شوند؛
- search/filter/pagination قابل‌فهم باشند؛
- action/wait/block copy روشن باشد؛
- role proposal با assignment اشتباه نشود؛
- action due و target جدا باشند؛
- stale/overdue قابل‌فهم باشند و jargon فنی نداشته باشند؛
- deep-linkها مسیرهای حاکم را باز کنند؛
- عرض کم، RTL و keyboard قابل‌قبول باشند؛
- flag OFF tab را مخفی و route را unavailable کند.

### Attestation لازم

```text
FO3_UX_ACCEPTED = true|false
reviewer = Emad211
reviewed_commit = 020803868e1c2755f7669d52da92cb8050a46018
reviewed_on_test_data = true
critical_ux_defects = <number>
notes = <observations or defects>
```

---

## 10. Exit Gate برای FO-4

FO-4 فقط پس از همهٔ موارد زیر قابل بررسی است:

```text
PR #85 runtime repair merged         = PASS
PR #88 operator copy repair merged   = PASS
Final CI 30827033618 green           = PASS
FO3_UX_ACCEPTED=true                 = PENDING
critical_ux_defects=0                = PENDING
governance authorization PR merged   = PENDING
```

تا آن زمان:

```text
Claim / Assignment
Routing / SLA mutation
Structured Contact automation
SMS automation
Appointment reaction
Outbox / Retry / Auto-close
Evidence Assist
```

همگی مسدودند.

---

## 11. Rollback

```powershell
$env:FOLLOWUP_UNIFIED_WORKLIST_READONLY = "0"
```

نتیجه:

- tab و routeهای FO-3 از دید کاربر خارج می‌شوند؛
- Worklist قدیمی ادامه می‌دهد؛
- data rollback لازم نیست؛
- Projection cache قابل rebuild است؛
- Source Truthها دست‌نخورده می‌مانند.

---

## 12. قواعد ایجنت

1. `main`، Issue #83، Issue #87، PRهای #85/#88 و این سند را بخواند؛
2. فقط post-fix UX review یا focused FO-3 defect fix انجام دهد؛
3. علت Incident 500 را Jinja dict-method collision گزارش کند؛
4. schema hardening را علت screenshot معرفی نکند؛
5. repair #87 را copy-only و technically validated بداند؛
6. هیچ Source Truth را تغییر ندهد؛
7. هر fix جدید full CI و owner re-review می‌خواهد؛
8. بدون owner attestation وارد FO-4 نشود.

---

## 13. Progress Ledger

| تاریخ | رویداد | وضعیت |
|---|---|---|
| 2026-08-03 | FO-0 validated | completed |
| 2026-08-03 | FO-1 PR #75 | validated |
| 2026-08-03 | FO-2 PR #78 | validated |
| 2026-08-03 | FO-3 PR #81 | technically validated |
| 2026-08-03 | مالک generic 500 گزارش کرد | UX blocked |
| 2026-08-03 | PR #85 علت Jinja را رفع و cache را harden کرد | technically validated |
| 2026-08-03 | Issue #87 jargon فنی کپی عملیاتی را ثبت کرد | focused defect |
| 2026-08-03 | PR #88 کپی عملیاتی و guard بازگشت را اصلاح کرد | technically validated |
| 2026-08-03 | Plan v1.4.4 | owner UX review pending |

---

## 14. تصمیم فعلی

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 RUNTIME REPAIR = TECHNICALLY VALIDATED
FO-3 OPERATOR COPY REPAIR = TECHNICALLY VALIDATED
FO-3 POST-FIX LOCAL UX ACCEPTANCE = PENDING
FO-4 AND LATER = BLOCKED
```
