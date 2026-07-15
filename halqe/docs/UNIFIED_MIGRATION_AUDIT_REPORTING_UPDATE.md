# به‌روزرسانی حسابرسی یکپارچه — گزارش، حقوق و ETL مالی

این addendum وضعیت جدید شاخهٔ یکپارچه را نسبت به
`UNIFIED_MIGRATION_AUDIT.md` ثبت می‌کند. کد و تست‌های synthetic کامل شده‌اند؛ این
سند به‌هیچ‌وجه به معنی اجرای مهاجرت روی `clinic_new.db` واقعی یا مجوز cutover نیست.

## قابلیت‌هایی که اکنون runtime-complete هستند

### گزارش و حقوق

- داشبورد مالی manager-only در `/accounting/reports`؛
- KPI فاکتور، بیمار، تعهد مالی، payment state و هزینه مصرفی؛
- روند روزانه درآمد؛
- گزارش فاکتور با فیلتر وضعیت، بیمه و پذیرش؛
- گزارش یکپارچه ویزیت، پرستاری، پروسیجر و مصرفی؛
- خروجی CSV فارسی؛
- محاسبه read-only حقوق در `/accounting/payroll`؛
- تفکیک پایه شیفت، سهم ویزیت، تزریق، پروسیجر، مالیات و خالص؛
- read port فیزیکی SELECT-only برای گزارش‌ها؛
- tenant isolation و manager/admin authorization.

### مهاجرت تاریخی مالی

- preflight فقط‌خواندنی SQLite با quick-check، schema، FK و orphan checks؛
- بررسی WAL/SHM/journal و الزام snapshot متوقف‌شده؛
- SHA-256 فایل و manifest تمام جدول‌های داخل دامنه؛
- snapshot مبلغ‌های invoice، item، payment و درآمد عملیاتی؛
- dry-run روی writer role و constraintهای واقعی PostgreSQL با rollback کامل؛
- apply اتمیک در یک transaction و تأیید اجباری SHA فایل؛
- append-only import ledger دارای RLS و source/target fingerprint؛
- replay idempotent و رد source drift یا target drift؛
- canonical reuse فقط در صورت برابری semantic و بدون overwrite؛
- حفظ `custom/medicine` در `legacy_service_type` و الزام mapping عملیاتی صریح؛
- ثبت فاکتورهای تاریخی با `pricing_version=legacy`؛
- reconciliation مبلغی فقط روی imported scope، نه کل tenant؛
- verifier مستقل و SELECT-only؛
- exact source↔ledger coverage؛
- target fingerprint continuity؛
- exact invoice child/payment completeness؛
- گزارش‌های خصوصی atomic با permission برابر `0600`؛
- runbook کامل preflight → dry-run → apply → verify → dual-run.

## تعریف مالی تثبیت‌شده

درآمد عملیاتی مطابق oracle برنامهٔ Flask قدیمی برابر است با:

```text
ویزیت فاکتور بسته + پرستاری/تزریق فاکتور بسته + پروسیجر فاکتور بسته
```

مصرفی در این جمع وارد نمی‌شود. مصرفی مرکز جداگانه نمایش داده می‌شود و مصرفی
آوردهٔ بیمار یا exception در نمای پیش‌فرض گزارش حذف می‌شود.

## تعریف payroll تثبیت‌شده

- حضور پزشک از روز/شیفت ویزیت استنتاج می‌شود؛
- حضور پرستار از invoice دارای تزریق یا پروسیجر همان پرستار استنتاج می‌شود؛
- فقط ویزیت فاکتور بسته کارمزد ویزیت دارد؛
- سهم تزریق پزشک فقط در invoice دارای ویزیت همان پزشک محاسبه می‌شود؛
- سهم پروسیجر پزشک و پرستار جداست؛
- مالیات مطابق legacy فقط در شاخه پزشک کسر می‌شود؛
- صفحه payroll فقط preview است و سند پرداخت ایجاد نمی‌کند.

## اعتبارسنجی آخرین head کد ETL و verifier

- backend PostgreSQL: **۹۰۵ passed**، یک skipped، صفر failed؛
- dry-run، apply، replay، source drift و target drift: passed؛
- verification سالم، source mismatch، target mismatch و child اضافه: passed؛
- exact OpenAPI lock: passed؛
- schema guard: passed؛
- accounting money oracle: passed؛
- specialist suite: passed؛
- Jest، TypeScript، ESLint و production build: passed.

## وضعیت دقیق ETL

| بخش | وضعیت |
|---|---|
| preflight و source manifest | runtime-complete |
| importer اتمیک | runtime-complete |
| append-only ledger و replay | runtime-complete |
| verifier count/hash/money/child | runtime-complete |
| command و runbook عملیاتی | runtime-complete |
| rehearsal روی snapshot واقعی | external-gate |
| mapping واقعی service typeها | external-gate |
| reconciliation صندوق/بیمه/payroll | external-gate |
| dual-run | external-gate |
| cutover و rollback واقعی | external-gate |

## موارد باقی‌مانده برای انتقال کامل حسابداری

1. اجرای preflight روی یک snapshot امن و واقعی `clinic_new.db`؛
2. بررسی و تصویب mapping مقدارهای واقعی `services.service_type`؛
3. dry-run و apply rehearsal در محیط staging؛
4. نمونه‌برداری انسانی فاکتور، آیتم، پرداخت، بیمه و payroll؛
5. audit search مدیریتی؛
6. backup/restore rehearsal؛
7. dual-run و reconciliation صندوق/بیمه/payroll؛
8. تصمیم رسمی GO/NO_GO برای cutover.
