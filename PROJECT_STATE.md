# وضعیت حاکم پروژه — Clinic Management

> **Source of Truth مدیریتی مخزن.** پیش از توسعه، وضعیت واقعی GitHub، این فایل و `PROJECT_STATE.json` خوانده شوند.

- آخرین ممیزی: `2026-08-04 04:12 +03:30`
- شاخهٔ مرجع: `main`
- محیط Specialist: `TEST_ONLY / SYNTHETIC_OR_RESETTABLE`
- دادهٔ واقعی بیمار: `NOT EXPECTED`

---

## جریان‌ها

| جریان | وضعیت | اختیار فعلی | ممنوعیت |
|---|---|---|---|
| Specialist Product | `ACTIVE_PRE_PRODUCTION` | رفتار واقعی main | تغییر بالینی بدون گیت |
| SMS Consent UX | `COMPLETED` | رابط روشن رضایت پیامکی | تغییر policy یا consent defaults |
| FOUX-V1 | `FO_0..FO_4_VALIDATED / FO_5_TECHNICALLY_VALIDATED / OWNER_UX_PENDING` | مرور UX مالک یا defect متمرکز FO-5 | FO-6+ و توسعهٔ بیشتر Runtime |
| Clinical Engine v2 | `INFRASTRUCTURE_IMPLEMENTED / ACTIVATION_GATED` | runtime/audit | activation بدون approval |
| Rule package | `LEGACY_DRAFT_QUARANTINED` | provenance/test | clinical use |
| ADA research | `FROZEN_V0_9_4` | evidence draft | runtime authority |
| Hypoglycemia Shadow | `PAUSED_FOR_RECONCILIATION` | experiment | expansion |
| Release A15 | `STALE_DIVERGED_DRAFT` | reference | direct merge |
| Halqe | `SEPARATE_STRATEGIC_STREAM` | design/rehearsal | automatic cutover |

---

## SMS Consent UX — COMPLETED

```text
Issue #92 / PR #93
Merge 2f78d8b6087df9999ebf953ddbc6bce9e0789379
CI 30842741569
765 Specialist + 54 Accounting
```

Consent defaults، append-only history، stale guard و send policy تغییر نکردند.

---

## FOUX-V1 authority

```text
Canonical plan:
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md
Version 1.7.0

Complete roadmap:
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md
Roadmap version 1.2.0
```

```text
Gate progress = 5.8 / 11 = 52.7% (~53%)
Technical implementation through FO-5 = 6 / 11 = 54.5%
Fully owner-accepted tranches = 5 / 11
Remaining = 47.3%
```

این درصد فقط trancheهای FOUX-V1 را می‌سنجد و production-readiness کل Specialist Clinic نیست.

### FO-0 / FO-1 / FO-2

```text
FO-0 Merge 901dbfdf9c358ecc09d2a60a0680f6a4a8370d17 — 731 + 54
FO-1 Merge 15ef1585c069a74c26fbc0ce859e03906e5f475a — 736 + 54
FO-2 Merge 6c6e33203376a32165418e0d3c6f2a4a48253e7b — CI 30773195914 — 747 + 54
```

### FO-3 — VALIDATED WITH OWNER ACCEPTANCE

```text
FO3_UX_ACCEPTED = true
reviewer = Emad211
reviewed_commit = 020803868e1c2755f7669d52da92cb8050a46018
reviewed_on_test_data = true
critical_ux_defects = 0
```

### FO-4 — VALIDATED WITH OWNER ACCEPTANCE

Ownership/routing:

```text
Issue #94 / PR #95
Merge 27ccb992f2cb43c78bfe98549c3f0414b88fd1d8
Final CI 30844075841
773 Specialist + 54 Accounting
```

Seeded Unified Worklist repair:

```text
Issue #97 / PR #98
Merge 24119671b8b93fdb20db3064a59d416e02d81ef6
CI 30851594179
781 Specialist + 54 Accounting
```

Effective SLA repair:

```text
Issue #99 / PR #100
Merge cd243424ecbae98892e0dfde1780bb846554942f
CI 30852909213
784 Specialist + 54 Accounting
```

Owner attestation:

```text
FO4_UX_ACCEPTED = true
reviewer = Emad211
reviewed_commit = cd243424ecbae98892e0dfde1780bb846554942f
reviewed_on_test_data = true
critical_ux_defects = 0
notes = بررسی شد و مشکل بحرانی مشاهده نشد
```

### FO-5 — TECHNICALLY VALIDATED / OWNER UX PENDING

```text
Authorization Issue = #103
Governance PR = #104
Governance merge = 9c296e70511d73dd79a447cc34ef2aeb79f4edd9
Implementation Issue = #105
Implementation PR = #106
Final head = 2ab1cb1ec956bb9534dea7dd383b76bbf5fb3f5c
Merge = 94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852
CI = 30865955479
801 Specialist + 54 Accounting
```

Technical validation includes:

- authoritative append-only `followup_contact_events` and Episode contact links;
- structured outcome → deterministic next action;
- future callback validation with Jalali date plus time;
- bounded retry and exactly-once unreachable escalation;
- threshold escalation with no remaining due callback;
- `PHONE_INVALID` → Reception/contact repair;
- Routing kill switch as an FO-5 prerequisite;
- exact replay and stale/terminal/permission/owner fail-closed guards;
- free note excluded from Unified Timeline;
- zero automatic SMS, Appointment mutation, clinical completion/decision or Accounting write.

Current gate:

```text
Issue = #107
Action = Local Owner UX Acceptance on merge 94aa2c3e...
Allowed = owner review or focused FO-5 defect fix only
FO-6+ = BLOCKED
```

Local review guide:

```text
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_FO5_LOCAL_UX_ACCEPTANCE.md
```

---

## Feature Flags

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

---

## Exact continuation point

```text
CURRENT = FO-5 Local Owner UX Acceptance
ISSUE = #107
REVIEWED MERGE = 94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852
TECHNICAL CI = 30865955479 — 801 Specialist + 54 Accounting
ALLOWED = local owner review or focused FO-5 defect fix only
FO-6 AND LATER = BLOCKED
```

Remaining Exit Gate FO-5:

- execute the TEST_ONLY local review guide;
- record the acceptance block in Issue #107;
- `critical_ux_defects = 0` before acceptance;
- update Project State after owner acceptance;
- create a separate governance authorization before any FO-6 work.
