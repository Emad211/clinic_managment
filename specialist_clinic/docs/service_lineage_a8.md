# A8 — اتصال line item خدمت به Encounter و پرونده طولی

## هدف

تا پیش از A8، reconciliation مالی تعداد و مبلغ ویزیت، تزریق و کار عملی را نگه می‌داشت، اما خود line itemها در پروندهٔ تخصصی و Encounter قابل مشاهده نبودند. A8 همان شواهد حسابداری را بدون نوشتن در حسابداری به یک projection دقیق و append-only تبدیل می‌کند.

## مرز منبع حقیقت

- حسابداری فقط با SQLite `mode=ro` و `query_only=ON` خوانده می‌شود.
- summary مالی و line itemهای خدمت از یک read transaction یکسان استخراج می‌شوند.
- line itemها فقط شامل داده‌ای هستند که schema حسابداری صریحاً دارد: نوع ساختاری خدمت، شرح، زمان، تعداد، مبلغ و performer در صورت وجود.
- line item حسابداری تشخیص، نتیجهٔ درمان، یادداشت بالینی یا تأیید کیفیت خدمت نیست.

## قرارداد COMPLETE

manifest با وضعیت `COMPLETE` فقط وقتی ثبت می‌شود که:

1. تعداد lineها با `billable_item_count` observation مالی برابر باشد؛
2. مجموع `total_amount` lineها با `billed_amount` برابر باشد؛
3. invoice، Journey، Encounter و بیمار در lineها و observation یکسان باشند؛
4. همهٔ lineها در همان transaction محلی و پیش از manifest ثبت شده باشند.

## قرارداد legacy

برای observationهای قدیمی که جزئیات line item در زمان ثبت موجود نبوده است:

- manifest با وضعیت `LEGACY_UNAVAILABLE` ساخته می‌شود؛
- هیچ line ساختگی ایجاد نمی‌شود؛
- reconciliation بعدی می‌تواند یک manifest `COMPLETE` جدید را به‌صورت append-only روی همان invoice ثبت کند.

## پرونده بیمار

فقط lineهای manifest جاری، `COMPLETE` و متصل به observation مالی جاری در timeline دیده می‌شوند. ویزیت عمومی حسابداری تنها زمانی حذف می‌شود که همان `invoice_id` یک line دقیق `VISIT` داشته باشد؛ تشابه تاریخ برای حذف کافی نیست.

## ممنوعیت‌ها

- نوشتن در `webapp` یا دیتابیس حسابداری؛
- استنتاج تشخیص یا outcome از نام خدمت؛
- ساخت line از totals مالی؛
- overwrite یا delete تاریخچه manifest/line؛
- مخلوط‌کردن manifest قدیمی با observation مالی جدید.
