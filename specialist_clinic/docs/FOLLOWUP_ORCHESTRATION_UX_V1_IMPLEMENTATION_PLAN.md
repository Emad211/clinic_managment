# Follow-up Orchestration & UX v1 — Canonical Implementation Plan

> **نام فایل مرجع:** `specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md`
>
> **کد برنامه:** `FOUX-V1`
>
> **نسخه:** `1.3.0`
>
> **آخرین بازبینی:** `2026-08-03`
>
> **وضعیت:** `FO_0_VALIDATED / FO_1_VALIDATED / FO_2_VALIDATED / FO_3_AUTHORIZED`
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

در صورت تعارض، منبع پایین‌تر قبل از توسعه اصلاح می‌شود. هر PR باید در body خود مشخص کند:

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

وجود branch یا PR به معنی تکمیل نیست. فقط merge روی `main` همراه با evidence، CI و به‌روزرسانی دفتر پیشرفت معتبر است.

---

## 1. مسئلهٔ محصول

سامانه رویدادها و تسک‌ها را می‌سازد، اما یک پیگیری از دید کاربر میان چند Source of Truth پخش می‌شود:

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

نتیجهٔ UX فعلی:

- اقدام بعدی فوری فهمیده نمی‌شود؛
- مسئول یا صف نقش همیشه روشن نیست؛
- SMS، تماس، نوبت و Task Timeline مشترک ندارند؛
- callback، retry، escalation و closure دستی‌اند؛
- چند source مرتبط زیر reason کلی گم می‌شوند؛
- state فنی به‌جای زبان عملیاتی دیده می‌شود؛
- پزشک ممکن است با کار روتین درگیر شود؛
- سلامت automation برای اپراتور قابل مشاهده نیست.

صورت مسئله:

> هر Work Item باید در چند ثانیه نشان دهد چرا ساخته شده، مسئول آن کیست، منتظر چیست، آخرین اتفاق چه بوده و اقدام بعدی دقیقاً چیست.

---

## 2. طبقه‌بندی داده و Baseline

طبق attestation مالک در تاریخ `2026-08-03`:

```text
Current specialist.db data class = TEST_ONLY
Real patient PHI                 = NOT PRESENT BY OWNER ATTESTATION
Data may be reset/reseeded       = YES
Production-volume inference      = FORBIDDEN
```

این طبقه‌بندی فقط governance محیط فعلی است و نباید shortcut runtime ایجاد کند. پیش از ورود اولین دادهٔ واقعی بیمار:

- production-readiness review؛
- privacy/security review؛
- backup/restore rehearsal؛
- role/consent review؛
- baseline بدون PHI؛
- و بازبینی automation flagها الزامی است.

دادهٔ تستی correctness، migration، parity و usability اولیه را اثبات می‌کند؛ نه KPI تجاری.

---

## 3. اهداف

### 3.1 محصول و UX

- تبدیل Task، SMS، Contact، Appointment و Outcome به Episode قابل‌ردیابی؛
- ساخت Unified Work Item Projection قابل‌بازسازی؛
- محاسبهٔ مرکزی `next_action`، `waiting_reason` و `blocked_reason`؛
- پیشنهاد role مناسب؛
- نمایش یک CTA اصلی؛
- Timeline واحد؛
- کاهش navigation و ورود تکراری داده؛
- کاهش تأیید دستی پیام‌های allowlisted در tranche مربوط؛
- مشاهده‌پذیری سلامت automation.

### 3.2 فنی

- migration additive و idempotent؛
- lineage event append-only؛
- mutation idempotent؛
- Projection deterministic و rebuildable؛
- source revision/fingerprint؛
- stale protection؛
- flag و rollback برای هر tranche؛
- عدم بازنویسی Source of Truthهای موجود.

---

## 4. Anti-goalها

این برنامه نباید:

- workflow builder عمومی مانند n8n بسازد؛
- Rule بالینی تولید یا فعال کند؛
- تشخیص، نسخه، دارو، دوز یا ارجاع را خودکار کند؛
- Recommendation بالینی را بدون انسان بپذیرد؛
- Clinical Task را بدون Evidence تکمیل کند؛
- Consent، quiet hours، cap، cooldown یا idempotency را دور بزند؛
- Episode/Projection را جای Source of Truth بالینی بنشاند؛
- migration destructive ایجاد کند؛
- UI قدیمی را پیش از parity و rollback حذف کند؛
- منطق دامنه را در template/JavaScript پراکنده کند؛
- `clinic_new.db` را از Specialist Clinic mutate کند.

---

## 5. Invariantهای غیرقابل‌مذاکره

1. `followup_tasks` حقیقت تسک اداری باقی می‌ماند.
2. Clinical Task identity/lifecycle حاکم حفظ می‌شود.
3. completion بالینی بدون Evidence معتبر غیرممکن است.
4. Appointment، Clinical Task را complete نمی‌کند.
5. Episode فقط حقیقت رابطه و lineage عملیاتی است.
6. Projection cache/read model است، نه source truth.
7. هر mutation orchestration idempotency key دارد.
8. هر event actor، time، version و content hash دارد.
9. relation یا outcome ساختگی تولید نمی‌شود.
10. ambiguity با orphan/conflict reason ثبت می‌شود.
11. Rule و Hypoglycemia Shadow خارج از scope هستند.
12. flagها default OFF می‌مانند تا tranche مربوط validated شود.
13. فرض `TEST_ONLY` باعث کاهش guardrail نمی‌شود.
14. FO-3 فقط خواندنی است و هیچ mutation جدیدی ندارد.
15. UI قدیمی در FO-3 همچنان مسیر عملیاتی اصلی است.

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
| Appointment | `appointments` | existing workflow |
| Scheduler ownership | `operational_leases` | lease/fencing |
| Durable job result | `operational_job_runs` | idempotent lifecycle |
| Episode identity | `followup_episodes` | immutable — FO-1 |
| Episode-source relation | `followup_episode_links` | immutable — FO-1 |
| Episode lineage event | `followup_episode_events` | append-only — FO-1 |
| Unified shadow read model | `followup_work_item_projection` | disposable/rebuildable cache — FO-2 |

---

## 7. معماری هدف

```text
Existing Source Truths
        ↓
Read Adapters
        ↓
Episode Identity + Source Linker       ← FO-1 validated
        ↓
Append-only Episode Event Stream       ← FO-1 validated
        ↓
Projection / Policy Layer              ← FO-2 validated
  ├─ current source state
  ├─ next action / wait / block
  ├─ action_due / target
  ├─ role proposal
  ├─ parity
  └─ lag / rebuild metrics
        ↓
Read-only Unified Worklist + Timeline  ← FO-3 current
        ↓
Claim/Assignment/Contact/SMS/Outbox/Evidence/Health
```

مسئولیت‌ها:

```text
src/services/followup_orchestration/
  identity.py
  backfill.py
  source_state.py
  next_action_policy.py
  projection_service.py
  read_model_service.py
  timeline_service.py
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

از God Service جلوگیری شود؛ persistence، policy، HTTP و presentation جدا باشند.

---

## 8. FO-1 Contract — Episode Identity & Links

FO-1 validated است.

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

Identity از patient/type/semantic/period/version با JSON canonical و SHA-256 ساخته می‌شود. متن فارسی و state mutable در identity نیست.

### 8.2 Source links

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

هر link patient-safe، immutable و دارای source revision است.

### 8.3 Episode events

FO-1 فقط:

```text
EPISODE_OPENED
SOURCE_LINKED
```

Event stream append-only، linear، idempotent و content-hashed است.

### 8.4 Backfill

- dry-run read-only؛
- explicit apply؛
- aggregate-only output؛
- orphan reason برای ambiguity؛
- no startup backfill؛
- source digest before/after برابر.

### 8.5 Evidence

```text
Issue               = #74
PR                  = #75
Merge               = 15ef1585c069a74c26fbc0ce859e03906e5f475a
Specialist tests    = 736
Accounting tests    = 54
Synthetic Episodes  = 4
Synthetic Links     = 12
Second apply new    = 0
Source digest       = unchanged
```

---

## 9. FO-2 Contract — Projection, Next Action & Shadow Parity

FO-2 validated است.

### 9.1 Projection cache

`followup_work_item_projection` شامل:

```text
episode_id
patient_link_id
episode_type
reason_code / reason_label / why_created
current_state
state_class
next_action_code / label
waiting_reason_code / label
blocked_reason_code / label
owner_role_proposal
owner_user_id = NULL in FO-2
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
state_detail_json
projection_version
policy_version
as_of_at
projection_hash
rebuilt_at
```

Projection disposable و rebuildable است؛ source truth نیست.

### 9.2 State invariant

هر nonterminal item دقیقاً یکی از این حالت‌هاست:

```text
ACTION_REQUIRED
WAITING
BLOCKED
```

و دقیقاً یک explanation دارد:

```text
next_action
waiting_reason
blocked_reason
```

Terminal هیچ action/wait/block و owner proposal ندارد.

### 9.3 Source-state reader

Adapterهای read-only برای همهٔ source typeهای FO-1:

- patient scope دوباره کنترل می‌شود؛
- head lifecycle حاکم خوانده می‌شود؛
- raw PHI، message body، note و clinical value وارد projection نمی‌شود؛
- missing/mismatch/read failure به BLOCKED reason تبدیل می‌شود.

### 9.4 Policy v1

`FOUX-NEXT-ACTION-V1` fail-closed است. نمونه:

```text
pending approval       → REVIEW_SMS
SMS permanent failure  → CALL_PATIENT
scheduled appointment  → WAITING_FOR_APPOINTMENT
cancelled appointment  → REBOOK_APPOINTMENT
no-show                → FOLLOW_UP_NO_SHOW
clinical outcome       → REVIEW_CLINICAL_EVIDENCE
missing/mismatch       → SOURCE_STATE_UNAVAILABLE
wrong number           → CONTACT_DATA_INVALID
terminal source        → TERMINAL
```

Policy فقط state را توصیف می‌کند؛ هیچ actionی اجرا نمی‌کند.

### 9.5 Parity و rebuild

- legacy admin/clinical/commitment open sources شمرده می‌شوند؛
- matched، legacy-only و projection-only reason-code دارند؛
- same source + same as-of → same projection hash؛
- `rebuilt_at` در hash نیست؛
- delete/rebuild باید equivalent باشد؛
- lag و duration metric تولید می‌شود.

### 9.6 CLI و flag

```bash
python specialist_clinic/scripts/rebuild_followup_projection.py \
  --database specialist_clinic/specialist.db \
  --as-of "2026-08-03 12:00:00"

FOLLOWUP_PROJECTION_SHADOW=1 \
python specialist_clinic/scripts/rebuild_followup_projection.py \
  --database specialist_clinic/specialist.db \
  --as-of "2026-08-03 12:00:00" --apply
```

Apply نیازمند flag صریح است. Scheduler/request/UI در FO-2 به projection متصل نشدند.

### 9.7 Evidence

```text
Issue                         = #77
PR                            = #78
Merge                         = 6c6e33203376a32165418e0d3c6f2a4a48253e7b
Final CI run                  = 30773195914
Specialist tests              = 747
Accounting tests              = 54
Canonical projections         = 4
Legacy coverage               = 100%
Hidden legacy sources         = 0
Explainable mismatches        = 100%
Rebuild equivalence           = PASS
Source truth unchanged        = PASS
Missing/patient drift blocked = PASS
```

اجرای اول CI نقص fixture را کشف کرد؛ fixture به schema حاکم lifecycle ارتقا یافت و policy تضعیف نشد. اجرای کامل دوباره سبز شد.

FO-2 Exit Gate: **PASS**.

---

## 10. FO-3 Contract — Read-only Unified Worklist & Timeline

**وضعیت فعلی:** `AUTHORIZED`

FO-3 اولین تغییر قابل‌مشاهده برای کاربر است، اما فقط read-only. UI قدیمی همچنان مسیر انجام کار و Source of Truth عملیاتی است.

### 10.1 Feature flag

```text
FOLLOWUP_UNIFIED_WORKLIST_READONLY
```

Default OFF. وقتی OFF است:

- route جدید نباید در navigation ظاهر شود؛
- Worklist قدیمی بدون تغییر کار می‌کند؛
- هیچ query/rebuild اضافه در request قدیمی اجرا نمی‌شود.

وقتی ON است، فقط route و UI خواندنی جدید قابل مشاهده است. این flag اجازهٔ mutation نمی‌دهد.

### 10.2 Route و authorization

مسیر پیشنهادی:

```text
/followups/unified
/followups/unified/<episode_id>
```

قواعد:

- همان permission مشاهدهٔ Task/Worklist؛
- server-side authorization؛
- pagination و search؛
- filterهای whitelist‌شده؛
- episode متعلق به بیمار معتبر؛
- no POST/mutation endpoint در FO-3؛
- no PHI در log یا query diagnostics.

### 10.3 Read Model Service

UI مستقیم SQL پراکنده اجرا نمی‌کند. Service خواندنی:

```text
projection cache
+ minimum patient identity for list view
+ episode links
+ source summary/deep links
+ timeline events
```

باید:

- بدون N+1 باشد؛
- pagination اجباری داشته باشد؛
- state/role/due/search filter را پشتیبانی کند؛
- Projection missing/stale را به empty/error state قابل‌فهم تبدیل کند؛
- rebuild خودکار در request انجام ندهد؛
- stale projection age را نشان دهد؛
- raw note/message body/clinical payload را در list view نیاورد.

### 10.4 صفحهٔ لیست

Tabs/filters اولیه:

```text
همه
نیازمند اقدام
در انتظار
مسدود
پایان‌یافته
پیشنهاد صف پذیرش
پیشنهاد صف پرستاری
نیازمند پزشک
موعدگذشته
```

در FO-3 «کارهای من» واقعی نیست، چون assignment هنوز FO-4 است. عنوان باید صادقانه `صف پیشنهادی نقش` باشد.

### 10.5 کارت Work Item

هر کارت/ردیف حداقل:

```text
نام بیمار
دلیل قابل‌فهم
چرا ساخته شده
state class
اقدام بعدی یا waiting/block reason
role proposal
زمان اقدام
target time
آخرین رویداد
SMS/Appointment/Evidence summary
source count
projection age
```

CTA اصلی در FO-3 **اجرا نمی‌شود**. فقط label خواندنی یا deep-link به مسیر فعلی حاکم نمایش داده می‌شود:

```text
اقدام پیشنهادی: تماس با بیمار
[بازکردن Worklist فعلی]
```

نباید دکمه‌ای وانمود کند action داخل Unified UI انجام شده است.

### 10.6 Timeline

Timeline ترکیب read-only این منابع است:

```text
Episode opened / source linked
Administrative task created/resolved
Clinical task events
Clinical outcome events
Encounter commitment events
Contact events
Engagement approval state
SMS submission/delivery
Appointment state
```

نمایش Timeline:

- زبان کاربر؛
- ترتیب زمانی deterministic؛
- source type و provenance؛
- deep-link به صفحهٔ حاکم در صورت وجود؛
- hash/ID technical فقط در بخش audit؛
- no free-text sensitive detail مگر permission و نیاز صریح؛
- conflict/missing source به‌صورت warning، نه حذف.

### 10.7 Deep-linkها

FO-3 فقط deep-link می‌دهد:

```text
Worklist قدیمی
پروندهٔ بیمار
صف تأیید پیام
گزارش پیام
نوبت مرتبط
صف/صفحهٔ Clinical Task حاکم
```

هیچ deep-link نباید permission را دور بزند.

### 10.8 UX states

ضروری:

```text
loading
empty
no projection yet
projection stale
blocked/conflict
permission denied
pagination boundary
search no result
```

عبارات فنی مثل enum/hash در متن اصلی نمایش داده نشوند.

### 10.9 Accessibility و RTL

- RTL کامل؛
- keyboard navigation؛
- focus visible؛
- semantic headings/table/list؛
- badge تنها حامل رنگ نباشد؛
- mobile/tablet/desktop؛
- جلالی و اعداد فارسی مطابق conventions؛
- action/wait/block با متن و icon قابل‌تفکیک.

### 10.10 Telemetry اولیه

بدون ذخیرهٔ PHI:

```text
view opened
filter used
episode detail opened
deep-link clicked
projection stale/error viewed
```

Telemetry اختیاری است؛ اگر در FO-3 اضافه شود باید aggregate و فاقد patient identifier در log عمومی باشد. KPI usability می‌تواند در تست دستی ثبت شود.

### 10.11 تست FO-3

- flag OFF → route/navigation unavailable or hidden؛
- flag ON → authorized GET works؛
- no POST/mutation route؛
- no N+1 برای list؛
- pagination/search/filter correctness؛
- role/state/due filters؛
- projection stale/empty/error states؛
- timeline order و source labels؛
- deep-link correctness و permission؛
- RTL/Jalali/fa number؛
- no raw technical state in primary copy؛
- no source mutation؛
- legacy Worklist unchanged؛
- full regression.

### 10.12 Exit Gate FO-3

```text
100% projected items discoverable in read-only UI
zero source/projection mutation from GET routes
legacy Worklist parity preserved
all states have understandable primary copy
all deep-links permission-safe
no critical accessibility defect
no N+1 / pagination required
flag OFF restores exact prior visible behavior
full CI green
manual UX review confirms next action understood rapidly
```

FO-4 و mutationهای ownership تا این gate مسدودند.

---

## 11. State و زبان کاربر

هر nonterminal item یکی از:

```text
ACTION_REQUIRED
WAITING
BLOCKED
```

و دقیقاً یکی از:

```text
next_action
waiting_reason
blocked_reason
```

نمونهٔ copy:

| State فنی | نمایش کاربر |
|---|---|
| pending approval | متن آماده است؛ نیازمند بازبینی مجاز |
| delivered | پیام تحویل شد؛ تا موعد پاسخ منتظر بمانید |
| provider rejected | پیام نرسید؛ با بیمار تماس بگیرید |
| scheduled | نوبت ثبت شده؛ فعلاً اقدامی لازم نیست |
| cancelled | نوبت لغو شد؛ هماهنگی مجدد لازم است |
| evidence missing | برای تکمیل، شاهد معتبر ثبت کنید |

Enum/hash فقط در audit نمایش داده می‌شود.

---

## 12. Routing، Ownership و SLA آینده

ترتیب:

```text
role proposal        FO-2 validated
read-only display    FO-3 current
claim/assignment     FO-4
SLA/escalation       FO-4/FO-5
```

Roleهای هدف:

```text
Reception / Secretary
Nursing
Physician
Manager / Operations
```

Auto-assign فردی تا وجود shift/availability معتبر ممنوع است.

---

## 13. Contact Outcome آینده

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

در FO-5 outcomeها action بعدی را policy-driven می‌کنند. note فقط مکمل است.

---

## 14. SMS Policy آینده

```text
AUTO
AUTO_WITH_GUARDS
REQUIRES_REVIEW
CLINICIAN_ONLY
```

Auto فقط با allowlist، consent، شماره canonical، quiet hours، cap، cooldown، freshness و idempotency مجاز است. `CLINICIAN_ONLY` هرگز auto-send نمی‌شود.

---

## 15. Cross-channel و Outbox آینده

از FO-7:

```text
SMS delivered             → WAITING_PATIENT
SMS permanent failure     → CALL_PATIENT / FIX_CONTACT_DATA
Appointment booked        → WAITING_APPOINTMENT
Appointment cancelled     → REOPEN_ACTION
Appointment no-show       → FOLLOW_UP_REQUIRED
Administrative goal met   → close administrative episode
```

هیچ transitionی Clinical Task را خودکار complete نمی‌کند.

---

## 16. Clinical Evidence Assist آینده

Evidence Assist candidate را پیدا، provenance را نمایش و form را prefill می‌کند. accept/reject و completion انسانی باقی می‌ماند. شاهد stale، بدون provenance یا متعلق به بیمار/task دیگر رد می‌شود.

---

## 17. Automation Health آینده

در FO-9:

```text
scheduler heartbeat
last successful tick
job failures
lease owner and age
outbox backlog
projection lag
stale approvals
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

همه default OFF. وضعیت:

```text
Episode infrastructure          = merged, explicit backfill only
Projection shadow infrastructure= merged, explicit rebuild only
Unified read-only UI            = not implemented yet
Action/mutation flags           = OFF and unused
```

---

## 19. برنامهٔ اجرایی Tranche-by-Tranche

### FO-0 — Governance, Baseline & Registration

**Status:** `VALIDATED`

```text
PR #72 / #73
merge 901dbfdf9c358ecc09d2a60a0680f6a4a8370d17
731 Specialist + 54 Accounting
```

### FO-1 — Episode Identity & Append-only Links

**Status:** `VALIDATED`

```text
Issue #74 / PR #75
merge 15ef1585c069a74c26fbc0ce859e03906e5f475a
736 Specialist + 54 Accounting
4 Episodes / 12 Links / idempotent
```

### FO-2 — Projection, Next Action & Shadow Parity

**Status:** `VALIDATED`

```text
Issue #77 / PR #78
merge 6c6e33203376a32165418e0d3c6f2a4a48253e7b
747 Specialist + 54 Accounting
100% coverage / 0 hidden / deterministic rebuild
```

### FO-3 — Read-only Unified Worklist & Timeline

**Status:** `AUTHORIZED`

- feature-flagged read-only route؛
- list/filter/search/pagination؛
- understandable card copy؛
- role proposal؛
- projection age/stale state؛
- read-only Timeline؛
- permission-safe deep-links؛
- no mutation؛
- legacy Worklist unchanged.

### FO-4 — Claim, Assignment, Routing & SLA

**Status:** `BLOCKED_PENDING_FO_3`

- atomic claim/release/reassign؛
- role queues؛
- assignment؛
- SLA state؛
- audit/stale protection.

### FO-5 — Structured Contact, Retry & Escalation

**Status:** `NOT_STARTED`

### FO-6 — Governed SMS Automation & Freshness

**Status:** `NOT_STARTED`

### FO-7 — Cross-channel Transition & Outbox

**Status:** `NOT_STARTED`

### FO-8 — Clinical Evidence Assist

**Status:** `NOT_STARTED`

### FO-9 — Automation Health

**Status:** `NOT_STARTED`

### FO-10 — Pilot, KPI, Cutover & Legacy Retirement

**Status:** `NOT_STARTED`

---

## 20. Testing Strategy

### Unit

identity/hash، source adapters، projection policy، read model mapping، Timeline mapping، routing، SLA، contact، SMS، transition و evidence match.

### Schema/Repository

fresh/existing/rerun، append-only، idempotency، patient scope، projection rebuild و stale source.

### Integration

source → Episode → Projection → read-only UI، rebuild، delivery/appointment state و source digest.

### E2E هدف

1. appointment reminder؛
2. SMS delivered then wait؛
3. permanent failure then call؛
4. two medications in one Episode؛
5. no-answer/callback/escalation؛
6. wrong phone؛
7. appointment booking؛
8. cancellation؛
9. no-show؛
10. clinical recommendation confirmation؛
11. evidence suggestion؛
12. Scheduler fencing؛
13. projection rebuild؛
14. stale approval؛
15. dead-letter retry.

هر PR:

```text
focused tests
full Specialist suite
Accounting suite when shared/governance impact exists
migration tests when schema changes
git diff check
CI artifacts
```

---

## 21. Security، Privacy و Reliability

- permission server-side؛
- CSRF برای mutationهای آینده؛
- no PHI in logs/aggregate reports؛
- actor/time/policy/version audit؛
- source revision/hash؛
- bounded query/pagination؛
- no N+1؛
- one bad source does not break list؛
- explicit transaction boundaries؛
- projection rebuild resumable؛
- list view حداقل دادهٔ حساس را نمایش می‌دهد.

---

## 22. Rollback

### FO-3 UI rollback

`FOLLOWUP_UNIFIED_WORKLIST_READONLY=0` و route/navigation جدید حذف از دید کاربر؛ Worklist قدیمی بدون تغییر باقی می‌ماند.

### Projection rollback

`FOLLOWUP_PROJECTION_SHADOW=0`؛ cache retained-but-unused یا rebuildable.

### Orchestration rollback

Action flags OFF؛ Source Truth حذف/بازنویسی نمی‌شود.

### Data rollback

Schema additive retained-but-unused؛ destructive rollback ممنوع.

---

## 23. KPIها

```text
100% nonterminal item has action/wait/block
100% item has owner role or explicit reason
median next-action comprehension ≤ 5 sec
primary action starts ≤ 2 interactions after FO-4+
zero stale SMS
zero duplicate mutation
zero clinical completion without evidence
zero hidden critical automation failure
≥80% reduction routine manual SMS approval
unassigned overdue <5% in pilot
reduced navigation and duplicate entry
```

FO-3 فقط discoverability و comprehension را می‌سنجد؛ operational action KPI از trancheهای mutationدار شروع می‌شود.

---

## 24. Requirement Registry

### Governance

- `GOV-001` این سند مرجع اجرایی است.
- `GOV-002` `PROJECT_STATE.*` مقدم است.
- `GOV-003` هر PR tranche/requirement/flag/rollback دارد.
- `GOV-004` هر contract نسخه/evidence دارد.
- `GOV-005` طبقه‌بندی محیط ثبت می‌شود.

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
- `ORCH-007` FO-2 shadow/read-only.
- `ORCH-008` FO-3 UI has no mutation.

### UX

- `UX-001` یک primary action label.
- `UX-002` زبان عملیاتی.
- `UX-003` Timeline واحد.
- `UX-004` کاهش navigation.
- `UX-005` role/waiting/overdue views.
- `UX-006` blocked reason قابل‌فهم.
- `UX-007` read-only UI never implies action completion.
- `UX-008` projection age/stale state visible.
- `UX-009` pagination/accessibility/RTL mandatory.

### SMS

- `SMS-001` چهار policy level.
- `SMS-002` auto فقط allowlisted+guarded.
- `SMS-003` clinician-only never auto.
- `SMS-004` pre-send freshness.
- `SMS-005` stale superseded.
- `SMS-006` consent/quiet/cap/cooldown/idempotency.

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
| FO-1 | VALIDATED | `15ef1585c069a74c26fbc0ce859e03906e5f475a` | #75 | 736 + 54؛ 4 Episodes/12 Links |
| FO-2 | VALIDATED | `6c6e33203376a32165418e0d3c6f2a4a48253e7b` | #78 | 747 + 54؛ 100% parity coverage |
| FO-3 | AUTHORIZED | — | — | read-only UI/Timeline only |
| FO-4 | BLOCKED | — | — | pending FO-3 gate |
| FO-5 | NOT_STARTED | — | — | — |
| FO-6 | NOT_STARTED | — | — | — |
| FO-7 | NOT_STARTED | — | — | — |
| FO-8 | NOT_STARTED | — | — | — |
| FO-9 | NOT_STARTED | — | — | — |
| FO-10 | NOT_STARTED | — | — | — |

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
| DEC-009 | 2026-08-03 | deterministic baseline برای FO-0 | ACCEPTED |
| DEC-010 | 2026-08-03 | FO-0 validated | COMPLETED |
| DEC-011 | 2026-08-03 | Episode identity/link/event بدون reaction | IMPLEMENTED |
| DEC-012 | 2026-08-03 | ambiguity → orphan reason | IMPLEMENTED |
| DEC-013 | 2026-08-03 | FO-1 validated | COMPLETED |
| DEC-014 | 2026-08-03 | Projection fail-closed و deterministic | IMPLEMENTED |
| DEC-015 | 2026-08-03 | owner در FO-2 فقط role proposal | IMPLEMENTED |
| DEC-016 | 2026-08-03 | FO-2 validated؛ FO-3 فقط read-only | ACCEPTED |

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
FO-3 — Read-only Unified Worklist & Timeline
```

FO-4 یا هر mutation ownership/routing پیش از Exit Gate FO-3 ممنوع است.
