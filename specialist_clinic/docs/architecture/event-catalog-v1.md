# Event Catalog — نسخهٔ ۱

قراردادِ رویدادهای مرزیِ حسابداری → تخصصی (ADR-0003). این قرارداد **پایدار** است و مستقل از پیاده‌سازی (SQLite امروز، Postgres فردا).

## رویدادهای v1

| رویداد | تریگر (file:line) | payloadِ کمینه | کلیدِ idempotency |
|---|---|---|---|
| **`invoice.closed`** ⭐ | پایانِ `close_invoice` وقتی `rowcount>0` (`webapp/src/adapters/sqlite/invoices_repo.py:275`) + sweeper برای closedهای جامانده | `{schema_version, invoice_id, national_id, work_date, total_amount, items:[{type, name}]}` | `invoice.closed:{invoice_id}` |

> رویدادِ اصلیِ v1 همین یکی است. مصرف‌کننده از `items` (نوعِ ویزیت/تزریق/پروسیجر) تریگرهای پایین‌دست را مشتق می‌کند: **پیامکِ تشکر** (هر فاکتورِ بسته) و **دعوتِ پروسیجرِ** پس‌از (شستشوی گوش/پانسمان/بخیه ← `procedure_type`). پس `procedure.recorded` رویدادِ جدا لازم ندارد.

### رزروشده (نه در v1)
- `invoice.opened` — **لازم نیست**؛ صفِ زندهٔ پزشک با **خواندنِ زندهٔ فاکتورهای باز** از پل پر می‌شود، نه رویداد.
- `procedure.recorded` — از `items`ِ `invoice.closed` مشتق می‌شود.
- `patient.registered` — برای آینده‌ای که تخصصی بخواهد بیمار را به‌جای poll با رویداد آینه کند (PWA).

## اصولِ قرارداد
- **`national_id` کلیدِ مرزی است، نه `patient_id`ِ داخلیِ حسابداری.** payload باید `national_id` بدهد تا تخصصی بدونِ join به `patients` به `patient_links` بچسبد. (در `invoices` فقط `patient_id` هست → موقعِ ساختِ رویداد با join به `patients` گرفته می‌شود؛ ردیفِ `national_id IS NULL` نادیده.)
- **payloadِ کمینه + claim-check:** فقط شناسه‌ها و حداقلِ زمینه؛ دادهٔ سنگین/مالی را مصرف‌کننده با پلِ read-only می‌خواند → تعریفِ درآمد یک‌جا می‌ماند (`accounting_bridge`). از کپیِ snapshotِ مبلغ در payload پرهیز (drift + تکرارِ PII).
- **نسخه‌بندی:** `schema_version` (شروع از `1`). افزایشِ سازگار = فیلدِ اختیاریِ نو؛ ناسازگار = `*.v2`. مصرف‌کننده **tolerant reader** (فیلدِ ناشناخته را نادیده).
- **ترتیب:** ترتیبِ سراسری تضمین نمی‌شود؛ مصرف‌کننده باید **idempotent/commutative** باشد. outbox یک `id`/`seq` صعودی دارد و cursor بیشینهٔ مصرف‌شده را نگه می‌دارد.
- **معناشناسیِ تحویل:** **at-least-once**؛ exactly-once وعده داده نمی‌شود. تکرار با لجرِ UNIQUE خنثی می‌شود (`processed_invoices.outbox_id UNIQUE` + `INSERT OR IGNORE`، الگوی `engagement_dispatch`).
- **Fail-loud:** اگر منبع در دسترس نبود، cursor جلو نرود و در tick بعد retry شود.

## شکلِ نمونه (payload)
```json
{
  "schema_version": 1,
  "event": "invoice.closed",
  "invoice_id": 12345,
  "national_id": "00xxxxxxxx",
  "work_date": "2026-06-20",
  "total_amount": 2550000,
  "items": [{"type": "procedure", "name": "پانسمان"}, {"type": "visit", "name": "ویزیت"}]
}
```

## حریم (هماهنگ با `security-privacy-advisor`)
`national_id` داخلِ outbox **لازم و داخلی** است؛ ولی نباید کامل در لاگِ ممیزی ثبت شود، در نمای بیمار بیاید، یا در مدلِ آیندهٔ چندمستأجره بدونِ `tenant_id`/surrogate حمل شود.
