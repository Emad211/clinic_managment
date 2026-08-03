# وضعیت حاکم پروژه — Clinic Management

> **Source of Truth مدیریتی مخزن.** پیش از توسعه، وضعیت واقعی GitHub، این فایل و `PROJECT_STATE.json` خوانده شوند.

- آخرین ممیزی: `2026-08-03 21:50 +03:30`
- شاخهٔ مرجع: `main`
- head مرجع پیش از authorization: `f6fb9f87c7fe302c6e18d7f5909aed4128a7f5ca`
- محیط Specialist: `TEST_ONLY / SYNTHETIC_OR_RESETTABLE`
- دادهٔ واقعی بیمار: `NOT EXPECTED`

---

## جریان‌ها

| جریان | وضعیت | اختیار فعلی | ممنوعیت |
|---|---|---|---|
| Specialist Product | `ACTIVE_PRE_PRODUCTION` | رفتار main | تغییر بالینی بدون گیت |
| FOUX-V1 | `FO_0/1/2_VALIDATED / FO_3_OWNER_ACCEPTED / FO_4_AUTHORIZED` | Claim/Assignment/Routing/SLA محدود | FO-5+، SMS automation، Clinical completion |
| Clinical Engine v2 | `INFRASTRUCTURE_IMPLEMENTED / ACTIVATION_GATED` | runtime/audit | activation بدون approval |
| Rule package | `LEGACY_DRAFT_QUARANTINED` | provenance/test | clinical use |
| ADA research | `FROZEN_V0_9_4` | evidence draft | runtime authority |
| Hypoglycemia Shadow | `PAUSED_FOR_RECONCILIATION` | experiment | expansion |
| Release A15 | `STALE_DIVERGED_DRAFT` | reference | direct merge |
| Halqe | `SEPARATE_STRATEGIC_STREAM` | design/rehearsal | automatic cutover |

---

## FOUX-V1

Canonical plan:

```text
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md
Version 1.5.0
```

### FO-0 — VALIDATED

```text
Issue #71 / PR #72/#73
Merge 901dbfdf9c358ecc09d2a60a0680f6a4a8370d17
731 Specialist + 54 Accounting
```

### FO-1 — VALIDATED

```text
Issue #74 / PR #75
Merge 15ef1585c069a74c26fbc0ce859e03906e5f475a
736 Specialist + 54 Accounting
```

### FO-2 — VALIDATED

```text
Issue #77 / PR #78
Merge 6c6e33203376a32165418e0d3c6f2a4a48253e7b
CI 30773195914
747 Specialist + 54 Accounting
```

### FO-3 — VALIDATED WITH OWNER ACCEPTANCE

```text
Initial PR #81
Runtime repair #84/#85
Operator copy repair #87/#88
Runtime/UI commit 020803868e1c2755f7669d52da92cb8050a46018
Governance main f6fb9f87c7fe302c6e18d7f5909aed4128a7f5ca
Latest CI 30828272752
762 Specialist + 54 Accounting
```

Issue #83:

```text
FO3_UX_ACCEPTED = true
reviewer = Emad211
reviewed_commit = 020803868e1c2755f7669d52da92cb8050a46018
reviewed_on_test_data = true
critical_ux_defects = 0
```

Issue #83 بسته شد. درخواست شفاف‌سازی بخش رضایت پیامکی یک task مستقل UX است.

### FO-4 — AUTHORIZED

Issue حاکم: `#90`

دامنهٔ مجاز:

- append-only ownership/routing events؛
- atomic claim/release/reassign؛
- role queues و role compatibility؛
- stale form/current-head guard؛
- actor/reason/idempotency audit؛
- owner و SLA در Unified UI؛
- Projection rebuild از event stream؛
- feature flags default OFF.

دامنهٔ ممنوع:

- Clinical completion یا decision؛
- Structured Contact، retry یا escalation؛
- SMS automation؛
- Appointment reaction؛
- outbox/dead-letter؛
- Evidence Assist؛
- FO-5 و بعد.

Feature flags:

```text
FOLLOWUP_UNIFIED_WORKLIST_ACTIONS
FOLLOWUP_AUTO_ROUTING
```

هر دو default OFF هستند.

---

## Exit Gate FO-4

```text
concurrent claim one winner              = REQUIRED
stale mutation fail closed               = REQUIRED
zero silent reassignment                 = REQUIRED
projection rebuild preserves ownership   = REQUIRED
source truth unchanged                   = REQUIRED
full CI green                            = REQUIRED
local owner UX acceptance                = REQUIRED
```

تا آن زمان FO-5 و بعد مسدود است.

---

## Freeze فعلی

```text
FOUX FO-4 bounded implementation = AUTHORIZED AFTER GOVERNANCE MERGE
FOUX FO-5 and later              = BLOCKED
New clinical rules               = PAUSED
Hypoglycemia Shadow expansion    = PAUSED
Write to clinic_new.db           = FORBIDDEN
```

---

## تصمیم فعلی

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 = VALIDATED WITH OWNER ACCEPTANCE
FO-4 = AUTHORIZED
FO-5 AND LATER = BLOCKED
```
