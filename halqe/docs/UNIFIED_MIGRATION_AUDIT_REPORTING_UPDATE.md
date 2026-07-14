# به‌روزرسانی حسابرسی یکپارچه — گزارش مالی و حقوق

این addendum وضعیت جدید شاخهٔ یکپارچه را نسبت به
`UNIFIED_MIGRATION_AUDIT.md` ثبت می‌کند.

## قابلیت‌هایی که اکنون runtime-complete هستند

- داشبورد مالی manager-only در `/accounting/reports`؛
- KPI فاکتور، بیمار، تعهد مالی، payment state و هزینه مصرفی؛
- روند روزانه درآمد؛
- گزارش فاکتور با فیلتر وضعیت، بیمه و پذیرش؛
- گزارش یکپارچه ویزیت، پرستاری، پروسیجر و مصرفی؛
- خروجی CSV فارسی برای فاکتور، خدمت و payroll؛
- محاسبه read-only حقوق در `/accounting/payroll`؛
- تفکیک پایه شیفت، سهم ویزیت، تزریق، پروسیجر، مالیات و خالص؛
- read port فیزیکی SELECT-only برای گزارش‌ها؛
- tenant isolation و manager/admin authorization.

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

## اعتبارسنجی

روی head سبز گزارش/payroll:

- backend PostgreSQL: ۸۸۹ passed، یک skipped، صفر failed؛
- exact OpenAPI lock: passed؛
- schema guard: passed؛
- accounting money oracle: passed؛
- specialist suite: passed؛
- Jest، TypeScript، ESLint و production build: passed.

## موارد باقی‌مانده برای انتقال کامل حسابداری

1. ETL تاریخی `clinic_new.db`؛
2. append-only import ledger؛
3. تطبیق count/hash و مبلغ برای invoice/item/payment؛
4. audit search مدیریتی؛
5. backup/restore و dual-run rehearsal؛
6. cutover و rollback واقعی.
