# وضعیت حاکم پروژه — Clinic Management

> **Source of Truth مدیریتی مخزن.** پیش از هر توسعه، وضعیت واقعی GitHub، این فایل و `PROJECT_STATE.json` باید خوانده شوند. حافظهٔ گفتگو یا branch قدیمی به‌تنهایی معتبر نیست.

- آخرین ممیزی: `2026-08-03 02:14 +03:30`
- شاخهٔ مرجع محصول: `main`
- head مرجع پیش از این تغییر حاکمیتی: `901dbfdf9c358ecc09d2a60a0680f6a4a8370d17`
- وضعیت کلی: `PRODUCT_OPERATIONAL / PRE_PRODUCTION_TEST_DATA / CLINICAL_CONTENT_NOT_APPROVED / GOVERNANCE_RECONCILIATION_REQUIRED`

---

## 1. تعریف پروژه

Monorepo شامل جریان‌های مستقل زیر است:

1. `webapp/` — حسابداری Flask + SQLite، پورت 8080؛
2. `specialist_clinic/` — مدیریت بیماری مزمن، Worklist، SMS، نوبت، پرونده و Clinical Engine v2، پورت 8090؛
3. Clinical Engine v2 — زیرساخت deterministic، audit، review، activation seal و rollback؛
4. Clinical Rule Research — پژوهش شواهد برای Rule Library؛
5. Hypoglycemia Shadow — آزمایش داخلی غیرتجویزی؛
6. Follow-up Orchestration & UX v1 — Episode، Projection، Routing و اتوماسیون عملیاتی؛
7. Release Engineering؛
8. Halqe Migration.

این جریان‌ها اختیار یکدیگر را ندارند.

---

## 2. طبقه‌بندی دادهٔ محیط فعلی

مالک محصول در تاریخ `2026-08-03` اعلام کرده است که دیتابیس فعلی Specialist Clinic فقط دادهٔ تستی دارد:

```text
specialist.db data class = TEST_ONLY / SYNTHETIC_OR_RESETTABLE
real patient PHI         = NOT EXPECTED
reset/reseed             = ALLOWED
```

پیامدها:

- دادهٔ فعلی می‌تواند برای migration rehearsal، backfill و تست deterministic استفاده شود؛
- شمارش یک دیتابیس محلی resettable معیار business/production نیست؛
- KPI واقعی فقط در Pilot ثبت می‌شود؛
- پیش از ورود اولین دادهٔ واقعی بیمار، production-readiness، privacy، backup/restore و baseline دوباره اجباری است؛
- این طبقه‌بندی نباید وارد منطق runtime یا باعث کاهش guardrail شود.

---

## 3. ماتریس جریان‌ها

| جریان | مرجع | وضعیت | اختیار | ممنوعیت |
|---|---|---|---|---|
| محصول عملیاتی | `main` | `ACTIVE_PRODUCT_PRE_PRODUCTION` | رفتار واقعی برنامه | تغییر بالینی بدون گیت |
| Follow-up Orchestration & UX v1 | سند canonical / Issueهای FOUX | `FO_0_VALIDATED / FO_1_AUTHORIZED` | Episode/Link/Event در FO-1 | UI، Projection، routing و automation پیش از gate |
| Clinical Engine v2 | کد و تست main | `INFRASTRUCTURE_IMPLEMENTED / ACTIVATION_GATED` | runtime و audit | activation بدون approval |
| Rule package فعلی | `2026.1-draft.3` | `LEGACY_DRAFT_QUARANTINED` | provenance و تست فنی | clinical use |
| پژوهش ADA | PR #60 | `FROZEN_V0_9_4 / EVIDENCE_AUTHORITY_DRAFT` | evidence آینده | runtime authority |
| Hypoglycemia Shadow | PR #62–#67 | `PAUSED_FOR_RECONCILIATION` | data-quality experiment | Rule/Task/Alert/medication expansion |
| Shadow disposition | branch مربوط | `PAUSED_DO_NOT_MERGE` | ندارد | توسعه و merge |
| Release A15 | PR #59 | `STALE_DIVERGED_DRAFT` | requirement reference | merge مستقیم |
| Halqe Migration | PRهای قدیمی | `SEPARATE_STRATEGIC_STREAM` | design/rehearsal | cutover خودکار |

---

## 4. وضعیت Follow-up Orchestration & UX v1

### 4.1 مرجع‌ها

```text
Plan:
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md

Baseline:
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_BASELINE.md

FO-0 Issue: #71
FO-0 PR:    #72
FO-0 merge: 901dbfdf9c358ecc09d2a60a0680f6a4a8370d17
```

### 4.2 FO-0

```text
Repository/UI baseline      = RECORDED
Owner test-only attestation = RECORDED
Synthetic aggregate test    = PASS
Feature flags               = 10/10 OFF
Runtime consumer            = NONE
FOUX schema                 = NONE
Specialist CI               = 731 PASS
Accounting CI               = 54 PASS
Status                      = VALIDATED
```

Snapshot عددی production برای FO-0 لازم نیست، چون محیط فعلی test-only و resettable است. baseline واقعی قبل از Pilot/ورود دادهٔ واقعی دوباره ثبت می‌شود.

### 4.3 قدم مجاز فعلی

```text
FO-1 — Episode Identity & Append-only Links
```

دامنهٔ مجاز FO-1:

- schema additive/idempotent فقط برای Episode، Link و Event؛
- identity builder deterministic/versioned؛
- source linker و orphan reason؛
- dry-run/backfill روی دادهٔ تستی؛
- rebuild/audit؛
- flag default OFF؛
- بدون تغییر UI، SMS، Scheduler behavior، routing یا Clinical logic.

FO-2 و بالاتر تا Exit Gate FO-1 مسدودند.

---

## 5. Feature Flagهای FOUX-V1

همه فعلاً OFF:

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

در FO-1 فقط `FOLLOWUP_EPISODES_ENABLED` ممکن است توسط زیرساخت Episode مصرف شود، اما default آن باید OFF بماند و هیچ رفتار UI یا automation را فعال نکند.

---

## 6. وضعیت محصول Specialist Clinic

قابلیت‌های موجود:

- patient link و پروندهٔ طولی؛
- دارو، آلرژی، آزمایش و vital؛
- Appointment و Doctor Queue؛
- Encounter documentation امضاشده؛
- Plan Commitment و Worklist؛
- Contact event append-only؛
- SMS consent، approval، campaign، delivery و attribution؛
- financial bridge read-only؛
- Scheduler با lease/fencing/idempotency؛
- Clinical Engine v2 suggestion-only.

Specialist Clinic فقط `clinic_new.db` را read-only می‌خواند. هر Write به دیتابیس حسابداری ممنوع است.

---

## 7. Clinical Engine v2 و Ruleها

```text
Engine infrastructure       = IMPLEMENTED
Clinical content approval   = NOT COMPLETED
Visible clinical activation = BLOCKED
```

بستهٔ `2026.1-draft.3` شامل شش Rule quarantined است:

```text
T2-REDFLAG-BP
T2-SAFE-MET-STOP
T2-SAFE-MET-REVIEW
T2-MON-A1C-DUE
T2-MON-EGFR-DUE
T2-MON-UACR-DUE
```

هر Rule باید بعداً `REVALIDATE / REPLACE / RETIRE` شود. تست فنی معادل clinical approval نیست.

---

## 8. پژوهش ADA

PR #60 فقط Evidence Authority آینده است:

```text
Rule Candidate = 0
Accepted Rule  = 0
Licensing      = HOLD
Activation     = BLOCKED
```

پژوهش جدید فقط در صورت decision-changing retrieval مجاز است.

---

## 9. Hypoglycemia Shadow

وضعیت:

```text
EXPERIMENTAL_INTERNAL_SHADOW
PAUSED_FOR_RECONCILIATION
```

ممنوع:

- disposition expansion؛
- Task/SLA/Alert؛
- medication logic؛
- معرفی به‌عنوان Rule معتبر؛
- rollout بالینی.

تصمیم آینده: `KEEP_AS_DATA_QUALITY_WORKFLOW / REWORK / REVERT`.

---

## 10. Release Engineering و Halqe

A15 باید از main فعلی بازسازی شود و Windows build، self-test و backup/restore rehearsal داشته باشد. PR #59 مستقیم merge نمی‌شود.

Halqe یک جریان استراتژیک جداست. Flask/SQLite فعلی تا تصمیم رسمی cutover، Product Authority باقی می‌ماند.

---

## 11. قوانین Scope و اعتماد

پیش از هر tranche:

1. جریان متعلق مشخص شود؛
2. خروجی اجرایی/تصمیمی روشن باشد؛
3. scope متناسب با ریسک باشد؛
4. feature flag و rollback مشخص باشد؛
5. focused و full test تعریف شود؛
6. Project State و سند canonical پس از merge به‌روزرسانی شوند.

قواعد ثابت:

- Shadow بدون approval به Rule تبدیل نمی‌شود؛
- Rule Draft وارد rollout نمی‌شود؛
- یک failure فقط capability وابسته را block می‌کند؛
- source truth بالینی append-only باقی می‌ماند؛
- FO-1 هیچ تصمیم، پیام، routing یا completion خودکاری ایجاد نمی‌کند؛
- feature branch نیمه‌کاره مسیر پروژه را تعیین نمی‌کند.

---

## 12. ترتیب ادامه

### جریان عملیاتی FOUX

```text
FO-1 Episode/Link/Event
→ FO-2 Projection Shadow
→ FO-3 Read-only Worklist
→ FO-4 Ownership/Routing/SLA
→ FO-5 Structured Contact
→ FO-6 Governed SMS
→ FO-7 Cross-channel/Outbox
→ FO-8 Evidence Assist
→ FO-9 Automation Health
→ FO-10 Pilot/Cutover
```

### جریان کلان پروژه

```text
R0 Governance Reconciliation
R1 Release Baseline
R2 Bounded Clinical Content
```

این جریان‌ها می‌توانند با scope مستقل جلو بروند، اما نباید قراردادهای یکدیگر را دور بزنند.

---

## 13. تصمیم فعلی

```text
FOUX FO-0                     = VALIDATED
FOUX FO-1                     = ALLOWED_WITHIN_CANONICAL_SCOPE
FOUX FO-2+                    = BLOCKED_PENDING_FO_1_EXIT
New clinical rules           = PAUSED
Hypoglycemia Shadow expansion= PAUSED
Disposition branch           = DO_NOT_MERGE
Focused bug/security fixes   = ALLOWED
Release cleanup              = ALLOWED on fresh main branch
```
