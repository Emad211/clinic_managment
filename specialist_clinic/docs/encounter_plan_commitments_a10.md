# A10 — اتصال Plan امضاشده به Worklist

## هدف

متن آزاد `plan` به‌تنهایی تعهد اجرایی ایجاد نمی‌کند. پزشک در زمان مستندسازی Encounter باید اقدام‌های قابل‌پیگیری را به‌صورت ردیف‌های ساختاریافته وارد کند. هنگام امضا، همان ردیف‌ها در یک تراکنش به تعهدهای immutable و taskهای Worklist تبدیل می‌شوند.

## مسیر حقیقت

```text
Encounter
→ Signed document version
→ Immutable plan commitments
→ Existing followup_tasks identities
→ Append-only commitment events
→ Contact / booking / evidence
→ Completed or cancelled
```

`followup_tasks` فقط هویت task و نقطهٔ اتصال به Worklist است. وضعیت، موعد جاری، مسئول، نوبت و نتیجه از آخرین `care_plan_commitment_events` استخراج می‌شوند؛ ستون mutable task منبع حقیقت نیست.

## انواع تعهد

- `CALL_CHECK`
- `IN_PERSON_REVIEW`
- `LAB_REVIEW`
- `MEDICATION_REVIEW`
- `REFERRAL_CHECK`
- `HOME_MONITORING_REVIEW`

هر ردیف دارای کلید پایدار سمت کاربر، دستور صریح، موعد، شیوه انجام و مسئول اختیاری است.

## قواعد outcome سند

- `FOLLOWUP_REQUIRED`: حداقل یک commitment صریح؛
- `REFERRED`: حداقل یک `REFERRAL_CHECK`؛
- `URGENT_ESCALATION`: حداقل یک commitment مسئول‌دار با موعد حداکثر ۲۴ ساعت؛
- هیچ commitmentی از `plan`، assessment یا عنوان line item حسابداری استخراج نمی‌شود.

## lifecycle عملیاتی

```text
CREATED → STARTED / ASSIGNED / RESCHEDULED / SCHEDULED
        → COMPLETED / CANCELLED / ENTERED_IN_ERROR
```

تمام رویدادها append-only، idempotent و دارای optimistic concurrency هستند. مسیر resolve سادهٔ task اداری و UPDATE مستقیم SQLite برای taskهای `encounter_plan` مسدود است.

## شواهد تکمیل

شاهد باید متعلق به همان بیمار/Task، از نوع مجاز و بعد از ایجاد commitment باشد:

- رویداد تماس همان task؛
- نوبت همان بیمار فقط پس از `done`؛
- سند Encounter امضاشدهٔ بعدی؛
- نتیجه آزمایش؛
- رویداد دارویی؛
- Vital ثبت‌شده؛
- تأیید مستند دستی با توضیح کافی.

رزرو نوبت فقط `SCHEDULED` است و completion محسوب نمی‌شود.

## اتمیک‌بودن

در امضای ویزیت، این عملیات یک transaction محلی‌اند:

```text
Vitals
Signed document
Commitment roots
Worklist task identities
CREATED events
Doctor Queue done
Encounter COMPLETED
```

شکست هر بخش، همهٔ عملیات را rollback می‌کند.

## مرز حسابداری

A10 هیچ فایل، جدول، فاکتور، پرداخت یا status در `webapp` را تغییر نمی‌دهد. اتصال حسابداری همان مسیر read-only تثبیت‌شدهٔ A0–A9 است.
