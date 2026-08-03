# وضعیت حاکم پروژه — Clinic Management

> **Source of Truth مدیریتی مخزن.** پیش از توسعه، وضعیت واقعی GitHub، این فایل و `PROJECT_STATE.json` خوانده شوند.

- آخرین ممیزی: `2026-08-04 01:20 +03:30`
- شاخهٔ مرجع: `main`
- head مرجع runtime/UI برای مرور: `cd243424ecbae98892e0dfde1780bb846554942f`
- محیط Specialist: `TEST_ONLY / SYNTHETIC_OR_RESETTABLE`
- دادهٔ واقعی بیمار: `NOT EXPECTED`

---

## جریان‌ها

| جریان | وضعیت | اختیار فعلی | ممنوعیت |
|---|---|---|---|
| Specialist Product | `ACTIVE_PRE_PRODUCTION` | رفتار واقعی main | تغییر بالینی بدون گیت |
| SMS Consent UX | `COMPLETED` | رابط روشن رضایت پیامکی | تغییر policy یا consent defaults |
| FOUX-V1 | `FO_0/1/2_VALIDATED / FO_3_OWNER_ACCEPTED / FO_4_TECHNICALLY_VALIDATED / UX_PENDING` | مرور لوکال یا defect متمرکز FO-4 | FO-5+ و اتوماسیون‌های بعدی |
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

Presentation روشن شد؛ consent defaults، append-only history، stale guard و send policy تغییر نکردند.

---

## FOUX-V1

Canonical plan:

```text
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md
Version 1.5.2
```

Complete roadmap:

```text
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md
FO-0 through FO-10
Gate progress = 4.8 / 11 = 43.6% (~44%)
Technical implementation through FO-4 = 5 / 11 = 45.5%
Remaining = 56.4%
```

مدل درصد رسمی فقط trancheهای FOUX-V1 را می‌سنجد: FO-0 تا FO-3 امتیاز کامل و FO-4 به‌دلیل pending بودن owner acceptance امتیاز 0.8 دارد. این درصد production-readiness کل Specialist Clinic نیست.

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

### FO-4 ownership/routing — TECHNICALLY VALIDATED

```text
Issue #94 / PR #95
Merge 27ccb992f2cb43c78bfe98549c3f0414b88fd1d8
CI 30844075841
773 Specialist + 54 Accounting
```

قابلیت‌ها: atomic one-winner claim، append-only ownership events، stale/permission/terminal fail-closed، release و assign/reassign، صف مؤثر و مسئول واقعی، rebuild-preserved ownership و flag-off POST=404.

### FO-4 seeded Worklist repair — COMPLETED

```text
Issue #97 / PR #98
Final head 452b7c6eb89eb0b19da1e0de0167860fff8f6c71
Merge 24119671b8b93fdb20db3064a59d416e02d81ef6
CI 30851594179
781 Specialist + 54 Accounting
```

- seed، Episode/Link reconciliation و Projection rebuild را صریح اجرا می‌کند؛
- دیتابیس seedشده recovery command دارد؛
- Source Data + empty Projection به‌صورت controlled state دیده می‌شود؛
- fixture task ID پایدار است؛
- پیگیری دستی TEST حفظ می‌شود؛
- seed تکراری Episode/Link/Event تکراری نمی‌سازد؛
- GET/startup rebuild پنهانی ندارد.

### FO-4 canonical effective SLA — COMPLETED

```text
Issue #99 / PR #100
Final head 3c11ef590581b60a140c27f4924adc4ad9f67c41
Merge cd243424ecbae98892e0dfde1780bb846554942f
CI 30852909213
784 Specialist + 54 Accounting
```

وضعیت‌های معتبر موعد:

```text
FUTURE / DUE_TODAY / OVERDUE / DUE_UNKNOWN / WAITING / BLOCKED / TERMINAL
```

فیلتر و badge بر اساس SLA مؤثر در زمان مشاهده کار می‌کنند؛ گذشت موعد بدون Projection rebuild نیز فوراً در `OVERDUE` دیده می‌شود و هیچ read-time write انجام نمی‌شود.

### مراحل باقی‌ماندهٔ ثبت‌شده در رودمپ

```text
FO-5  Structured Contact, Retry & Escalation       = BLOCKED
FO-6  Governed SMS Automation & Freshness          = BLOCKED
FO-7  Cross-channel Transitions & Outbox            = BLOCKED
FO-8  Clinical Evidence Assist                      = BLOCKED
FO-9  Automation Health & Operational Control       = BLOCKED
FO-10 Controlled Pilot, KPI Proof & Cutover         = BLOCKED
```

تعریف کامل scope، safety boundary، exit gate و KPI این مراحل در رودمپ کامل موجود است. حضور آن‌ها در سند به‌معنی authorization نیست.

---

## قدم مجاز فعلی

```text
Issue #94 — FO-4 Local Owner UX Acceptance
Runtime/UI review commit = cd243424ecbae98892e0dfde1780bb846554942f
```

راه‌اندازی:

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

---

## Exit Gate برای FO-5

```text
FO-4 ownership/routing                 = PASS
Seeded Unified Worklist repair         = PASS
Canonical effective SLA                = PASS
Latest code CI 30852909213             = PASS
FO4_UX_ACCEPTED=true                   = PENDING
critical_ux_defects=0                  = PENDING
separate governance authorization      = PENDING
```

تا آن زمان Structured Contact، Retry/Escalation، SMS automation، Appointment reaction، Outbox/Dead-letter، Evidence Assist و FO-5+ مسدودند.

---

## Freeze و تصمیم فعلی

```text
FOUX FO-4 local UX review       = ALLOWED
FOUX focused FO-4 defect fix    = ALLOWED IF DEFECT FOUND
FOUX FO-5 and later             = BLOCKED
New clinical rules              = PAUSED
Hypoglycemia Shadow expansion   = PAUSED
Write to clinic_new.db          = FORBIDDEN

FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 = VALIDATED WITH OWNER ACCEPTANCE
FO-4 = TECHNICALLY VALIDATED / LOCAL UX ACCEPTANCE PENDING
FO-5 AND LATER = BLOCKED
```