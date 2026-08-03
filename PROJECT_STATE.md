# وضعیت حاکم پروژه — Clinic Management

> **Source of Truth مدیریتی مخزن.** پیش از هر توسعه، وضعیت واقعی GitHub، این فایل و `PROJECT_STATE.json` باید خوانده شوند. حافظهٔ گفتگو یا branch قدیمی به‌تنهایی معتبر نیست.

- آخرین ممیزی: `2026-08-03 04:30 +03:30`
- شاخهٔ مرجع: `main`
- head مرجع: `afed3545c0a90a1ed7ff7e0a892df89fffac00c2`
- وضعیت کلی: `PRODUCT_OPERATIONAL / PRE_PRODUCTION_TEST_DATA / CLINICAL_CONTENT_NOT_APPROVED / GOVERNANCE_RECONCILIATION_REQUIRED`

---

## 1. جریان‌های مستقل

1. `webapp/` — حسابداری Flask + SQLite؛
2. `specialist_clinic/` — محصول مدیریت بیماری مزمن؛
3. Clinical Engine v2؛
4. Clinical Rule Research؛
5. Hypoglycemia Shadow؛
6. Follow-up Orchestration & UX v1؛
7. Release Engineering؛
8. Halqe Migration.

هیچ جریان، اختیار ضمنی برای تغییر جریان دیگر ندارد.

---

## 2. طبقه‌بندی محیط

```text
specialist.db data class = TEST_ONLY / SYNTHETIC_OR_RESETTABLE
real patient PHI         = NOT EXPECTED
reset/reseed             = ALLOWED
```

این attestation فقط برای محیط فعلی است. پیش از ورود دادهٔ واقعی، production-readiness، privacy، backup/restore، consent/role review و baseline بدون PHI اجباری است. هیچ shortcut مبتنی بر `TEST_ONLY` وارد runtime نمی‌شود.

---

## 3. ماتریس جریان‌ها

| جریان | وضعیت | اختیار فعلی | ممنوعیت |
|---|---|---|---|
| محصول عملیاتی | `ACTIVE_PRODUCT_PRE_PRODUCTION` | رفتار واقعی main | تغییر بالینی بدون گیت |
| FOUX-V1 | `FO_0/1/2_VALIDATED / FO_3_TECHNICALLY_VALIDATED / UX_ACCEPTANCE_PENDING` | مرور لوکال UI خواندنی و patch محدود | FO-4، mutation، claim، SMS یا routing |
| Clinical Engine v2 | `INFRASTRUCTURE_IMPLEMENTED / ACTIVATION_GATED` | runtime/audit | activation بدون approval |
| Rule package | `LEGACY_DRAFT_QUARANTINED` | provenance/test | clinical use |
| ADA research | `FROZEN_V0_9_4` | evidence draft | runtime authority |
| Hypoglycemia Shadow | `PAUSED_FOR_RECONCILIATION` | experiment | expansion/Rule/Task/Alert |
| Shadow disposition | `PAUSED_DO_NOT_MERGE` | ندارد | merge/development |
| Release A15 | `STALE_DIVERGED_DRAFT` | requirement reference | direct merge |
| Halqe | `SEPARATE_STRATEGIC_STREAM` | design/rehearsal | automatic cutover |

---

## 4. FOUX-V1

### منابع حاکم

```text
Plan:
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md

Baseline:
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_BASELINE.md
```

Plan version: `1.4.0`

### FO-0 — VALIDATED

```text
Issue #71
PR #72 / #73
merge 901dbfdf9c358ecc09d2a60a0680f6a4a8370d17
731 Specialist + 54 Accounting
```

### FO-1 — VALIDATED

```text
Issue #74
PR #75
merge 15ef1585c069a74c26fbc0ce859e03906e5f475a
736 Specialist + 54 Accounting
4 Episodes / 12 Links / zero duplicates on second apply
source truth unchanged
```

زیرساخت:

```text
followup_episodes              immutable identity
followup_episode_links         immutable patient-safe links
followup_episode_events        append-only linear lineage
```

### FO-2 — VALIDATED

```text
Issue #77
PR #78
merge 6c6e33203376a32165418e0d3c6f2a4a48253e7b
Final CI run 30773195914
747 Specialist + 54 Accounting
100% legacy coverage
0 hidden legacy sources
100% explainable mismatch
rebuild deterministic
source truth unchanged
```

زیرساخت:

```text
followup_work_item_projection   rebuildable cache
source-state readers            read-only
FOUX-NEXT-ACTION-V1             fail-closed policy
state classes                   ACTION_REQUIRED / WAITING / BLOCKED / TERMINAL
role                            proposal only
CLI                             explicit shadow rebuild
```

### FO-3 — TECHNICALLY VALIDATED

```text
Issue #80
PR #81
final head 14e8bf56782ead4ccef46db05eb8c4b6b034d263
merge afed3545c0a90a1ed7ff7e0a892df89fffac00c2
Final CI run 30775348057
754 Specialist + 54 Accounting
```

قابلیت‌های merge‌شده:

```text
GET /followups/unified/
GET /followups/unified/<episode_id>
feature flag: FOLLOWUP_UNIFIED_WORKLIST_READONLY
```

مرزهای اثبات‌شده:

- list/detail فقط GET؛
- POST برابر 405؛
- flag OFF برابر 404 و navigation مخفی؛
- pagination/search/filter whitelist؛
- query count محدود و source-link batch؛
- Timeline deterministic و provenance-aware؛
- عدم نمایش message body، note آزاد، raw clinical value و payload JSON؛
- digest Source Truth و Projection بعد از GET بدون تغییر؛
- Worklist قدیمی authority اقدام باقی مانده است؛
- role فقط proposal است؛
- هیچ SMS، Appointment، Scheduler، Rule، Shadow یا Accounting behavior تغییر نکرد.

اولین CI پنج failure ناشی از fixture فشردهٔ FO-1 بدون ستون‌های هویت بیمار پیدا کرد. fixture به schema واقعی ارتقا یافت؛ query محصول تضعیف نشد. دور دوم کامل سبز شد.

### گام مجاز فعلی: FO-3 Local UX Acceptance

```text
FO-3 code/CI = VALIDATED
Rendered local UX = PENDING OWNER ACCEPTANCE
FO-4 = BLOCKED
```

کار مجاز:

- فعال‌سازی محلی روی دادهٔ تست؛
- مرور لیست، فیلترها، stale/overdue و Timeline؛
- بررسی RTL، keyboard، موبایل و deep-linkها؛
- ثبت attestation مالک؛
- patch محدود برای نقص FO-3.

ممنوع:

- claim/assignment؛
- routing mutation و SLA escalation؛
- SMS auto-send یا approval change؛
- appointment reaction؛
- outbox/retry/auto-close؛
- Evidence Assist؛
- Clinical decision؛
- Rule/Shadow change؛
- accounting write.

---

## 5. اجرای مرور لوکال FO-3

```powershell
cd specialist_clinic
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe seed_demo_data.py

$env:FOLLOWUP_PROJECTION_SHADOW = "1"
.\.venv\Scripts\python.exe scripts\rebuild_followup_projection.py `
  --database specialist.db `
  --as-of "2026-08-03 12:00:00" `
  --apply

$env:FOLLOWUP_UNIFIED_WORKLIST_READONLY = "1"
.\.venv\Scripts\python.exe start.py
```

آدرس: `http://127.0.0.1:8090`  
ورود توسعه: `admin / admin`

attestation لازم:

```text
FO3_UX_ACCEPTED = true|false
reviewer = Emad211
reviewed_commit = afed3545c0a90a1ed7ff7e0a892df89fffac00c2
reviewed_on_test_data = true
critical_ux_defects = 0
notes = ...
```

---

## 6. Feature Flagها

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

در وضعیت فعلی فقط `FOLLOWUP_UNIFIED_WORKLIST_READONLY` برای مرور لوکال ممکن است ON شود. `FOLLOWUP_UNIFIED_WORKLIST_ACTIONS` و تمام flags بعدی ممنوع‌اند.

---

## 7. وضعیت Specialist Clinic

قابلیت‌های موجود:

- patient link و پروندهٔ طولی؛
- دارو، آلرژی، آزمایش و vital؛
- Appointment و Doctor Queue؛
- Encounter documentation append-only؛
- Plan Commitment و Worklist؛
- Contact Event append-only؛
- SMS consent/approval/campaign/delivery؛
- financial bridge read-only؛
- Scheduler lease/fencing/idempotency؛
- Clinical Engine v2 suggestion-only؛
- FOUX Episode، Projection و Unified Read-only UI.

Specialist Clinic فقط `clinic_new.db` را read-only می‌خواند.

---

## 8. Clinical Engine و Ruleها

```text
Engine infrastructure       = IMPLEMENTED
Clinical content approval   = NOT COMPLETED
Visible clinical activation = BLOCKED
```

Ruleهای `2026.1-draft.3` quarantined هستند و باید `REVALIDATE / REPLACE / RETIRE` شوند. تست فنی معادل clinical approval نیست.

---

## 9. Freeze فعلی

```text
FOUX FO-3 local UX review          = ALLOWED
FOUX FO-3 focused fixes            = ALLOWED
FOUX FO-4 and later                = BLOCKED
New clinical rules                 = PAUSED
Hypoglycemia Shadow expansion      = PAUSED
Disposition branch                 = DO NOT MERGE
Focused bug/security fixes         = ALLOWED
```

---

## 10. قواعد ادامه

هر ایجنت باید:

1. وضعیت واقعی GitHub را بخواند؛
2. plan v1.4.0، JSON state و این فایل را تطبیق دهد؛
3. از branch تازهٔ main کار کند؛
4. فقط Local UX review یا patch محدود FO-3 انجام دهد؛
5. بدون attestation مالک وارد FO-4 نشود؛
6. قبل از merge کل CI را اجرا کند؛
7. هیچ ادعای push/merge/test بدون SHA و run ID مطرح نکند.

---

## 11. تصمیم فعلی

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 = TECHNICALLY_VALIDATED
FO-3 LOCAL UX ACCEPTANCE = PENDING
FO-4 AND LATER = BLOCKED
```
