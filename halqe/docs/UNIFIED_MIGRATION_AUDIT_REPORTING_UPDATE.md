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
- Navigation گروهی و responsive؛
- read-portهای فیزیکی SELECT-only و role/tenant authorization.

### مهاجرت تاریخی مالی

- preflight SQLite، source manifest و sidecar checks؛
- dry-run relational، apply اتمیک و تأیید SHA؛
- append-only ledger دارای RLS و fingerprint؛
- replay idempotent و رد source/target drift؛
- حفظ metadata نوع خدمت legacy و `pricing_version=legacy`؛
- verifier SELECT-only برای count/hash/money/child/payment؛
- گزارش private و runbook کامل.

### Backup و restore

- custom-format dump validation و اتصال dump به manifest؛
- fingerprint streaming جدول‌ها، sequenceها و schema ledger؛
- constraint، index، RLS، policy، trigger، function و extension؛
- owner، ACL، default ACL، view definition، type و commentها؛
- role capability و schema/content/database digest؛
- restore verifier با خروجی VERIFIED/FAILED؛
- runbookهای capture و restore verification.

### Dual-run و sign-off

- مقایسه exact و بدون tolerance برای فاکتور، خدمت، payment، درآمد و payroll؛
- breakdown روز، شیفت و بیمه؛
- mapping کادر فقط از import ledger؛
- command `compare_accounting_dual_run` با private GO/NO_GO report؛
- الزام all/morning/evening/night برای روزهای متوالی؛
- command `verify_accounting_cutover_signoff`؛
- hash binding تمام evidenceهای machine-generated؛
- تأیید صندوق، بیمه، payroll و نمونه فاکتورها؛
- رد discrepancy باز/deferred و packet دارای شناسه مستقیم بیمار؛
- private sign-off report و runbook روزانه.

### Release manifest نهایی

- command `build_accounting_release_manifest`؛
- بازاجرای sign-off به‌جای اعتماد صرف به report ذخیره‌شده؛
- بازاعتبارسنجی bytes و manifest فایل backup؛
- اجرای تازهٔ import verifier در لحظهٔ release؛
- بازتولید چهار scope آخرین dual-run از SQLite دقیقاً امضاشده؛
- الزام full Git SHA و container image digest تغییرناپذیر؛
- fresh reportهای owner-only؛
- release ID قطعی بر اساس همه hashها، commit، image و status checkها؛
- NO_GO در تغییر snapshot، evidence، target database یا شناسه release.

## تعریف‌های مالی تثبیت‌شده

```text
درآمد عملیاتی = ویزیت بسته + پرستاری/تزریق بسته + پروسیجر بسته
```

مصرفی وارد درآمد عملیاتی نمی‌شود. Payroll نیز مطابق oracle برنامه قدیمی است.

## اعتبارسنجی آخرین head release manifest

- backend PostgreSQL: **۹۲۳ passed**، یک skipped، صفر failed؛
- release manifest GO، deterministic ID، snapshot drift و mutable identifier guards: passed؛
- cutover sign-off و dual-run evidence tests: passed؛
- backup security fingerprint و import verifier: passed؛
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
| fresh deterministic release manifest | runtime-complete |
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
4. verification import و نمونه‌برداری انسانی؛
5. اجرای واقعی `pg_dump → manifest → pg_restore → verify`؛
6. dual-run واقعی برای تعداد روزهای مصوب و تمام شیفت‌ها؛
7. دریافت sign-off برابر GO؛
8. ساخت release manifest برابر GO با commit/image واقعی؛
9. تصمیم رسمی GO/NO_GO و سپس cutover کنترل‌شده.
