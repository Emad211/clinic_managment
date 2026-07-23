# تاریخچهٔ طولی Clinical Flags

## هدف

`clinical_flag_events` منبع حقیقت وضعیت‌های ساختاریافته‌ای است که در eligibility،
safety exclusion، risk context یا توضیح recommendation مصرف می‌شوند. این داده‌ها
یادداشت آزاد یا مقدار nullable نیستند. سیستم باید میان پاسخ منفی، نامشخص و
پرسیده‌نشده تفاوت قطعی نگه دارد.

## وضعیت‌ها

| state | value | معنا |
|---|---|---|
| `PRESENT` | مقدار typed | پاسخ مشخص ثبت شده؛ boolean می‌تواند `true` یا `false` باشد |
| `UNKNOWN` | `NULL` | سؤال بررسی شده، اما پاسخ معتبر یا قابل اتکا در دست نیست |
| `NOT_ASKED` | `NULL` | سؤال هنوز از بیمار/منبع مربوط پرسیده یا بررسی نشده است |

در نتیجه:

```text
PRESENT(false) != UNKNOWN != NOT_ASKED
```

## قرارداد زمانی

هر event دو زمان مستقل دارد:

- `effective_at`: پاسخ از چه زمانی از نظر بالینی صادق بوده است.
- `recorded_at`: سامانه از چه زمانی از این پاسخ اطلاع داشته است.

Projection تاریخی هم‌زمان هر دو cutoff را رعایت می‌کند. اصلاحی که بعداً ثبت شده،
دانش موجود در snapshot قدیمی را بازنویسی نمی‌کند.

## append-only و supersession

- `UPDATE` و `DELETE` رویداد ممنوع است.
- اولین event یک flag، `supersedes_event_id=NULL` دارد.
- هر event بعدی باید دقیقاً head جاری همان بیمار و همان `flag_key` را supersede کند.
- هر event حداکثر یک child دارد؛ تاریخچه یک زنجیرهٔ خطی است.
- `recorded_at` در زنجیره نمی‌تواند به عقب حرکت کند.
- یک batch فرم با `BEGIN IMMEDIATE` و optimistic concurrency ثبت می‌شود.

## تعریف catalog

هر تعریف semantic دارای این identity است:

```text
flag_key
flag_type
canonical options_json
is_active
definition_version
definition_hash
```

تغییر label، ترتیب یا محل نمایش identity را تغییر نمی‌دهد. تغییر type، options یا
active state، `definition_version` را افزایش می‌دهد و hash جدید می‌سازد. حتی اگر
تعریف بعداً به مقادیر قبلی برگردد، پاسخ‌های قدیمی خودکار دوباره معتبر نمی‌شوند و
نیازمند مرور مجدد هستند.

## انواع مقدار

- `bool`: JSON boolean واقعی، شامل پاسخ صریح `false`
- `enum`: فقط یکی از valueهای canonical catalog
- `date`: تاریخ Gregorian ISO به شکل `YYYY-MM-DD`
- `text`: متن trim‌شده با حداکثر ۲۰۰۰ کاراکتر

قرارداد هم در service و هم در triggerهای SQLite کنترل می‌شود.

## migration

ردیف‌های mutable قدیمی به‌صورت محافظه‌کارانه تبدیل می‌شوند:

```text
"1" / true  -> PRESENT(true),  PROVISIONAL
"0" / false -> PRESENT(false), PROVISIONAL
blank        -> UNKNOWN,        UNVERIFIED
enum/date نامعتبر -> migration failure
flag بدون catalog -> migration failure
```

پس از اثبات وجود event متناظر برای تمام ردیف‌ها، جدول `patient_flags` حذف می‌شود.
هر ابهام باعث rollback کامل migration می‌شود؛ داده حدس زده یا silently dropped
نمی‌شود.

## UI و concurrency

فرم boolean چهار انتخاب صریح دارد:

```text
بله / خیر / نامشخص / پرسیده‌نشده
```

هر input همراه `expected_current_event_id` و `expected_definition_hash` ارسال می‌شود.
اگر یک کاربر یا تغییر catalog بعد از بارگذاری صفحه رخ داده باشد، کل batch رد می‌شود و
هیچ subsetی از فرم ثبت نمی‌شود.

## اثر روی Clinical Engine

Factهای تولیدی می‌توانند این شکل‌ها را داشته باشند:

```text
flag.pregnancy = PRESENT(false), CONFIRMED
flag.smoking   = UNKNOWN
flag.ascvd     = NOT_ASKED
```

تغییر این قرارداد باعث تغییر engine identity به
`2.5.0-flag-history` شده است؛ run، activation report و seal مربوط به build قبلی
برای runtime جدید معتبر نیستند.

## محدودیت فعلی

خود row کاتالوگ هنوز projection جاری تعریف است و یک registry کامل از نسخه‌های
گذشتهٔ catalog نیست. eventها hash تعریف زمان ثبت را حفظ می‌کنند و در تغییر تعریف
fail-closed به `UNKNOWN` می‌روند. اگر در آینده نمایش دقیق تعریف تاریخی لازم باشد،
یک append-only definition registry مستقل اضافه خواهد شد؛ این محدودیت نباید با
بازاعتباردهی خودکار event قدیمی دور زده شود.

## دروازهٔ انتشار این مرحله

این tranche فقط زمانی آمادهٔ review نهایی است که همهٔ شروط زیر هم‌زمان برقرار باشند:

- دیتابیس تازه از ابتدا فقط `clinical_flag_events` بسازد و جدول mutable قدیمی نداشته باشد.
- کپی دیتابیس قدیمی، مقدار صریح false را بدون تبدیل به `NOT_ASKED` مهاجرت دهد.
- دادهٔ نامعتبر، orphan catalog یا زنجیرهٔ چندریشه باعث rollback کامل migration شود.
- projection دو‌زمانه، اصلاح دیرهنگام را وارد snapshot دانش قدیمی نکند.
- تغییر نمایشی catalog، revision بیمار را عوض نکند؛ تغییر معنایی آن را منسوخ کند.
- فرم stale هیچ subsetی را ثبت نکند و کاربر را مجبور به مرور مجدد سازد.
- Factهای موتور false، unknown و not-asked را با status و verification مستقل حمل کنند.
- run و activation evidence متعلق به engine identity قبلی current تلقی نشوند.
- تمام تست‌های Specialist Clinic و Accounting بدون failure، error یا skip عبور کنند.
