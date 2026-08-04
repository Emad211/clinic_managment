# وضعیت حاکم پروژه — Clinic Management

> **Source of Truth مدیریتی مخزن.** پیش از توسعه، وضعیت واقعی GitHub، این فایل و `PROJECT_STATE.json` خوانده شوند.

- آخرین ممیزی: `2026-08-04 17:20 +03:30`
- شاخهٔ مرجع: `main`
- محیط Specialist: `TEST_ONLY / SYNTHETIC_OR_RESETTABLE`
- دادهٔ واقعی بیمار: `NOT EXPECTED`

---

## جریان‌ها

| جریان | وضعیت | اختیار فعلی | ممنوعیت |
|---|---|---|---|
| Specialist Product | `ACTIVE_PRE_PRODUCTION` | رفتار واقعی main | تغییر بالینی بدون گیت |
| SMS Consent UX | `COMPLETED` | رابط روشن رضایت پیامکی | تغییر policy یا consent defaults |
| FOUX-V1 | `FO_0..FO_5_VALIDATED / FO_6_AUTHORIZED` | فقط پیاده‌سازی محدود SMS CARE اداری تحت Issue #109 | FO-7+، کمپین/MARKETING و اتوماسیون بالینی |
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
Version 1.8.0

Complete roadmap:
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md
Roadmap version 1.3.0
```

```text
Gate progress = 6.0 / 11 = 54.5% (~55%)
Technical implementation through FO-5 = 6 / 11 = 54.5%
Fully owner-accepted tranches = 6 / 11
Remaining = 45.5%
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

### FO-5 — VALIDATED WITH OWNER ACCEPTANCE

```text
Implementation Issue = #105 / PR #106
Runtime merge = 94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852
Runtime CI = 30865955479 — 801 Specialist + 54 Accounting
Governance/docs PR = #108
Governance merge = 7810245d6e858098af1a0db15d3f9d23bf97e138
Owner acceptance Issue = #107 (completed)
```

```text
FO5_UX_ACCEPTED = true
reviewer = Emad211
reviewed_commit = 94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852
reviewed_on_test_data = true
critical_ux_defects = 0
notes = بررسی شد و مشکل بحرانی مشاهده نشد
```

### FO-6 — AUTHORIZED / IMPLEMENTATION PENDING

```text
Authorization Issue = #109
Governance PR = #110
Scope = Administrative CARE SMS freshness and AUTO_GUARDED only
Feature Flag = FOLLOWUP_SMS_AUTO_GUARDED
Default = OFF
```

محدودهٔ مجاز:

- policy levels: `CLINICIAN_ONLY / MANUAL_APPROVAL / AUTO_GUARDED`؛
- AUTO_GUARDED فقط برای `appointment_reminder` و `refill_due`؛
- purpose فقط `CARE`؛
- immutable policy/template/candidate/decision؛
- TTL پیش‌فرض ۲۴ ساعت با بازهٔ ۱ تا ۷۲ ساعت؛
- revalidation کامل consent، phone، template/body hash، source period، quiet hours، daily cap، cooldown، idempotency و provider؛
- executor صریح و محدود؛ بدون ارسال از GET یا startup.

خارج از دامنه:

- MARKETING و campaign auto-send؛
- free-text auto-send؛
- `CLINICIAN_ONLY` یا `MANUAL_APPROVAL` auto-send؛
- `lapsed`، دعوت‌ها و invoice outreach در allowlist اولیه؛
- Appointment mutation یا clinical decision/completion؛
- SMS delivery → Episode transition؛
- Outbox، dead-letter، scheduler health و FO-7+؛
- Rule/Hypoglycemia یا Accounting write.

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
CURRENT = FO-6 Governed SMS Automation & Freshness implementation
ISSUE = #109
BASE = main after governance PR #110
ALLOWED = bounded administrative CARE SMS implementation only
FO-7 AND LATER = BLOCKED
```

Exit Gate FO-6:

- immutable policy/template/candidate/decision contracts؛
- exact allowlist and policy-level enforcement؛
- fresh consent/phone/template/body/source validation؛
- expiry and append-only supersession؛
- quiet-hours/daily-cap/cooldown/provider fail-closed؛
- exact replay and concurrent one-winner؛
- zero GET/startup send؛
- zero campaign/MARKETING/free-text/clinical automatic send؛
- full CI؛
- local owner UX acceptance؛
- separate governance before FO-7.
