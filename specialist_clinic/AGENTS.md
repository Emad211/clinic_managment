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
FO-4 = AUTHORIZED
FO-5 and later = BLOCKED
CURRENT ISSUE = #90
```

Canonical plan: `v1.5.0`.

### FO-3 acceptance

```text
Issue #83 = completed
FO3_UX_ACCEPTED = true
reviewer = Emad211
reviewed_commit = 020803868e1c2755f7669d52da92cb8050a46018
reviewed_on_test_data = true
critical_ux_defects = 0
```

### دامنهٔ مجاز FO-4

- append-only ROUTED / CLAIMED / ASSIGNED events؛
- atomic claim و یک winner؛
- release توسط مالک یا مدیر؛
- assign/reassign با `followup.admin.manage`؛
- role compatibility؛
- stale current-head protection؛
- idempotency و actor/reason audit؛
- owner/SLA read model و UI؛
- Projection rebuild که ownership را حفظ کند؛
- rollback با خاموش‌کردن feature flagها.

### دامنهٔ ممنوع

- mutation حقیقت بالینی یا Source Truth؛
- Clinical Task completion؛
- Structured Contact یا callback؛
- retry/escalation؛
- SMS automation یا approval change؛
- Appointment reaction؛
- outbox/dead-letter؛
- Evidence Assist؛
- Rule یا Hypoglycemia Shadow؛
- write به `clinic_new.db`؛
- FO-5 و بعد.

## Permission contract

```text
view            = clinical.task.view
assign/reassign = followup.admin.manage
PHYSICIAN claim = clinical.task.transition
MANAGER queue   = manager-equivalent effective permission
```

Claim برای صف‌های دیگر باید با permission عملیاتی متناظر fail closed شود.

## Mutation contract

هر mutation باید ثبت کند:

```text
episode_id
action
owner_role
owner_user_id
actor_username
actor_user_id
reason_code
expected_current_assignment_event_id
idempotency_key
effective_at
recorded_at
```

- ownership eventها append-only هستند؛
- stale form mutation ممنوع است؛
- reassignment پنهان ممنوع است؛
- exact replay باید idempotent باشد؛
- terminal item قابل claim/assign نیست.

## Feature Flags

همه default OFF، به‌ویژه:

```text
FOLLOWUP_UNIFIED_WORKLIST_ACTIONS
FOLLOWUP_AUTO_ROUTING
```

وقتی actions flag خاموش است، Unified UI همان FO-3 read-only باقی می‌ماند.

## PR Contract

هر FO-4 PR باید Issue #90، schema/cache impact، permission، stale guard، idempotency، tests، rollback و ثابت‌ماندن Source Truth/Accounting/Clinical Rule را ثبت کند.

Full Specialist + Accounting CI و local owner UX acceptance الزامی است. بدون validation وارد FO-5 نشوید.
