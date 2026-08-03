# Specialist Clinic — Agent Instructions

این فایل نزدیک‌ترین دستور حاکم برای تغییرات زیر `specialist_clinic/` است.

## ترتیب مطالعه

1. وضعیت واقعی `main`، PRها و Issueها؛
2. `PROJECT_STATE.md` و `PROJECT_STATE.json`؛
3. `AGENTS.md` ریشه؛
4. همین فایل؛
5. سند canonical مرتبط.

برای Follow-up، Task، Worklist، SMS، Contact و Appointment:

```text
docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md
```

## محیط

```text
specialist.db = TEST_ONLY / SYNTHETIC_OR_RESETTABLE
real patient PHI = NOT EXPECTED
```

این وضعیت هیچ guardrail امنیتی یا بالینی را حذف نمی‌کند.

## وضعیت FOUX-V1

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 = VALIDATED WITH OWNER ACCEPTANCE
FO-4 = TECHNICALLY VALIDATED
FO-4 LOCAL UX ACCEPTANCE = PENDING
FO-5 and later = BLOCKED
CURRENT ISSUE = #94
```

Canonical plan: `v1.5.2`.

## FO-4 Evidence

### Ownership / Routing

```text
Issue #94 / PR #95
Merge 27ccb992f2cb43c78bfe98549c3f0414b88fd1d8
Final CI 30844075841
773 Specialist + 54 Accounting
```

### Seeded Unified Worklist repair

```text
Issue #97 / PR #98
Final head 452b7c6eb89eb0b19da1e0de0167860fff8f6c71
Merge 24119671b8b93fdb20db3064a59d416e02d81ef6
CI 30851594179
781 Specialist + 54 Accounting
```

### Canonical effective SLA

```text
Issue #99 / PR #100
Final head 3c11ef590581b60a140c27f4924adc4ad9f67c41
Merge cd243424ecbae98892e0dfde1780bb846554942f
CI 30852909213
784 Specialist + 54 Accounting
```

## قرارداد معتبر FO-4

- append-only `ROUTED / CLAIMED / ASSIGNED`؛
- atomic claim و دقیقاً یک winner؛
- exact replay idempotent؛
- stale، permission و terminal checks به‌صورت fail closed؛
- release، assign/reassign و route مدیریتی؛
- owner و صف مؤثر در list/detail؛
- ownership batch overlay بدون N+1؛
- Projection rebuild که ownership را حفظ کند؛
- seed صریحاً Episode/Link و Projection را آماده کند؛
- GET/startup rebuild پنهانی نداشته باشد؛
- seed تکراری task دستی را حفظ و Episode/Link/Event تکراری نسازد؛
- Source Data + empty Projection controlled recovery state باشد؛
- SLA filter فقط `FUTURE / DUE_TODAY / OVERDUE / DUE_UNKNOWN / WAITING / BLOCKED / TERMINAL` را مصرف کند؛
- موعد گذشته در request بعدی فوراً `OVERDUE` شود، بدون read-time write؛
- Source Truth بدون تغییر بماند.

## دامنهٔ مجاز فعلی

فقط:

- مرور لوکال Issue #94 روی runtime/UI commit `cd243424ecbae98892e0dfde1780bb846554942f`؛
- ثبت feedback و owner attestation؛
- focused FO-4 defect fix با Issue/PR/CI مستقل؛
- governance update پس از نتیجهٔ مرور.

## دامنهٔ ممنوع

- شروع FO-5؛
- Clinical Task completion یا clinical decision؛
- Structured Contact، callback، retry یا escalation؛
- SMS automation یا approval change؛
- Appointment reaction؛
- outbox/dead-letter؛
- Evidence Assist؛
- Rule یا Hypoglycemia Shadow؛
- write به `clinic_new.db`.

## Feature Flags

همه default OFF، به‌ویژه:

```text
FOLLOWUP_PROJECTION_SHADOW
FOLLOWUP_UNIFIED_WORKLIST_READONLY
FOLLOWUP_UNIFIED_WORKLIST_ACTIONS
FOLLOWUP_AUTO_ROUTING
```

با Actions خاموش، Unified UI باید FO-3 read-only باشد و POSTها 404 شوند.

## مرور Issue #94

```powershell
git checkout main
git pull origin main
cd specialist_clinic

$env:FOLLOWUP_PROJECTION_SHADOW = "1"
.\.venv\Scripts\python.exe scripts\prepare_seeded_followup_view.py `
  --database specialist.db

$env:FOLLOWUP_UNIFIED_WORKLIST_READONLY = "1"
$env:FOLLOWUP_UNIFIED_WORKLIST_ACTIONS = "1"
$env:FOLLOWUP_AUTO_ROUTING = "1"
.\.venv\Scripts\python.exe start.py
```

Attestation:

```text
FO4_UX_ACCEPTED = true|false
reviewer = Emad211
reviewed_commit = cd243424ecbae98892e0dfde1780bb846554942f
reviewed_on_test_data = true
critical_ux_defects = <number>
notes = <observations or defects>
```

## PR Contract

هر fix باید Issue، scope، feature flag، permission، stale/terminal/idempotency guard، full tests، rollback و ثابت‌ماندن Source Truth/Accounting/Clinical Rule را ثبت کند.

بدون `FO4_UX_ACCEPTED=true`، `critical_ux_defects=0` و governance مستقل وارد FO-5 نشوید.
