# راهنمای عملیاتی مهاجرت پروندهٔ کلینیک تخصصی به حلقه

این سند برای انتقال تاریخی داده‌های `specialist.db` به PostgreSQL حلقه نوشته شده است. اجرای آن یک عملیات بالینی و داده‌ای حساس است؛ هیچ مرحله‌ای نباید مستقیماً روی تنها نسخهٔ دیتابیس مبدأ یا بدون نسخهٔ پشتیبان مقصد انجام شود.

## ۱. دامنهٔ انتقال

فرمان `import_specialist_record` این حوزه‌ها را منتقل یا به رکورد موجود تطبیق می‌دهد:

- کاتالوگ بیماری‌ها، فلگ‌ها، کلاس‌های دارویی، داروها و آزمایش‌ها؛
- enrollment بیمار، مشروط به resolveشدن هویت در `accounting.patients`؛
- بیماری‌ها، داروها و timeline رویدادهای دارویی؛
- حساسیت‌ها، علائم حیاتی و نتایج آزمایش؛
- فلگ‌های ساختاریافتهٔ بالینی؛
- نوبت‌ها، پیگیری‌ها و suggestion log؛
- سابقهٔ جراحی، سابقهٔ پزشکی و یادداشت‌های بالینی؛
- نسخه‌های قدیمی JSON و ارتباط آن‌ها با پیگیری و کاربر مقصد.

موارد زیر عمداً در این ETL وارد نمی‌شوند:

- موجودی کیف پول و `wallet_transactions`؛
- فاکتور، پرداخت یا ledger حسابداری؛
- کمپین‌ها، پیام‌ها، approvalها و dispatchهای تعامل؛
- activity logهای legacy؛
- rule/indicatorهای مدیریتی که منبع حقیقت آن‌ها کاتالوگ حلقه است.

وجود دادهٔ مالی در مبدأ در گزارش dry-run نمایش داده می‌شود و اجرای واقعی بدون acknowledgment صریح متوقف خواهد شد.

## ۲. قراردادهای ایمنی

1. حالت پیش‌فرض فرمان، **dry-run بدون اثر ماندگار** است.
2. dry-run تمام ردیف‌های برنامه‌ریزی‌شده را با ID منفی داخل transaction برگشت‌پذیر materialize می‌کند؛ بنابراین FK، CHECK، RLS و lookupهای واقعی PostgreSQL بررسی می‌شوند، اما هیچ ردیفی باقی نمی‌ماند و sequence مصرف نمی‌شود.
3. همهٔ writeها در حالت `--apply` داخل یک transaction واحد هستند.
4. هر source row یک digest در `clinical.record_import_ledger` می‌گیرد.
5. اجرای دقیقاً مشابه، replay و idempotent است.
6. تغییر payload یک source row پس از import قبلی، conflict و rollback کامل ایجاد می‌کند؛ overwrite ساکت وجود ندارد.
7. هویت بیمار فقط از مرز حسابداری resolve می‌شود. ETL پرونده اجازهٔ ساخت یا تغییر دموگرافی حسابداری را ندارد.
8. رضایت پیامک هرگز از دادهٔ legacy استنباط نمی‌شود. opt-out محافظه‌کارانه قابل حفظ است، ولی consent جدید ساخته نمی‌شود.
9. vital خوداظهاری به‌عنوان دادهٔ تأییدنشده وارد می‌شود و تا بازبینی پزشک وارد موتور تصمیم‌یار نمی‌شود.
10. برای آزمایش کاتالوگی، نام، واحد و محدودهٔ مرجع فقط از کاتالوگ فعال tenant snapshot می‌شوند.

## ۳. پیش‌نیازهای غیرقابل حذف

پیش از شروع:

- PR مربوطه باید merge و نسخهٔ deployشده باید شامل SQL sliceهای import ledger و sequence sync باشد.
- CI همان commit باید در هر سه gate سبز باشد:
  - backend PostgreSQL pytest؛
  - schema guard؛
  - Jest، TypeScript، ESLint و Next.js production build.
- دسترسی اپراتور به فایل مبدأ و PostgreSQL باید ثبت و محدود باشد.
- یک maintenance window برای توقف writeهای برنامهٔ تخصصی تعیین شود.
- `pg_dump` یا snapshot قابل‌بازیابی از دیتابیس مقصد گرفته شود.
- فایل مبدأ باید روی storage رمزگذاری‌شده و با دسترسی حداقلی نگهداری شود.
- پزشک مسئول یا نمایندهٔ کلینیک باید نمونه‌های بالینی reconciliation را از قبل تعیین کند.

## ۴. تهیهٔ snapshot قابل‌اعتماد از SQLite

برنامهٔ کلینیک تخصصی و schedulerهای آن را متوقف کنید. سپس روی همان میزبان:

```bash
sqlite3 /srv/specialist/specialist.db "PRAGMA wal_checkpoint(TRUNCATE);"
sqlite3 /srv/specialist/specialist.db "PRAGMA quick_check;"
```

خروجی `quick_check` باید دقیقاً `ok` باشد.

از فایل خام روی محل import کپی بگیرید؛ ETL نباید روی تنها نسخهٔ production اجرا شود:

```bash
install -m 0600 /srv/specialist/specialist.db \
  /secure-migration/specialist-2026-07-13.db
sha256sum /secure-migration/specialist-2026-07-13.db \
  > /secure-migration/specialist-2026-07-13.db.sha256
```

وجود فایل WAL غیرخالی باعث توقف فرمان می‌شود. گزینهٔ `--allow-live-source` فقط برای وضعیت اضطراری مستندشده است و در cutover معمول نباید استفاده شود.

## ۵. پشتیبان مقصد و preflight

```bash
pg_dump --format=custom --file=/secure-migration/halqe-before-record-import.dump \
  "$DATABASE_URL"
sha256sum /secure-migration/halqe-before-record-import.dump \
  > /secure-migration/halqe-before-record-import.dump.sha256
```

سپس schema را با نسخهٔ deployشده همگام کنید:

```bash
python manage.py apply_schema
python manage.py dump_openapi --check
python manage.py check
```

تعداد ledgerهای قبلی source را ثبت کنید:

```sql
SELECT source_id, source_table, count(*) AS imported_rows
FROM clinical.record_import_ledger
WHERE tenant_id = 1
GROUP BY source_id, source_table
ORDER BY source_id, source_table;
```

## ۶. اجرای dry-run

برای هر فایل مبدأ یک `source-id` پایدار و غیرقابل‌استفاده برای دیتابیس دیگری انتخاب کنید:

```bash
python manage.py import_specialist_record \
  --sqlite /secure-migration/specialist-2026-07-13.db \
  --source-id sib-gorgan-specialist-primary \
  --tenant-id 1 \
  --report /secure-migration/reports/record-dry-run.json
```

بدون `--apply` هیچ داده‌ای commit نمی‌شود.

### معیار پذیرش گزارش dry-run

برای هر جدول:

```text
source_rows == accounted_rows
```

و باید این شرایط برقرار باشند:

- `mode` برابر `dry-run` باشد؛
- `error` تهی باشد؛
- `unresolved_patients` تهی باشد، مگر اینکه تصمیم مکتوب برای `--skip-unresolved` وجود داشته باشد؛
- `source_file_sha256` با hash فایل کپی‌شده یکسان باشد؛
- `source_manifest_sha256` مقدار داشته باشد؛
- `ledger_rows_after` در dry-run مقدار جدیدی ایجاد نکند؛
- هیچ هشدار ناشناخته یا mapping حذف‌شده وجود نداشته باشد؛
- داده‌های مالی out-of-scope بررسی و به تیم حسابداری ارجاع شده باشند.

پس از dry-run، نبود اثر ماندگار را بررسی کنید:

```sql
SELECT count(*)
FROM clinical.record_import_ledger
WHERE tenant_id = 1
  AND source_id = 'sib-gorgan-specialist-primary';
```

در اولین dry-run این مقدار باید صفر باشد.

## ۷. بررسی بیمارهای resolve‌نشده

رفتار پیش‌فرض fail-closed است. اگر بیمار در `accounting.patients` پیدا نشود، هیچ child record مربوط به او وارد نمی‌شود و کل import متوقف می‌شود.

ابتدا مشکل هویت را در فرایند onboarding/accounting حل کنید. استفاده از:

```text
--skip-unresolved
```

فقط در صورتی مجاز است که:

- فهرست بیمارهای حذف‌شده از import به گزارش رسمی پیوست شود؛
- تعداد child rowهای skipشده برای هر جدول مشخص باشد؛
- پزشک/مالک داده تأیید کند این بیماران در wave بعدی منتقل می‌شوند؛
- source-id برای اجرای بعدی ثابت بماند.

هیچ تطبیق تقریبی بر اساس شباهت نام یا شماره تلفن مجاز نیست.

## ۸. اجرای واقعی

فقط پس از sign-off dry-run:

```bash
python manage.py import_specialist_record \
  --sqlite /secure-migration/specialist-2026-07-13.db \
  --source-id sib-gorgan-specialist-primary \
  --tenant-id 1 \
  --apply \
  --report /secure-migration/reports/record-apply.json \
  --imported-by migration-operator-2026-07-13
```

اگر گزارش dry-run وجود دادهٔ مالی را نشان داده و انتقال مالی در این wave عمداً خارج از دامنه است، فقط با تصمیم مکتوب گزینهٔ زیر اضافه می‌شود:

```text
--acknowledge-financial-data-out-of-scope
```

این گزینه دادهٔ مالی را وارد نمی‌کند؛ فقط مانع سکوت دربارهٔ حذف آن از دامنه می‌شود.

## ۹. آزمون idempotency پس از apply

همان فرمان `--apply` را بدون هیچ تغییر در source تکرار کنید. اجرای دوم باید:

- `inserted` جدید نداشته باشد؛
- ردیف‌ها را `replayed` یا در موارد natural-key موجود `reused` گزارش کند؛
- count جدول‌های مقصد را تغییر ندهد؛
- همان manifest را تولید کند؛
- conflict نداشته باشد.

هر اختلاف، cutover را متوقف می‌کند.

## ۱۰. reconciliation دیتابیسی

### ۱۰.۱ ledger بر اساس جدول

```sql
SELECT source_table,
       target_table,
       count(*) AS rows,
       count(DISTINCT source_row_id) AS distinct_source_rows
FROM clinical.record_import_ledger
WHERE tenant_id = 1
  AND source_id = 'sib-gorgan-specialist-primary'
GROUP BY source_table, target_table
ORDER BY source_table;
```

`rows` و `distinct_source_rows` باید برابر باشند.

### ۱۰.۲ نبود ID منفی بعد از dry-run/apply

```sql
SELECT 'conditions' AS table_name, count(*)
FROM clinical.conditions WHERE id < 0
UNION ALL
SELECT 'patient_medications', count(*)
FROM clinical.patient_medications WHERE id < 0
UNION ALL
SELECT 'lab_results', count(*)
FROM clinical.lab_results WHERE id < 0;
```

تمام countها باید صفر باشند.

### ۱۰.۳ رویدادهای دارویی orphan

```sql
SELECT count(*)
FROM clinical.medication_events e
LEFT JOIN clinical.patient_medications m
  ON m.tenant_id = e.tenant_id
 AND m.id = e.medication_id
WHERE e.tenant_id = 1
  AND e.medication_id IS NOT NULL
  AND m.id IS NULL;
```

باید صفر باشد.

### ۱۰.۴ self-reportهای واردشده

```sql
SELECT source, verified, count(*)
FROM clinical.vital_readings
WHERE tenant_id = 1
GROUP BY source, verified
ORDER BY source, verified;
```

ردیف‌های `patient_self` نباید بدون بازبینی پزشک verified باشند.

### ۱۰.۵ آزمایش‌های کاتالوگی

```sql
SELECT count(*) AS metadata_mismatch
FROM clinical.lab_results r
JOIN clinical.lab_test_catalog c
  ON c.tenant_id = r.tenant_id
 AND c.test_key = r.test_key
WHERE r.tenant_id = 1
  AND (
      r.test_name IS DISTINCT FROM c.name_fa
      OR r.unit IS DISTINCT FROM c.unit
      OR r.ref_low IS DISTINCT FROM c.ref_low
      OR r.ref_high IS DISTINCT FROM c.ref_high
  );
```

برای داده‌های واردشده با کاتالوگ هم‌نسخه، انتظار صفر است. اگر کاتالوگ بعداً تغییر کرده باشد، snapshot تاریخی ممکن است عمداً متفاوت باشد؛ در آن حالت نتیجه باید با timestamp و نسخهٔ کاتالوگ مستند شود.

### ۱۰.۶ sequenceها

```sql
SELECT max(id) FROM clinical.conditions;
SELECT last_value, is_called FROM clinical.conditions_id_seq;
```

درج عادی بعدی نباید شناسهٔ موجود را تکرار کند. SQL slice همگام‌سازی identity این قرارداد را برای تمام schemaهای application اعمال می‌کند.

## ۱۱. نمونه‌برداری بالینی اجباری

حداقل این cohortها را در UI حلقه و SQLite مبدأ کنار هم بررسی کنید:

1. بیمار با چند بیماری مزمن؛
2. بیمار با داروی فعال، تغییر دوز و داروی قطع‌شده؛
3. بیمار دارای حساسیت شدید؛
4. بیمار دارای vital خوداظهاری؛
5. بیمار با چند آزمایش و reference range؛
6. بیمار دارای فلگ enum و تاریخ معاینه؛
7. بیمار دارای جراحی، سابقهٔ پزشکی و یادداشت بالینی؛
8. بیمار دارای appointment دوره‌ای و follow-up؛
9. نسخهٔ آزاد؛
10. نسخهٔ بیمه‌ای یا JSON legacy نامعمول.

برای هر نمونه این موارد ثبت شوند:

- شناسهٔ بیمار و source rowها؛
- screenshot یا export sanitised از هر دو سامانه؛
- نتیجهٔ تطبیق نام/تاریخ/وضعیت/دوز؛
- امضای بررسی‌کننده و زمان بررسی؛
- discrepancy و تصمیم اصلاحی.

## ۱۲. cutover

پس از apply و reconciliation:

1. کلینیک تخصصی را در حالت read-only نگه دارید.
2. dual-write آزاد نکنید؛ دو منبع حقیقت هم‌زمان ایجاد نکنید.
3. تمام ثبت‌های جدید پرونده فقط در حلقه انجام شوند.
4. برای یک بازهٔ توافق‌شده، SQLite فقط برای مقایسه و audit قابل‌خواندن بماند.
5. access log و audit log حلقه پایش شود.
6. پزشک مسئول نمایش پرونده، دارو، حساسیت و آزمایش را تأیید کند.
7. تیم حسابداری وضعیت wallet/financial out-of-scope را مستقل ببندد.

## ۱۳. rollback

### خطا حین import

فرمان transaction کامل را rollback می‌کند. در این حالت:

- ledger ناقص نباید باقی بماند؛
- source تغییر نمی‌کند؛
- گزارش خطا نگهداری می‌شود؛
- پس از اصلاح علت، همان source-id دوباره استفاده می‌شود.

### خطا پس از commit موفق

حذف دستی ردیف‌ها بر اساس timestamp یا ترتیب ID ممنوع است. راه برگشت استاندارد:

1. توقف writeهای حلقه؛
2. نگهداری گزارش apply و ledger برای forensic؛
3. restore کامل snapshot/backup مقصد که قبل از import گرفته شده بود؛
4. اجرای validation و smoke test پس از restore؛
5. ثبت incident و علت rollback.

یک undo انتخابی فقط با ابزار جداگانه‌ای مجاز است که dependency graph، ledger و ردیف‌های reused را تشخیص دهد؛ چنین undoای نباید با چند `DELETE` دستی جایگزین شود.

## ۱۴. نگهداری artifactها

این فایل‌ها باید کنار change record نگهداری شوند:

- hash و کپی read-only SQLite؛
- hash و backup PostgreSQL قبل از import؛
- گزارش dry-run؛
- گزارش apply؛
- گزارش اجرای دوم idempotency؛
- خروجی SQL reconciliation؛
- نمونه‌برداری بالینی و sign-off؛
- commit SHA و image tag نسخهٔ حلقه؛
- نام اپراتور و maintenance window.

فایل‌های دارای PHI نباید در Git، ticket عمومی، artifact عمومی CI یا پیام‌رسان قرار گیرند.

## ۱۵. چک‌لیست go/no-go

### Go

- [ ] source quiesced و `quick_check=ok`
- [ ] hash source ثبت شده
- [ ] backup مقصد بازیابی‌پذیر است
- [ ] CI commit deployشده کاملاً سبز است
- [ ] dry-run بدون error و mismatch است
- [ ] unresolved patient صفر یا دارای waiver مکتوب است
- [ ] financial exclusions تعیین تکلیف شده‌اند
- [ ] apply موفق است
- [ ] اجرای دوم idempotent است
- [ ] SQL reconciliation بدون orphan/mismatch غیرتوضیح‌داده است
- [ ] نمونه‌های بالینی تأیید شده‌اند
- [ ] cutover و rollback owner مشخص دارند

### No-go

هرکدام از موارد زیر انتقال را متوقف می‌کند:

- WAL فعال یا تغییر hash مبدأ در حین اجرا؛
- source row conflict؛
- unresolved identity بدون waiver؛
- اختلاف count/manifest؛
- sequence یا FK failure؛
- self-report تأییدشدهٔ ناخواسته؛
- metadata جعل‌پذیر آزمایش؛
- نبود backup قابل restore؛
- شکست هر gate CI؛
- نبود sign-off بالینی.
