# وضعیت حاکم پروژه — Clinic Management

> **Source of Truth مدیریتی مخزن.** پیش از هر توسعه، وضعیت واقعی GitHub، این فایل و `PROJECT_STATE.json` باید خوانده شوند. حافظهٔ گفتگو یا branch قدیمی به‌تنهایی معتبر نیست.

- آخرین ممیزی: `2026-08-03 02:51 +03:30`
- شاخهٔ مرجع محصول: `main`
- head مرجع پیش از این attestation: `15ef1585c069a74c26fbc0ce859e03906e5f475a`
- وضعیت کلی: `PRODUCT_OPERATIONAL / PRE_PRODUCTION_TEST_DATA / CLINICAL_CONTENT_NOT_APPROVED / GOVERNANCE_RECONCILIATION_REQUIRED`

---

## 1. تعریف پروژه

Monorepo شامل جریان‌های مستقل زیر است:

1. `webapp/` — حسابداری Flask + SQLite؛
2. `specialist_clinic/` — مدیریت بیماری مزمن، Worklist، SMS، نوبت، پرونده و Clinical Engine v2؛
3. Clinical Engine v2؛
4. Clinical Rule Research؛
5. Hypoglycemia Shadow؛
6. Follow-up Orchestration & UX v1؛
7. Release Engineering؛
8. Halqe Migration.

این جریان‌ها اختیار یکدیگر را ندارند.

---

## 2. طبقه‌بندی دادهٔ محیط فعلی

طبق attestation مالک در `2026-08-03`:

```text
specialist.db data class = TEST_ONLY / SYNTHETIC_OR_RESETTABLE
real patient PHI         = NOT EXPECTED
reset/reseed             = ALLOWED
```

این وضعیت فقط برای محیط فعلی است. پیش از ورود دادهٔ واقعی بیمار، production-readiness، privacy، backup/restore، role/consent review و baseline بدون PHI الزامی است. هیچ shortcut مبتنی بر `TEST_ONLY` نباید وارد runtime شود.

---

## 3. ماتریس جریان‌ها

| جریان | مرجع | وضعیت | اختیار | ممنوعیت |
|---|---|---|---|---|
| محصول عملیاتی | `main` | `ACTIVE_PRODUCT_PRE_PRODUCTION` | رفتار واقعی برنامه | تغییر بالینی بدون گیت |
| FOUX-V1 | plan canonical / Project State | `FO_0_VALIDATED / FO_1_VALIDATED / FO_2_AUTHORIZED` | shadow projection در FO-2 | UI/mutation/routing/automation |
| Clinical Engine v2 | code/tests main | `INFRASTRUCTURE_IMPLEMENTED / ACTIVATION_GATED` | runtime/audit | activation بدون approval |
| Rule package | `2026.1-draft.3` | `LEGACY_DRAFT_QUARANTINED` | provenance/test | clinical use |
| پژوهش ADA | PR #60 | `FROZEN_V0_9_4` | evidence draft | runtime authority |
| Hypoglycemia Shadow | PR #62–#67 | `PAUSED_FOR_RECONCILIATION` | experiment | expansion/Rule/Task/Alert |
| Shadow disposition | branch مربوط | `PAUSED_DO_NOT_MERGE` | ندارد | merge/development |
| Release A15 | PR #59 | `STALE_DIVERGED_DRAFT` | requirements | direct merge |
| Halqe | PRهای قدیمی | `SEPARATE_STRATEGIC_STREAM` | design/rehearsal | automatic cutover |

---

## 4. Follow-up Orchestration & UX v1

### 4.1 مرجع‌ها

```text
Plan:
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md

Baseline:
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_BASELINE.md
```

### 4.2 FO-0 — VALIDATED

```text
Issue           = #71
Implementation  = PR #72
Attestation     = PR #73
Merge           = 901dbfdf9c358ecc09d2a60a0680f6a4a8370d17
Specialist CI   = 731 passed
Accounting CI   = 54 passed
Flags           = 10/10 OFF
```

### 4.3 FO-1 — VALIDATED

```text
Issue           = #74
Implementation  = PR #75
Merge           = 15ef1585c069a74c26fbc0ce859e03906e5f475a
Specialist CI   = 736 passed
Accounting CI   = 54 passed
Synthetic run   = 4 Episodes / 12 Links
Second apply    = 0 new Episodes / 0 new Links
Source digest   = unchanged
```

FO-1 قابلیت‌های زیر را اضافه کرد:

- `followup_episodes` با identity immutable و versioned؛
- `followup_episode_links` با patient-scope و source revision؛
- `followup_episode_events` append-only و linear؛
- explicit orphan reason به‌جای حدس؛
- dry-run/apply backfill CLI؛
- schema additive/idempotent؛
- بدون automatic startup backfill؛
- بدون تغییر Worklist، Scheduler، SMS، Appointment، Rule یا source truth.

### 4.4 قدم مجاز فعلی

```text
FO-2 — Projection, Next Action & Shadow Parity
```

دامنهٔ مجاز FO-2:

- `followup_work_item_projection` به‌عنوان cache/read model؛
- source-state adapterهای read-only؛
- state class: `ACTION_REQUIRED / WAITING / BLOCKED / TERMINAL`؛
- next action، waiting reason و blocked reason؛
- جداسازی `action_due_at` و `target_at`؛
- owner role proposal فقط به‌صورت پیشنهاد؛
- deterministic projection hash/rebuild؛
- parity report با Worklist فعلی؛
- lag/performance metrics؛
- explicit CLI/test execution؛
- flag `FOLLOWUP_PROJECTION_SHADOW` default OFF.

ممنوع در FO-2:

- UI جدید؛
- claim/assignment؛
- routing mutation یا SLA escalation؛
- SMS auto-send؛
- appointment reaction؛
- outbox؛
- automatic closure؛
- Evidence Assist؛
- clinical decision؛
- Rule/Shadow change.

FO-3 و بالاتر تا Exit Gate FO-2 مسدودند.

---

## 5. Feature Flagهای FOUX-V1

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

Episode schema و CLI روی main وجود دارند، ولی backfill و projection فقط با اجرای صریح انجام می‌شوند. هیچ request/Scheduler/UI behavior به‌طور پیش‌فرض تغییر نکرده است.

---

## 6. Specialist Clinic Product State

قابلیت‌های موجود:

- patient link و پروندهٔ طولی؛
- medication/allergy/lab/vital؛
- Appointment و Doctor Queue؛
- Encounter documentation append-only؛
- Plan Commitment و Worklist؛
- Contact events append-only؛
- SMS consent/approval/campaign/delivery/attribution؛
- financial bridge read-only؛
- Scheduler با lease/fencing/idempotency؛
- Clinical Engine v2 suggestion-only؛
- FOUX Episode lineage.

Specialist Clinic فقط `clinic_new.db` را read-only می‌خواند. هر Write به دیتابیس حسابداری ممنوع است.

---

## 7. Clinical Engine و Rule Content

```text
Engine infrastructure       = IMPLEMENTED
Clinical content approval   = NOT COMPLETED
Visible clinical activation = BLOCKED
```

Ruleهای `2026.1-draft.3` quarantined هستند و باید بعداً `REVALIDATE / REPLACE / RETIRE` شوند. تست فنی معادل clinical approval نیست.

---

## 8. پژوهش ADA و Hypoglycemia Shadow

PR #60 فقط Evidence Authority draft است:

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

افزودن Task/SLA/Alert/medication logic یا معرفی آن به‌عنوان Rule معتبر ممنوع است.

---

## 9. Release Engineering و Halqe

A15 باید از main فعلی بازسازی شود و Windows build، self-test و backup/restore rehearsal داشته باشد. PR #59 مستقیم merge نمی‌شود.

Halqe جریان استراتژیک جداست. Flask/SQLite فعلی تا تصمیم رسمی cutover، Product Authority باقی می‌ماند.

---

## 10. قوانین Scope و توسعه

پیش از هر tranche:

1. جریان و خروجی مشخص شود؛
2. Scope متناسب با ریسک باشد؛
3. feature flag و rollback تعریف شود؛
4. focused/full tests تعریف شود؛
5. source truth و clinical safety ثابت بماند؛
6. بعد از merge، Project State و plan به‌روزرسانی شوند.

قواعد ثابت:

- relation مبهم → orphan reason؛
- projection حقیقت بالینی نیست؛
- FO-2 فقط shadow/read-only است؛
- owner role در FO-2 فقط proposal است؛
- هیچ تاریخ یا next action ساختگی بدون policy/version تولید نمی‌شود؛
- هر nonterminal projection باید action/wait/block روشن داشته باشد؛
- same source snapshot باید same projection hash بدهد؛
- feature branch نیمه‌کاره مسیر پروژه را تعیین نمی‌کند.

---

## 11. ترتیب ادامهٔ FOUX

```text
FO-0 Governance                 VALIDATED
FO-1 Episode/Link/Event         VALIDATED
FO-2 Projection Shadow          AUTHORIZED
FO-3 Read-only Worklist         BLOCKED
FO-4 Ownership/Routing/SLA      NOT_STARTED
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
FOUX FO-2                     = ALLOWED_WITHIN_CANONICAL_SHADOW_SCOPE
FOUX FO-3+                    = BLOCKED_PENDING_FO_2_EXIT
New clinical rules           = PAUSED
Hypoglycemia Shadow expansion= PAUSED
Disposition branch           = DO_NOT_MERGE
Focused bug/security fixes   = ALLOWED
Release cleanup              = ALLOWED on fresh main branch
```
