# Follow-up Orchestration & UX v1 — Complete Roadmap

> **Program:** `FOUX-V1`
>
> **Roadmap version:** `1.0.0`
>
> **Canonical implementation plan:** `specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md`
>
> **Last audited:** `2026-08-04`
>
> **Current runtime authority:** `main@cd243424ecbae98892e0dfde1780bb846554942f`
>
> **Environment:** `TEST_ONLY / SYNTHETIC_OR_RESETTABLE`
>
> **Current gate:** `FO-4 Local Owner UX Acceptance — Issue #94`

---

## 1. Purpose

این سند نمای کامل و مرحله‌بندی‌شدهٔ برنامهٔ Follow-up Orchestration & UX v1 را از FO-0 تا FO-10 نگه می‌دارد. سند implementation plan وضعیت اثبات‌شده، invariantها و دستور اجرای tranche جاری را نگه می‌دارد؛ این سند دامنه، dependency، exit gate و ترتیب تمام trancheهای باقی‌مانده را مشخص می‌کند.

هیچ tranche صرفاً با حضور در این رودمپ مجاز نمی‌شود. شروع هر tranche نیازمند:

1. عبور از gate مرحلهٔ قبلی؛
2. Issue حاکم با scope صریح؛
3. PR مستقل؛
4. feature flag خاموش به‌صورت پیش‌فرض؛
5. Specialist و Accounting CI سبز؛
6. به‌روزرسانی Project State و اسناد حاکمیتی است.

---

## 2. Progress model

برای جلوگیری از درصدسازی مبهم، پیشرفت برنامه با tranche-equivalent محاسبه می‌شود:

```text
VALIDATED_WITH_REQUIRED_ACCEPTANCE = 1.0
TECHNICALLY_VALIDATED_ACCEPTANCE_PENDING = 0.8
AUTHORIZED_NOT_STARTED = 0.0
BLOCKED_NOT_STARTED = 0.0
```

FOUX-V1 یازده tranche دارد: `FO-0` تا `FO-10`.

وضعیت فعلی:

```text
FO-0 = 1.0
FO-1 = 1.0
FO-2 = 1.0
FO-3 = 1.0
FO-4 = 0.8
FO-5..FO-10 = 0.0
--------------------------------
Total = 4.8 / 11 = 43.6%
```

بنابراین:

- **پیشرفت رسمی roadmap gate:** `43.6%`، گرد شده `44%`؛
- **پیاده‌سازی فنی FO-0 تا FO-4:** `5 / 11 = 45.5%`؛
- **کار باقی‌مانده:** `6.2 tranche-equivalent = 56.4%`؛
- بعد از owner acceptance موفق FO-4، پیشرفت gate به `45.5%` می‌رسد؛ FO-5 همچنان فقط پس از governance مستقل مجاز می‌شود.

این درصد، KPI کسب‌وکار یا production-readiness کل سامانه نیست؛ فقط پیشرفت برنامهٔ FOUX-V1 است.

---

## 3. Master sequence

| Tranche | عنوان | وضعیت فعلی | Feature flag اصلی | Dependency |
|---|---|---|---|---|
| FO-0 | Governance, Baseline & Registration | `VALIDATED` | همه OFF | — |
| FO-1 | Episode Identity & Append-only Links | `VALIDATED` | `FOLLOWUP_EPISODES_ENABLED` | FO-0 |
| FO-2 | Projection, Next Action & Shadow Parity | `VALIDATED` | `FOLLOWUP_PROJECTION_SHADOW` | FO-1 |
| FO-3 | Read-only Unified Worklist & Timeline | `VALIDATED_WITH_OWNER_ACCEPTANCE` | `FOLLOWUP_UNIFIED_WORKLIST_READONLY` | FO-2 |
| FO-4 | Claim, Assignment, Routing & Effective SLA | `TECHNICALLY_VALIDATED / OWNER_UX_PENDING` | `FOLLOWUP_AUTO_ROUTING` | FO-3 |
| FO-5 | Structured Contact, Retry & Escalation | `BLOCKED_NOT_STARTED` | `FOLLOWUP_STRUCTURED_CONTACT` | FO-4 acceptance + authorization |
| FO-6 | Governed SMS Automation & Freshness | `BLOCKED_NOT_STARTED` | `FOLLOWUP_SMS_AUTO_GUARDED` | FO-5 + SMS policy approval |
| FO-7 | Cross-channel Transitions & Outbox | `BLOCKED_NOT_STARTED` | `FOLLOWUP_APPOINTMENT_SYNC` | FO-5/FO-6 |
| FO-8 | Clinical Evidence Assist | `BLOCKED_NOT_STARTED` | `FOLLOWUP_EVIDENCE_ASSIST` | FO-7 + clinical safety review |
| FO-9 | Automation Health & Operational Control | `BLOCKED_NOT_STARTED` | `FOLLOWUP_AUTOMATION_HEALTH` | FO-7 operational contracts |
| FO-10 | Pilot, KPI Proof, Cutover & Legacy Retirement | `BLOCKED_NOT_STARTED` | controlled rollout set | FO-0..FO-9 |

---

## 4. Completed foundation

### FO-0 — Governance, Baseline & Registration

**Result:** validated.

- program registered;
- TEST_ONLY classification recorded;
- source-of-truth map stored;
- all ten flags default OFF;
- baseline capture is read-only and PHI-free;
- no runtime/schema behavior introduced.

**Evidence:** Issue #71، PR #72/#73، merge `901dbfdf9c358ecc09d2a60a0680f6a4a8370d17`، `731 Specialist + 54 Accounting`.

### FO-1 — Episode Identity & Append-only Links

**Result:** validated.

- stable Episode identity;
- append-only Episode/Link/Event storage;
- deterministic and idempotent backfill;
- patient mismatch rejection;
- operational Source Truth unchanged.

**Evidence:** Issue #74، PR #75، merge `15ef1585c069a74c26fbc0ce859e03906e5f475a`، `736 + 54`.

### FO-2 — Projection, Next Action & Shadow Parity

**Result:** validated.

- rebuildable projection cache;
- canonical next-action policy;
- explicit action/wait/block state;
- action due and target separation;
- 100% legacy coverage in validated fixture;
- deterministic delete/rebuild equivalence.

**Evidence:** Issue #77، PR #78، merge `6c6e33203376a32165418e0d3c6f2a4a48253e7b`، CI `30773195914`، `747 + 54`.

### FO-3 — Read-only Unified Worklist & Timeline

**Result:** validated with owner acceptance.

- unified read-only list/detail/timeline;
- controlled unavailable states;
- deep links and masked identity;
- bounded reads without N+1;
- owner accepted the UX with zero critical defect.

**Evidence:** Issue #83، PR #81/#85/#88، runtime commit `020803868e1c2755f7669d52da92cb8050a46018`، `762 + 54`.

### FO-4 — Claim, Assignment, Routing & Effective SLA

**Result:** technically validated; local owner acceptance pending.

Implemented and validated:

- append-only `ROUTED / CLAIMED / ASSIGNED` events;
- atomic one-winner claim;
- exact replay idempotency;
- stale/permission/terminal fail-closed behavior;
- owner release and manager assign/reassign/routing;
- effective queue and current owner shown separately;
- ownership preserved across projection rebuild;
- explicit seed → Episode/Link → Projection preparation;
- stable fixture task IDs and preservation of manual TEST follow-ups;
- no duplicate Episode/Link/Event on repeated seed;
- controlled `PROJECTION_EMPTY_WITH_SOURCE_DATA` recovery state;
- canonical SLA vocabulary:
  `FUTURE / DUE_TODAY / OVERDUE / DUE_UNKNOWN / WAITING / BLOCKED / TERMINAL`;
- request-time effective overdue filtering without read-time mutation.

Runtime evidence:

```text
Ownership/routing: Issue #94 / PR #95 / CI 30844075841 / 773 + 54
Seed repair:       Issue #97 / PR #98 / CI 30851594179 / 781 + 54
SLA repair:        Issue #99 / PR #100 / CI 30852909213 / 784 + 54
Review commit:     cd243424ecbae98892e0dfde1780bb846554942f
```

Remaining FO-4 gate:

```text
FO4_UX_ACCEPTED=true
critical_ux_defects=0
reviewed_commit=cd243424ecbae98892e0dfde1780bb846554942f
```

---

## 5. Remaining delivery roadmap

## FO-5 — Structured Contact, Retry & Escalation

### Product outcome

تماس از note آزاد و هماهنگی دستی به یک جریان structured، audit‌شده و قابل ادامه تبدیل شود.

### Scope

- structured contact outcomes؛
- append-only contact attempt timeline؛
- callback scheduling؛
- attempt policy و threshold؛
- unreachable escalation؛
- invalid-phone workflow؛
- low-click call CTA/form؛
- optional free-text note فقط به‌عنوان مکمل.

Canonical outcomes حداقل شامل:

```text
NO_ANSWER
PHONE_INVALID
REACHED_APPOINTMENT_BOOKED
REACHED_CALLBACK_REQUESTED
ESCALATED_TO_DOCTOR
```

### Safety boundaries

- outcome متنی آزاد اتوماسیون مهم اجرا نمی‌کند؛
- escalation بالینی تصمیم درمانی تولید نمی‌کند؛
- Clinical Task بدون Evidence complete نمی‌شود؛
- callback، retry و escalation همگی idempotent و stale-protected هستند.

### Exit gate

- حداقل 90% تماس‌های pilot دارای structured outcome؛
- duplicate submit رویداد دوم نسازد؛
- callback گم‌شده صفر؛
- threshold و routing تست‌شده؛
- owner UX acceptance؛
- full CI green.

### Authorization state

`BLOCKED` تا FO-4 owner acceptance و governance مستقل.

---

## FO-6 — Governed SMS Automation & Freshness

### Product outcome

پیام‌های روتین allowlisted با guard کامل خودکار شوند و موارد حساس همچنان review/clinician-only بمانند.

### Scope

- policy level: `AUTO / AUTO_WITH_GUARDS / REQUIRES_REVIEW / CLINICIAN_ONLY`؛
- template versioning؛
- approval expiry؛
- source revision/content hash؛
- pre-send revalidation؛
- stale supersession؛
- guarded auto path؛
- limited manager configuration UI؛
- decision audit event.

### Mandatory guards

```text
consent
purpose
canonical phone
quiet hours
daily cap
cooldown
idempotency
source freshness
template version
provider readiness
```

### Exit gate

- stale SMS sent = 0؛
- duplicate SMS = 0؛
- clinician-only auto-send = 0؛
- routine allowlisted manual approvals حداقل 80% کاهش؛
- complete audit trail؛
- policy/consent review approved.

### Authorization state

`BLOCKED` تا FO-5 validation و SMS governance مستقل.

---

## FO-7 — Cross-channel Transitions & Operational Outbox

### Product outcome

SMS، Appointment و Work Item transition از دست نرود و replay امن باشد.

### Scope

- operational outbox؛
- delivered/failed SMS transitions؛
- permanent failure → call/fix-contact؛
- appointment booked/cancelled/no-show transitions؛
- wait-state lifecycle؛
- administrative goal completion؛
- retry and dead-letter.

### Safety boundaries

- booking یا SMS delivery، Clinical Task را خودکار complete نمی‌کند؛
- permanent و retryable failure جدا هستند؛
- transaction failure و replay duplicate-safe است؛
- outbox authority بالینی نیست.

### Exit gate

- lost cross-channel transition = 0 در validation suite؛
- replay safe؛
- dead-letter visible؛
- rollback rehearsal passed؛
- delivery/appointment state within defined SLA reflected.

### Authorization state

`BLOCKED` تا FO-5/FO-6 contracts validated.

---

## FO-8 — Clinical Evidence Assist

### Product outcome

ورود دوبارهٔ Evidence کاهش یابد، بدون تکمیل خودکار یا کاهش ایمنی.

### Scope

- required-evidence contract reader؛
- candidate matcher؛
- provenance/confidence UI؛
- accept/reject candidate؛
- governed completion handoff؛
- mismatch explanation.

### Safety boundaries

- wrong patient/task rejected؛
- missing provenance rejected؛
- stale evidence rejected؛
- no automatic clinical completion؛
- explicit authorized confirmation mandatory؛
- historical Fact mutation forbidden.

### Exit gate

- clinical completion without confirmation = 0؛
- measurable reduction in duplicate data entry؛
- clinical reviewer UX/audit approval؛
- full safety and permission tests green.

### Authorization state

`BLOCKED` تا cross-channel foundation و clinical safety governance.

---

## FO-9 — Automation Health & Operational Control

### Product outcome

failure مهم فقط در log پنهان نماند و اپراتور علت و اقدام بعدی را ببیند.

### Scope

- scheduler heartbeat؛
- job history projection؛
- outbox/dead-letter dashboard؛
- projection lag؛
- stale approval monitor؛
- safe retry controls؛
- admin alerts؛
- recovery runbook.

### Required visibility

```text
last heartbeat
last successful tick
job success/failure
lease owner and age
outbox backlog and oldest item
projection lag
stale approvals
SMS pending/unknown/failed
dead-letter items
unassigned overdue items
automation paused reasons
```

### Exit gate

- hidden critical automation failure = 0؛
- stale heartbeat detected؛
- retry permission/idempotency validated؛
- recovery rehearsal passed؛
- no guardrail bypass.

### Authorization state

`BLOCKED` until operational contracts from FO-7 exist.

---

## FO-10 — Controlled Pilot, KPI Proof, Cutover & Legacy Retirement

### Product outcome

ارزش، ایمنی و قابلیت rollback در cohort محدود اثبات شود؛ سپس cutover مرحله‌ای انجام شود.

### Pilot constraints

- role محدود و patient cohort محدود؛
- only test/safely approved data environment before real rollout؛
- auto SMS فقط allowlisted templates؛
- daily review در شروع؛
- rollback switches آماده؛
- old/new parity monitoring.

### KPI gates

```text
100% open items have next action/wait/block
100% items have owner role or explicit unassigned reason
median time to identify next action <= 5 seconds
primary action starts in <= 2 interactions
zero stale SMS sent
zero duplicate mutation on scheduler rerun
zero clinical completion without evidence
zero hidden critical automation failure
>=80% reduction in routine SMS manual approval
unassigned overdue <5% in pilot
reduced cross-screen navigation
reduced manual callback scheduling
```

### Cutover gate

- KPI thresholds met؛
- security/privacy review؛
- clinical safety review؛
- migration/rebuild rehearsal؛
- rollback rehearsal؛
- full CI green؛
- user acceptance signed؛
- Project State updated؛
- production TEST_ONLY assumption explicitly revoked before real PHI.

### Legacy retirement

رابط قدیمی ابتدا compatibility read-only می‌شود. حذف UI یا source table فقط با evidence و migration/governance مستقل مجاز است.

### Authorization state

`BLOCKED` تا تکمیل FO-0..FO-9.

---

## 6. Exact continuation point

```text
CURRENT = FO-4 Local Owner UX Acceptance
ISSUE   = #94
REVIEW  = main@cd243424ecbae98892e0dfde1780bb846554942f
NEXT    = owner attestation with critical_ux_defects=0
THEN    = separate governance decision whether FO-5 may start
```

کار مجاز پیش از attestation:

- تکمیل اسناد و review package؛
- اجرای CI و smoke evidence؛
- ثبت defectهای مشاهده‌شده؛
- focused FO-4 fixes با Issue/PR/CI مستقل.

کار غیرمجاز:

- شروع Structured Contact؛
- retry/escalation automation؛
- SMS automation؛
- Appointment sync/outbox؛
- Evidence Assist؛
- Automation Health runtime؛
- FO-10 pilot.

---

## 7. Owner acceptance command

```powershell
git checkout main
git pull origin main
cd specialist_clinic
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

$env:FOLLOWUP_PROJECTION_SHADOW = "1"
.\.venv\Scripts\python.exe scripts\prepare_seeded_followup_view.py `
  --database specialist.db

$env:FOLLOWUP_UNIFIED_WORKLIST_READONLY = "1"
$env:FOLLOWUP_UNIFIED_WORKLIST_ACTIONS = "1"
$env:FOLLOWUP_AUTO_ROUTING = "1"
.\.venv\Scripts\python.exe start.py
```

Attestation template:

```text
FO4_UX_ACCEPTED = true|false
reviewer = Emad211
reviewed_commit = cd243424ecbae98892e0dfde1780bb846554942f
reviewed_on_test_data = true
critical_ux_defects = <number>
notes = <observations or defects>
```
