# وضعیت حاکم پروژه — Clinic Management

> **Source of Truth مدیریتی مخزن.** پیش از هر توسعه، وضعیت واقعی GitHub، این فایل و `PROJECT_STATE.json` باید خوانده شوند. حافظهٔ گفتگو یا branch قدیمی به‌تنهایی معتبر نیست.

- آخرین ممیزی: `2026-08-03 03:32 +03:30`
- شاخهٔ مرجع: `main`
- head مرجع پیش از این attestation: `6c6e33203376a32165418e0d3c6f2a4a48253e7b`
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

این attestation فقط برای محیط فعلی است. قبل از دادهٔ واقعی، production-readiness، privacy، backup/restore، consent/role review و baseline بدون PHI اجباری است. هیچ shortcut مبتنی بر `TEST_ONLY` وارد runtime نمی‌شود.

---

## 3. ماتریس جریان‌ها

| جریان | وضعیت | اختیار فعلی | ممنوعیت |
|---|---|---|---|
| محصول عملیاتی | `ACTIVE_PRODUCT_PRE_PRODUCTION` | رفتار واقعی main | تغییر بالینی بدون گیت |
| FOUX-V1 | `FO_0/1/2_VALIDATED / FO_3_AUTHORIZED` | UI خواندنی FO-3 | هر mutation، claim، SMS یا routing |
| Clinical Engine v2 | `INFRASTRUCTURE_IMPLEMENTED / ACTIVATION_GATED` | runtime/audit | activation بدون approval |
| Rule package | `LEGACY_DRAFT_QUARANTINED` | provenance/test | clinical use |
| ADA research | `FROZEN_V0_9_4` | evidence draft | runtime authority |
| Hypoglycemia Shadow | `PAUSED_FOR_RECONCILIATION` | experiment | expansion/Rule/Task/Alert |
| Shadow disposition | `PAUSED_DO_NOT_MERGE` | ندارد | merge/development |
| Release A15 | `STALE_DIVERGED_DRAFT` | requirement reference | direct merge |
| Halqe | `SEPARATE_STRATEGIC_STREAM` | design/rehearsal | automatic cutover |

---

## 4. FOUX-V1

### منابع

```text
Plan:
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md

Baseline:
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_BASELINE.md
```

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

FO-1 روی main:

```text
followup_episodes              immutable identity
followup_episode_links         immutable patient-safe links
followup_episode_events        append-only linear lineage
```

Backfill explicit است و startup backfill خودکار ندارد.

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

FO-2 روی main:

```text
followup_work_item_projection   rebuildable cache
source-state readers            read-only
FOUX-NEXT-ACTION-V1             fail-closed policy
state classes                   ACTION_REQUIRED / WAITING / BLOCKED / TERMINAL
role                            proposal only
CLI                             explicit shadow rebuild
```

هیچ Worklist، Scheduler، SMS، Appointment یا Clinical behavior به Projection متصل نشده است.

### قدم مجاز فعلی: FO-3

```text
FO-3 — Read-only Unified Worklist & Timeline
```

دامنهٔ مجاز:

- route و template خواندنی و feature-flagged؛
- pagination، search و filter؛
- کارت با زبان عملیاتی؛
- action/wait/block copy؛
- role proposal؛
- projection age/stale state؛
- Timeline read-only؛
- permission-safe deep-links؛
- accessibility/RTL/Jalali؛
- no POST/mutation endpoint؛
- Worklist قدیمی همچنان operational authority.

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

FO-4 و بالاتر تا Exit Gate FO-3 مسدودند.

---

## 5. Feature Flagها

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

در FO-3 فقط `FOLLOWUP_UNIFIED_WORKLIST_READONLY` ممکن است مصرف شود. وقتی OFF است، route/navigation جدید نباید قابل مشاهده باشد و رفتار قدیمی دقیقاً حفظ شود.

---

## 6. وضعیت Specialist Clinic

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
- FOUX Episode lineage و Shadow Projection.

Specialist Clinic فقط `clinic_new.db` را read-only می‌خواند.

---

## 7. Clinical Engine و Ruleها

```text
Engine infrastructure       = IMPLEMENTED
Clinical content approval   = NOT COMPLETED
Visible clinical activation = BLOCKED
```

Ruleهای `2026.1-draft.3` quarantined هستند و باید `REVALIDATE / REPLACE / RETIRE` شوند. تست فنی معادل clinical approval نیست.

---

## 8. ADA Research و Hypoglycemia Shadow

PR #60:

```text
Rule Candidate = 0
Accepted Rule  = 0
Licensing      = HOLD
Activation     = BLOCKED
```

Hypoglycemia Shadow:

```text
EXPERIMENTAL_INTERNAL_SHADOW
PAUSED_FOR_RECONCILIATION
```

Task/SLA/Alert/medication expansion یا معرفی به‌عنوان Rule معتبر ممنوع است.

---

## 9. Release و Halqe

A15 باید از main فعلی بازسازی شود و Windows build، self-test و backup/restore rehearsal داشته باشد. PR #59 مستقیم merge نمی‌شود.

Halqe جریان مستقل است. Flask/SQLite فعلی تا cutover رسمی Product Authority است.

---

## 10. قوانین ثابت توسعه

- Source Truthها authoritative می‌مانند.
- Episode و Projection حقیقت بالینی نیستند.
- relation مبهم با reason code ثبت می‌شود.
- same snapshot + same as-of → same projection hash.
- FO-3 فقط read-only است.
- Worklist قدیمی در FO-3 حذف یا تغییر نمی‌کند.
- deep-link permission را دور نمی‌زند.
- no N+1 و pagination اجباری است.
- state فنی در copy اصلی نمایش داده نمی‌شود.
- Clinical completion بدون Evidence ممنوع است.
- branch نیمه‌کاره مسیر پروژه را تعیین نمی‌کند.

---

## 11. ترتیب FOUX

```text
FO-0 Governance                 VALIDATED
FO-1 Episode/Link/Event         VALIDATED
FO-2 Projection Shadow          VALIDATED
FO-3 Read-only Worklist         AUTHORIZED
FO-4 Ownership/Routing/SLA      BLOCKED
FO-5 Structured Contact         NOT_STARTED
FO-6 Governed SMS               NOT_STARTED
FO-7 Cross-channel/Outbox       NOT_STARTED
FO-8 Evidence Assist            NOT_STARTED
FO-9 Automation Health          NOT_STARTED
FO-10 Pilot/Cutover             NOT_STARTED
```

---

## 12. تصمیم فعلی

```text
FOUX FO-0                     = VALIDATED
FOUX FO-1                     = VALIDATED
FOUX FO-2                     = VALIDATED
FOUX FO-3                     = ALLOWED_READ_ONLY
FOUX FO-4+                    = BLOCKED_PENDING_FO_3_EXIT
New clinical rules           = PAUSED
Hypoglycemia Shadow expansion= PAUSED
Disposition branch           = DO_NOT_MERGE
Focused bug/security fixes   = ALLOWED
Release cleanup              = ALLOWED on fresh main branch
```
