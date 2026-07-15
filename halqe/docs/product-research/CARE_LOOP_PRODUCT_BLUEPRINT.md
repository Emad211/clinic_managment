# blueprint محصول Care Loop در حلقه

**وضعیت:** تصمیم محصول و دامنه؛ جزئیات schema و API باید در ADRهای جداگانه تصویب شوند.

## تعریف

Care Loop یک مسئله یا فرصت مراقبتی است که:

1. از یک داده، فاصلهٔ مراقبتی، رویداد یا تصمیم ایجاد می‌شود؛
2. توسط فرد یا تیم مشخص بررسی می‌شود؛
3. به برنامه و کارهای روشن تبدیل می‌شود؛
4. بیمار یا همراه می‌داند چه کاری باید انجام دهد؛
5. پاسخ و دادهٔ بعدی دریافت می‌شود؛
6. نتیجه با شواهد کافی ثبت می‌شود؛
7. حلقه بسته، لغو، escalated یا دوباره باز می‌شود.

Task فقط یکی از اجزای Care Loop است. Suggestion نیز فقط یک ورودی دانشی است و به‌تنهایی تصمیم یا اقدام محسوب نمی‌شود.

## اجزای دامنه

| جزء | مسئولیت |
|---|---|
| CarePlan | برنامهٔ مراقبت در یک بازه و زمینهٔ چندبیماری |
| CareGoal | هدف قابل‌فهم برای بیمار و قابل‌اندازه‌گیری برای تیم |
| CareLoop | یک مسئلهٔ زمان‌دار که باید به نتیجه برسد |
| CareActivity | اقدام برنامه‌ریزی‌شده در CarePlan |
| CareTask | کار اجرایی با مالک، صف، موعد و وضعیت |
| PatientAction | کار مشخص برای بیمار یا همراه |
| Communication | درخواست و رخداد واقعی پیام، تماس یا پاسخ |
| ReviewDecision | تصمیم فرد مجاز دربارهٔ داده یا پیشنهاد |
| OutcomeEvidence | داده یا سندی که نتیجه را اثبات می‌کند |
| Escalation | تغییر سطح رسیدگی، علت و گیرنده |
| CaregiverAccess | رابطه، سطح دسترسی، رضایت و انقضا |
| KnowledgeRecommendation | خروجی موتور علمی پیش از تبدیل به برنامه یا کار |

## چرخهٔ اصلی

```text
Detected
→ Triaged
→ Planned
→ Active
→ Waiting for patient / team
→ Verification due
→ Closed
```

حالت‌های فرعی:

```text
Blocked
Escalated
Cancelled
Expired
Reopened
```

هر تغییر وضعیت باید یک event تغییرناپذیر داشته باشد. وضعیت جاری برای UI یک projection است؛ تاریخچه overwrite نمی‌شود.

## قرارداد بسته‌شدن

یک Care Loop تنها با برچسب «انجام شد» بسته نمی‌شود. بستن آن نیازمند موارد زیر است:

- owner یا policy معتبر برای مسئولیت؛
- تکمیل یا تعیین تکلیف کارهای ضروری؛
- evidence موردنیاز؛
- نتیجه یا closure code؛
- تعیین گام یا موعد بازبینی بعدی؛
- نداشتن escalation حل‌نشدهٔ بحرانی؛
- ثبت ارتباط یا acknowledgement در موارد لازم.

اگر نتیجهٔ جدید با closure قبلی ناسازگار باشد، loop با دلیل مشخص دوباره باز می‌شود.

## مالکیت و صف

مالکیت باید ساختاریافته باشد:

- user owner؛
- care team؛
- queue؛
- نقش موردنیاز؛
- زمان پذیرش کار؛
- زمان پاسخ و زمان حل؛
- جایگزین در غیبت؛
- escalation path.

متن آزاد `assigned_to` برای عملیات چندکلینیکی و گزارش SLA کافی نیست.

## تفاوت با FollowupTask فعلی

FollowupTask فعلی برای worklist اولیه مناسب است، اما این اطلاعات را ندارد:

- owner identity و team queue؛
- پاسخ و حل در SLA؛
- waiting-on-patient و waiting-on-team؛
- attempt history ساختاریافته؛
- blocked/escalated؛
- required evidence؛
- closure code و outcome؛
- ارتباط با plan و goal؛
- reopen reason؛
- acknowledgement بیمار یا همراه.

مهاجرت باید تدریجی باشد و write path قدیمی تا پایان reconciliation حذف نشود.

## تفاوت با SuggestionLog فعلی

چرخهٔ پیشنهاد هدف:

```text
Generated
→ Suppressed or deduplicated
→ Presented
→ Accepted / dismissed / snoozed
→ Converted to plan or task
→ Completed / expired / superseded
```

قبول پیشنهاد به معنی اجرای آن نیست. باید تبدیل recommendation به plan/task و نتیجهٔ بعدی قابل‌ردیابی باشد.

## تجربهٔ بیمار

داشبورد بیمار باید اول این سؤال را جواب دهد:

> امروز مهم‌ترین کار من چیست و پس از انجام آن چه اتفاقی می‌افتد؟

صفحهٔ اول باید شامل این موارد باشد:

- یک اقدام اصلی؛
- حداکثر دو اقدام بعدی؛
- علت اهمیت اقدام با زبان ساده؛
- وضعیت دریافت و بررسی داده؛
- زمان مورد انتظار پاسخ تیم؛
- گام بعدی و موعد؛
- پیام ایمنی کوتاه و مسیر کمک؛
- پیشرفت نسبت به هدف.

منوهای سطح بعدی:

```text
Today
Plan & Goals
Measurements
Medicines
Messages
Appointments
Results
Learn
Family & Access
Billing
```

Billing نباید در صفحهٔ اول با اقدامات درمانی رقابت کند.

## تجربهٔ تیم درمان

Inbox باید بر اساس کار قابل‌اقدام سازمان‌دهی شود:

- فوری؛
- در انتظار review؛
- overdue؛
- منتظر بیمار؛
- منتظر تیم؛
- blocked؛
- بدون owner؛
- آمادهٔ closure؛
- reopened؛
- care gaps جمعیتی.

قابلیت‌های ضروری:

- assign گروهی؛
- outreach گروهی کنترل‌شده؛
- template و نتیجهٔ ساختاریافته؛
- dedup و suppression؛
- نمایش aging و SLA؛
- exception report؛
- ثبت خودکار رخدادهای سیستم بدون مستندسازی دوباره.

## همراه و خانواده

همراه باید هویت و دسترسی مستقل داشته باشد، نه password مشترک:

- دعوت و رضایت بیمار؛
- نوع رابطه؛
- سطح دسترسی مشاهده، اقدام، پیام و داده؛
- انقضا و revoke؛
- audit مستقل؛
- مشخص‌بودن اینکه یک کار را بیمار یا همراه انجام داده است.

## چندمستاجری

هر tenant می‌تواند این موارد را تنظیم کند:

- تیم‌ها و صف‌ها؛
- SLA؛
- کانال و زمان پیام؛
- escalation policy؛
- care pathway template؛
- branding و زبان؛
- location و ساعات؛
- device integration؛
- آموزش محلی و تنظیمات مالی.

اما این baselineها قابل‌خاموش‌شدن نیستند:

- tenant isolation؛
- audit و event history؛
- عدم استفاده از دادهٔ تأییدنشده در موتور؛
- consent و دسترسی همراه؛
- provenance موتور علمی؛
- evidence لازم برای closureهای حساس؛
- ممنوعیت PHI در log.

## مسیر مهاجرت

### فاز ۱: wrapper سازگار

- FollowupTask و SuggestionLog فعلی حفظ شوند؛
- CareLoop برای follow-upهای جدید ساخته شود؛
- task سازگاری برای UI قدیمی ایجاد شود؛
- eventهای جدید در کنار state قدیمی ثبت شوند.

### فاز ۲: inbox جدید

- تیم از Care Loop inbox استفاده کند؛
- worklist قبلی compatibility شود؛
- شمارش و نتیجهٔ دو مسیر مقایسه شود.

### فاز ۳: backfill محدود

فقط follow-upهای باز و قابل‌تفسیر منتقل شوند. برای دادهٔ تاریخی precision مصنوعی ساخته نشود.

### فاز ۴: بازنشستگی write قدیمی

فقط پس از dual-run، UX sign-off، migration rehearsal و rollback test.

## Minimum Viable Closed Loop

نسخهٔ حداقلی باید داشته باشد:

- CareLoop؛
- CareTask؛
- event history؛
- user/team/queue ownership؛
- response و resolution SLA؛
- waiting، blocked، closed و reopened؛
- evidence link و closure code؛
- staff inbox؛
- Patient Today؛
- telemetry کامل؛
- دو مسیر محدود برای آزمایش عملیات.

معیار موفقیت MVP تعداد feature نیست؛ کاهش حلقه‌های بدون owner، کاهش زمان review و افزایش closure معتبر است.

## ADRهای لازم

1. Aggregate root و event model.
2. user/team/queue ownership.
3. closure evidence.
4. communication و delivery receipt.
5. patient identity و caregiver proxy.
6. consent و access lifecycle.
7. knowledge artifact و rule release.
8. SLA و escalation policy.
9. migration از FollowupTask.
10. interoperability boundary.
