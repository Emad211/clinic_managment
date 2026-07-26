# A7 — تفکیک پرداخت و اصلاحات مالی مستند

## منبع حقیقت

A7 سه منبع را از هم جدا نگه می‌دارد:

1. **مشاهدهٔ مالی A4**: مبلغ صورتحساب و وصول ثبت‌شده در دیتابیس حسابداری؛
2. **تفکیک payer**: فقط بر اساس `invoice_item_payments.payment_type` و `is_paid`؛
3. **اصلاح مالی تخصصی**: refund، chargeback، write-off یا اصلاح تسویهٔ بیمه با شاهد صریح.

دیتابیس حسابداری همچنان فقط‌خواندنی است. A7 هیچ refund یا settlement را از نبود رکورد نتیجه‌گیری نمی‌کند.

## تفکیک payer

مبالغ وصول‌شده فقط در این گروه‌ها قرار می‌گیرند:

- نقد؛
- کارت؛
- بیمه؛
- نوع پرداخت نامشخص.

مبلغ پرداخت‌نشده به بیمار یا بیمه منتسب نمی‌شود مگر آن‌که accounting evidence آن را مشخص کرده باشد. snapshotهای قدیمی که تفکیک payer ندارند، با برچسب `LEGACY_UNAVAILABLE` تمام وصول را در گروه «نامشخص» قرار می‌دهند.

## Review obligation

هر observation مالی جاری یک stream بازبینی دارد. وضعیت‌های اصلی:

```text
REVIEW_REQUIRED
→ REVIEWED_NO_ADJUSTMENT | REVIEWED_WITH_ADJUSTMENT
→ REOPENED (در صورت snapshot یا adjustment جدید)
```

بازبینی فقط برای observation جاری معتبر است. ورود snapshot جدید، review قبلی را stale می‌کند. adjustment فعالِ متعلق به observation قدیمی باید اصلاح یا reverse شود و نمی‌تواند برای snapshot جدید تأیید شود.

## اصلاحات مالی

هر adjustment append-only است و باید این اطلاعات را داشته باشد:

- نوع adjustment؛
- مبلغ علامت‌دار به تومان؛
- نوع و شناسهٔ شاهد؛
- زمان وقوع؛
- ثبت‌کننده؛
- توضیح اصلاح یا reversal.

Refund، chargeback و write-off باید مبلغ منفی داشته باشند. مجموع adjustmentها نمی‌تواند وصول را به کمتر از صفر برساند.

## انتشار عدد

`adjusted_collected` فقط زمانی قابل جمع است که:

- payer breakdown برای observation جاری موجود باشد؛
- review جاری با وضعیت `REVIEWED` ثبت شده باشد؛
- adjustment فعال متعلق به observation قدیمی وجود نداشته باشد.

A6 نیز فقط از همین مبلغ بازبینی‌شده برای ROI کمپین استفاده می‌کند. gross collection برای مشاهده باقی می‌ماند، اما تا تکمیل review وارد ROI نمی‌شود.

## مرز دامنه

A7 جایگزین ledger رسمی refund، settlement بیمه یا حسابداری تعهدی نیست. اگر سامانهٔ حسابداری در آینده جدول‌های canonical برای این رویدادها اضافه کند، adapter باید آن evidence را read-only ingest کند و review فعلی را دوباره باز کند.
