# Follow-up Orchestration & UX v1 — Canonical Implementation Plan

> **نام فایل مرجع:** `specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md`
>
> **کد برنامه:** `FOUX-V1`
>
> **نسخه:** `1.4.2`
>
> **آخرین بازبینی:** `2026-08-03`
>
> **وضعیت:** `FO_0_VALIDATED / FO_1_VALIDATED / FO_2_VALIDATED / FO_3_TECHNICALLY_VALIDATED / FO_3_LOCAL_UX_BLOCKED_BY_CONFIRMED_RUNTIME_DEFECT / FOCUSED_FIX_IN_PROGRESS`
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
| FO-3 Local UX | `BLOCKED_BY_CONFIRMED_RUNTIME_DEFECT` | owner screenshot + CI traceback، Issue #84 |
| FO-4 و بعد | `BLOCKED` | repair، full CI، merge و پذیرش UX جدید لازم است |

### Evidence پایهٔ FO-3

```text
Tracking Issue       = #80
Implementation PR    = #81
Final head           = 14e8bf56782ead4ccef46db05eb8c4b6b034d263
Merge commit         = afed3545c0a90a1ed7ff7e0a892df89fffac00c2
Final CI run         = 30775348057
Specialist tests     = 754 passed
Accounting tests     = 54 passed
```

---

## 4. Incident FO3_UI_500

### 4.1 مشاهدهٔ مالک

در مرور لوکال دادهٔ تست، کلیک روی «نمای یکپارچه» generic HTTP 500 نشان داد. پذیرش UX فوراً متوقف و Issue #84 ساخته شد.

### 4.2 علت قطعی

تست integration با Flask و Jinja واقعی در CI run `30808217800` traceback دقیق را ثبت کرد:

```text
TypeError: 'builtin_function_or_method' object is not iterable
src/templates/followups/unified_worklist.html
{% for item in model.items %}
```

علت:

- `model` یک `dict` است؛
- Jinja در dot notation، attribute را قبل از mapping key resolve می‌کند؛
- بنابراین `model.items` به متد داخلی `dict.items` اشاره کرد، نه آرایهٔ Work Itemها؛
- همین collision علت مستقیم 500 گزارش‌شده بود؛
- `timeline.items` نیز همان ریسک را داشت و پیشگیرانه اصلاح شد.

اصلاح حاکم:

```jinja2
model['items']
timeline['items']
```

Guard دائمی باید بازگشت `model.items` و `timeline.items` را رد کند.

### 4.3 Hardening ثانویه

در بررسی incident، gap مستقلی نیز تأیید شد:

- Read Model فقط وجود table را بررسی می‌کرد؛
- required columns/schema compatibility را پیش از query نمی‌سنجید؛
- SQLite با `CREATE TABLE IF NOT EXISTS` جدول قدیمی را upgrade نمی‌کند؛
- persisted pre-final Projection cache می‌توانست generic 500 دیگری تولید کند.

بنابراین repair شامل دو لایه است:

1. رفع علت قطعی Jinja collision؛
2. fail-safe کردن disposable cache/schema drift.

این hardening نباید به‌عنوان علت قطعی screenshot معرفی شود؛ علت screenshot با traceback Jinja اثبات شده است.

### 4.4 مجوز فعلی

```text
Focused repair issue = #84
Implementation PR    = #85
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
14. mapping keyهای متعارض با متدهای dict در Jinja باید bracket notation داشته باشند.
15. known schema drift نباید generic 500 تولید کند.
16. فقط cache disposable می‌تواند recreate شود؛ Source Truth هرگز drop/rewrite نمی‌شود.
17. FO-4 و بعد بدون attestation جدید ممنوع است.

---

## 7. قرارداد Focused Repair

### 7.1 Template correctness

- list و detail باید با Flask/Jinja واقعی render شوند؛
- `model.items` و `timeline.items` ممنوع‌اند؛
- integration test باید list و Timeline واقعی را render کند؛
- error template نیز باید با Jinja واقعی render شود؛
- mock کردن `render_template` به‌تنهایی برای Exit Gate کافی نیست.

### 7.2 Projection cache compatibility

اگر `followup_work_item_projection` موجود، required columns canonical را ندارد:

1. فقط همین cache حذف شود؛
2. schema canonical دوباره ساخته شود؛
3. cache خالی بماند؛
4. rebuild فقط صریح اجرا شود؛
5. Episode/Link/Event و Source Truthها تغییر نکنند؛
6. rerun idempotent باشد.

### 7.3 Read-model preflight

پیش از product query، حداقل read contract بررسی می‌شود:

```text
followup_work_item_projection
patient_links
followup_episode_links
```

Readiness codeهای PHI-free:

```text
READY
PROJECTION_NOT_BUILT
PROJECTION_SCHEMA_INCOMPATIBLE
PATIENT_IDENTITY_SCHEMA_INCOMPATIBLE
EPISODE_LINK_SCHEMA_INCOMPATIBLE
PROJECTION_READ_FAILED
```

### 7.4 Controlled UX state

در خطاهای SQLite/schema شناخته‌شده:

- صفحهٔ فارسی کنترل‌شده نمایش داده شود، نه generic 500؛
- Worklist قدیمی مسیر اصلی باقی بماند؛
- هیچ داده یا رابطه‌ای حدس زده نشود؛
- raw exception یا PHI نمایش داده نشود؛
- خطاهای ناشناخته با `except Exception` پنهان نشوند.

### 7.5 Test requirements

- real Flask/Jinja list render؛
- real Flask/Jinja Timeline render؛
- static guard علیه Jinja dict-method collision؛
- legacy cache safely recreated empty؛
- migration rerun idempotent؛
- Source Truth و Episode digest ثابت؛
- incompatible read schema → controlled page؛
- feature OFF → 404/navigation hidden؛
- POST → 405؛
- full Specialist و Accounting CI سبز.

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

در repair فقط Read-only flag مصرف می‌شود. Action flags ممنوع‌اند.

---

## 9. Evidence trancheهای قبلی

```text
FO-0: Issue #71 / PR #72/#73 / 731 Specialist + 54 Accounting
FO-1: Issue #74 / PR #75 / 736 Specialist + 54 Accounting
FO-2: Issue #77 / PR #78 / 747 Specialist + 54 Accounting
FO-3: Issue #80 / PR #81 / 754 Specialist + 54 Accounting
```

### Repair evidence

```text
Issue                     = #84
PR                        = #85
Owner screenshot          = generic HTTP 500
Root-cause CI run         = 30808217800
Root-cause failed test    = real Flask/Jinja rendering test
Root cause                = JINJA_DICT_METHOD_COLLISION_ON_ITEMS_KEY
Repair final head         = pending
Repair final CI           = pending
Repair merge              = pending
Post-fix local UX review  = pending
```

---

## 10. Local UX re-review after repair

پس از merge:

```powershell
git checkout main
git pull origin main
cd specialist_clinic
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

برنامه یک بار اجرا و بسته شود تا cache migration اعمال شود. سپس:

```powershell
$env:FOLLOWUP_PROJECTION_SHADOW = "1"
.\.venv\Scripts\python.exe scripts\rebuild_followup_projection.py `
  --database specialist.db `
  --as-of "2026-08-03 12:00:00" `
  --apply

$env:FOLLOWUP_UNIFIED_WORKLIST_READONLY = "1"
.\.venv\Scripts\python.exe start.py
```

مرور باید شامل list، search/filter، Timeline، stale/overdue، deep-link، RTL/keyboard و flag-off باشد. Attestation باید commit نهایی repair را ثبت کند.

---

## 11. Trancheهای آینده

### FO-4 — Claim, Assignment & Controlled Actions

**وضعیت: BLOCKED**

فقط پس از:

```text
PR #85 merged
full CI green
post-fix FO3_UX_ACCEPTED=true
critical_ux_defects=0
governance PR مستقل
```

### FO-5 تا FO-10

**وضعیت: BLOCKED**

Routing/SLA، Structured Contact، SMS automation، Appointment reaction، Outbox، Evidence Assist و Automation Health هرکدام contract، Issue، flag، CI و rollback مستقل می‌خواهند.

---

## 12. Rollback

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

## 13. قواعد ایجنت

1. `main`، Issue #84 و PR #85 را بخواند؛
2. plan، Project State و AGENTS را تطبیق دهد؛
3. فقط focused repair را تغییر دهد؛
4. علت قطعی را مطابق traceback Jinja گزارش کند؛
5. schema hardening را علت قطعی screenshot معرفی نکند؛
6. فقط cache disposable را repair کند؛
7. Source Truthها را تغییر ندهد؛
8. full CI را پس از آخرین commit اجرا کند؛
9. FO-4 را مجاز نکند.

---

## 14. Progress Ledger

| تاریخ | رویداد | وضعیت |
|---|---|---|
| 2026-08-03 | FO-0 validated | completed |
| 2026-08-03 | FO-1 PR #75 | validated |
| 2026-08-03 | FO-2 PR #78 | validated |
| 2026-08-03 | FO-3 PR #81 | technically validated |
| 2026-08-03 | Plan v1.4.0 / PR #82 | UX gate defined |
| 2026-08-03 | مالک generic 500 گزارش کرد | UX blocked |
| 2026-08-03 | Issue #84 / PR #85 | focused repair in progress |
| 2026-08-03 | real render test علت Jinja collision را ثبت کرد | root cause confirmed |
| 2026-08-03 | bracket notation و cache hardening اعمال شد | CI pending |

---

## 15. تصمیم فعلی

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 = TECHNICALLY_VALIDATED
FO-3 LOCAL UX ACCEPTANCE = BLOCKED BY CONFIRMED JINJA RUNTIME DEFECT
FOCUSED FO-3 FIX = IN PROGRESS
FO-4 AND LATER = BLOCKED
```
