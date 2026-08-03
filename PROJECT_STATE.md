# وضعیت حاکم پروژه — Clinic Management

> **Source of Truth مدیریتی مخزن.** پیش از توسعه، وضعیت واقعی GitHub، این فایل و `PROJECT_STATE.json` خوانده شوند.

- آخرین ممیزی: `2026-08-03 22:45 +03:30`
- شاخهٔ مرجع: `main`
- head مرجع محصول: `27ccb992f2cb43c78bfe98549c3f0414b88fd1d8`
- محیط Specialist: `TEST_ONLY / SYNTHETIC_OR_RESETTABLE`
- دادهٔ واقعی بیمار: `NOT EXPECTED`

---

## جریان‌ها

| جریان | وضعیت | اختیار فعلی | ممنوعیت |
|---|---|---|---|
| Specialist Product | `ACTIVE_PRE_PRODUCTION` | رفتار واقعی main | تغییر بالینی بدون گیت |
| SMS Consent UX | `COMPLETED` | رابط روشن رضایت پیامکی | تغییر policy یا consent defaults |
| FOUX-V1 | `FO_0/1/2_VALIDATED / FO_3_OWNER_ACCEPTED / FO_4_TECHNICALLY_VALIDATED / UX_PENDING` | فقط مرور لوکال یا defect متمرکز FO-4 | FO-5+ و اتوماسیون‌های بعدی |
| Clinical Engine v2 | `INFRASTRUCTURE_IMPLEMENTED / ACTIVATION_GATED` | runtime/audit | activation بدون approval |
| Rule package | `LEGACY_DRAFT_QUARANTINED` | provenance/test | clinical use |
| ADA research | `FROZEN_V0_9_4` | evidence draft | runtime authority |
| Hypoglycemia Shadow | `PAUSED_FOR_RECONCILIATION` | experiment | expansion |
| Release A15 | `STALE_DIVERGED_DRAFT` | reference | direct merge |
| Halqe | `SEPARATE_STRATEGIC_STREAM` | design/rehearsal | automatic cutover |

---

## اصلاح مستقل رضایت پیامکی — COMPLETED

```text
Issue #92 / PR #93
Final head 5d0568568706d514a1c11da362248e68868b7a33
Merge 2f78d8b6087df9999ebf953ddbc6bce9e0789379
CI 30842741569
765 Specialist + 54 Accounting
```

بخش پروندهٔ بیمار اکنون:

- هدف «تنظیم دریافت پیامک» را توضیح می‌دهد؛
- پیام‌های مراقبتی و پیام‌های عمومی/تبلیغاتی را مستقل معرفی می‌کند؛
- مثال، پیامد و action صریح دارد؛
- وضعیت را با «دریافت می‌کند / دریافت نمی‌کند» نشان می‌دهد؛
- کدهای فنی را در جزئیات جمع‌شونده قرار می‌دهد.

پیش‌فرض رضایت، تاریخچهٔ append-only، stale guard، permission و سیاست ارسال تغییر نکردند.

---

## FOUX-V1

Canonical plan:

```text
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md
Version 1.5.1
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
Governance merge f6fb9f87c7fe302c6e18d7f5909aed4128a7f5ca
CI 30828272752
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

### FO-4 — TECHNICALLY VALIDATED / OWNER UX PENDING

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
- exact idempotent replay؛
- stale-form و permission fail closed؛
- release، assign/reassign و تغییر صف؛
- terminal action rejection پیش از role check؛
- صف مسئول و مسئول واقعی در لیست و جزئیات؛
- role filter براساس صف مؤثر؛
- ownership overlay به‌صورت batch و بدون N+1؛
- حفظ ownership پس از Projection rebuild؛
- POSTهای FO-4 با flag خاموش = 404؛
- Source Truth بدون تغییر.

---

## قدم مجاز فعلی

```text
Issue #94 — FO-4 Local Owner UX Acceptance
```

اجرای برنامه:

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

---

## Exit Gate برای FO-5

```text
PR #95 merged                          = PASS
CI 30844075841 green                   = PASS
atomic/stale/permission/terminal gates = PASS
ownership rebuild preservation         = PASS
Source Truth unchanged                 = PASS
FO4_UX_ACCEPTED=true                   = PENDING
critical_ux_defects=0                  = PENDING
separate governance authorization      = PENDING
```

تا آن زمان Structured Contact، Retry/Escalation، SMS automation، Appointment reaction، Outbox/Dead-letter، Evidence Assist و FO-5+ مسدودند.

---

## Freeze فعلی

```text
FOUX FO-4 local UX review       = ALLOWED
FOUX focused FO-4 defect fix    = ALLOWED IF DEFECT FOUND
FOUX FO-5 and later             = BLOCKED
New clinical rules              = PAUSED
Hypoglycemia Shadow expansion   = PAUSED
Write to clinic_new.db          = FORBIDDEN
```

---

## تصمیم فعلی

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 = VALIDATED WITH OWNER ACCEPTANCE
FO-4 = TECHNICALLY VALIDATED / LOCAL UX ACCEPTANCE PENDING
FO-5 AND LATER = BLOCKED
```
