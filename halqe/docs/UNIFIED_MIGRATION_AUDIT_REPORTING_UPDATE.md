# به‌روزرسانی حسابرسی یکپارچه — گزارش، حقوق، audit، ETL و backup

این addendum وضعیت جدید شاخهٔ یکپارچه را نسبت به
`UNIFIED_MIGRATION_AUDIT.md` ثبت می‌کند. کد و تست‌های synthetic کامل شده‌اند؛ این
سند به‌هیچ‌وجه به معنی اجرای مهاجرت روی دیتابیس واقعی یا مجوز cutover نیست.

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

### بازبینی رویدادهای حسابداری

- workspace مدیریتی `/accounting/audit` با UI فارسی و responsive؛
- فیلتر بازه، کاربر، نوع/دسته عملیات، فاکتور، بیمار و متن؛
- pagination، summary دسته‌ها و CSV همان صفحه؛
- نمایش کنترل‌شدهٔ before/after و metadata محدودشده؛
- endpoint فقط‌خواندنی `/accounting/audit/logs`؛
- transaction اجباری READ ONLY روی `accounting_read`؛
- مجوز صریح SELECT برای `platform_app` و revoke کامل از `clinical_app`؛
- indexهای tenant-leading و تست role/tenant/API/UI.

### مهاجرت تاریخی مالی

- preflight فقط‌خواندنی SQLite با quick-check، schema، FK و orphan checks؛
- بررسی WAL/SHM/journal و الزام snapshot متوقف‌شده؛
- SHA-256 فایل و manifest تمام جدول‌های داخل دامنه؛
- snapshot مبلغ‌های invoice، item، payment و درآمد عملیاتی؛
- dry-run روی constraintهای واقعی PostgreSQL با rollback کامل؛
- apply اتمیک و تأیید اجباری SHA فایل؛
- append-only import ledger دارای RLS و source/target fingerprint؛
- replay idempotent و رد source drift یا target drift؛
- canonical reuse بدون overwrite؛
- حفظ `custom/medicine` در `legacy_service_type`؛
- فاکتور تاریخی با `pricing_version=legacy`؛
- reconciliation مبلغی imported scope؛
- verifier مستقل SELECT-only، exact source↔ledger coverage و child/payment completeness؛
- گزارش‌های خصوصی atomic و runbook کامل.

### Backup و restore verification

- پذیرش فقط PostgreSQL custom-format dump با magic برابر `PGDMP`؛
- الزام فایل owner-only، غیر symlink و اتصال manifest به SHA و اندازه dump؛
- fingerprint streaming تمام جدول‌ها با ترتیب primary key؛
- count و SHA جدول‌ها، sequence state و schema-version ledger؛
- constraint، index، RLS، policy، trigger، function و extension؛
- owner و ACL دیتابیس، schema، relation، function و type؛
- default ACLهای schemaهای محافظت‌شده؛
- view/materialized-view definition و owner؛
- commentهای schema، relation، column، function، constraint، policy، trigger و type؛
- role capabilityهای ضروری؛
- digest مستقل schema، content و کل دیتابیس؛
- verifier مستقل restore با گزارش VERIFIED/FAILED؛
- runbookهای `backup_capture_runbook.md` و `backup_restore_verification.md`.

## تعریف مالی تثبیت‌شده

```text
درآمد عملیاتی = ویزیت بسته + پرستاری/تزریق بسته + پروسیجر بسته
```

مصرفی وارد درآمد عملیاتی نمی‌شود و جداگانه نمایش داده می‌شود.

## تعریف payroll تثبیت‌شده

- حضور پزشک از روز/شیفت ویزیت استنتاج می‌شود؛
- حضور پرستار از تزریق یا پروسیجر استنتاج می‌شود؛
- فقط ویزیت فاکتور بسته کارمزد دارد؛
- سهم تزریق پزشک فقط با ویزیت همان پزشک در همان invoice محاسبه می‌شود؛
- سهم پروسیجر پزشک و پرستار جداست؛
- مالیات مطابق legacy فقط در شاخه پزشک کسر می‌شود؛
- صفحه payroll فقط preview است.

## اعتبارسنجی آخرین head امنیت backup

- backend PostgreSQL: **۹۱۲ passed**، یک skipped، صفر failed؛
- owner/default ACL/view/comment security digest tests: passed؛
- audit API، filters، pagination، role و tenant isolation: passed؛
- dry-run، apply، replay و drift tests: passed؛
- backup manifest، clean verification و data drift: passed؛
- exact OpenAPI lock: **۹۶ path و ۱۰۰ operation**؛
- schema guard، accounting money oracle و specialist suite: passed؛
- Jest، TypeScript، ESLint و production build: passed.

## وضعیت دقیق

| بخش | وضعیت |
|---|---|
| گزارش، payroll و audit UI/API | runtime-complete |
| preflight و importer حسابداری | runtime-complete |
| ledger، replay و verifier مالی | runtime-complete |
| backup manifest و restore verifier | runtime-complete |
| runbookهای مهاجرت و backup | runtime-complete |
| rehearsal روی snapshot واقعی SQLite | external-gate |
| mapping واقعی service typeها | external-gate |
| restore واقعی روی staging مستقل | external-gate |
| reconciliation صندوق/بیمه/payroll | external-gate |
| dual-run | external-gate |
| cutover و rollback واقعی | external-gate |

## موارد باقی‌مانده برای انتقال کامل حسابداری

1. اجرای preflight روی snapshot امن و واقعی `clinic_new.db`؛
2. تصویب mapping مقدارهای واقعی `services.service_type`؛
3. dry-run و apply rehearsal در staging؛
4. نمونه‌برداری انسانی فاکتور، آیتم، پرداخت، بیمه و payroll؛
5. اجرای `pg_dump → manifest → pg_restore → verify` روی staging مستقل؛
6. dual-run و reconciliation صندوق/بیمه/payroll؛
7. تصمیم رسمی GO/NO_GO برای cutover.
