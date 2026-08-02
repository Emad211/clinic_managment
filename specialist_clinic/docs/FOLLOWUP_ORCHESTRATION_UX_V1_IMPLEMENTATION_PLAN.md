# Follow-up Orchestration & UX v1 — Canonical Implementation Plan

> **نام فایل مرجع:** `specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md`
>
> **نقش سند:** منبع اصلی اجرای بازطراحی Follow-up، Task، SMS و UX عملیاتی در Specialist Clinic.
>
> **نسخه:** `1.0.0`
>
> **تاریخ:** `2026-08-03`
>
> **وضعیت:** `CANONICAL_PLAN / IMPLEMENTATION_NOT_STARTED`
>
> **دامنه:** فقط `specialist_clinic/`
>
> **خارج از دامنه:** `webapp/`، هرگونه Write به `clinic_new.db`، تغییر محتوای Ruleهای بالینی، توسعهٔ Hypoglycemia Shadow و هرگونه خودکارسازی تصمیم درمانی.

---

## 1. جایگاه حاکمیتی سند

این سند Source of Truth اجرایی جریان Follow-up Orchestration & UX v1 است. `PROJECT_STATE.md` و `PROJECT_STATE.json` همچنان Source of Truth مدیریتی کل مخزن هستند. در صورت تعارض:

1. وضعیت واقعی `main`، schema، migrationها، تست‌ها و CI بررسی شود؛
2. `PROJECT_STATE.*` بر این سند مقدم است؛
3. این سند پیش از ادامهٔ توسعه اصلاح شود؛
4. هیچ رفتار جدیدی صرفاً بر اساس متن گفتگو یا branch قدیمی ساخته نشود.

تمام PRهای این جریان باید در توضیحات خود:

- به این سند لینک دهند؛
- شناسهٔ tranche و Requirementهای مرتبط را ذکر کنند؛
- دامنه، migration، feature flag، تست، rollback و اثر UX را مشخص کنند؛
- ثابت کنند Clinical Safety و مرز suggestion-only نقض نشده است.

نام برنامه:

```text
Follow-up Orchestration & UX v1
```

کد کوتاه برنامه:

```text
FOUX-V1
```

---

## 2. مسئله‌ای که حل می‌کنیم

سامانه در تشخیص رویدادها و ساخت آبجکت‌های عملیاتی توانمند است، اما در هدایت کار تا نتیجه ضعف دارد. یک رویداد ممکن است هم‌زمان در چند منبع جدا ظاهر شود:

```text
followup_tasks
clinical_task_events
encounter_plan_commitments
engagement_approvals
engagement_dispatch
sms_messages
appointments
contact/call logs
clinical_outcome_events
```

کاربر برای فهم یک پیگیری مجبور است بین Worklist، صف تأیید پیامک، پروندهٔ بیمار، صفحهٔ نوبت، وضعیت تحویل SMS و فرم پایان تسک جابه‌جا شود. نتیجه:

- اقدام بعدی روشن نیست؛
- مالک کار مشخص نیست؛
- پیام، تماس، نوبت و تسک به شکل یک Journey واحد دیده نمی‌شوند؛
- کار دستی برای assignment، retry، callback، escalation و closure زیاد است؛
- چند منبع مرتبط زیر یک reason کلی گم می‌شوند؛
- وضعیت‌های فنی به‌جای زبان عملیاتی کاربر نمایش داده می‌شوند؛
- اعتماد کاربر به فعال‌بودن اتوماسیون پایین می‌آید؛
- پزشک ممکن است با کارهای روتین غیرضروری مواجه شود.

صورت مسئلهٔ محصول:

> کاربر باید ظرف چند ثانیه بفهمد این مورد چرا ساخته شده، مسئول آن کیست، منتظر چیست، چه چیزی قبلاً انجام شده و اقدام بعدی دقیقاً چیست.

---

## 3. اهداف

### 3.1 هدف محصول

تبدیل مجموعهٔ پراکندهٔ Task، SMS، Contact، Appointment و Outcome به یک Journey قابل‌ردیابی و یک Work Item قابل‌اقدام.

### 3.2 هدف UX

هر Work Item در نمای اصلی باید حداکثر این موارد را نشان دهد:

```text
چه کسی؟
چرا؟
اهمیت و موعد؟
مسئول؟
آخرین اتفاق؟
منتظر چه چیزی است؟
اقدام بعدی چیست؟
```

برای هر ردیف فقط یک CTA اصلی نمایش داده شود. اقدامات ثانویه داخل منوی جزئیات یا پنل Timeline قرار گیرند.

### 3.3 هدف عملیاتی

- auto-routing به صف نقش مناسب؛
- کاهش کارهای بدون مسئول؛
- retry و escalation سیاست‌محور؛
- اتصال دوطرفهٔ SMS، Appointment و Follow-up؛
- بسته‌شدن خودکار کارهای اداری فقط پس از تحقق outcome تعریف‌شده؛
- عدم بسته‌شدن خودکار Clinical Task بدون Evidence و transition معتبر.

### 3.4 هدف فنی

ساخت یک orchestration layer قابل‌ممیزی، idempotent، rebuildable و feature-flagged بدون جایگزینی Source of Truthهای حاکم موجود.

---

## 4. Anti-goals

این برنامه نباید:

- یک n8n یا workflow builder عمومی بسازد؛
- Ruleهای بالینی جدید تولید یا فعال کند؛
- تشخیص، نسخه، تغییر دارو یا تغییر دوز را خودکار کند؛
- Recommendation بالینی را بدون تصمیم انسان قبول کند؛
- Clinical Task را بدون Evidence کامل کند؛
- Consent، quiet hours، daily cap یا provider guardrail را دور بزند؛
- دادهٔ بالینی append-only را با UPDATE/DELETE تغییر دهد؛
- `webapp/` یا `clinic_new.db` را mutate کند؛
- migration بزرگ و غیرقابل rollback بسازد؛
- UI قدیمی را پیش از اثبات parity حذف کند؛
- منطق بالینی را در template، route یا JavaScript پخش کند.

---

## 5. اصول ثابت معماری

### 5.1 Source of Truthها حفظ می‌شوند

Sourceهای فعلی حذف نمی‌شوند. لایهٔ جدید آن‌ها را به Episode متصل و به Projection تبدیل می‌کند:

```text
Administrative follow-up truth → followup_tasks
Clinical task truth            → clinical_task_events + outcome events
Encounter commitment truth     → encounter plan commitment events
SMS truth                      → engagement approvals + sms_messages
Appointment truth              → appointments
```

### 5.2 Episode حقیقت عملیاتی رابط است، نه حقیقت بالینی

Episode فقط روابط، وضعیت عملیاتی، مالکیت، انتظار و اقدام بعدی را هماهنگ می‌کند. Episode حق ندارد نتیجهٔ Rule، تصمیم پزشک یا Evidence بالینی را بازنویسی کند.

### 5.3 همهٔ mutationهای orchestration باید idempotent باشند

هر action باید `idempotency_key` پایدار داشته باشد. rerun Scheduler، refresh صفحه، double-click و اجرای هم‌زمان چند process نباید mutation تکراری تولید کند.

### 5.4 Projection قابل بازسازی است

`followup_work_item_projection` cache/read model است. حذف و rebuild آن از Sourceها و eventها باید نتیجهٔ معادل تولید کند.

### 5.5 Clinical Safety مقدم بر UX convenience است

در موارد بالینی، UX می‌تواند Evidence را پیدا و فرم را prefill کند، ولی تصمیم، confirmation و completion همچنان از contract حاکم care loop پیروی می‌کند.

### 5.6 تغییرات با feature flag و shadow mode وارد می‌شوند

هیچ cutover مستقیم وجود ندارد. مسیر جدید ابتدا فقط projection می‌سازد، سپس read-only نمایش می‌دهد، بعد mutation محدود و در پایان pilot انجام می‌شود.

---

## 6. معماری هدف

```text
Existing Sources
  ├─ followup_tasks
  ├─ clinical_task_events
  ├─ encounter_plan_commitments
  ├─ engagement_approvals
  ├─ engagement_dispatch
  ├─ sms_messages
  ├─ appointments
  ├─ contact events
  └─ clinical outcomes
          ↓
Source Adapters
          ↓
Follow-up Episode Linker
          ↓
Episode Event Stream
          ↓
Orchestration Policy Engine
  ├─ next action
  ├─ waiting reason
  ├─ role routing
  ├─ SLA
  ├─ retry
  ├─ escalation
  └─ closure suggestion/action
          ↓
Unified Work Item Projection
          ↓
Worklist / Patient Timeline / Automation Health UI
```

### 6.1 اجزای پیشنهادی

```text
src/services/followup_orchestration/
  episode_service.py
  source_linker.py
  projection_service.py
  next_action_policy.py
  routing_policy.py
  sla_policy.py
  contact_outcome_service.py
  sms_transition_service.py
  appointment_transition_service.py
  evidence_assist_service.py
  outbox_dispatcher.py
  health_service.py

src/adapters/sqlite/
  followup_episode_repo.py
  followup_episode_event_repo.py
  followup_projection_repo.py
  contact_attempt_repo.py
  operational_outbox_repo.py
```

نام‌ها در زمان implementation می‌توانند با سبک موجود repo هماهنگ شوند، اما مسئولیت‌ها نباید در یک God Service ادغام شوند.

---

## 7. مدل دادهٔ پیشنهادی

تمام migrationها additive و idempotent باشند.

### 7.1 `followup_episodes`

هویت پایدار Journey:

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
```

قواعد:

- یک episode برای یک patient + semantic purpose + period؛
- reason کلی مانند `refill` به‌تنهایی identity نیست؛
- episode می‌تواند چند source child داشته باشد؛
- closure باید outcome/disposition معتبر داشته باشد؛
- clinical episode نباید source truth بالینی را جایگزین کند.

### 7.2 `followup_episode_links`

اتصال منابع:

```text
id
episode_id
source_type
source_id
source_revision
relation_type
is_current
linked_at
content_hash
```

نمونهٔ source type:

```text
ADMIN_TASK
CLINICAL_TASK
ENCOUNTER_COMMITMENT
ENGAGEMENT_APPROVAL
SMS_MESSAGE
APPOINTMENT
CONTACT_ATTEMPT
CLINICAL_OUTCOME
```

### 7.3 `followup_episode_events`

event stream append-only:

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

رویدادهای اولیه:

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

UPDATE و DELETE برای eventها ممنوع باشد.

### 7.4 `followup_work_item_projection`

read model:

```text
episode_id
patient_link_id
patient_name
national_id
phone_number
episode_type
reason_label
why_created
current_state
next_action_code
next_action_label
primary_cta
waiting_reason
owner_role
owner_user_id
priority
sla_status
action_due_at
target_at
last_activity_at
last_activity_label
related_sms_state
related_appointment_state
related_evidence_state
open_child_count
blocked_reason
projection_version
projected_at
```

Invariant:

> هر Work Item غیرterminal باید `next_action_code` داشته باشد یا یک `waiting_reason`/`blocked_reason` صریح ارائه کند.

### 7.5 `contact_attempt_events`

نتیجهٔ تماس ساختاری:

```text
id
episode_id
patient_link_id
channel
outcome_code
attempt_number
callback_at
actor_user_id
started_at
finished_at
note
idempotency_key
```

Outcomeهای نسخهٔ اول:

```text
REACHED_APPOINTMENT_BOOKED
REACHED_CALLBACK_REQUESTED
REACHED_INFORMATION_PROVIDED
REACHED_DECLINED
NO_ANSWER
BUSY
PHONE_INVALID
UNREACHABLE
ESCALATED_TO_NURSE
ESCALATED_TO_DOCTOR
OTHER
```

### 7.6 `operational_outbox`

برای انتقال قابل‌اعتماد eventهای متقاطع:

```text
id
topic
aggregate_type
aggregate_id
payload_json
idempotency_key
status
attempt_count
available_at
claimed_at
processed_at
last_error
created_at
```

هدف: جلوگیری از dual-write ناقص میان Task، SMS، Appointment و Episode.

---

## 8. قرارداد زمان و موعد

دو مفهوم باید جدا شوند:

```text
action_due_at
زمانی که کاربر باید اقدام کند

target_at
زمان رویداد واقعی مانند نوبت، اتمام دارو یا موعد آزمایش
```

UI نباید این دو را با هم نمایش دهد. نمونه:

```text
اقدام امروز: تماس با بیمار
هدف: نوبت چهار روز دیگر
```

SLA از `action_due_at` محاسبه می‌شود؛ متن و urgency بالینی نباید از target date استنباط پراکنده کند.

---

## 9. قرارداد مالکیت و Routing

### 9.1 owner role

نسخهٔ اول:

```text
RECEPTION
NURSE
DOCTOR
MANAGER
```

### 9.2 routing پیش‌فرض

```text
appointment reminder / reschedule / lapsed administrative
→ RECEPTION

refill coordination / measurement follow-up / education / lab coordination
→ NURSE

clinical decision / high-risk escalation / recommendation approval
→ DOCTOR

provider failure / policy conflict / dead-letter / configuration issue
→ MANAGER
```

### 9.3 تفاوت role queue و person assignment

- سیستم می‌تواند episode را خودکار به یک role queue route کند؛
- auto-assignment به یک user مشخص فقط وقتی مجاز است که availability/shift policy معتبر وجود داشته باشد؛
- تا آن زمان user از صف نقش، item را claim می‌کند؛
- claim باید atomic و دارای stale protection باشد؛
- manager می‌تواند reassign کند و دلیل reassign در event stream ثبت شود.

---

## 10. قرارداد Next Action

`next_action` از یک policy مرکزی تولید می‌شود، نه از template یا routeهای مختلف.

نمونه‌ها:

```text
SMS_REVIEW_REQUIRED
SEND_ROUTINE_SMS
CALL_PATIENT
BOOK_APPOINTMENT
WAIT_FOR_APPOINTMENT
WAIT_FOR_PATIENT_RESPONSE
FIX_CONTACT_DATA
RETRY_SMS
REVIEW_CLINICAL_RECOMMENDATION
CONFIRM_MATCHED_EVIDENCE
RECORD_CONTACT_OUTCOME
MANAGER_REVIEW
NO_ACTION_WAITING
```

هر code باید داشته باشد:

```text
label_fa
eligible_roles
primary_cta
route_name/action endpoint
preconditions
postconditions
idempotency contract
```

UI فقط label و CTA را از projection دریافت می‌کند و نباید منطق مستقل تصمیم‌گیری داشته باشد.

---

## 11. قرارداد SMS Automation

چهار policy level:

```text
AUTO
AUTO_WITH_GUARDS
REQUIRES_REVIEW
CLINICIAN_ONLY
```

### 11.1 `AUTO`

فقط برای پیام‌های کاملاً سیستمی و فاقد محتوای شخصی/بالینی، در صورت تصویب صریح product policy. استفاده در v1 محدود بماند.

### 11.2 `AUTO_WITH_GUARDS`

برای templateهای allowlisted روتین مانند یادآوری نوبت و هماهنگی عمومی:

- Consent فعلی؛
- purpose صحیح؛
- شمارهٔ canonical؛
- quiet hours؛
- daily cap؛
- cooldown؛
- idempotency؛
- source freshness؛
- template version؛
- provider readiness.

### 11.3 `REQUIRES_REVIEW`

برای پیام‌های شخصی‌سازی‌شده، استثنایی یا دارای ریسک سوءبرداشت. approval باید expiry و source revision داشته باشد.

### 11.4 `CLINICIAN_ONLY`

برای هر پیام دارای Recommendation، interpretation یا محتوای تصمیم‌ساز بالینی. این سطح هرگز به ارسال خودکار تبدیل نمی‌شود.

### 11.5 stale revalidation

قبل از ارسال، دوباره بررسی شود:

```text
appointment still active?
source event still due?
patient phone unchanged/valid?
consent still allowed?
template version current?
approval not expired?
message content hash unchanged?
```

در صورت stale:

```text
approval/message candidate → SUPERSEDED
هیچ ارسال انجام نشود
episode projection → next action جدید
```

---

## 12. قرارداد Contact Outcome Automation

ثبت نتیجه تماس باید actionهای downstream را اتمیک و idempotent تولید کند.

نمونه:

```text
NO_ANSWER
→ attempt_count + 1
→ callback according to policy
→ optional routine SMS if allowed
→ after threshold escalate to UNREACHABLE workflow

PHONE_INVALID
→ stop SMS
→ FIX_CONTACT_DATA
→ route to RECEPTION

REACHED_APPOINTMENT_BOOKED
→ link appointment
→ move episode to waiting for visit
→ administrative contact goal met

REACHED_CALLBACK_REQUESTED
→ set callback_at
→ next action becomes WAIT/CALL_AT_TIME

ESCALATED_TO_DOCTOR
→ route to DOCTOR
→ record explicit reason
```

هیچ outcome متنی آزاد نباید به‌تنهایی اتوماسیون مهم اجرا کند؛ note فقط مکمل structured code است.

---

## 13. قرارداد Appointment Synchronization

### 13.1 booking

ساخت نوبت از یک Work Item:

- appointment به episode link شود؛
- administrative coordination می‌تواند goal-met شود؛
- episode به `WAITING_FOR_APPOINTMENT` برود؛
- Clinical Task فقط event `SCHEDULED` بگیرد و کامل نشود.

### 13.2 cancellation

لغو نوبت:

- waiting state پایان یابد؛
- next action دوباره محاسبه شود؛
- در صورت policy، تماس یا rebooking ایجاد شود؛
- SMS قدیمی مربوط به نوبت لغوشده stale شود.

### 13.3 no-show

No-show:

- episode دوباره فعال شود؛
- routing براساس policy انجام شود؛
- attempt count و previous history در اولویت‌بندی لحاظ شود؛
- هیچ clinical conclusion از no-show تولید نشود.

---

## 14. قرارداد Clinical Evidence Assist

این قابلیت فقط assistive است:

1. outcome/evidence موردنیاز Clinical Task خوانده شود؛
2. Fact، lab، vital یا appointment outcomeهای جدید جست‌وجو شوند؛
3. matchهای ممکن با provenance و confidence توضیح‌پذیر پیشنهاد شوند؛
4. کاربر مجاز match را تأیید یا رد کند؛
5. transition حاکم Clinical Care Loop اجرا شود.

ممنوع:

- تکمیل خودکار Clinical Task؛
- ساخت Evidence جعلی؛
- استفاده از outcome متعلق به بیمار یا task دیگر؛
- تغییر Fact تاریخی؛
- قبول Recommendation بدون clinician decision.

---

## 15. UX هدف

### 15.1 نمای اصلی

Tabهای اولیه:

```text
کارهای من
صف نقش من
بدون مسئول
در انتظار بیمار
در انتظار نوبت/نتیجه
نیازمند پزشک
موعدگذشته
```

### 15.2 کارت Work Item

حداقل محتوا:

```text
نام بیمار
دلیل قابل‌فهم
اقدام بعدی
مسئول یا صف نقش
action due و target
آخرین رویداد
خلاصه وضعیت SMS/Appointment/Evidence
CTA اصلی
```

نمونه:

```text
علی رضایی
تمدید دو دارو تا سه روز آینده

اقدام بعدی: امروز با بیمار تماس بگیرید
مسئول: صف پرستاری — بدون دریافت‌کننده
آخرین اتفاق: پیامک دیروز تحویل شد

[شروع تماس] [جزئیات]
```

### 15.3 Timeline

تمام source eventها در یک timeline با زبان کاربر:

```text
موعد شناسایی شد
پیام آماده شد
پیام ارسال شد
پیام تحویل شد
تماس ناموفق بود
تماس مجدد زمان‌بندی شد
نوبت ثبت شد
```

شناسه‌ها، hashها و stateهای فنی فقط در بخش audit/debug نمایش داده شوند.

### 15.4 یک CTA اصلی

در هر لحظه فقط یک primary CTA. Secondary actionها:

```text
مشاهده پرونده
مشاهده پیام
تغییر مسئول
تعویق
ثبت خطا
مشاهده audit
```

در overflow یا detail drawer قرار گیرند.

### 15.5 کاهش navigation

کاربر باید بدون خروج از Worklist بتواند:

- شماره و اطلاعات ضروری بیمار را ببیند؛
- تماس را شروع و نتیجه را ثبت کند؛
- پیام و delivery را ببیند؛
- نوبت بسازد یا به نوبت مرتبط برود؛
- child sourceها را ببیند؛
- Timeline را مرور کند.

---

## 16. Automation Health

صفحهٔ مدیر باید نشان دهد:

```text
scheduler last heartbeat
last successful tick
job success/failure by name
lease owner and age
outbox backlog
oldest pending outbox
projection lag
stale approval count
SMS pending/unknown/failed
dead-letter items
unassigned overdue items
automation paused reasons
```

هر failure مهم باید در UI قابل مشاهده باشد؛ log تنها کافی نیست.

Admin actionهای مجاز:

```text
retry retryable item
rebuild projection
pause/resume operational policy
inspect dead-letter
reassign work
mark source entered-in-error through governed path
```

Admin action نباید guardrail یا clinical safety را bypass کند.

---

## 17. Feature Flagها

حداقل flagها:

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

همه در ابتدا OFF. Shadow flag می‌تواند فقط projection تولید و parity گزارش کند.

---

## 18. برنامهٔ اجرایی Tranche-by-Tranche

## FO-0 — Governance, Baseline & Registration

### هدف

ثبت رسمی برنامه بدون تغییر رفتار runtime.

### کارها

- merge این سند؛
- ثبت stream در `PROJECT_STATE.md/json`؛
- ثبت owner و status؛
- baseline از flowهای فعلی، click count، open task، unassigned، approval و failure؛
- فهرست Source of Truthها و invariantها؛
- اضافه‌کردن feature flagهای خاموش؛
- test guard برای جلوگیری از bypass مرزها.

### تست

- docs consistency؛
- flags default OFF؛
- هیچ schema/runtime behavior change؛
- full existing suite green.

### Exit gate

- سند روی main؛
- baseline report ذخیره؛
- PROJECT_STATE هماهنگ؛
- تمام flagها OFF؛
- CI سبز.

### Rollback

حذف registration و flagهای unused؛ بدون data rollback.

---

## FO-1 — Episode Identity & Append-only Links

### هدف

ایجاد هویت Journey و اتصال sourceها بدون تغییر UI و رفتار موجود.

### کارها

- schemaهای `followup_episodes`, `followup_episode_links`, `followup_episode_events`؛
- repositoryهای append-only؛
- semantic identity contract؛
- linker برای admin task، clinical task، commitment، approval، SMS و appointment؛
- backfill idempotent برای دادهٔ موجود؛
- rebuild command و audit report.

### تست

- migration idempotency؛
- duplicate source link rejected/ignored safely؛
- patient mismatch rejected؛
- event UPDATE/DELETE blocked؛
- backfill repeat produces no duplicates؛
- source truth unchanged.

### Exit gate

- 100% sourceهای pilot قابل link؛
- zero mutation در source truth؛
- rebuild deterministic؛
- full suite green.

### Flag

`FOLLOWUP_EPISODES_ENABLED`

---

## FO-2 — Projection, Next Action & Shadow Parity

### هدف

ساخت Unified Work Item Projection در shadow mode.

### کارها

- projection schema/repository؛
- adapterهای source state؛
- policy مرکزی next action؛
- waiting/block reason؛
- action_due/target separation؛
- default role routing؛
- parity report با Worklist فعلی؛
- rebuild and lag metrics.

### تست

- deterministic projection؛
- same inputs → same projection hash؛
- every nonterminal item has action/wait/block؛
- clinical state mapping does not relax rules؛
- stale source invalidates projection؛
- shadow does not mutate operational state.

### Exit gate

- ≥99% explainable parity برای موارد موجود؛
- تمام mismatchها طبقه‌بندی؛
- zero hidden item؛
- performance مناسب dataset هدف.

### Flag

`FOLLOWUP_PROJECTION_SHADOW`

---

## FO-3 — Read-only Unified Worklist & Timeline

### هدف

نمایش projection بدون mutation جدید.

### کارها

- صفحه Worklist جدید؛
- tabs نقش/owner/waiting/overdue؛
- card با CTA label غیرفعال/read-only؛
- detail drawer؛
- unified timeline؛
- deep links به source pages؛
- UX telemetry برای click و time-to-understand.

### تست

- authorization؛
- RTL، جلالی، accessibility؛
- no source mutation؛
- empty/error/loading state؛
- pagination/search؛
- source links correct.

### Exit gate

- کاربران pilot همه موارد خود را پیدا کنند؛
- هیچ discrepancy بحرانی با UI قدیمی؛
- median task understanding ≤ 5 sec در تست usability؛
- main CTA قابل تشخیص.

### Flag

`FOLLOWUP_UNIFIED_WORKLIST_READONLY`

---

## FO-4 — Claim, Assignment, Routing & SLA

### هدف

مالکیت واضح و کاهش موارد بدون مسئول.

### کارها

- atomic claim/release/reassign؛
- role queues؛
- routing policy؛
- SLA state؛
- bulk claim/assign فقط برای admin work؛
- audit actor/reason؛
- stale form protection.

### تست

- concurrent claim فقط یک winner؛
- unauthorized assignment rejected؛
- clinical role boundary؛
- reassignment audit؛
- SLA timezone correct؛
- rerun idempotent.

### Exit gate

- 100% item دارای owner role یا blocked reason؛
- unassigned overdue در pilot <5%؛
- zero silent reassignment.

### Flag

`FOLLOWUP_AUTO_ROUTING`

---

## FO-5 — Structured Contact, Retry & Escalation

### هدف

حذف reliance بر call_log متنی و خودکارسازی follow-up بعد از تماس.

### کارها

- structured outcomes؛
- contact attempt timeline؛
- callback scheduling؛
- attempt policy؛
- unreachable escalation؛
- phone invalid workflow؛
- CTA تماس و فرم کم‌کلیک؛
- note اختیاری.

### تست

- each outcome produces expected next action؛
- duplicate submit idempotent؛
- callback future validation؛
- attempt threshold؛
- escalation route؛
- clinical escalation creates no clinical decision.

### Exit gate

- ≥90% تماس‌های pilot با structured outcome؛
- manual rescheduling به‌طور محسوس کاهش یابد؛
- هیچ callback گم‌شده.

### Flag

`FOLLOWUP_STRUCTURED_CONTACT`

---

## FO-6 — Governed SMS Automation & Freshness

### هدف

ارسال خودکار پیام‌های روتین allowlisted و حفظ review برای موارد حساس.

### کارها

- policy level per template/event؛
- template versioning؛
- approval expiry؛
- source revision/hash؛
- pre-send revalidation؛
- stale supersession؛
- auto guarded path؛
- manager configuration UI محدود؛
- audit decision event.

### تست

- consent denied؛
- quiet hours؛
- cap/cooldown؛
- stale appointment/refill؛
- changed phone/template؛
- duplicate scheduler run؛
- clinician-only never auto-sends؛
- provider failure safe.

### Exit gate

- zero stale message sent؛
- zero duplicate SMS؛
- ≥80% کاهش approval دستی templateهای روتین allowlisted؛
- تمام ارسال‌ها audit trail کامل.

### Flag

`FOLLOWUP_SMS_AUTO_GUARDED`

---

## FO-7 — Cross-channel Transitions & Outbox

### هدف

همگام‌سازی قابل‌اعتماد SMS، Appointment و Work Item.

### کارها

- operational outbox؛
- SMS delivered/failed transition؛
- permanent failure → call/fix contact؛
- appointment booked/cancelled/no-show transitions؛
- wait state؛
- administrative goal completion؛
- retry/dead-letter.

### تست

- transaction failure recovery؛
- outbox duplicate processing؛
- permanent vs retryable SMS؛
- booking/cancel/no-show؛
- clinical task not auto-completed؛
- dead-letter visible.

### Exit gate

- no cross-channel lost transition؛
- outbox replay safe؛
- delivery/appointment state reflected within SLA؛
- rollback rehearsed.

### Flags

`FOLLOWUP_APPOINTMENT_SYNC`, `FOLLOWUP_UNIFIED_WORKLIST_ACTIONS`

---

## FO-8 — Clinical Evidence Assist

### هدف

کاهش ورود دستی Evidence بدون کاهش ایمنی.

### کارها

- contract reader؛
- candidate matcher؛
- provenance UI؛
- accept/reject match؛
- governed completion handoff؛
- mismatch explanation.

### تست

- wrong patient/task rejected؛
- missing provenance rejected؛
- stale evidence rejected؛
- no auto completion؛
- permission checks؛
- outcome reuse constraints.

### Exit gate

- zero clinical completion without explicit confirmation؛
- measurable reduction in duplicate data entry؛
- clinical reviewers approve UX and audit.

### Flag

`FOLLOWUP_EVIDENCE_ASSIST`

---

## FO-9 — Automation Health & Operational Control

### هدف

قابل‌مشاهده‌کردن سلامت اتوماسیون.

### کارها

- scheduler heartbeat؛
- job history projection؛
- outbox/dead-letter dashboard؛
- projection lag؛
- stale approval monitor؛
- safe retry controls؛
- admin alerts؛
- runbook.

### تست

- job failure appears in UI؛
- stale heartbeat detected؛
- retry permission/idempotency؛
- no guardrail bypass؛
- rebuild audit.

### Exit gate

- zero hidden critical automation failure؛
- operator can identify failure cause and next step؛
- recovery rehearsal passed.

### Flag

`FOLLOWUP_AUTOMATION_HEALTH`

---

## FO-10 — Pilot, KPI Proof, Cutover & Legacy Retirement

### هدف

اثبات ارزش و cutover کنترل‌شده.

### Pilot

- ابتدا role محدود و patient cohort محدود؛
- auto SMS فقط templateهای allowlisted؛
- daily review در شروع؛
- rollback switch آماده؛
- old and new UI parity monitoring.

### KPIها

```text
100% open items have next action/wait/block
100% items have owner role or explicit unassigned reason
median time to identify next action ≤ 5 seconds
primary action starts in ≤ 2 interactions
zero stale SMS sent
zero duplicate mutation on scheduler rerun
zero clinical completion without evidence
zero hidden critical automation failure
≥80% reduction in routine SMS manual approval
unassigned overdue <5% in pilot
reduction in navigation between screens
reduction in manual callback scheduling
```

### Cutover gate

- KPI threshold met؛
- security review؛
- clinical safety review؛
- migration/rebuild rehearsal؛
- rollback rehearsal؛
- full suite and CI green؛
- user acceptance signed؛
- PROJECT_STATE updated.

### Legacy retirement

UI قدیمی ابتدا read-only compatibility mode، سپس با evidence حذف می‌شود. Source tables تا زمان migration مستقل و تصمیم حاکمیتی حذف نمی‌شوند.

---

## 19. Testing Strategy

### 19.1 Unit

- identity؛
- next action؛
- routing؛
- SLA؛
- SMS policy؛
- contact outcome؛
- appointment transition؛
- evidence matcher.

### 19.2 Repository/schema

- migration idempotency؛
- append-only triggers؛
- unique/idempotency constraints؛
- foreign patient/source rejection؛
- concurrency and stale event.

### 19.3 Service integration

- source → episode → projection؛
- scheduler rerun؛
- outbox replay؛
- SMS provider states؛
- booking/cancel/no-show؛
- contact retry/escalation.

### 19.4 End-to-end scenarios

1. appointment reminder auto guarded SMS؛
2. SMS delivered then wait؛
3. SMS permanent failure then call task؛
4. refill with two medications aggregated in one episode؛
5. no answer then callback then escalation؛
6. invalid phone then reception correction؛
7. appointment booked from work item؛
8. appointment cancelled then re-open action؛
9. no-show then follow-up؛
10. clinical recommendation requiring confirmation؛
11. clinical evidence suggested and human-confirmed؛
12. scheduler duplicate instance and lease fencing؛
13. projection rebuild؛
14. stale approval superseded؛
15. outbox dead-letter and safe retry.

### 19.5 UX tests

- role-based usability؛
- time to identify next action؛
- click count؛
- wrong-action rate؛
- RTL/mobile/desktop؛
- keyboard and accessibility؛
- error recovery comprehension.

### 19.6 Full regression

هر tranche پیش از merge:

- focused tests؛
- full Specialist Clinic suite؛
- accounting suite در صورت shared-file impact؛
- migration from clean and copied DB؛
- `git diff --check`؛
- CI artifacts retained.

---

## 20. Security, Privacy & Audit

- least privilege per role؛
- CSRF برای تمام mutationها؛
- no PHI in application logs؛
- immutable actor/time/idempotency trail؛
- permission checks server-side؛
- phone and consent revalidation؛
- source hash/revision؛
- no raw clinical payload in generic episode metadata unless necessary؛
- sensitive detail redaction in list view؛
- audit view access محدود؛
- all automation decisions record policy/version/reason.

---

## 21. Performance & Reliability Targets

- Worklist initial query بدون N+1؛
- projection indexed by owner role/user, state, due, patient؛
- pagination اجباری؛
- scheduler/outbox batch bounded؛
- lease/fencing retained؛
- projection lag قابل اندازه‌گیری؛
- rebuild resumable؛
- failure isolation per episode؛
- one bad source must not stop entire batch؛
- database busy timeout and transaction boundaries explicit.

---

## 22. Rollback Strategy

سه سطح rollback:

### UI rollback

flag نمای جدید OFF؛ UI قدیمی باقی می‌ماند.

### Orchestration rollback

action flags OFF؛ episode/projection فقط read-only/shadow می‌ماند.

### Data rollback

چون schema additive است، tables جدید می‌توانند retained but unused باشند. Source truth rollback نمی‌شود. migration destructive ممنوع است.

در rollback:

- pending outbox مشخص و freeze شود؛
- auto SMS خاموش شود؛
- existing SMS/provider reconciliation ادامه یابد؛
- هیچ Clinical Task یا event حذف نشود؛
- rollback event و علت در PROJECT_STATE/PR ثبت شود.

---

## 23. Requirement Registry

### Governance

- `GOV-001` این سند مرجع اجرایی است.
- `GOV-002` PROJECT_STATE مقدم است.
- `GOV-003` هر PR tranche/requirement/flag/rollback را ذکر کند.
- `GOV-004` تغییر رفتار پیش از FO-0 ممنوع است.

### Data

- `DATA-001` migrationها additive/idempotent باشند.
- `DATA-002` episode source truth بالینی نیست.
- `DATA-003` eventها append-only باشند.
- `DATA-004` projection rebuildable باشد.
- `DATA-005` source links patient-safe باشند.
- `DATA-006` action_due و target جدا باشند.

### Orchestration

- `ORCH-001` هر item اقدام/انتظار/مانع روشن دارد.
- `ORCH-002` mutationها idempotent هستند.
- `ORCH-003` role routing مرکزی است.
- `ORCH-004` contact outcomes ساختاری‌اند.
- `ORCH-005` cross-channel transitions از outbox استفاده می‌کنند.
- `ORCH-006` retry/escalation policy-versioned است.

### SMS

- `SMS-001` چهار policy level وجود دارد.
- `SMS-002` auto-send فقط allowlisted + guarded است.
- `SMS-003` clinician-only هرگز auto-send نمی‌شود.
- `SMS-004` pre-send freshness اجباری است.
- `SMS-005` stale candidate superseded می‌شود.
- `SMS-006` consent/quiet/cap/cooldown/idempotency اجباری‌اند.

### UX

- `UX-001` یک primary CTA برای هر item.
- `UX-002` زبان عملیاتی جای state فنی را می‌گیرد.
- `UX-003` Timeline یکپارچه است.
- `UX-004` کار اصلی بدون navigation غیرضروری انجام می‌شود.
- `UX-005` role/waiting/overdue views وجود دارد.
- `UX-006` error/blocked reason قابل‌فهم است.

### Clinical

- `CLIN-001` هیچ تصمیم درمانی خودکار نمی‌شود.
- `CLIN-002` Clinical Task بدون Evidence کامل نمی‌شود.
- `CLIN-003` appointment clinical task را کامل نمی‌کند.
- `CLIN-004` Evidence Assist نیازمند confirmation است.
- `CLIN-005` Rule/Shadow freeze نقض نمی‌شود.

### Operations

- `OPS-001` سلامت Scheduler قابل مشاهده است.
- `OPS-002` outbox/dead-letter قابل مشاهده است.
- `OPS-003` failure بحرانی پنهان نمی‌ماند.
- `OPS-004` safe retry وجود دارد.
- `OPS-005` projection lag اندازه‌گیری می‌شود.

### Security

- `SEC-001` mutationها role/permission checked هستند.
- `SEC-002` CSRF و stale protection اجباری است.
- `SEC-003` PHI در log نشت نمی‌کند.
- `SEC-004` actor/policy/version audit می‌شود.

---

## 24. Definition of Done کل برنامه

این برنامه فقط وقتی تمام است که:

- تمام trancheهای لازم merge شده باشند؛
- KPIهای pilot برآورده شده باشند؛
- user acceptance ثبت شده باشد؛
- rollback rehearsal موفق باشد؛
- Clinical Safety review موفق باشد؛
- هیچ critical automation failure پنهان نباشد؛
- Work Itemهای باز next action/wait/block و owner role روشن داشته باشند؛
- routine SMS approval دستی به‌طور اثبات‌شده کاهش یافته باشد؛
- duplicate navigation و data entry کاهش یافته باشد؛
- UI legacy فقط پس از اثبات parity retire شده باشد؛
- PROJECT_STATE به وضعیت نهایی به‌روزرسانی شده باشد.

اعلام پایان بر اساس «ساخته‌شدن UI» یا «سبزشدن چند تست focused» مجاز نیست.

---

## 25. ترتیب شروع قطعی

اولین تغییر بعد از merge این سند باید فقط FO-0 باشد:

```text
register stream in PROJECT_STATE
→ create baseline report
→ record current flow metrics
→ add feature flags OFF
→ add governance/test guards
→ no runtime behavior change
```

شروع FO-1 یا هر migration رفتاری پیش از بسته‌شدن FO-0 ممنوع است.
