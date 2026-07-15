# به‌روزرسانی حسابرسی یکپارچه — حسابداری و پرونده تخصصی

این addendum وضعیت واقعی شاخهٔ یکپارچه را ثبت می‌کند. کامل‌بودن ابزار و تست synthetic
به معنی اجرای مهاجرت روی دیتابیس واقعی یا مجوز cutover نیست.

## قابلیت‌های runtime-complete حسابداری

### عملیات، تنظیمات و UI مدیریتی

- پذیرش، بیمار، فاکتور، ویزیت، پرستاری، پروسیجر، مصرفی، payment و close؛
- invoice workbench و اصلاحات tenant-safe؛
- تنظیم کادر، بیمه، تعرفه، کاتالوگ، exclusion و قرارداد payroll؛
- گزارش‌های مالی `/accounting/reports` و payroll `/accounting/payroll`؛
- audit مدیریتی `/accounting/audit` با filter، pagination و CSV؛
- Navigation گروهی و responsive برای عملیات، حسابداری و مدیریت؛
- read-portهای فیزیکی SELECT-only و role/tenant authorization.

### مهاجرت تاریخی مالی

- preflight SQLite با quick-check، schema، FK، orphan و sidecar checks؛
- SHA فایل و manifest جداول داخل دامنه؛
- dry-run relational با rollback کامل؛
- apply اتمیک با تأیید SHA؛
- append-only ledger دارای RLS و source/target fingerprint؛
- replay idempotent و رد source/target drift؛
- حفظ metadata نوع خدمت legacy؛
- فاکتورهای تاریخی با `pricing_version=legacy`؛
- verifier مستقل SELECT-only برای count/hash/money/child/payment؛
- گزارش private و runbook کامل.

### Backup و restore

- custom-format dump validation و اتصال dump به manifest؛
- fingerprint streaming تمام جدول‌ها و sequenceها؛
- constraint، index، RLS، policy، trigger، function و extension؛
- owner و ACL دیتابیس، schema، relation، function و type؛
- default ACL، view/materialized-view definition و commentها؛
- role capability و schema-version ledger؛
- schema/content/database digest؛
- restore verifier با خروجی VERIFIED/FAILED؛
- runbookهای capture و restore verification.

### Dual-run و reconciliation روزانه

- مقایسهٔ exact و بدون tolerance برای فاکتور، خدمت، payment و درآمد؛
- breakdown بر اساس روز، شیفت و بیمه؛
- payroll legacy-faithful برای پزشک و پرستار؛
- mapping کادر فقط از import ledger، نه تطبیق نام؛
- PostgreSQL snapshot در `REPEATABLE READ READ ONLY`؛
- snapshot SQLite immutable و PHI-free report؛
- command `compare_accounting_dual_run` با private GO/NO_GO report؛
- اجرای کل روز و morning/evening/night؛
- runbook `accounting_dual_run_runbook.md`.

### Sign-off نهایی حسابداری

- command `verify_accounting_cutover_signoff`؛
- hash binding برای import verification، restore verification و تمام dual-run reportها؛
- الزام روزهای متوالی و چهار scope کامل برای هر روز؛
- پشتیبانی از snapshot متفاوت برای هر روز ولی snapshot یکسان در چهار scope همان روز؛
- تأیید جداگانه صندوق، بیمه، payroll و نمونه فاکتورها؛
- رد discrepancy باز یا deferred؛
- رد packet دارای شناسه مستقیم بیمار؛
- private sign-off report و exit غیرصفر در NO_GO؛
- جلوگیری از alias شدن output با هر artifact ورودی.

## تعریف‌های مالی تثبیت‌شده

```text
درآمد عملیاتی = ویزیت بسته + پرستاری/تزریق بسته + پروسیجر بسته
```

مصرفی وارد درآمد عملیاتی نمی‌شود و جداگانه نمایش داده می‌شود.

Payroll مطابق oracle برنامه قدیمی است: حضور شیفت، ویزیت بسته، سهم تزریق و پروسیجر،
مالیات پزشک و سهم‌های مستقل پرستار.

## اعتبارسنجی آخرین head sign-off

- backend PostgreSQL: **۹۲۰ passed**، یک skipped، صفر failed؛
- dual-run GO، money drift، mapping drift و private command report: passed؛
- cutover sign-off GO، missing scope، failed restore/import، hash tampering، PHI و deferred discrepancy: passed؛
- backup ownership/default ACL/view/comment fingerprint: passed؛
- import dry-run/apply/replay/verifier: passed؛
- audit role/tenant/API/UI: passed؛
- exact OpenAPI lock: **۹۶ path و ۱۰۰ operation**؛
- schema guard، accounting money oracle و specialist suite: passed؛
- Jest، TypeScript، ESLint و production build: passed.

## وضعیت دقیق

| بخش | وضعیت |
|---|---|
| عملیات و UI حسابداری | runtime-complete |
| گزارش، payroll و audit | runtime-complete |
| preflight، importer، ledger و verifier | runtime-complete |
| backup manifest و restore verifier | runtime-complete |
| dual-run comparator و runbook | runtime-complete |
| cutover sign-off evidence gate | runtime-complete |
| اجرای واقعی روی `clinic_new.db` | external-gate |
| تصویب mapping واقعی service typeها | external-gate |
| restore واقعی روی staging | external-gate |
| dual-run واقعی روزهای مصوب | external-gate |
| امضای مسئول صندوق/بیمه/payroll | external-gate |
| cutover و rollback واقعی | external-gate |

## موارد باقی‌مانده برای انتقال کامل حسابداری

1. preflight روی snapshot امن و واقعی `clinic_new.db`؛
2. تصویب mapping مقدارهای واقعی `services.service_type`؛
3. dry-run و apply rehearsal در staging؛
4. verification import و نمونه‌برداری انسانی فاکتور، آیتم و payment؛
5. اجرای واقعی `pg_dump → manifest → pg_restore → verify`؛
6. dual-run واقعی برای تعداد روزهای مصوب و تمام شیفت‌ها؛
7. تکمیل packet انسانی و دریافت sign-off برابر GO؛
8. تصمیم رسمی GO/NO_GO و سپس cutover کنترل‌شده.
