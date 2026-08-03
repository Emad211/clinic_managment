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

Canonical plan: `v1.5.1`.

### FO-4 Evidence

```text
Authorization Issue #90 / PR #91
Implementation Issue #94 / PR #95
Final head ec98140fc262f26089e5a05b3e24a2b9647882ff
Merge 27ccb992f2cb43c78bfe98549c3f0414b88fd1d8
Final CI 30844075841
773 Specialist + 54 Accounting
```

### قرارداد معتبر FO-4

- append-only `ROUTED / CLAIMED / ASSIGNED` events؛
- atomic claim و دقیقاً یک winner؛
- exact replay idempotent؛
- stale current-head protection؛
- role/permission compatibility؛
- release توسط owner یا مدیر؛
- assign/reassign و route مدیریتی؛
- terminal action rejection قبل از role/owner checks؛
- owner و صف مؤثر در list/detail؛
- ownership batch overlay بدون N+1؛
- Projection rebuild که ownership را حفظ کند؛
- Source Truth بدون تغییر.

## دامنهٔ مجاز فعلی

فقط:

- مرور لوکال Issue #94 روی commit `27ccb992f2cb43c78bfe98549c3f0414b88fd1d8`؛
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

## Permission و Mutation Contract

```text
view            = clinical.task.view
assign/reassign = followup.admin.manage
PHYSICIAN claim = clinical.task.transition
MANAGER queue   = manager-equivalent effective permission
```

هر mutation باید Episode، action، owner role/user، actor، reason، expected event، idempotency key و timestamps را ثبت کند.

- stale form mutation ممنوع است؛
- reassignment پنهان ممنوع است؛
- terminal item هیچ ownership actionی ندارد؛
- exact replay event دوم نمی‌سازد.

## Feature Flags

همه default OFF، به‌ویژه:

```text
FOLLOWUP_UNIFIED_WORKLIST_READONLY
FOLLOWUP_UNIFIED_WORKLIST_ACTIONS
FOLLOWUP_AUTO_ROUTING
```

مرور FO-4 با هر سه flag روشن انجام می‌شود. با Actions خاموش، Unified UI باید همان FO-3 read-only باشد و POSTها 404 شوند.

## مرور Issue #94

```powershell
git checkout main
git pull origin main
cd specialist_clinic

$env:FOLLOWUP_PROJECTION_SHADOW = "1"
.\.venv\Scripts\python.exe scripts\rebuild_followup_projection.py `
  --database specialist.db `
  --as-of "2026-08-03 12:00:00" `
  --apply

$env:FOLLOWUP_UNIFIED_WORKLIST_READONLY = "1"
$env:FOLLOWUP_UNIFIED_WORKLIST_ACTIONS = "1"
$env:FOLLOWUP_AUTO_ROUTING = "1"
.\.venv\Scripts\python.exe start.py
```

Attestation:

```text
FO4_UX_ACCEPTED = true|false
reviewer = Emad211
reviewed_commit = 27ccb992f2cb43c78bfe98549c3f0414b88fd1d8
reviewed_on_test_data = true
critical_ux_defects = <number>
notes = <observations or defects>
```

## SMS Consent UX

Issue #92 / PR #93 با merge `2f78d8b6087df9999ebf953ddbc6bce9e0789379` تکمیل شد. این تغییر فقط presentation است؛ consent defaults، append-only history، stale guard و send policy تغییر نکردند.

## PR Contract

هر fix باید Issue، scope، feature flag، permission، stale/terminal/idempotency guard، full tests، rollback و ثابت‌ماندن Source Truth/Accounting/Clinical Rule را ثبت کند.

بدون `FO4_UX_ACCEPTED=true` و governance مستقل وارد FO-5 نشوید.
