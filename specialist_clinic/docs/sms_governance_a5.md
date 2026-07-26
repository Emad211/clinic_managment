# A5 — حاکمیت پیامک و حقیقت تحویل

## قرارداد رضایت

رضایت پیام‌های `CARE` و `MARKETING` مستقل است و در `sms_consent_events` به‌صورت append-only ثبت می‌شود. نبود opt-in تبلیغاتی به معنی عدم مجوز است. لغو پیام مراقبتی، مجوز marketing را تغییر نمی‌دهد و بالعکس.

Consent پیش‌فرض هنگام enrollment یا اولین mutation ارسال ثبت می‌شود. بازکردن صفحهٔ پرونده فقط projection می‌خواند و event جدیدی ایجاد نمی‌کند.

## قرارداد ارسال

هر پیام جدید پیش از claim ارسال باید یک ردیف immutable در `sms_message_governance` داشته باشد که این موارد را به هم متصل می‌کند:

- بیمار؛
- purpose؛
- consent event مؤثر؛
- provider دقیق؛
- شماره canonical؛
- policy source.

SQLite اجازهٔ ورود پیام به وضعیت `Submitting` بدون این snapshot را نمی‌دهد.

## قرارداد provider

provider پیام در زمان ساخت ثابت می‌شود. تغییر پنل فعال فقط بر پیام‌های جدید اثر دارد. reconciliation هر پیام با provider ذخیره‌شدهٔ همان پیام انجام می‌شود و failover پنهان ممنوع است.

## تحویل واقعی

پذیرش درخواست توسط پنل (`Accepted`) تحویل به گیرنده نیست. وضعیت‌های provider در `sms_delivery_events` append-only ذخیره می‌شوند. برای کاوه‌نگار فقط status code `10` از `sms/status` برابر `Delivered` است.

KPI «ارسال‌شده» در UI جدید به‌عنوان پذیرش پنل تفسیر نمی‌شود؛ `Accepted`، `In flight`، `Delivered`، `Failed` و `Unknown` جدا نمایش داده می‌شوند.

## Secrets

در production کلیدها فقط از متغیرهای محیطی زیر خوانده می‌شوند:

```text
CLINIC_KAVENEGAR_API_KEY
CLINIC_MEDIANA_API_KEY
```

مقدار خام secret در UI نمایش داده نمی‌شود. SQLite فقط برای development/test fallback است.

## ایزوله‌سازی تنظیمات اپلیکیشن

هر Flask app ابتدا تنظیمات پایه را snapshot و سپس overrideهای همان instance را اعمال می‌کند. readerهای حسابداری مسیر را از `current_app` می‌گیرند؛ بنابراین test app یا process دیگر نمی‌تواند با تغییر `Config` سراسری مسیر حسابداری این instance را آلوده کند.

## Gate انتشار

Gate محدود A5 خروجی کامل pytest را همراه JUnit نگه می‌دارد، regression واقعی A4 یعنی `test_specialist_attendance_collection.py` را اجرا می‌کند، قراردادهای قدیمی تست را بدون عقب‌گرد منطق محصول به `Accepted ≠ Delivered` و consent append-only منتقل می‌کند، `webapp` را با `main` مقایسه می‌کند و فقط exact tested tree را commit می‌کند.

## مرز مالی

این tranche هیچ درآمد یا ROI را از provider acceptance نتیجه‌گیری نمی‌کند. campaign attribution تا اتصال صریح campaign→Journey→Encounter→Invoice fail-closed باقی می‌ماند.
