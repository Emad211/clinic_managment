# حلقهٔ بستهٔ مراقبت بالینی

## هدف

این قرارداد recommendation را به یک outcome قابل‌ممیزی متصل می‌کند، بدون آن‌که
پذیرش recommendation یا ساخت task هیچ درمان، نسخه، تشخیص یا ارجاع خارجی را خودکار
اجرا کند.

```text
recommendation
→ presented
→ clinician decision
→ clinical task
→ assigned / scheduled / in-progress / deferred
→ completed / not-done / entered-in-error
→ outcome evidence
```

ردیف `followup_tasks` برای task بالینی فقط identity ثابت است. وضعیت جاری از head
جدول append-only `clinical_task_events` projection می‌شود.

## مرز با پیگیری اداری

پیگیری‌های refill، lapsed، manual و سایر عملیات اداری می‌توانند workflow سادهٔ
mutable خود را داشته باشند. اما task دارای:

```text
source_engine = clinical_v2
```

فقط از repository و route بالینی تغییر می‌کند. `FollowupRepository.resolve`،
`set_appointment` و bulk appointment اجازهٔ mutation مستقیم task بالینی ندارند.

## lifecycle

رویدادهای معتبر:

| event | state |
|---|---|
| `CREATED` | `OPEN` |
| `ASSIGNED` | `ASSIGNED` |
| `SCHEDULED` | `SCHEDULED` |
| `STARTED` | `IN_PROGRESS` |
| `DEFERRED` | `DEFERRED` |
| `COMPLETED` | `COMPLETED` |
| `NOT_DONE` | `NOT_DONE` |
| `ENTERED_IN_ERROR` | `ENTERED_IN_ERROR` |

- UPDATE و DELETE event ممنوع است.
- هر task دقیقاً یک root دارد.
- هر event بعدی باید head جاری همان task را supersede کند.
- هر event حداکثر یک child دارد.
- `recorded_at` در زنجیره به عقب نمی‌رود.
- فرم stale کل transition را رد می‌کند.
- task terminal دوباره باز نمی‌شود؛ تنها ثبت `ENTERED_IN_ERROR` مجاز است.

## completion evidence

`COMPLETED` بدون `clinical_outcome_events.id` متعلق به همان task در سطح SQLite رد
می‌شود. outcome دارای این provenance است:

```text
outcome_type
fact_key / value / unit
verification
observed_at
recorded_at
source_system
source_record_id
actor
content_hash
```

ثبت outcome به‌تنهایی Fact تاریخی بیمار را بازنویسی نمی‌کند. تبدیل outcome به Fact
فقط از adapter صریح یک منبع canonical در tranche بعدی یا rule package مجاز است.

## NOT_DONE

بستن بدون انجام نیازمند disposition صریح است:

```text
PATIENT_DECLINED
UNREACHABLE
CLINICIAN_CANCELLED
DUPLICATE
NO_LONGER_NEEDED
OTHER
```

نبودن disposition یا استفاده از متن آزاد به‌عنوان تنها دلیل، transition را متوقف
می‌کند.

## appointment

ساخت appointment برای task بالینی، task را `COMPLETED` نمی‌کند. فقط event
`SCHEDULED` ثبت می‌شود. appointment باید به همان بیمار تعلق داشته باشد. تکمیل task
بعد از مراجعه همچنان به outcome evidence نیاز دارد.

## idempotency و recurrence

هویت ساخت task شامل این ابعاد است:

```text
patient
semantic_key
context_hash
due_period
evidence_fact_ids
```

تا زمانی که task همان semantic/context/period غیرterminal است، task تکراری ساخته
نمی‌شود. بعد از terminal شدن، due period جدید می‌تواند task جدید بسازد. index قدیمی
که فقط semantic/context را می‌دید حذف شده است.

## migration

- task بالینی legacy با وضعیت `open` و بدون event به root `CREATED/OPEN` تبدیل می‌شود.
- task بالینی legacy که پیش‌تر با UPDATE به `done/dismissed` رسیده ولی outcome evidence
  ندارد، fail-loud است؛ migration outcome ساختگی تولید نمی‌کند.
- داده‌های اداری تغییر نمی‌کنند.
- identity ردیف‌های بالینی و تمام eventها غیرقابل‌ویرایش و غیرقابل‌حذف است.

با توجه به seed بودن دادهٔ فعلی، در صورت برخورد با terminal task قدیمی، reset همان
seed از جعل شاهد بالینی ایمن‌تر است.

## authorization

- همهٔ کاربران احراز‌شده می‌توانند worklist و وضعیت task را ببینند.
- ثبت outcome و transition بالینی فعلاً به نقش manager محدود است.
- این نقش coarse در گام ششم با مجوزهای بالینی تفصیلی جایگزین می‌شود.

## دروازهٔ انتشار

- completion بدون outcome در service و SQLite شکست بخورد.
- outcome task دیگر قابل استفاده نباشد.
- stale event id هیچ transitionی ثبت نکند.
- UPDATE/DELETE eventها شکست بخورد.
- appointment بیمار دیگر رد شود.
- generic follow-up repository نتواند task بالینی را ببندد یا relink کند.
- UI برای task بالینی دکمهٔ legacy «انجام شد» نشان ندهد.
- task جدید همراه root event و source recommendation/context ثبت شود.
- recurrence فقط در due period جدید و پس از terminal state مجاز باشد.
- targeted care-loop، follow-up، authorization و migration tests سبز باشند.
