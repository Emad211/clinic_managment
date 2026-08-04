# Follow-up Orchestration & UX v1 — Complete Roadmap

> **Program:** `FOUX-V1`
>
> **Roadmap version:** `1.3.0`
>
> **Canonical plan:** `specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md`
>
> **Last audited:** `2026-08-04`
>
> **Environment:** `TEST_ONLY / SYNTHETIC_OR_RESETTABLE`
>
> **Current gate:** `FO-6 Governed SMS Automation implementation — Issue #109`

---

## 1. Governance contract

این سند ترتیب کامل FO-0 تا FO-10، وابستگی‌ها، محدوده و Exit Gate هر مرحله را نگه می‌دارد. حضور یک مرحله در رودمپ به‌معنی مجوز اجرا نیست. هر مرحله نیازمند عبور از گیت قبلی، Issue حاکم، PR مستقل، Feature Flag خاموش، CI کامل و به‌روزرسانی Project State است.

اصول غیرقابل‌مذاکره:

- Source Truthهای موجود authoritative می‌مانند؛
- Episode حقیقت بالینی نیست و Projection فقط cache است؛
- mutationهای orchestration append-only و idempotent هستند؛
- Clinical Task بدون Evidence و transition معتبر کامل نمی‌شود؛
- Appointment به‌تنهایی Clinical Task را کامل نمی‌کند؛
- هیچ Write به `clinic_new.db` انجام نمی‌شود؛
- SMS، Appointment، Evidence Assist و تصمیم بالینی فقط در tranche مجاز خود تغییر می‌کنند؛
- تمام Feature Flagها به‌صورت پیش‌فرض OFF هستند.

---

## 2. Progress model

```text
VALIDATED_WITH_REQUIRED_ACCEPTANCE       = 1.0
TECHNICALLY_VALIDATED_ACCEPTANCE_PENDING = 0.8
AUTHORIZED_NOT_STARTED                   = 0.0
BLOCKED_NOT_STARTED                      = 0.0
```

وضعیت فعلی:

```text
FO-0 = 1.0
FO-1 = 1.0
FO-2 = 1.0
FO-3 = 1.0
FO-4 = 1.0
FO-5 = 1.0
FO-6..FO-10 = 0.0
--------------------------------
Total = 6.0 / 11 = 54.5%
Technical implementation = 6 / 11 = 54.5%
Remaining = 45.5%
```

این درصد فقط برنامهٔ FOUX-V1 را می‌سنجد و معیار آمادگی Production کل مطب نیست.

---

## 3. Master sequence

| Tranche | عنوان | وضعیت | Feature Flag | Dependency |
|---|---|---|---|---|
| FO-0 | Governance, Baseline & Registration | `VALIDATED` | همه OFF | — |
| FO-1 | Episode Identity & Append-only Links | `VALIDATED` | `FOLLOWUP_EPISODES_ENABLED` | FO-0 |
| FO-2 | Projection, Next Action & Shadow Parity | `VALIDATED` | `FOLLOWUP_PROJECTION_SHADOW` | FO-1 |
| FO-3 | Read-only Unified Worklist & Timeline | `VALIDATED_WITH_OWNER_ACCEPTANCE` | `FOLLOWUP_UNIFIED_WORKLIST_READONLY` | FO-2 |
| FO-4 | Claim, Assignment, Routing & Effective SLA | `VALIDATED_WITH_OWNER_ACCEPTANCE` | `FOLLOWUP_AUTO_ROUTING` | FO-3 |
| FO-5 | Structured Contact, Retry & Escalation | `VALIDATED_WITH_OWNER_ACCEPTANCE` | `FOLLOWUP_STRUCTURED_CONTACT` | FO-4 + PR #104/#106/#108 |
| FO-6 | Governed SMS Automation & Freshness | `AUTHORIZED_NOT_STARTED` | `FOLLOWUP_SMS_AUTO_GUARDED` | FO-5 acceptance + Issue #109/PR #110 |
| FO-7 | Cross-channel Transitions & Operational Outbox | `BLOCKED_NOT_STARTED` | `FOLLOWUP_APPOINTMENT_SYNC` | FO-5/FO-6 |
| FO-8 | Clinical Evidence Assist | `BLOCKED_NOT_STARTED` | `FOLLOWUP_EVIDENCE_ASSIST` | FO-7 + clinical safety review |
| FO-9 | Automation Health & Operational Control | `BLOCKED_NOT_STARTED` | `FOLLOWUP_AUTOMATION_HEALTH` | FO-7 contracts |
| FO-10 | Controlled Pilot, KPI Proof, Cutover & Legacy Retirement | `BLOCKED_NOT_STARTED` | controlled rollout | FO-0..FO-9 |

---

## 4. Completed foundation

### FO-0 — Governance, Baseline & Registration

ثبت برنامه، نقشهٔ Source Truth، طبقه‌بندی TEST_ONLY، Feature Flagهای OFF و baseline خواندنی بدون PHI.

**Evidence:** Issue #71، PR #72/#73، merge `901dbfdf9c358ecc09d2a60a0680f6a4a8370d17`، `731 Specialist + 54 Accounting`.

### FO-1 — Episode Identity & Append-only Links

Episode identity پایدار، Link و Event append-only، backfill deterministic و idempotent، بدون تغییر Source Truth.

**Evidence:** Issue #74، PR #75، merge `15ef1585c069a74c26fbc0ce859e03906e5f475a`، `736 + 54`.

### FO-2 — Projection, Next Action & Shadow Parity

Projection قابل‌بازسازی، policy مرکزی Next Action، جداسازی action due/target و parity کامل fixture معتبر.

**Evidence:** Issue #77، PR #78، merge `6c6e33203376a32165418e0d3c6f2a4a48253e7b`، CI `30773195914`، `747 + 54`.

### FO-3 — Read-only Unified Worklist & Timeline

Unified list/detail/timeline خواندنی، deep-linkها، controlled unavailable state، masked identity و پذیرش مالک با صفر defect بحرانی.

**Evidence:** Issue #83، PR #81/#85/#88، runtime `020803868e1c2755f7669d52da92cb8050a46018`، `762 + 54`.

### FO-4 — Claim, Assignment, Routing & Effective SLA

- append-only `ROUTED / CLAIMED / ASSIGNED`؛
- atomic one-winner claim؛
- stale/permission/terminal fail-closed؛
- release، assign/reassign و routing؛
- صف مؤثر و مسئول واقعی؛
- seed → Episode/Link → Projection preparation؛
- حفظ پیگیری دستی TEST و جلوگیری از duplicate history؛
- SLAهای canonical و محاسبهٔ effective overdue در زمان مشاهده؛
- پذیرش مالک با صفر defect بحرانی.

**Evidence:** Issue #94، PR #95/#98/#100، runtime `cd243424ecbae98892e0dfde1780bb846554942f`.

```text
FO4_UX_ACCEPTED = true
reviewer = Emad211
reviewed_commit = cd243424ecbae98892e0dfde1780bb846554942f
reviewed_on_test_data = true
critical_ux_defects = 0
notes = بررسی شد و مشکل بحرانی مشاهده نشد
```

---

## 5. FO-5 — Structured Contact, Retry & Escalation

```text
Technical validation = PASS
Owner UX acceptance = PASS
Acceptance Issue = #107 completed
Reviewed runtime = 94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852
critical_ux_defects = 0
```

**State:** `VALIDATED_WITH_OWNER_ACCEPTANCE`.

---

## 6. FO-6 — Governed SMS Automation & Freshness

### Authorization evidence

```text
Issue #109
Governance PR #110
Feature Flag FOLLOWUP_SMS_AUTO_GUARDED
Default OFF
```

### Authorized outcome

فقط `appointment_reminder` و `refill_due` با purpose=`CARE` می‌توانند پس از policy/template/candidate snapshot immutable و pre-send revalidation کامل به مسیر `AUTO_GUARDED` برسند.

### Policy levels

```text
CLINICIAN_ONLY  → never automatic
MANUAL_APPROVAL → current manual queue, fresh approval only
AUTO_GUARDED    → exact administrative CARE allowlist only
```

### Freshness gate

Consent head، phone، source period، policy، template hash، body hash، expiry، quiet hours، daily cap، cooldown، idempotency و provider باید همگی PASS باشند. هر failure/unknown، send را متوقف و decision audit ثبت می‌کند.

### Execution boundary

ارسال از GET/startup، scheduler پنهان، campaign/MARKETING/free-text، clinical content، Appointment mutation و Outbox/Dead-letter ممنوع است.

### Exit

- stale/duplicate auto-send = صفر؛
- `CLINICIAN_ONLY` automatic = صفر؛
- full CI؛
- local owner UX acceptance؛
- governance مستقل برای FO-7.

**State:** `AUTHORIZED_NOT_STARTED`.

---

## 7. FO-7 — Cross-channel Transitions & Operational Outbox

Operational Outbox، SMS delivered/failed transition، Appointment booked/cancelled/no-show، retry/dead-letter و administrative goal completion؛ بدون تکمیل خودکار Clinical Task.

**State:** `BLOCKED_NOT_STARTED`.

---

## 8. FO-8 — Clinical Evidence Assist

Required-evidence reader، candidate matcher، provenance/confidence UI و accept/reject handoff؛ بدون auto-completion یا Fact mutation.

**State:** `BLOCKED_NOT_STARTED`.

---

## 9. FO-9 — Automation Health & Operational Control

Scheduler heartbeat، job history، outbox/dead-letter، projection lag، stale approval monitor، safe retry controls و runbook.

**State:** `BLOCKED_NOT_STARTED`.

---

## 10. FO-10 — Controlled Pilot, KPI Proof, Cutover & Legacy Retirement

Security/privacy، clinical safety، migration/rebuild، rollback rehearsal، user acceptance و لغو صریح TEST_ONLY پیش از PHI واقعی لازم است.

**State:** `BLOCKED_NOT_STARTED`.

---

## 11. Exact continuation point

```text
CURRENT = FO-6 Governed SMS Automation & Freshness implementation
ISSUE   = #109
BASE    = main after governance PR #110
THEN    = technical validation and local owner UX acceptance
FO-7+   = BLOCKED
```

کار مجاز:

- Issue و PR مستقل runtime؛
- additive append-only policy/template/candidate/decision storage؛
- allowlist دقیق `appointment_reminder/refill_due`؛
- CARE-only pre-send revalidation؛
- executor صریح و bounded؛
- Feature Flag OFF by default؛
- full CI و owner review.

کار غیرمجاز:

- campaign/MARKETING/free-text یا clinical auto-send؛
- Appointment mutation؛
- delivery transition به Episode؛
- Outbox/dead-letter/scheduler health؛
- FO-7 تا FO-10.
