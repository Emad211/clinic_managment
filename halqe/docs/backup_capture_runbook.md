# Capture امن backup حلقه

هدف این مرحله ساخت یک زوج تغییرناپذیر است:

```text
PostgreSQL custom dump + Halqe fingerprint manifest
```

موفقیت `pg_dump` به‌تنهایی کافی نیست. Manifest همان snapshot را به count و SHA داده‌ها،
sequenceها و catalog امنیتی متصل می‌کند.

## پیش‌نیاز

- CI همان commit کاملاً سبز باشد؛
- maintenance mode فعال باشد؛
- web، worker، scheduler و تمام writerها متوقف باشند؛
- transaction باز طولانی وجود نداشته باشد؛
- فضای امن با permission خصوصی آماده باشد؛
- نقش‌های `platform_app`، `accounting_app` و `clinical_app` موجود باشند.

وضعیت مبدأ را ثبت کنید:

```sql
SELECT current_database(),
       pg_get_userbyid(datdba) AS database_owner,
       current_setting('server_version'),
       current_setting('TimeZone')
FROM pg_database
WHERE datname=current_database();
```

## ایجاد dump

```bash
umask 077
mkdir -p /secure/halqe-backup
chmod 700 /secure/halqe-backup

pg_dump \
  --format=custom \
  --compress=9 \
  --file=/secure/halqe-backup/halqe.dump \
  "$DATABASE_URL"

chmod 600 /secure/halqe-backup/halqe.dump
```

این گزینه‌ها ممنوع‌اند:

```text
--no-owner
--no-acl
```

فایل باید custom-format باشد و با magic برابر `PGDMP` شروع شود.

## ساخت manifest

در حالی که writerها همچنان متوقف‌اند:

```bash
python manage.py capture_halqe_backup_manifest \
  --backup-file /secure/halqe-backup/halqe.dump \
  --output /secure/halqe-backup/halqe-manifest.json \
  --database-name "$PG_DB" \
  --confirm-quiesced
```

Manifest با mode برابر `0600` نوشته می‌شود و موارد زیر را فقط به شکل count و SHA ثبت
می‌کند:

- همه جدول‌ها با ترتیب قطعی primary key؛
- sequence state؛
- constraint، index، RLS، policy، trigger و function؛
- owner و ACL دیتابیس، schema، relation، function و type؛
- default ACL؛
- view و materialized-view definition؛
- commentهای schema، relation، column، function، constraint، policy، trigger و type؛
- extension، role capability و `platform.schema_version`؛
- digest مستقل schema، content و کل دیتابیس.

هیچ مقدار خام بیمار، متن comment یا view definition داخل manifest ذخیره نمی‌شود.

## معیار پذیرش capture

- dump و manifest هر دو regular file و غیر symlink باشند؛
- permission فایل‌ها `0600` و دایرکتوری `0700` باشد؛
- فرمان بدون warning یا exception تمام شود؛
- نام دیتابیس و تعداد جدول/sequence در خروجی منطقی باشد؛
- SHA فایل dump پس از capture تغییر نکرده باشد؛
- dump و manifest با هم نگهداری و جابه‌جا شوند.

پس از capture می‌توان writerها را طبق change plan باز کرد. هر تغییر در dump یا manifest،
زوج artifact را باطل می‌کند و capture باید از ابتدا تکرار شود.
