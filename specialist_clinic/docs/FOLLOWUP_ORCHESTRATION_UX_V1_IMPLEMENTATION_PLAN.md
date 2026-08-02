# Follow-up Orchestration & UX v1 — Canonical Implementation Plan

> **نام فایل مرجع:** `specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md`
>
> **کد برنامه:** `FOUX-V1`
>
> **نسخه:** `1.1.0`
>
> **آخرین بازبینی:** `2026-08-03`
>
> **وضعیت:** `FO_0_VALIDATED / FO_1_AUTHORIZED`
>
> **مالک:** `Emad211`
>
> **دامنه:** فقط `specialist_clinic/`
>
> **طبقه‌بندی محیط فعلی:** `TEST_ONLY / SYNTHETIC_OR_RESETTABLE_DATA`
>
> **خارج از دامنه:** تغییر Rule بالینی، گسترش Hypoglycemia Shadow، تصمیم درمانی خودکار، Write به `clinic_new.db` و تغییر رفتار `webapp/`.

---

## 0. حاکمیت و ترتیب اعتماد

این سند Source of Truth اجرایی جریان `FOUX-V1` است، اما Source of Truth مدیریتی کل مخزن را جایگزین نمی‌کند. ترتیب اعتماد:

1. وضعیت واقعی `main`، schema، CI و تست‌ها؛
2. `PROJECT_STATE.md` و `PROJECT_STATE.json`؛
3. این سند؛
4. اسناد و ADRهای نزدیک به کد؛
5. Issue و PRهای همین جریان؛
6. متن گفتگو یا حافظهٔ ایجنت.

در صورت تعارض، سند پایین‌تر باید پیش از ادامه اصلاح شود. هر PR این جریان باید موارد زیر را در body ذکر کند:

```text
Program / Tranche
Requirement IDs
Scope and anti-scope
Schema/migration impact
Feature flag
Focused and full tests
Rollback
UX impact
Clinical-safety impact
```

وجود branch یا PR به معنی تکمیل tranche نیست. فقط merge روی `main` همراه با evidence و به‌روزرسانی دفتر پیشرفت معتبر است.

---

## 1. تصمیم جدید دربارهٔ داده و Baseline

### 1.1 طبقه‌بندی داده

طبق اعلام صریح مالک محصول در تاریخ `2026-08-03`، دیتابیس فعلی Specialist Clinic فقط شامل داده‌های تستی است. در نتیجه:

```text
Current specialist.db data class = TEST_ONLY
Real patient PHI                 = NOT PRESENT BY OWNER ATTESTATION
Data may be reset/reseeded       = YES
Production-volume inference      = FORBIDDEN
```

این تصمیم فقط دربارهٔ محیط فعلی است. قبل از ورود اولین دادهٔ واقعی بیمار، برنامه باید دوباره به حالت production-safety بازبینی شود و هیچ فرض `TEST_ONLY` نباید وارد منطق runtime شود.

### 1.2 اثر تصمیم روی FO-0

برای محیطی که فقط دادهٔ تستی و resettable دارد، snapshot عددی یک دیتابیس محلی معیار محصول معناداری نیست؛ زیرا با seed، reset و اجرای تست تغییر می‌کند. بنابراین Exit Gate صحیح FO-0 چنین است:

```text
Repository/UI baseline recorded
+ deterministic synthetic aggregate baseline tested
+ owner attestation: TEST_ONLY
+ no runtime/schema behavior change
+ all feature flags OFF
+ full CI green
= FO-0 VALIDATED
```

Baseline عددی محیط production به tranche Pilot/FO-10 منتقل می‌شود؛ چون فقط آن زمان حجم و رفتار عملیاتی واقعی قابل‌اندازه‌گیری است.

### 1.3 Evidence بسته‌شدن FO-0

```text
Canonical plan PR       = #70
FO-0 implementation PR = #72
FO-0 merge commit       = 901dbfdf9c358ecc09d2a60a0680f6a4a8370d17
Specialist tests        = 731 passed
Accounting tests        = 54 passed
Feature flags           = 10/10 default OFF
FOUX schema             = absent
Runtime consumer        = absent
```

پس از merge نسخهٔ 1.1.0 این سند و هماهنگی `PROJECT_STATE.*`، FO-1 مجاز است.

---

## 2. مسئلهٔ محصول

سامانه در تشخیص رویداد و ساخت آبجکت‌های عملیاتی قوی است، اما از دید کاربر یک پیگیری واحد در چند صفحه و چند Source of Truth پخش می‌شود:

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

کاربر برای پاسخ به سؤال سادهٔ «الان چه کاری باید انجام دهم؟» مجبور است وضعیت تسک، تماس، پیام، نوبت و نتیجه را ذهنی ترکیب کند. پیامدها:

- مالک کار مبهم است؛
- اقدام بعدی واضح نیست؛
- تسک و پیام مرتبط یک Timeline مشترک ندارند؛
- callback، retry، escalation و closure دستی‌اند؛
- چند source مرتبط زیر reason کلی پنهان می‌شوند؛
- وضعیت فنی به‌جای زبان عملیاتی نمایش داده می‌شود؛
- پزشک ممکن است با کار روتین غیرضروری درگیر شود؛
- سلامت Scheduler برای اپراتور قابل‌مشاهده نیست.

صورت مسئله:

> هر Work Item باید به‌صورت فوری نشان دهد چرا ساخته شده، مسئول آن کیست، منتظر چه چیزی است، آخرین اتفاق چه بوده و اقدام بعدی دقیقاً چیست.

---

## 3. اهداف و Anti-goalها

### 3.1 اهداف

- تبدیل Task، SMS، Contact، Appointment و Outcome پراکنده به یک Episode قابل‌ردیابی؛
- ساخت Unified Work Item Projection قابل‌بازسازی؛
- محاسبهٔ مرکزی `next_action`، `waiting_reason` و `blocked_reason`؛
- routing به صف نقش مناسب؛
- کاهش تأیید دستی SMSهای روتین و allowlisted؛
- retry و escalation قراردادمحور؛
- اتصال قابل‌اعتماد appointment/SMS/task؛
- Evidence Assist بدون تصمیم یا completion خودکار؛
- UI با یک CTA اصلی و Timeline واحد؛
- مشاهده‌پذیری کامل سلامت اتوماسیون.

### 3.2 Anti-goalها

این برنامه نباید:

- یک workflow builder عمومی شبیه n8n بسازد؛
- Rule بالینی جدید تولید یا فعال کند؛
- دارو، دوز، تشخیص یا ارجاع را خودکار تغییر دهد؛
- Recommendation بالینی را بدون انسان بپذیرد؛
- Clinical Task را بدون Evidence تکمیل کند؛
- Consent، quiet hours، daily cap یا cooldown را دور بزند؛
- Source of Truthهای فعلی را بازنویسی کند؛
- migration destructive ایجاد کند؛
- UI قدیمی را پیش از parity و rollback حذف کند؛
- منطق دامنه را در template یا JavaScript پخش کند.

---

## 4. Invariantهای غیرقابل‌مذاکره

1. `followup_tasks` حقیقت تسک اداری باقی می‌ماند.
2. وضعیت Clinical Task فقط از head رویدادهای append-only به‌دست می‌آید.
3. completion بالینی بدون Evidence معتبر غیرممکن می‌ماند.
4. ساخت Appointment، Clinical Task را completed نمی‌کند.
5. Episode حقیقت رابط عملیاتی است، نه حقیقت بالینی.
6. Projection cache/read model است و باید از sourceها rebuild شود.
7. همهٔ mutationهای orchestration باید idempotent باشند.
8. هر event جدید actor، time، policy/version و idempotency key دارد.
9. Specialist Clinic هرگز به `clinic_new.db` نمی‌نویسد.
10. Rule و Hypoglycemia Shadow خارج از scope باقی می‌مانند.
11. هر tranche با flag مستقل و rollback روشن وارد می‌شود.
12. فرض `TEST_ONLY` فقط governance محیط فعلی است و وارد منطق محصول نمی‌شود.

---

## 5. Source of Truth فعلی

| Concern | Source | Mutation model |
|---|---|---|
| Administrative task | `followup_tasks` خارج از governed engines | mutable compact lifecycle |
| Clinical task identity | `followup_tasks` با `source_engine='clinical_v2'` | immutable identity |
| Clinical state | `clinical_task_events` | append-only linear stream |
| Clinical outcome | `clinical_outcome_events` | append-only |
| Encounter commitment identity | `care_plan_commitments` | immutable |
| Encounter commitment state | `care_plan_commitment_events` | append-only |
| Contact history | `followup_contact_events` | append-only |
| Engagement candidate | `engagement_approvals` | approval workflow |
| Engagement dedupe | `engagement_dispatch` | idempotent ledger |
| SMS submission/delivery | `sms_messages` | governed dispatch/reconciliation |
| Appointment | `appointments` | appointment workflow |
| Scheduler ownership | `operational_leases` | lease + fencing |
| Durable scheduler result | `operational_job_runs` | idempotent job lifecycle |

لایهٔ جدید حق حذف یا تغییر معنای هیچ‌کدام را ندارد.

---

## 6. معماری هدف

```text
Existing source truths
        ↓
Read adapters
        ↓
Episode identity + source linker
        ↓
Append-only episode events
        ↓
Policy services
  ├─ next action
  ├─ waiting/block reason
  ├─ role routing
  ├─ SLA
  ├─ retry/escalation
  └─ administrative goal completion
        ↓
Rebuildable Work Item Projection
        ↓
Unified Worklist / Timeline / Automation Health
```

مسئولیت‌های پیشنهادی:

```text
src/services/followup_orchestration/
  identity.py
  episode_service.py
  source_linker.py
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
  followup_projection_repo.py
  operational_outbox_repo.py
```

نام فایل‌ها می‌تواند با سبک ریپو اصلاح شود، ولی boundaryها نباید در God Service ادغام شوند.

---

## 7. مدل دادهٔ هدف

### 7.1 `followup_episodes`

```text
id
patient_link_id
episode_type
semantic_key
period_key
status
priority
owner_role
owner_user_id
action_due_at
target_at
opened_at
closed_at
created_at
created_by
schema_version
identity_hash
```

قواعد:

- هویت بر مبنای patient + semantic purpose + period است؛
- reason کلی مثل `refill` به‌تنهایی identity نیست؛
- یک Episode می‌تواند چند source child داشته باشد؛
- episode clinical منبع تصمیم یا outcome بالینی نیست؛
- terminal episode فقط با outcome/disposition روشن بسته می‌شود.

### 7.2 `followup_episode_links`

```text
id
episode_id
source_type
source_id
source_revision
relation_type
linked_at
content_hash
```

Source typeهای اولیه:

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

هر source فقط به Episode همان بیمار link می‌شود. duplicate link باید idempotent باشد.

### 7.3 `followup_episode_events`

```text
id
episode_id
event_type
actor_type
actor_id
recorded_at
idempotency_key
supersedes_event_id
payload_json
content_hash
```

رویدادهای پایه:

```text
EPISODE_OPENED
SOURCE_LINKED
ROUTED
CLAIMED
ASSIGNED
ACTION_DUE_CHANGED
TARGET_CHANGED
WAITING_STARTED
WAITING_ENDED
CONTACT_RECORDED
SMS_QUEUED
SMS_SENT
SMS_DELIVERED
SMS_FAILED
APPOINTMENT_BOOKED
APPOINTMENT_CANCELLED
APPOINTMENT_NO_SHOW
EVIDENCE_SUGGESTED
ESCALATED
ADMINISTRATIVE_GOAL_MET
EPISODE_CLOSED
ENTERED_IN_ERROR
```

UPDATE و DELETE event ممنوع است. Event stream باید linear و stale-safe باشد.

### 7.4 `followup_work_item_projection`

```text
episode_id
patient_link_id
reason_label
why_created
current_state
next_action_code
next_action_label
waiting_reason
blocked_reason
owner_role
owner_user_id
action_due_at
target_at
priority
sla_state
last_event_at
sms_summary
appointment_summary
evidence_summary
source_count
projection_version
projection_hash
rebuilt_at
```

Projection باید بدون N+1، صفحه‌بندی‌شده و بر owner/state/due index شود.

### 7.5 `operational_outbox`

از FO-7 به بعد برای transitionهای cross-channel استفاده می‌شود. FO-1 فقط Episode/Link/Event را می‌سازد و Outbox را جلوتر از tranche خودش وارد نمی‌کند.

---

## 8. قرارداد Identity

Identity باید deterministic و versioned باشد:

```text
identity_version
patient_link_id
episode_type
semantic_key
period_key
source semantic dimensions
```

نمونه‌ها:

```text
appointment reminder → patient + appointment_id
refill → patient + medication/refill group + due period
lapsed → patient + lapsed month/threshold version
clinical task → canonical clinical_task_key
encounter commitment → commitment_id
```

Hash از JSON canonical با sort key و encoding ثابت ساخته می‌شود. Identity نباید به متن فارسی قابل‌ویرایش یا شناسهٔ موقت UI وابسته باشد.

---

## 9. Next Action و State زبان کاربر

هر Work Item non-terminal دقیقاً یکی از این سه حالت را دارد:

```text
ACTION_REQUIRED
WAITING
BLOCKED
```

و باید یکی از فیلدهای زیر پر باشد:

```text
next_action
waiting_reason
blocked_reason
```

نمونه:

| State فنی | نمایش عملیاتی |
|---|---|
| pending approval | متن آماده است؛ نیازمند تأیید مجاز |
| SMS delivered | پیام تحویل شد؛ تا موعد پاسخ منتظر بمانید |
| SMS permanent failure | پیام نرسید؛ با بیمار تماس بگیرید |
| appointment scheduled | نوبت ثبت شده؛ فعلاً اقدامی لازم نیست |
| appointment cancelled | نوبت لغو شد؛ هماهنگی مجدد لازم است |
| clinical evidence missing | برای تکمیل، شاهد معتبر ثبت کنید |

Enum خام فقط در audit/debug نمایش داده می‌شود.

---

## 10. Routing، Ownership و SLA

اول role queue، سپس user assignment:

```text
Reception / Secretary
Nursing
Physician
Manager / Operations
```

قواعد اولیه:

- نوبت، no-show، عدم مراجعه و اصلاح شماره → Reception؛
- آزمایش، شاخص، آموزش و پیگیری بالینی غیرتصمیمی → Nursing؛
- تصمیم درمانی، تعارض مهم یا تأیید Recommendation → Physician؛
- dead-letter، policy failure و assignment conflict → Manager.

Auto-assign مستقیم به شخص تا زمانی که شیفت/availability معتبر نداریم ممنوع است. Claim باید atomic باشد؛ stale form یا double-click نباید دو owner ایجاد کند.

`action_due_at` زمان اقدام کارمند است؛ `target_at` زمان هدف بالینی/نوبت/تمدید. این دو نباید یکی فرض شوند.

---

## 11. Contact Outcome

نتیجه تماس باید ساختاری باشد:

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

هر outcome policy مشخص دارد. مثال:

```text
NO_ANSWER → attempt + 1 → callback policy
WRONG_NUMBER → block SMS → route to reception data correction
CALLBACK_REQUESTED → require future callback time
BOOKED → link appointment → waiting state
DECLINED → governed disposition; no silent close
```

یادداشت متن آزاد فقط مکمل است، نه تنها منبع تصمیم اتوماسیون.

---

## 12. سیاست SMS

چهار سطح:

```text
AUTO
AUTO_WITH_GUARDS
REQUIRES_REVIEW
CLINICIAN_ONLY
```

شرایط auto-send:

- event/template روی allowlist؛
- purpose و consent معتبر؛
- شماره canonical؛
- quiet hours، daily cap و cooldown رعایت شده؛
- source revision و freshness معتبر؛
- idempotency key پایدار؛
- متن فاقد تصمیم یا ادعای بالینی حساس.

قبل از ارسال باید source دوباره بررسی شود. نوبت لغوشده، موعد تغییرکرده، شماره یا Template تغییرکرده باعث `SUPERSEDED` شدن candidate می‌شود. `CLINICIAN_ONLY` هرگز auto-send نمی‌شود.

---

## 13. Cross-channel Transition

از FO-7:

```text
SMS delivered → WAITING_PATIENT
SMS permanent failure → CALL_PATIENT or FIX_CONTACT_DATA
Appointment booked → WAITING_APPOINTMENT
Appointment cancelled → REOPEN_ACTION
No-show → FOLLOW_UP_REQUIRED
Administrative goal met → close administrative episode
```

هیچ transition cross-channel نباید Clinical Task را خودکار complete کند. Outbox replay باید idempotent باشد و dead-letter در UI دیده شود.

---

## 14. Clinical Evidence Assist

Evidence Assist فقط:

- candidate evidence را پیدا می‌کند؛
- provenance و match reason را نمایش می‌دهد؛
- form را prefill می‌کند؛
- accept/reject انسانی ثبت می‌کند؛
- سپس از همان Clinical Care Loop حاکم عبور می‌کند.

ممنوع:

- انتخاب خودکار outcome نهایی؛
- completion خودکار؛
- استفاده از شاهد بیمار یا task دیگر؛
- استفاده از evidence stale یا بدون provenance؛
- کاهش verification contract.

---

## 15. UX هدف

صف‌های اصلی:

```text
کارهای من
صف نقش من
بدون مسئول
در انتظار بیمار
در انتظار نوبت یا نتیجه
نیازمند پزشک
موعدگذشته
```

کارت Work Item:

```text
نام بیمار
دلیل قابل‌فهم
چرا ساخته شده
اقدام بعدی
مسئول/صف نقش
action due و target
آخرین اتفاق
خلاصه SMS/Appointment/Evidence
یک CTA اصلی
```

Timeline باید همهٔ source eventها را با زبان کاربر نمایش دهد. Audit technical details در drawer جداست. کاربر باید بدون ترک Worklist تماس، نتیجه تماس، مشاهده پیام، ساخت نوبت و مرور Timeline را انجام دهد.

---

## 16. Automation Health

صفحهٔ مدیر در FO-9:

```text
scheduler heartbeat
last successful tick
job success/failure
lease owner and age
outbox backlog
oldest pending item
projection lag
stale approval count
SMS unknown/failed
unassigned overdue
dead-letter
automation paused reasons
```

Log به‌تنهایی کافی نیست. Retry فقط برای موارد retryable و با permission/idempotency انجام می‌شود.

---

## 17. Feature Flagها

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

FO-0 آن‌ها را ثبت کرد و همه OFF هستند. هر tranche فقط flag متعلق به خودش را مصرف می‌کند. فعال‌کردن flag در production/pilot نیازمند تصمیم صریح همان tranche است.

---

## 18. برنامهٔ اجرایی Tranche-by-Tranche

### FO-0 — Governance, Baseline & Registration

**Status:** `VALIDATED`

انجام‌شده:

- سند canonical روی main؛
- stream در `PROJECT_STATE.*`؛
- owner و Issue؛
- repository/UI baseline؛
- ابزار read-only aggregate capture؛
- ده flag خاموش؛
- nearest `AGENTS.md`؛
- guard عدم schema/runtime؛
- CI کامل 731 + 54؛
- attestation محیط `TEST_ONLY`.

Exit gate: **PASS**.

### FO-1 — Episode Identity & Append-only Links

**Status:** `AUTHORIZED`

هدف: ساخت identity و روابط مشترک بدون تغییر UI و بدون reaction اتوماتیک.

کارها:

- schema additive/idempotent برای episode/link/event؛
- repositoryهای محدود؛
- identity builder versioned؛
- linker برای admin task، clinical task، encounter commitment، approval، SMS و appointment؛
- dry-run/backfill report؛
- backfill فقط برای روابط قابل‌اثبات؛
- orphan reason codes؛
- rebuild/audit command؛
- flag `FOLLOWUP_EPISODES_ENABLED` همچنان OFF در default.

تست:

- fresh/existing/rerun migration؛
- append-only UPDATE/DELETE guard؛
- deterministic identity/hash؛
- duplicate link idempotency؛
- patient mismatch rejection؛
- source truth unchanged؛
- no UI behavior change؛
- no clinical completion/change؛
- full suite green.

Exit gate:

```text
100% supported synthetic/test sources link or get explicit orphan reason
zero mutation of existing source truths
rebuild deterministic
all new events append-only
feature default OFF
full CI green
```

### FO-2 — Projection, Next Action & Shadow Parity

- projection table/repository؛
- source adapters؛
- central next-action policy؛
- waiting/block reason؛
- role routing proposal؛
- action_due/target؛
- parity report؛
- rebuild and lag metrics.

Flag: `FOLLOWUP_PROJECTION_SHADOW`.

Exit: ≥99% explainable parity، zero hidden item، deterministic hash.

### FO-3 — Read-only Unified Worklist

- read-only page؛
- role/owner/waiting/overdue tabs؛
- one disabled/read-only CTA label؛
- detail drawer and Timeline؛
- deep links؛
- usability telemetry.

Flag: `FOLLOWUP_UNIFIED_WORKLIST_READONLY`.

### FO-4 — Claim, Assignment, Routing & SLA

- atomic claim/release/reassign؛
- role queues؛
- routing policy؛
- SLA state؛
- admin-only bulk operations؛
- stale protection and audit.

Flag: `FOLLOWUP_AUTO_ROUTING`.

### FO-5 — Structured Contact, Retry & Escalation

- contact outcome-driven actions؛
- callback scheduling؛
- attempt policy؛
- unreachable/invalid phone flow؛
- low-click contact UI.

Flag: `FOLLOWUP_STRUCTURED_CONTACT`.

### FO-6 — Governed SMS Automation & Freshness

- policy level per event/template؛
- template versioning؛
- approval expiry؛
- source hash/revision؛
- pre-send revalidation؛
- stale supersession؛
- guarded auto path؛
- audit decision event.

Flag: `FOLLOWUP_SMS_AUTO_GUARDED`.

### FO-7 — Cross-channel Transition & Outbox

- durable outbox؛
- SMS delivery/failure reactions؛
- appointment booked/cancelled/no-show reactions؛
- administrative goal completion؛
- retry/dead-letter.

Flags: `FOLLOWUP_APPOINTMENT_SYNC`, `FOLLOWUP_UNIFIED_WORKLIST_ACTIONS`.

### FO-8 — Clinical Evidence Assist

- contract reader؛
- evidence candidate matcher؛
- provenance UI؛
- human accept/reject؛
- governed completion handoff.

Flag: `FOLLOWUP_EVIDENCE_ASSIST`.

### FO-9 — Automation Health

- heartbeat/job history؛
- outbox/dead-letter؛
- projection lag؛
- stale approval monitor؛
- safe retry controls؛
- operator runbook.

Flag: `FOLLOWUP_AUTOMATION_HEALTH`.

### FO-10 — Pilot, KPI Proof, Cutover & Retirement

- role/cohort محدود؛
- allowlisted SMS only؛
- old/new parity؛
- daily review ابتدا؛
- rollback switch؛
- production baseline قبل از ورود داده واقعی؛
- usability and operational KPI؛
- legacy UI retirement فقط پس از اثبات.

---

## 19. Testing Strategy

### Unit

identity، hash، next action، routing، SLA، contact policy، SMS policy، transition و evidence match.

### Schema/Repository

fresh DB، existing DB، rerun، append-only trigger، unique/idempotency، patient scope، stale head و rollback.

### Integration

source → episode → links/events، rebuild، Scheduler rerun، outbox replay، delivery/appointment transition.

### E2E سناریوها

1. appointment reminder؛
2. delivery then wait؛
3. permanent SMS failure then call؛
4. دو دارو در یک episode؛
5. no-answer/callback/escalation؛
6. wrong phone؛
7. appointment booking؛
8. cancellation؛
9. no-show؛
10. clinical recommendation needing confirmation؛
11. evidence suggested then human confirmed؛
12. duplicate scheduler and fencing؛
13. projection rebuild؛
14. stale approval superseded؛
15. dead-letter retry.

### Regression

هر PR:

```text
focused tests
full Specialist suite
Accounting suite when shared/governance impact exists
migration fresh + copied DB when schema changes
git diff check
CI artifacts
```

---

## 20. Security، Privacy و Reliability

- permission server-side؛
- CSRF برای mutation؛
- no PHI in logs/metrics؛
- actor/time/policy/version audit؛
- consent and phone revalidation؛
- source revision/hash؛
- bounded batches؛
- lease/fencing retained؛
- one bad source does not stop batch؛
- busy timeout and transaction boundary explicit؛
- projection rebuild resumable؛
- no raw clinical payload in generic episode metadata مگر ضرورت قراردادی.

طبقه‌بندی `TEST_ONLY` باعث حذف این guardrailها نمی‌شود؛ فقط baseline محیط فعلی را تعیین می‌کند.

---

## 21. Rollback

سه سطح:

### UI rollback

flag UI جدید OFF؛ UI قدیمی مسیر اصلی می‌ماند.

### Orchestration rollback

action flags OFF؛ Episode/Projection فقط shadow/read-only باقی می‌ماند.

### Data rollback

schema additive retained-but-unused؛ destructive rollback ممنوع. Source truth حذف یا بازنویسی نمی‌شود.

در rollback، pending outbox freeze، auto-SMS OFF و دلیل rollback ثبت می‌شود.

---

## 22. KPIها

```text
100% nonterminal item has action/wait/block
100% item has owner role or explicit unassigned reason
median next-action comprehension ≤ 5 sec
primary action starts ≤ 2 interactions
zero stale SMS
zero duplicate mutation on rerun
zero clinical completion without evidence
zero hidden critical automation failure
≥80% reduction in routine manual SMS approval
unassigned overdue <5% in pilot
reduced navigation and duplicate data entry
```

KPIهای عملیاتی واقعی فقط بعد از ورود محیط pilot قابل‌اندازه‌گیری‌اند. دادهٔ تستی برای اثبات correctness استفاده می‌شود، نه ادعای business impact.

---

## 23. Requirement Registry

### Governance

- `GOV-001`: این سند مرجع اجرایی است.
- `GOV-002`: `PROJECT_STATE.*` مقدم است.
- `GOV-003`: هر PR tranche/requirement/flag/rollback را ذکر کند.
- `GOV-004`: هر تغییر contract نسخه و Decision Log دارد.
- `GOV-005`: طبقه‌بندی داده محیطی و تاریخ اعتبار آن ثبت می‌شود.

### Data

- `DATA-001`: migration additive/idempotent.
- `DATA-002`: Episode حقیقت بالینی نیست.
- `DATA-003`: Event append-only.
- `DATA-004`: Projection rebuildable.
- `DATA-005`: Source link patient-safe.
- `DATA-006`: action_due و target جدا.
- `DATA-007`: no fabricated source relation/event.

### Orchestration

- `ORCH-001`: action/wait/block روشن.
- `ORCH-002`: mutation idempotent.
- `ORCH-003`: role routing مرکزی.
- `ORCH-004`: contact structured.
- `ORCH-005`: cross-channel via outbox.
- `ORCH-006`: retry/escalation versioned.

### SMS

- `SMS-001`: چهار policy level.
- `SMS-002`: auto فقط allowlisted + guarded.
- `SMS-003`: clinician-only never auto.
- `SMS-004`: pre-send freshness.
- `SMS-005`: stale superseded.
- `SMS-006`: consent/quiet/cap/cooldown/idempotency.

### UX

- `UX-001`: یک primary CTA.
- `UX-002`: زبان عملیاتی.
- `UX-003`: Timeline واحد.
- `UX-004`: کاهش navigation.
- `UX-005`: role/waiting/overdue views.
- `UX-006`: blocked reason قابل‌فهم.

### Clinical

- `CLIN-001`: no automated treatment decision.
- `CLIN-002`: no completion without Evidence.
- `CLIN-003`: appointment does not complete clinical task.
- `CLIN-004`: Evidence Assist requires confirmation.
- `CLIN-005`: Rule/Shadow freeze respected.

### Operations/Security

- `OPS-001`: Scheduler health visible.
- `OPS-002`: outbox/dead-letter visible.
- `OPS-003`: no hidden critical failure.
- `OPS-004`: safe retry.
- `SEC-001`: permission/CSRF/stale protection.
- `SEC-002`: no PHI leakage.
- `SEC-003`: policy/version/actor audit.

---

## 24. دفتر پیشرفت

| Tranche | Status | Main commit | PR | Evidence | Notes |
|---|---|---|---|---|---|
| FO-0 | VALIDATED | `901dbfdf9c358ecc09d2a60a0680f6a4a8370d17` | #72 | CI `731 + 54`؛ owner test-only attestation | baseline/governance complete |
| FO-1 | AUTHORIZED | — | — | Issue بعدی | episode/link/event only |
| FO-2 | NOT_STARTED | — | — | — | projection/shadow |
| FO-3 | NOT_STARTED | — | — | — | read-only UX |
| FO-4 | NOT_STARTED | — | — | — | routing/SLA |
| FO-5 | NOT_STARTED | — | — | — | contact outcomes |
| FO-6 | NOT_STARTED | — | — | — | SMS policy/freshness |
| FO-7 | NOT_STARTED | — | — | — | cross-channel/outbox |
| FO-8 | NOT_STARTED | — | — | — | evidence assist |
| FO-9 | NOT_STARTED | — | — | — | health/metrics |
| FO-10 | NOT_STARTED | — | — | — | pilot/cutover |

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

## 25. Decision Log

| ID | تاریخ | تصمیم | وضعیت |
|---|---|---|---|
| DEC-001 | 2026-08-03 | Unified Projection به‌جای بازنویسی Source Truthها | ACCEPTED |
| DEC-002 | 2026-08-03 | role queue پیش از auto-assign فرد | ACCEPTED |
| DEC-003 | 2026-08-03 | چهار سطح SMS review | ACCEPTED_FOR_PLAN |
| DEC-004 | 2026-08-03 | Evidence فقط suggest/prefill؛ completion انسانی | ACCEPTED |
| DEC-005 | 2026-08-03 | durable outbox برای cross-channel | ACCEPTED_FOR_PLAN |
| DEC-006 | 2026-08-03 | legacy UI تا parity حذف نمی‌شود | ACCEPTED |
| DEC-007 | 2026-08-03 | Rule و Shadow خارج از scope | ACCEPTED |
| DEC-008 | 2026-08-03 | محیط فعلی فقط دادهٔ تستی و resettable دارد | OWNER_ATTESTED |
| DEC-009 | 2026-08-03 | در test-only، deterministic synthetic baseline جای snapshot تولیدی را برای FO-0 می‌گیرد | ACCEPTED |
| DEC-010 | 2026-08-03 | FO-0 پس از PR #72 و CI کامل validated است؛ FO-1 مجاز است | ACCEPTED |

---

## 26. دستور شروع هر ایجنت

1. `PROJECT_STATE.md/json` را بخوان؛
2. این سند را کامل بخوان؛
3. نزدیک‌ترین `AGENTS.md` را بخوان؛
4. `main`، PR، Issue، CI و schema را بررسی کن؛
5. tranche و Requirement ID را اعلام کن؛
6. ثابت کن Rule/Shadow/Accounting وارد scope نشده؛
7. branch تازه از `main` بساز؛
8. baseline focused test را اجرا کن؛
9. فقط همان tranche را تغییر بده؛
10. rollback و evidence را در PR ثبت کن؛
11. پس از merge دفتر پیشرفت و Project State را به‌روزرسانی کن.

---

## 27. قدم مجاز فعلی

```text
FO-1 — Episode Identity & Append-only Links
```

FO-2 یا هر UI/automation رفتاری قبل از بسته‌شدن Exit Gate FO-1 ممنوع است.
