# مهاجرت و بهره‌برداری از Clinical Reconciliation

> دامنه: `conditions`، `medications` و `allergies`  
> اصل ایمنی: «ردیف موجود» با «فهرست کامل و مرور‌شده» یکی نیست.  
> این سند به PR مربوط به Fact Reconciliation تعلق دارد و محتوای Rule Library را توسعه نمی‌دهد.

## ۱. هدف

این migration سه مسئلهٔ متفاوت را از هم جدا می‌کند:

1. آیا یک مورد مشخص در پرونده ثبت شده است؟
2. آیا کل فهرست توسط کاربر مجاز مرور شده است؟
3. آیا وضعیت ثبت‌شده برای زمان `as_of_at` موردنظر معتبر و قابل بازسازی است؟

پیش از این، خالی‌بودن جدول می‌توانست به‌اشتباه به‌معنای «موردی وجود ندارد» تفسیر شود. پس از این تغییر، فقدان داده تا زمان ثبت reconciliation کامل، `UNKNOWN` باقی می‌ماند.

## ۲. تغییرهای additive پایگاه داده

### ستون‌های طولی

- `patient_conditions.resolved_at`
- `patient_medications.end_date`
- `patient_medications.drug_catalog_id`
- `allergies.is_active`
- `allergies.resolved_at`

ستون‌های موجود حذف یا بازنام‌گذاری نمی‌شوند. ردیف‌های قدیمی حفظ می‌شوند.

### رویدادهای reconciliation

جدول `clinical_reconciliation_events` یک log افزایشی و append-only است. هر رویداد به این موارد متصل است:

- بیمار
- نوع فهرست
- کامل یا ناقص‌بودن مرور
- تعداد اقلام مؤثر در زمان مرور
- hash canonical همان اقلام
- زمان، actor و منبع مرور
- تأیید بیمار، در صورت ثبت
- رویداد قبلی که supersede شده است

UPDATE و DELETE این رویدادها با trigger دیتابیس ممنوع است. supersession فقط برای همان بیمار و همان نوع فهرست مجاز است.

## ۳. قرارداد state

| state | معنا | Verification | Freshness |
|---|---|---|---|
| `unreconciled` | هنوز کل فهرست مرور نشده | `UNVERIFIED` | `UNKNOWN` |
| `partial` | مرور انجام شده اما کامل نیست | `PROVISIONAL` | `FRESH` |
| `stale` | اقلام پس از مرور تغییر کرده‌اند | `UNVERIFIED` | `STALE` |
| `mapping_incomplete` | مرور کامل است ولی identity canonical ناقص است | `PROVISIONAL` یا `UNVERIFIED` | `FRESH` |
| `confirmed_present` | مرور کامل، hash منطبق و اقلام canonical موجودند | `CONFIRMED` | `FRESH` |
| `confirmed_absent` | مرور کامل، hash منطبق و هیچ مورد فعالی وجود ندارد | `CONFIRMED` | `FRESH` |

### نکتهٔ دارو

وجود `drug_class` آزاد به‌تنهایی identity دارو را تأیید نمی‌کند. aggregate و Fact اختصاصی دارو فقط وقتی `CONFIRMED` می‌شوند که ردیف به یک `drug_catalog_id` فعال متصل باشد. متن یا class آزاد برای نمایش descriptive حفظ می‌شود، اما `PROVISIONAL` است.

## ۴. Historical as-of

برای هر snapshot:

- تشخیص بر اساس onset/diagnosed و `resolved_at` بازسازی می‌شود.
- دارو بر اساس `start_date`، `end_date` و رویدادهای start/dose-change بازسازی می‌شود.
- حساسیت بر اساس `created_at` و `resolved_at` بازسازی می‌شود.

وقتی timestamp تاریخی لازم در دادهٔ legacy وجود ندارد، سیستم تاریخ را جعل نمی‌کند و warning زیر را ثبت می‌کند:

```text
HISTORICAL_INTERVAL_APPROXIMATION
```

دوزی که history کافی ندارد نیز با این warning مشخص می‌شود:

```text
HISTORICAL_DOSE_APPROXIMATION
```

Fact وابسته به interval مبهم از `CONFIRMED` به `PROVISIONAL` تنزل می‌کند.

## ۵. Backfill دارو

Backfill فقط match دقیق و امن با catalog را قبول می‌کند. fuzzy matching خودکار انجام نمی‌شود. ردیف مبهم باید در workspace بیمار توسط کاربر مجاز اصلاح شود.

پس از migration باید این گزارش بررسی شود:

```sql
SELECT id, patient_link_id, drug_name, drug_class
FROM patient_medications
WHERE is_active=1 AND drug_catalog_id IS NULL
ORDER BY patient_link_id, id;
```

وجود نتیجه در این query خطای migration نیست، ولی مانع تأیید کامل هویت دارویی همان بیمار است.

## ۶. ترتیب deployment

1. backup سازگار SQLite با Online Backup API ایجاد شود.
2. hash فایل backup ثبت شود.
3. برنامه با موتور در حالت `off` یا `shadow` بالا بیاید.
4. migration additive در bootstrap اجرا و schema guards بررسی شود.
5. تست integrity اجرا شود:

```sql
PRAGMA foreign_key_check;
PRAGMA integrity_check;
```

6. گزارش داروهای بدون concept بررسی شود.
7. workspace reconciliation برای cohort محدود مرور شود.
8. snapshotهای ساخته‌شده با JSON Schema منتشرشده تطبیق داده شوند.
9. فقط پس از تست و approval جدید، rollout موتور ادامه پیدا کند.

## ۷. rollback

### rollback runtime

اولویت نخست خاموش‌کردن خروجی است:

```text
clinical_engine_v2_mode = off
```

این کار audit و reconciliation eventها را حذف نمی‌کند.

### rollback کد

چون migration additive است، نسخهٔ قبلی برنامه می‌تواند ستون‌ها و جدول جدید را نادیده بگیرد. حذف فوری ستون یا eventها مجاز نیست. برای بازگشت کامل:

1. موتور خاموش شود.
2. از دیتابیس فعلی backup گرفته شود.
3. backup پیش از migration روی مسیر موقت restore و integrity-check شود.
4. پس از تأیید انسانی، فایل دیتابیس با عملیات atomic جایگزین شود.

رویدادهای reconciliation نباید برای «تمیزکردن rollback» دستی UPDATE یا DELETE شوند.

## ۸. محدودیت‌های شناخته‌شده

این tranche عمداً موارد زیر را کامل نمی‌کند:

- تاریخچهٔ `patient_flags` که هنوز current-state و overwrite-based است.
- vaccination reconciliation و تاریخچهٔ واکسن‌ها.
- context دقیق encounter/care-setting.
- concept system خارجی برای diagnosis و allergy.
- user-role بالینی تفصیلی؛ نقش‌های فعلی manager/staff هنوز coarse هستند.
- conflict resolution میان منابع متعدد medication/problem-list.
- بازیابی دقیق ردیف legacy غیرفعال که effective end date ندارد.

این محدودیت‌ها باید به‌صورت `UNKNOWN / PROVISIONAL / approximation warning` باقی بمانند و نباید با حدس پوشانده شوند.

## ۹. معیار پذیرش این migration

- migration روی DB تازه و کپی DB قدیمی idempotent باشد.
- empty collection بدون event، `UNKNOWN` باشد.
- absence فقط پس از مرور کامل `ABSENT + CONFIRMED` باشد.
- تغییر source بعد از مرور، projection را `STALE` کند.
- داروی بدون concept هرگز Fact تأییدشده نسازد.
- ownership هر mutation نسبت به بیمار URL بررسی شود.
- رویدادها append-only بمانند.
- summary سه فهرست از یک bundle bounded ساخته شود.
- هر Fact تولیدی با schema runtime و نسخهٔ research سازگار باشد.
- هر دو suite پروژه در CI سبز باشند.
