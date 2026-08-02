# Follow-up Orchestration & UX v1 — Canonical Implementation Plan

> **نام فایل مرجع:** `specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md`
>
> **کد برنامه:** `FOUX-V1`
>
> **نسخه:** `1.2.0`
>
> **آخرین بازبینی:** `2026-08-03`
>
> **وضعیت:** `FO_0_VALIDATED / FO_1_VALIDATED / FO_2_AUTHORIZED`
>
> **مالک:** `Emad211`
>
> **دامنه:** فقط `specialist_clinic/`
>
> **طبقه‌بندی محیط فعلی:** `TEST_ONLY / SYNTHETIC_OR_RESETTABLE_DATA`
>
> **خارج از دامنه:** تغییر Rule بالینی، گسترش Hypoglycemia Shadow، تصمیم درمانی خودکار، Write به `clinic_new.db` و تغییر رفتار `webapp/`.

---

## 0. نقش و حاکمیت سند

این سند Source of Truth اجرایی جریان `FOUX-V1` است. ترتیب اعتماد:

1. وضعیت واقعی `main`، schema، تست‌ها و CI؛
2. `PROJECT_STATE.md` و `PROJECT_STATE.json`؛
3. این سند؛
4. ADRها و اسناد نزدیک به کد؛
5. Issue و PRهای همین جریان؛
6. متن گفتگو یا حافظهٔ ایجنت.

در صورت تعارض، منبع پایین‌تر پیش از ادامه اصلاح می‌شود. هر PR این جریان باید در body خود موارد زیر را مشخص کند:

```text
Program / Tranche
Requirement IDs
Scope / Anti-scope
Schema and migration impact
Feature flag and default
Focused/full tests
Rollback
UX impact
Clinical-safety impact
```

وجود branch، commit یا PR به معنی تکمیل tranche نیست. فقط merge روی `main` همراه با evidence، CI و به‌روزرسانی دفتر پیشرفت معتبر است.

---

## 1. مسئلهٔ محصول

سامانه در تشخیص رویدادها و ساخت Task، پیام، نوبت و رویداد تماس توانمند است، اما کاربر برای دنبال‌کردن یک پیگیری مجبور است چند Source of Truth را ذهنی کنار هم بگذارد:

```text
followup_tasks
clinical_task_events
clinical_outcome_events
care_plan_commitments
care_plan_commitment_events
followup_contact_events
engagement_approvals
engagement_dispatch
sms_messages
appointments
operational_job_runs
```

پیامدهای فعلی:

- اقدام بعدی روشن نیست؛
- مالک یا صف مسئول همیشه واضح نیست؛
- SMS، تماس، نوبت و Task یک Timeline مشترک ندارند؛
- callback، retry، escalation و closure هنوز دستی‌اند؛
- چند source مرتبط زیر reason کلی پنهان می‌شوند؛
- stateهای فنی به‌جای زبان عملیاتی نمایش داده می‌شوند؛
- پزشک ممکن است با کارهای روتین درگیر شود؛
- سلامت Scheduler و شکست اتوماسیون برای اپراتور شفاف نیست.

صورت مسئله:

> هر Work Item باید در چند ثانیه نشان دهد چرا ساخته شده، مسئول آن کیست، منتظر چیست، آخرین اتفاق چه بوده و اقدام بعدی دقیقاً چیست.

---

## 2. تصمیم محیط و Baseline

مالک محصول در تاریخ `2026-08-03` تأیید کرده است که دیتابیس فعلی Specialist Clinic فقط دادهٔ تستی دارد:

```text
Current specialist.db data class = TEST_ONLY
Real patient PHI                 = NOT PRESENT BY OWNER ATTESTATION
Data may be reset/reseeded       = YES
Production-volume inference      = FORBIDDEN
```

این طبقه‌بندی فقط governance محیط فعلی است و نباید وارد منطق runtime شود. پیش از ورود اولین دادهٔ واقعی بیمار:

- production-readiness review؛
- privacy/security review؛
- backup/restore rehearsal؛
- role/consent review؛
- baseline بدون PHI؛
- و بازبینی همهٔ automation flagها الزامی است.

دادهٔ تستی برای اثبات correctness، migration و parity استفاده می‌شود، نه برای ادعای KPI تجاری.

---

## 3. اهداف

### 3.1 محصول و UX

- تبدیل Task، SMS، Contact، Appointment و Outcome به Episode قابل‌ردیابی؛
- ساخت Unified Work Item Projection قابل‌بازسازی؛
- محاسبهٔ مرکزی `next_action`، `waiting_reason` و `blocked_reason`؛
- routing به صف نقش مناسب؛
- نمایش یک CTA اصلی؛
- Timeline واحد؛
- کاهش navigation و ورود تکراری داده؛
- کاهش تأیید دستی پیام‌های روتین allowlisted؛
- مشاهده‌پذیری سلامت اتوماسیون.

### 3.2 فنی

- migrationهای additive و idempotent؛
- eventهای append-only؛
- mutationهای idempotent؛
- Projection deterministic و rebuildable؛
- source hash/revision؛
- stale protection؛
- feature flag و rollback برای هر tranche؛
- عدم بازنویسی Source of Truthهای فعلی.

---

## 4. Anti-goalها

این برنامه نباید:

- workflow builder عمومی مانند n8n بسازد؛
- Rule بالینی جدید تولید یا فعال کند؛
- تشخیص، نسخه، دارو، دوز یا ارجاع را خودکار کند؛
- Recommendation بالینی را بدون انسان بپذیرد؛
- Clinical Task را بدون Evidence تکمیل کند؛
- Consent، quiet hours، cap، cooldown یا idempotency را دور بزند؛
- Source of Truth بالینی را با Episode یا Projection جایگزین کند؛
- migration destructive ایجاد کند؛
- UI قدیمی را پیش از parity و rollback حذف کند؛
- منطق دامنه را در template یا JavaScript پراکنده کند؛
- `clinic_new.db` را از Specialist Clinic mutate کند.

---

## 5. Invariantهای غیرقابل‌مذاکره

1. `followup_tasks` حقیقت تسک اداری باقی می‌ماند.
2. Clinical Task identity و lifecycle حاکم فعلی حفظ می‌شود.
3. completion بالینی بدون Evidence معتبر غیرممکن می‌ماند.
4. Appointment، Clinical Task را completed نمی‌کند.
5. Episode فقط حقیقت رابطه و lineage عملیاتی است.
6. Projection cache/read model است، نه source truth.
7. هر mutation orchestration idempotency key دارد.
8. هر event actor، time، policy/version و content hash دارد.
9. هیچ رابطه یا outcome ساختگی تولید نمی‌شود.
10. Relation مبهم با orphan reason ثبت می‌شود، نه حدس.
11. Rule و Hypoglycemia Shadow خارج از scope هستند.
12. همهٔ flagها default OFF باقی می‌مانند تا tranche مربوط merge و تأیید شود.
13. فرض `TEST_ONLY` باعث کاهش security یا clinical guardrail نمی‌شود.

---

## 6. Source of Truthها

| Concern | Source | Mutation contract |
|---|---|---|
| Administrative task | `followup_tasks` خارج از governed engines | mutable compact lifecycle |
| Clinical task identity | `followup_tasks` با `source_engine='clinical_v2'` | immutable |
| Clinical state | `clinical_task_events` | append-only linear stream |
| Clinical outcome | `clinical_outcome_events` | append-only |
| Encounter commitment identity | `care_plan_commitments` | immutable |
| Encounter commitment state | `care_plan_commitment_events` | append-only |
| Contact history | `followup_contact_events` | append-only |
| Engagement candidate | `engagement_approvals` | approval workflow |
| Engagement dedupe | `engagement_dispatch` | idempotent ledger |
| SMS state | `sms_messages` | submission/delivery reconciliation |
| Appointment | `appointments` | existing appointment workflow |
| Scheduler ownership | `operational_leases` | lease/fencing |
| Durable job result | `operational_job_runs` | idempotent job lifecycle |
| Episode identity | `followup_episodes` | immutable, added in FO-1 |
| Episode-source relation | `followup_episode_links` | immutable, added in FO-1 |
| Episode lineage event | `followup_episode_events` | append-only, added in FO-1 |

---

## 7. معماری هدف

```text
Existing Source Truths
        ↓
Read Adapters
        ↓
Episode Identity + Source Linker       ← FO-1 completed
        ↓
Append-only Episode Event Stream       ← FO-1 completed
        ↓
Projection / Policy Layer              ← FO-2 current
  ├─ source-state adapters
  ├─ current state
  ├─ next action
  ├─ waiting / blocked reason
  ├─ action_due / target_at
  ├─ role-routing proposal
  └─ parity / lag / rebuild metrics
        ↓
Read-only Unified Worklist             ← FO-3
        ↓
Ownership / Contact / SMS / Outbox / Evidence / Health
```

پوشه‌های مسئولیت:

```text
src/services/followup_orchestration/
  identity.py
  backfill.py
  source_state.py
  projection_service.py
  next_action_policy.py
  routing_policy.py
  sla_policy.py
  contact_policy.py
  sms_transition_service.py
  appointment_transition_service.py
  evidence_assist_service.py
  health_service.py

src/adapters/sqlite/
  followup_episode_schema.py
  followup_episode_repo.py
  followup_projection_schema.py
  followup_projection_repo.py
  operational_outbox_repo.py
```

از God Service جلوگیری شود. Policy، persistence و HTTP/UI باید جدا بمانند.

---

## 8. FO-1 Contract — Episode Identity & Links

FO-1 روی `main` پیاده و validated شده است.

### 8.1 Episode identity

```text
episode_id
patient_link_id
episode_type
semantic_key
period_key
identity_version
opened_at
created_at
created_by
identity_hash
```

Identity از JSON canonical این ابعاد ساخته می‌شود:

```text
patient_link_id
episode_type
semantic_key
period_key
identity_version
```

SHA-256 کامل و prefix ثابت `fuep_` استفاده می‌شود. متن فارسی قابل‌ویرایش یا state جاری در identity دخالت ندارد.

### 8.2 Source links

Source typeهای فعلی:

```text
ADMIN_TASK
CLINICAL_TASK
ENCOUNTER_COMMITMENT
ENGAGEMENT_APPROVAL
SMS_MESSAGE
APPOINTMENT
CONTACT_EVENT
CLINICAL_OUTCOME
```

هر link:

```text
episode_id
patient_link_id
source_type
source_id
source_revision
relation_type
linked_at
linked_by
idempotency_key
content_hash
```

Source revision فقط از identity/provenance ثابت source ساخته می‌شود، نه lifecycle mutable.

### 8.3 Episode events

FO-1 فقط این eventها را ایجاد می‌کند:

```text
EPISODE_OPENED
SOURCE_LINKED
```

Event stream:

- append-only؛
- first event اجباری `EPISODE_OPENED`؛
- linear supersession؛
- patient/scope safe؛
- recorded time non-decreasing؛
- content-hashed و idempotent.

### 8.4 Backfill

CLI:

```bash
python specialist_clinic/scripts/backfill_followup_episodes.py \
  --database specialist_clinic/specialist.db

python specialist_clinic/scripts/backfill_followup_episodes.py \
  --database specialist_clinic/specialist.db --apply
```

ویژگی‌ها:

- dry-run به‌صورت `mode=ro`؛
- aggregate-only output؛
- no patient name/phone/message/clinical value؛
- explicit orphan reasons؛
- repeated apply بدون duplicate؛
- source truth digest قبل/بعد باید برابر باشد؛
- startup فقط schema additive را نصب می‌کند و backfill خودکار اجرا نمی‌شود.

### 8.5 Evidence FO-1

```text
Issue               = #74
PR                  = #75
Merge commit        = 15ef1585c069a74c26fbc0ce859e03906e5f475a
Specialist tests    = 736 passed
Accounting tests    = 54 passed
Synthetic Episodes  = 4
Synthetic Links     = 12
Second apply new    = 0
Source digest       = unchanged
```

FO-1 Exit Gate: **PASS**.

---

## 9. FO-2 Contract — Projection, Next Action & Shadow Parity

**وضعیت فعلی:** `AUTHORIZED`

FO-2 فقط یک Shadow Projection می‌سازد. هیچ UI اصلی، assignment، SMS، appointment reaction یا mutation عملیاتی جدیدی فعال نمی‌کند.

### 9.1 خروجی داده

جدول پیشنهادی `followup_work_item_projection`:

```text
episode_id PRIMARY KEY
patient_link_id
episode_type
reason_code
reason_label
why_created
current_state
state_class             ACTION_REQUIRED | WAITING | BLOCKED | TERMINAL
next_action_code
next_action_label
waiting_reason_code
waiting_reason_label
blocked_reason_code
blocked_reason_label
owner_role_proposal
owner_user_id           NULL in FO-2
action_due_at
target_at
priority
sla_state
last_source_event_at
last_episode_event_id
sms_state
appointment_state
evidence_state
source_count
source_fingerprint
projection_version
projection_hash
rebuilt_at
```

قواعد:

- projection source truth نیست؛
- UPDATE توسط policy rebuild مجاز است، ولی delete/rebuild باید معادل تولید کند؛
- هر nonterminal item دقیقاً یکی از `ACTION_REQUIRED / WAITING / BLOCKED` است؛
- اگر `ACTION_REQUIRED` است، `next_action_code` الزامی است؛
- اگر `WAITING` است، waiting reason الزامی است؛
- اگر `BLOCKED` است، blocked reason الزامی است؛
- state raw فقط در audit نگهداری می‌شود؛
- owner فقط role proposal است؛ assignment واقعی FO-4 است.

### 9.2 Source-state adapters

Adapterها باید state حاکم را بدون mutation بخوانند:

```text
ADMIN_TASK               followup_tasks.status
CLINICAL_TASK            head clinical_task_events
ENCOUNTER_COMMITMENT     head care_plan_commitment_events
ENGAGEMENT_APPROVAL      engagement_approvals.status
SMS_MESSAGE              sms_messages status/delivery
APPOINTMENT              appointments.status
CONTACT_EVENT            latest contact event
CLINICAL_OUTCOME         latest valid outcome reference
```

هر adapter باید:

- patient scope را دوباره کنترل کند؛
- source revision/fingerprint بدهد؛
- missing/stale/conflict را fail-loud کند؛
- هیچ SQL mutation انجام ندهد؛
- raw PHI را وارد generic projection نکند.

### 9.3 Next-action policy v1

Policy versioned و deterministic باشد. حداقل mapping:

```text
Administrative task open + no contact/appointment
→ ACTION_REQUIRED / CONTACT_PATIENT

Approval pending
→ ACTION_REQUIRED / REVIEW_SMS

SMS delivered + هنوز target نرسیده
→ WAITING / WAITING_FOR_PATIENT_OR_TARGET

SMS permanent failure
→ ACTION_REQUIRED / CALL_PATIENT

Phone invalid
→ BLOCKED / CONTACT_DATA_INVALID

Appointment scheduled
→ WAITING / WAITING_FOR_APPOINTMENT

Appointment cancelled
→ ACTION_REQUIRED / REBOOK_APPOINTMENT

Appointment no_show
→ ACTION_REQUIRED / FOLLOW_UP_NO_SHOW

Clinical task missing required outcome
→ ACTION_REQUIRED / RECORD_CLINICAL_EVIDENCE

Clinical task awaiting clinician decision
→ BLOCKED / CLINICIAN_DECISION_REQUIRED

Terminal source state
→ TERMINAL / no next action
```

FO-2 فقط **نمایش پیشنهادی** تولید می‌کند؛ هیچ transitionی اجرا نمی‌شود.

### 9.4 action_due_at و target_at

```text
action_due_at = زمانی که کارمند باید کاری انجام دهد
target_at     = موعد نوبت، دارو، آزمایش یا هدف پیگیری
```

نباید یکی فرض شوند. اگر تاریخ اقدام قابل‌اثبات نیست:

- policy fallback versioned؛ یا
- `BLOCKED / ACTION_DUE_UNKNOWN`؛

اما تاریخ ساختگی تولید نمی‌شود.

### 9.5 Role routing proposal

FO-2 فقط پیشنهاد role می‌دهد:

```text
Reception:
  appointment coordination, no-show, invalid phone, lapsed admin

Nursing:
  vitals, labs, education, non-prescriptive clinical follow-up

Physician:
  clinician decision, clinical conflict, governed recommendation review

Manager:
  policy/schema conflict, orphan, dead-letter-like operational block
```

Auto assignment به user ممنوع است.

### 9.6 Shadow parity

Projection جدید باید با Worklist فعلی مقایسه شود:

```text
legacy open item count
projected nonterminal episode count
matched
projection-only
legacy-only
blocked/conflict
explainable mismatch reason
```

Exit Gate:

- حداقل ۹۹٪ parity explainable روی cohort تستی؛
- zero hidden source؛
- تمام mismatchها reason code؛
- same source snapshot → same projection hash؛
- rebuild دوم بدون اختلاف؛
- source truth unchanged؛
- feature default OFF؛
- full CI green.

### 9.7 Feature flag

```text
FOLLOWUP_PROJECTION_SHADOW
```

Default OFF. اجرای explicit CLI/test مجاز است. Scheduler یا request path فقط در PR مستقل و پس از اثبات performance می‌تواند shadow rebuild را فراخوانی کند.

### 9.8 خارج از scope FO-2

- Worklist جدید؛
- primary CTA واقعی؛
- claim/assignment؛
- SMS auto-send؛
- retry/escalation mutation؛
- appointment reaction؛
- outbox؛
- Evidence Assist؛
- automatic close؛
- clinical decision.

---

## 10. State و زبان کاربر

هر Work Item nonterminal یکی از این سه حالت است:

```text
ACTION_REQUIRED
WAITING
BLOCKED
```

و دقیقاً یکی از این فیلدها باید توضیح کامل داشته باشد:

```text
next_action
waiting_reason
blocked_reason
```

نمونهٔ زبان عملیاتی:

| State فنی | نمایش کاربر |
|---|---|
| pending approval | متن آماده است؛ نیازمند بازبینی مجاز |
| delivered | پیام تحویل شد؛ تا موعد پاسخ منتظر بمانید |
| provider rejected | پیام نرسید؛ با بیمار تماس بگیرید |
| scheduled | نوبت ثبت شده؛ فعلاً اقدامی لازم نیست |
| cancelled | نوبت لغو شد؛ هماهنگی مجدد لازم است |
| evidence missing | برای تکمیل، شاهد معتبر ثبت کنید |

Enumها و hashها فقط در audit/debug نمایش داده می‌شوند.

---

## 11. Routing، Ownership و SLA آینده

ترتیب هدف:

```text
role queue proposal      FO-2
read-only display        FO-3
claim/assignment         FO-4
SLA and escalation       FO-4/FO-5
```

Roleهای هدف:

```text
Reception / Secretary
Nursing
Physician
Manager / Operations
```

Auto-assign فردی تا وجود شیفت و availability معتبر ممنوع است.

---

## 12. Contact Outcome آینده

Outcomeهای ساختاری موجود/هدف:

```text
REACHED
NO_ANSWER
BUSY
WRONG_NUMBER
CALLBACK_REQUESTED
DECLINED
BOOKED
MESSAGE_SENT
MESSAGE_DELIVERED
OTHER
```

در FO-5 هر outcome policy مشخص خواهد داشت. یادداشت متن آزاد فقط مکمل است.

---

## 13. SMS Policy آینده

چهار سطح:

```text
AUTO
AUTO_WITH_GUARDS
REQUIRES_REVIEW
CLINICIAN_ONLY
```

Auto فقط با allowlist، consent، شماره canonical، quiet hours، cap، cooldown، freshness و idempotency مجاز است. `CLINICIAN_ONLY` هرگز auto-send نمی‌شود.

---

## 14. Cross-channel و Outbox آینده

از FO-7:

```text
SMS delivered             → WAITING_PATIENT
SMS permanent failure     → CALL_PATIENT / FIX_CONTACT_DATA
Appointment booked        → WAITING_APPOINTMENT
Appointment cancelled     → REOPEN_ACTION
Appointment no-show       → FOLLOW_UP_REQUIRED
Administrative goal met   → close administrative episode
```

هیچ cross-channel transitionی Clinical Task را خودکار complete نمی‌کند.

---

## 15. Clinical Evidence Assist آینده

Evidence Assist فقط candidate را پیدا، provenance را نمایش و form را prefill می‌کند. accept/reject و completion انسانی باقی می‌ماند. شاهد stale، بدون provenance یا متعلق به بیمار/task دیگر رد می‌شود.

---

## 16. UX هدف

صف‌ها:

```text
کارهای من
صف نقش من
بدون مسئول
در انتظار بیمار
در انتظار نوبت/نتیجه
نیازمند پزشک
موعدگذشته
```

کارت Work Item:

```text
نام بیمار
دلیل قابل‌فهم
چرا ساخته شده
اقدام بعدی
مسئول یا صف نقش
action_due و target
آخرین رویداد
خلاصه SMS/Appointment/Evidence
یک CTA اصلی
```

Timeline باید تمام source eventها را با زبان کاربر نشان دهد و جزئیات فنی در drawer audit باشد.

---

## 17. Automation Health آینده

در FO-9 مدیر باید ببیند:

```text
scheduler heartbeat
last successful tick
job failures
lease owner and age
outbox backlog
projection lag
stale approval count
SMS unknown/failed
unassigned overdue
dead-letter
automation paused reasons
```

Log به‌تنهایی کافی نیست.

---

## 18. Feature Flagها

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

همه default OFF. وضعیت فعلی:

```text
Episode schema/backfill infrastructure = merged, explicit-use only
Projection shadow                      = not implemented yet
UI/action flags                        = OFF and unused
```

---

## 19. برنامهٔ اجرایی Tranche-by-Tranche

### FO-0 — Governance, Baseline & Registration

**Status:** `VALIDATED`

Evidence:

```text
PR #72
merge 901dbfdf9c358ecc09d2a60a0680f6a4a8370d17
731 Specialist tests
54 Accounting tests
owner test-only attestation via PR #73
```

### FO-1 — Episode Identity & Append-only Links

**Status:** `VALIDATED`

Evidence:

```text
Issue #74
PR #75
merge 15ef1585c069a74c26fbc0ce859e03906e5f475a
736 Specialist tests
54 Accounting tests
4 Episodes / 12 Links synthetic fixture
second apply: 0 new records
source digest unchanged
```

### FO-2 — Projection, Next Action & Shadow Parity

**Status:** `AUTHORIZED`

کارها:

- projection schema/repository؛
- source-state adapters؛
- central state/next-action policy؛
- waiting/block reasons؛
- action_due/target separation؛
- owner role proposal؛
- deterministic hash/rebuild؛
- parity report؛
- lag/performance metrics؛
- explicit CLI و focused/full tests.

Flag: `FOLLOWUP_PROJECTION_SHADOW`.

### FO-3 — Read-only Unified Worklist

**Status:** `BLOCKED_PENDING_FO_2`

- read-only page؛
- role/owner/waiting/overdue tabs؛
- one read-only CTA label؛
- detail drawer/Timeline؛
- deep links؛
- usability telemetry.

### FO-4 — Claim, Assignment, Routing & SLA

**Status:** `NOT_STARTED`

- atomic claim/release/reassign؛
- role queues؛
- routing policy؛
- SLA state؛
- audit and stale protection.

### FO-5 — Structured Contact, Retry & Escalation

**Status:** `NOT_STARTED`

- outcome-driven next action؛
- callback scheduling؛
- attempt policy؛
- invalid phone/unreachable flow؛
- low-click contact UI.

### FO-6 — Governed SMS Automation & Freshness

**Status:** `NOT_STARTED`

- policy level؛
- template versioning؛
- approval expiry؛
- source revision/freshness؛
- stale supersession؛
- guarded auto path؛
- audit decision event.

### FO-7 — Cross-channel Transition & Outbox

**Status:** `NOT_STARTED`

- durable outbox؛
- SMS/appointment reactions؛
- administrative goal completion؛
- retry/dead-letter.

### FO-8 — Clinical Evidence Assist

**Status:** `NOT_STARTED`

- contract reader؛
- evidence matcher؛
- provenance UI؛
- human accept/reject؛
- governed completion handoff.

### FO-9 — Automation Health

**Status:** `NOT_STARTED`

- heartbeat/job history؛
- outbox/dead-letter؛
- projection lag؛
- stale approval monitor؛
- safe retry controls؛
- runbook.

### FO-10 — Pilot, KPI, Cutover & Legacy Retirement

**Status:** `NOT_STARTED`

- cohort/role محدود؛
- allowlisted SMS only؛
- old/new parity؛
- production baseline؛
- rollback rehearsal؛
- KPI proof؛
- retirement فقط پس از evidence.

---

## 20. Testing Strategy

### Unit

- identity/hash؛
- source adapters؛
- projection policy؛
- routing proposal؛
- SLA؛
- contact policy؛
- SMS policy؛
- transition؛
- evidence match.

### Schema/Repository

- fresh DB؛
- existing/copied DB؛
- rerun migration؛
- append-only trigger؛
- unique/idempotency؛
- patient scope؛
- deterministic rebuild؛
- stale source.

### Integration

- source → Episode → Projection؛
- rebuild/replay؛
- Scheduler rerun؛
- outbox replay؛
- delivery/appointment states؛
- source digest unchanged.

### E2E هدف

1. appointment reminder؛
2. SMS delivered then wait؛
3. permanent SMS failure then call؛
4. two medications in one Episode؛
5. no-answer/callback/escalation؛
6. wrong phone؛
7. appointment booking؛
8. cancellation؛
9. no-show؛
10. clinical recommendation requiring confirmation؛
11. evidence suggested then human confirmed؛
12. duplicate Scheduler and fencing؛
13. projection rebuild؛
14. stale approval superseded؛
15. dead-letter retry.

هر PR:

```text
focused tests
full Specialist suite
Accounting suite when shared/governance impact exists
fresh/existing migration tests when schema changes
git diff check
CI artifacts
```

---

## 21. Security، Privacy و Reliability

- least privilege و permission server-side؛
- CSRF برای mutation؛
- no PHI in logs/aggregate reports؛
- actor/time/policy/version audit؛
- consent and phone revalidation؛
- source revision/hash؛
- bounded batches؛
- lease/fencing retained؛
- one bad source does not stop whole batch؛
- explicit transaction boundaries؛
- projection rebuild resumable؛
- no raw clinical payload in generic projection مگر ضرورت قراردادی.

---

## 22. Rollback

### UI rollback

flag UI OFF و UI قدیمی باقی می‌ماند.

### Projection rollback

`FOLLOWUP_PROJECTION_SHADOW=0`؛ projection table retained-but-unused؛ Episode lineage باقی می‌ماند.

### Orchestration rollback

action flags OFF؛ هیچ source truth حذف یا بازنویسی نمی‌شود.

### Data rollback

schema additive retained-but-unused؛ destructive rollback ممنوع.

---

## 23. KPIها

```text
100% nonterminal item has action/wait/block
100% item has owner role or explicit unassigned reason
median next-action comprehension ≤ 5 sec
primary action starts ≤ 2 interactions
zero stale SMS
zero duplicate mutation on rerun
zero clinical completion without evidence
zero hidden critical automation failure
≥80% reduction in routine SMS manual approval
unassigned overdue <5% in pilot
reduced navigation and duplicate entry
```

KPIهای واقعی فقط در Pilot معتبرند؛ دادهٔ تستی correctness و parity را اثبات می‌کند.

---

## 24. Requirement Registry

### Governance

- `GOV-001` این سند مرجع اجرایی است.
- `GOV-002` `PROJECT_STATE.*` مقدم است.
- `GOV-003` هر PR tranche/requirement/flag/rollback را ذکر می‌کند.
- `GOV-004` هر contract نسخه و evidence دارد.
- `GOV-005` طبقه‌بندی محیط و تاریخ اعتبار ثبت می‌شود.

### Data

- `DATA-001` migration additive/idempotent.
- `DATA-002` Episode/Projection حقیقت بالینی نیست.
- `DATA-003` Episode events append-only.
- `DATA-004` Projection rebuildable.
- `DATA-005` source link patient-safe.
- `DATA-006` action_due و target جدا.
- `DATA-007` relation/event ساختگی ممنوع.
- `DATA-008` same snapshot → same projection hash.

### Orchestration

- `ORCH-001` action/wait/block روشن.
- `ORCH-002` mutation idempotent.
- `ORCH-003` role proposal مرکزی.
- `ORCH-004` contact structured.
- `ORCH-005` cross-channel via outbox.
- `ORCH-006` retry/escalation versioned.
- `ORCH-007` FO-2 فقط shadow/read-only است.

### SMS

- `SMS-001` چهار policy level.
- `SMS-002` auto فقط allowlisted + guarded.
- `SMS-003` clinician-only never auto.
- `SMS-004` pre-send freshness.
- `SMS-005` stale superseded.
- `SMS-006` consent/quiet/cap/cooldown/idempotency.

### UX

- `UX-001` یک primary CTA.
- `UX-002` زبان عملیاتی.
- `UX-003` Timeline واحد.
- `UX-004` کاهش navigation.
- `UX-005` role/waiting/overdue views.
- `UX-006` blocked reason قابل‌فهم.

### Clinical

- `CLIN-001` no automated treatment decision.
- `CLIN-002` no completion without Evidence.
- `CLIN-003` appointment does not complete clinical task.
- `CLIN-004` Evidence Assist requires confirmation.
- `CLIN-005` Rule/Shadow freeze respected.

### Operations/Security

- `OPS-001` Scheduler health visible.
- `OPS-002` outbox/dead-letter visible.
- `OPS-003` no hidden critical failure.
- `OPS-004` safe retry.
- `OPS-005` projection lag measurable.
- `SEC-001` permission/CSRF/stale protection.
- `SEC-002` no PHI leakage.
- `SEC-003` policy/version/actor audit.

---

## 25. دفتر پیشرفت

| Tranche | Status | Main commit | PR | CI/Evidence |
|---|---|---|---|---|
| FO-0 | VALIDATED | `901dbfdf9c358ecc09d2a60a0680f6a4a8370d17` | #72/#73 | 731 + 54؛ test-only attestation |
| FO-1 | VALIDATED | `15ef1585c069a74c26fbc0ce859e03906e5f475a` | #75 | 736 + 54؛ 4 Episodes/12 Links؛ idempotent |
| FO-2 | AUTHORIZED | — | — | Projection/next-action shadow only |
| FO-3 | BLOCKED | — | — | pending FO-2 gate |
| FO-4 | NOT_STARTED | — | — | — |
| FO-5 | NOT_STARTED | — | — | — |
| FO-6 | NOT_STARTED | — | — | — |
| FO-7 | NOT_STARTED | — | — | — |
| FO-8 | NOT_STARTED | — | — | — |
| FO-9 | NOT_STARTED | — | — | — |
| FO-10 | NOT_STARTED | — | — | — |

Statusهای مجاز:

```text
NOT_STARTED
AUTHORIZED
IN_PROGRESS
BLOCKED
PR_OPEN
MERGED
VALIDATED
ROLLED_BACK
SUPERSEDED
```

---

## 26. Decision Log

| ID | تاریخ | تصمیم | وضعیت |
|---|---|---|---|
| DEC-001 | 2026-08-03 | Projection به‌جای بازنویسی Source Truth | ACCEPTED |
| DEC-002 | 2026-08-03 | role queue قبل از auto-assign فرد | ACCEPTED |
| DEC-003 | 2026-08-03 | چهار سطح SMS review | ACCEPTED_FOR_PLAN |
| DEC-004 | 2026-08-03 | Evidence suggest/prefill؛ completion انسانی | ACCEPTED |
| DEC-005 | 2026-08-03 | durable outbox برای cross-channel | ACCEPTED_FOR_PLAN |
| DEC-006 | 2026-08-03 | legacy UI تا parity حذف نمی‌شود | ACCEPTED |
| DEC-007 | 2026-08-03 | Rule و Shadow خارج از scope | ACCEPTED |
| DEC-008 | 2026-08-03 | محیط فعلی test-only/resettable | OWNER_ATTESTED |
| DEC-009 | 2026-08-03 | deterministic synthetic baseline برای FO-0 | ACCEPTED |
| DEC-010 | 2026-08-03 | FO-0 validated و FO-1 authorized | COMPLETED |
| DEC-011 | 2026-08-03 | Episode identity/link/event بدون runtime reaction | IMPLEMENTED |
| DEC-012 | 2026-08-03 | ambiguous relation → orphan reason، نه حدس | IMPLEMENTED |
| DEC-013 | 2026-08-03 | FO-1 validated؛ FO-2 فقط shadow projection | ACCEPTED |

---

## 27. دستور شروع هر ایجنت

1. `PROJECT_STATE.md/json` را بخوان؛
2. این سند را کامل بخوان؛
3. نزدیک‌ترین `AGENTS.md` را بخوان؛
4. `main`، Issue، PR، CI و schema را بررسی کن؛
5. tranche و Requirement ID را اعلام کن؛
6. ثابت کن Rule/Shadow/Accounting وارد scope نشده‌اند؛
7. branch تازه از `main` بساز؛
8. focused baseline را اجرا کن؛
9. فقط همان tranche را تغییر بده؛
10. rollback و evidence را در PR ثبت کن؛
11. بعد از merge دفتر پیشرفت و Project State را به‌روزرسانی کن.

---

## 28. قدم مجاز فعلی

```text
FO-2 — Projection, Next Action & Shadow Parity
```

FO-3 یا هر UI/automation mutation پیش از بسته‌شدن Exit Gate FO-2 ممنوع است.
