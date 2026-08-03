# Follow-up Orchestration & UX v1 — Canonical Implementation Plan

> **نام فایل مرجع:** `specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md`
>
> **کد برنامه:** `FOUX-V1`
>
> **نسخه:** `1.6.0`
>
> **آخرین بازبینی:** `2026-08-04`
>
> **وضعیت:** `FO_0_VALIDATED / FO_1_VALIDATED / FO_2_VALIDATED / FO_3_VALIDATED_WITH_OWNER_ACCEPTANCE / FO_4_VALIDATED_WITH_OWNER_ACCEPTANCE / FO_5_AUTHORIZED_IMPLEMENTATION_PENDING / FO_6_AND_LATER_BLOCKED`
>
> **مالک:** `Emad211`
>
> **دامنه:** فقط `specialist_clinic/`
>
> **محیط:** `TEST_ONLY / SYNTHETIC_OR_RESETTABLE_DATA`
>
> **رودمپ کامل FO-0 تا FO-10:** `specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md`

---

## 1. ترتیب اعتماد

1. وضعیت واقعی `main`، PRها، Issueها و CI؛
2. `PROJECT_STATE.json` و `PROJECT_STATE.md`؛
3. این سند و `specialist_clinic/AGENTS.md`؛
4. قراردادهای نزدیک به کد؛
5. متن PRهای تاریخی؛
6. حافظهٔ گفتگو یا ایجنت.

هر ادعای تکمیل یا merge باید SHA و CI evidence داشته باشد.

---

## 2. هدف محصول و معماری

Task، SMS، Contact، Appointment، Clinical Outcome و Encounter Commitment بدون بازنویسی Source of Truthهای موجود در Episode و Projection بازسازی‌پذیر دیده شوند تا اپراتور بداند چرا مورد ساخته شده، وضعیت و موعد چیست، صف مسئول کدام است، مسئول واقعی چه کسی است و اقدام بعدی چیست.

```text
Authoritative Source Truths
        ↓
Episode / Link / append-only Event       [FO-1]
        ↓
Deterministic Projection Cache           [FO-2]
        ↓
Unified Worklist / Timeline              [FO-3]
        ↓
Ownership / Routing / effective SLA      [FO-4]
```

Storageهای معتبر:

```text
followup_episodes
followup_episode_links
followup_episode_events
followup_work_item_projection
```

Episode حقیقت بالینی نیست؛ Projection cache قابل بازسازی است؛ Worklist قدیمی تا cutover مستقل authority بالینی باقی می‌ماند.

---

## 3. وضعیت trancheها

| Tranche | وضعیت | Evidence اصلی |
|---|---|---|
| FO-0 | `VALIDATED` | Issue #71، PR #72/#73، 731 + 54 |
| FO-1 | `VALIDATED` | Issue #74، PR #75، 736 + 54 |
| FO-2 | `VALIDATED` | Issue #77، PR #78، CI 30773195914، 747 + 54 |
| FO-3 | `VALIDATED_WITH_OWNER_ACCEPTANCE` | Issue #83، PR #81/#85/#88، 762 + 54 |
| FO-4 | `TECHNICALLY_VALIDATED / LOCAL_UX_PENDING` | Issue #94، PR #95، repairهای #97/#98 و #99/#100 |
| FO-5 و بعد | `BLOCKED` | owner acceptance و governance مستقل لازم است |

جزئیات کامل FO-5 تا FO-10، dependencyها، feature flagها، exit gateها و KPIهای pilot در رودمپ کامل ثبت شده‌اند.

---

## 4. Evidence معتبر

### FO-3 owner acceptance

```text
FO3_UX_ACCEPTED = true
reviewer = Emad211
reviewed_commit = 020803868e1c2755f7669d52da92cb8050a46018
reviewed_on_test_data = true
critical_ux_defects = 0
```

### FO-4 ownership / routing

```text
Authorization Issue #90 / PR #91
Implementation Issue #94 / PR #95
Final head ec98140fc262f26089e5a05b3e24a2b9647882ff
Merge 27ccb992f2cb43c78bfe98549c3f0414b88fd1d8
Final CI 30844075841
773 Specialist + 54 Accounting
```

قابلیت‌های معتبر:

- append-only `ROUTED / CLAIMED / ASSIGNED`؛
- atomic claim با یک winner؛
- exact replay idempotent؛
- stale form، permission و terminal checks به‌صورت fail closed؛
- release، assign/reassign و تغییر صف؛
- صف مؤثر و مسئول واقعی در list/detail؛
- ownership overlay بدون N+1؛
- حفظ ownership پس از Projection rebuild؛
- POSTهای FO-4 با flag خاموش = 404؛
- Source Truth بدون تغییر.

### FO-4 repair — Seeded Unified Worklist

```text
Issue #97 / PR #98
Final head 452b7c6eb89eb0b19da1e0de0167860fff8f6c71
Merge 24119671b8b93fdb20db3064a59d416e02d81ef6
CI 30851594179
781 Specialist + 54 Accounting
```

علت قطعی:

- seed منبع `followup_tasks` را می‌ساخت، اما Episode/Link reconciliation و Projection rebuild را اجرا نمی‌کرد؛
- جدول Projection موجود ولی خالی، به‌اشتباه READY تلقی می‌شد؛
- fixture taskها mapping پایدار بیرونی نداشتند.

اصلاح معتبر:

- `seed_demo_data.py` و action مدیریتی `prepare-demo-cohort` پس از commit منبع، Episode و Projection را صریح آماده می‌کنند؛
- recovery command مستقل برای دیتابیس seedشده اضافه شد؛
- GET و startup هیچ rebuild پنهانی انجام نمی‌دهند؛
- fixture task IDها با namespace تستی `settings` پایدار می‌مانند؛
- پیگیری دستی بیمار TEST حفظ می‌شود؛
- seed تکراری Episode/Link/Event تکراری نمی‌سازد؛
- وضعیت `PROJECTION_EMPTY_WITH_SOURCE_DATA` جای empty-result گمراه‌کننده را می‌گیرد؛
- SQL مربوط به persistence در `DemoSeedFollowupRepository` باقی می‌ماند.

### FO-4 repair — Canonical effective SLA

```text
Issue #99 / PR #100
Final head 3c11ef590581b60a140c27f4924adc4ad9f67c41
Merge cd243424ecbae98892e0dfde1780bb846554942f
CI 30852909213
784 Specialist + 54 Accounting
```

واژگان canonical:

```text
FUTURE
DUE_TODAY
OVERDUE
DUE_UNKNOWN
WAITING
BLOCKED
TERMINAL
```

Dropdown، read model و badgeها فقط همین واژگان را مصرف می‌کنند. SLA مؤثر در زمان request از `state_class`، `action_due_at` و Tehran-local `now` محاسبه می‌شود؛ بنابراین موردی که موعدش پس از آخرین rebuild گذشته است فوراً زیر `OVERDUE` دیده می‌شود، بدون read-time write.

---

## 5. Invariantهای غیرقابل‌مذاکره

1. Source Truthهای موجود authoritative می‌مانند.
2. Episode و Projection حقیقت بالینی نیستند.
3. relation، event، due date، target، outcome یا assignment جعل نمی‌شود.
4. هیچ GET یا startup، backfill/rebuild پنهانی انجام نمی‌دهد.
5. Clinical completion فقط با Evidence و transition معتبر انجام می‌شود.
6. Appointment به‌تنهایی Clinical Task را complete نمی‌کند.
7. owner role و owner user دو مفهوم جدا هستند.
8. ownership mutationها append-only، idempotent و audit‌شده‌اند.
9. claim هم‌زمان دقیقاً یک winner دارد.
10. stale form و terminal mutation fail closed هستند.
11. seed تکراری نباید task دستی یا Episode history را حذف/تکرار کند.
12. effective SLA فقط read model است و Projection یا Source Truth را در request تغییر نمی‌دهد.
13. `clinic_new.db` فقط read-only است.
14. FO-5 و بعد بدون owner acceptance و governance مستقل ممنوع است.

---

## 6. Feature Flags

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

---

## 7. قدم مجاز فعلی — FO-4 Local Owner UX Acceptance

Issue حاکم: `#94`

فقط مرور لوکال یا defect متمرکز FO-4 مجاز است. FO-5 و اتوماسیون جدید ممنوع‌اند.

### راه‌اندازی و آماده‌سازی seed

```powershell
git checkout main
git pull origin main
cd specialist_clinic
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

$env:FOLLOWUP_PROJECTION_SHADOW = "1"
.\.venv\Scripts\python.exe scripts\prepare_seeded_followup_view.py `
  --database specialist.db

$env:FOLLOWUP_UNIFIED_WORKLIST_READONLY = "1"
$env:FOLLOWUP_UNIFIED_WORKLIST_ACTIONS = "1"
$env:FOLLOWUP_AUTO_ROUTING = "1"
.\.venv\Scripts\python.exe start.py
```

اجرای دوبارهٔ `seed_demo_data.py` نیز seed و نمای یکپارچه را با هم آماده می‌کند.

### Checklist پذیرش

- seed موجود باید itemهای نمای یکپارچه را نشان دهد؛
- اگر Source Data هست ولی Projection آماده نیست، پیام recovery روشن دیده شود، نه «فیلتر نتیجه ندارد»؛
- seed دوباره، پیگیری دستی TEST را حفظ و Episode/Link/Event تکراری نسازد؛
- «صف مسئول» و «مسئول فعلی» جدا باشند؛
- دریافت، آزادکردن، assign/reassign و تغییر صف درست کار کنند؛
- Timeline تغییر صف و مسئول را نشان دهد؛
- stale form mutation نکند؛
- terminal item control عملیاتی نداشته باشد؛
- dropdown موعد فقط هفت وضعیت canonical را داشته باشد؛
- هر row badge وضعیت موعد واقعی داشته باشد؛
- موردی که موعدش گذشته فوراً در فیلتر «موعدگذشته» دیده شود، حتی بدون rebuild؛
- با Actions=0 رابط FO-3 read-only و POSTها 404 باشند؛
- Worklist قدیمی، SMS، Appointment و Clinical behavior تغییر نکرده باشند.

### Attestation لازم

```text
FO4_UX_ACCEPTED = true|false
reviewer = Emad211
reviewed_commit = cd243424ecbae98892e0dfde1780bb846554942f
reviewed_on_test_data = true
critical_ux_defects = <number>
notes = <observations or defects>
```

---

## 8. Exit Gate برای FO-5

```text
FO-4 ownership/routing merged           = PASS
Seeded Unified Worklist repair          = PASS
Canonical effective SLA                 = PASS
Latest code CI 30852909213              = PASS
FO4_UX_ACCEPTED=true                    = PENDING
critical_ux_defects=0                   = PENDING
separate governance authorization       = PENDING
```

Structured Contact، Retry/Escalation، SMS automation، Appointment reaction، Outbox/Dead-letter، Evidence Assist و FO-5+ تا آن زمان مسدودند.

---

## 9. Rollback

```powershell
$env:FOLLOWUP_UNIFIED_WORKLIST_ACTIONS = "0"
$env:FOLLOWUP_AUTO_ROUTING = "0"
```

FO-3 read-only باقی می‌ماند؛ audit events حذف نمی‌شوند؛ Source Truth rollback لازم ندارد.

---

## FO-4 Owner Acceptance and FO-5 Authorization

FO-4 owner acceptance در Issue #94 ثبت شد:

```text
FO4_UX_ACCEPTED = true
reviewer = Emad211
reviewed_commit = cd243424ecbae98892e0dfde1780bb846554942f
reviewed_on_test_data = true
critical_ux_defects = 0
notes = بررسی شد و مشکل بحرانی مشاهده نشد
```

FO-5 با Issue #103 و PR حاکمیتی #104 فقط برای دامنهٔ زیر مجاز است:

- structured contact outcomes؛
- callback scheduling؛
- bounded retry/attempt policy؛
- unreachable escalation؛
- phone-invalid workflow؛
- Unified contact UX؛
- append-only/idempotent audit؛
- feature flag `FOLLOWUP_STRUCTURED_CONTACT` با پیش‌فرض OFF.

SMS automation، Appointment mutation، Clinical completion/decision، Outbox و FO-6+ همچنان ممنوع‌اند.

---

## 10. Roadmap authority and measured progress

رودمپ کامل FO-0 تا FO-10 در فایل زیر نگهداری می‌شود:

```text
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md
```

مدل رسمی tranche-equivalent:

```text
FO-0..FO-3 validated                     = 4.0
FO-4 technically validated / UX pending = 0.8
FO-5..FO-10 blocked/not started          = 0.0
Progress                                 = 5.0 / 11 = 45.5%
Remaining                                = 54.5%
```

این درصد فقط FOUX-V1 است و production-readiness کل Specialist Clinic نیست. نقطهٔ ادامه Issue #103 و پیاده‌سازی FO-5 در یک Issue/PR مستقل است. حضور FO-5 تا FO-10 در رودمپ به‌معنی authorization نیست.

---

## 11. تصمیم فعلی

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 = VALIDATED WITH OWNER ACCEPTANCE
FO-4 = VALIDATED WITH OWNER ACCEPTANCE
FO-5 = AUTHORIZED / IMPLEMENTATION PENDING
FO-6 AND LATER = BLOCKED
```