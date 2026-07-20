# مرجع اتصال پیامک مدیانا

این سند از روی فایل OpenAPI «MEDIANA DOCUMENT.json» نسخهٔ ۱.۰.۰ و رفتار واقعی پنل تهیه شده است.

## تنظیمات

- Base URL: `https://api.mediana.ir`
- احراز هویت: هدر `X-API-KEY`
- ارسال عادی: `POST /sms/v1/send/sms`
- موجودی: `GET /sms/v1/account/balance`
- حداکثر گیرنده در ارسال عادی: ۱۰۰ شماره
- انتقال HTTP: کتابخانهٔ `requests`؛ `urllib` پشت ArvanCloud برای درخواست معتبر
  این API پاسخ ۵۰۲ متناوب برمی‌گرداند و نباید برای مدیانا استفاده شود.

بدنهٔ ارسال بدون خط اختصاصی:

```json
{
  "type": "Informational",
  "recipients": ["09xxxxxxxxx"],
  "messageText": "متن پیام"
}
```

انواع معتبر پیام عبارت‌اند از `Informational`، `PromotionalToCustomers` و
`PromotionalAll`. پیام‌های یادآوری و مراقبتی باید `Informational` باشند.

## تفسیر پاسخ

موفقیت فقط زمانی ثبت می‌شود که HTTP موفق باشد و `data.Succeed=true` برگردد.
شناسهٔ پیام از `data.SmsItems[0].SmsItemId` و در نبود آن از `RequestCode` یا
`RequestId` خوانده می‌شود. پاسخ timeout به‌صورت `pending` ثبت می‌شود و نباید
خودکار retry شود، زیرا ممکن است مدیانا پیام را پذیرفته اما پاسخ دیر رسیده باشد.

پاسخ زندهٔ مدیانا برخلاف casing ثبت‌شده در OpenAPI، گاهی همین فیلدها را به‌شکل
`succeed`، `smsItems` و `smsItemId` برمی‌گرداند. آداپتور باید هر دو شکل
PascalCase مستند و camelCase واقعی را بپذیرد.

پاسخ HTTP خطا یا پاسخ غیر JSON شکست قطعی همان تلاش است و همراه با کد HTTP ثبت
می‌شود. خطاهای عددی مستند مدیانا در `mediana_provider.py` به پیام فارسی نگاشت
شده‌اند.

## چک‌لیست تست واقعی

1. پنل فعال در تنظیمات روی «مدیانا» باشد.
2. کلید API و در صورت وجود خط اختصاصی ذخیره شده باشد.
3. endpoint موجودی پاسخ JSON موفق بدهد.
4. یک پیام `Informational` به شمارهٔ تحت کنترل ارسال شود.
5. رکورد `sms_messages` باید `sent` و دارای `provider_msgid` باشد.
6. در timeout یا پاسخ نامشخص، ارسال را تکرار نکنید تا پیام تکراری نشود.
