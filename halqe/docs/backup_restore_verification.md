# Restore و verification backup حلقه

این مرحله روی یک دیتابیس مستقل انجام می‌شود. verification روی دیتابیس مبدأ یا production
ممنوع است.

## آماده‌سازی مقصد

- cluster مقصد باید PostgreSQL major سازگار داشته باشد؛
- extensionها و نقش‌های ضروری از قبل provision شده باشند؛
- مالک دیتابیس مقصد با مالک دیتابیس مبدأ یکسان باشد؛
- هیچ application یا writer به دیتابیس مقصد متصل نباشد.

```bash
createdb --owner="$SOURCE_DATABASE_OWNER" halqe_restore_rehearsal
```

## Restore

```bash
pg_restore \
  --exit-on-error \
  --single-transaction \
  --clean \
  --if-exists \
  --dbname=halqe_restore_rehearsal \
  /secure/halqe-backup/halqe.dump
```

از `--no-owner` یا `--no-acl` استفاده نشود. warning مربوط به owner، ACL، extension،
constraint یا trigger قابل چشم‌پوشی نیست.

## اجرای verifier

اتصال restore از متغیرهای `RESTORE_PG_HOST`، `RESTORE_PG_PORT`، `RESTORE_PG_USER`
و `RESTORE_PG_PASSWORD` خوانده می‌شود.

```bash
python manage.py verify_halqe_restored_backup \
  --manifest /secure/halqe-backup/halqe-manifest.json \
  --backup-file /secure/halqe-backup/halqe.dump \
  --restored-database halqe_restore_rehearsal \
  --confirm-restored-database halqe_restore_rehearsal \
  --report /secure/halqe-backup/restore-verification.json
```

دو نام دیتابیس باید دقیقاً برابر باشند. گزینه `--allow-same-database` فقط برای تست
غیرproduction است و در production قابل استفاده نیست.

## معیار VERIFIED

خروجی قابل قبول:

```text
Restored backup VERIFIED for database halqe_restore_rehearsal
```

و داخل گزارش:

```json
{"decision": "VERIFIED"}
```

تمام checkها باید PASS باشند:

- `backup_artifact_continuity`
- `restored_database_identity`
- `postgres_compatibility`
- `database_settings`
- `extensions`
- `required_roles`
- `schema_ledger`
- `schema_catalog`
- `table_data_fingerprints`
- `sequence_state`
- `schema_digest`
- `content_digest`
- `database_digest`

هر اختلاف owner، default ACL، view definition، comment، RLS، sequence یا یک ردیف داده
باعث FAILED می‌شود.

## ممنوعیت اصلاح دستی

پس از FAILED این کارها ممنوع‌اند:

- حذف یا افزودن دستی ردیف برای برابرکردن count؛
- تغییر sequence با `setval`؛
- اجرای `apply_schema` فقط برای سبزکردن نتیجه؛
- تغییر owner یا ACL بدون ثبت علت؛
- ویرایش manifest یا verification report.

علت اختلاف باید مشخص شود و restore از dump اصلی دوباره اجرا شود.

## Smoke test پس از VERIFIED

بدون تغییر دیتابیس restore:

- login نقش‌های مجاز؛
- خواندن گزارش مالی و audit؛
- بازکردن یک پرونده sanitised؛
- بررسی RLS tenant دیگر؛
- اثبات ممنوعیت write از `platform_app` به accounting؛
- اثبات نامرئی‌بودن جداول حساس حسابداری برای `clinical_app`؛
- اجرای `python manage.py check` و OpenAPI lock.

Smoke test جای fingerprint verification را نمی‌گیرد.

## Sign-off

Artifactهای زیر در change record خصوصی نگهداری شوند:

- dump و SHA آن؛
- manifest؛
- restore verification report؛
- commit SHA و image digest؛
- زمان توقف writerها؛
- خروجی smoke test؛
- نام اپراتور، reviewer، cutover owner و rollback owner.

تا وقتی verification برابر VERIFIED، smoke test سبز و sign-off ثبت نشده است،
backup/restore rehearsal و cutover هر دو NO-GO هستند.
