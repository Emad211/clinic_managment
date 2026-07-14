# راهنمای عملیاتی مهاجرت پروندهٔ کلینیک تخصصی به حلقه

این سند مسیر کامل انتقال تاریخی `specialist.db` به PostgreSQL حلقه را تعریف می‌کند.
این عملیات بالینی و داده‌ای حساس است. هیچ مرحله‌ای نباید روی تنها نسخهٔ مبدأ، بدون
backup قابل‌بازیابی مقصد، یا با artifactهای عمومی انجام شود.

هیچ‌یک از فرمان‌های این سند PR را merge، نسخه را deploy یا cutover را خودکار
نمی‌کنند. تصمیم نهایی عملیاتی همچنان انسانی است.

---

## ۱. دامنهٔ انتقال

فرمان `import_specialist_record` حوزه‌های زیر را منتقل یا به رکورد canonical موجود
تطبیق می‌دهد:

- کاتالوگ بیماری، فلگ، کلاس دارویی، دارو و آزمایش؛
- enrollment بالینی، فقط پس از resolveشدن بیمار در `accounting.patients`؛
- بیماری‌های مزمن و تاریخچهٔ فعال/غیرفعال؛
- داروها و رویدادهای start، dose-change و stop؛
- حساسیت‌ها، علائم حیاتی و نتایج آزمایش؛
- فلگ‌های ساختاریافتهٔ بالینی؛
- نوبت، پیگیری و suggestion log؛
- سابقهٔ جراحی، سابقهٔ پزشکی و یادداشت بالینی؛
- نسخه‌های legacy JSON و ارتباط آن‌ها با پیگیری و کاربر مقصد.

موارد زیر عمداً در ETL پرونده وارد نمی‌شوند:

- موجودی کیف پول و `wallet_transactions`؛
- فاکتور، پرداخت یا ledger مالی؛
- کمپین، پیام، approval و dispatch تعامل؛
- activity logهای legacy؛
- rule/indicatorهایی که منبع حقیقت آن‌ها کاتالوگ حلقه است.

وجود wallet یا دادهٔ مالی در dry-run گزارش می‌شود. apply بدون acknowledgement صریح
متوقف خواهد شد؛ acknowledgement به معنی انتقال پول نیست.

---

## ۲. قراردادهای ایمنی غیرقابل‌تغییر

1. حالت پیش‌فرض، dry-run بدون اثر ماندگار است.
2. dry-run ردیف‌ها را با IDهای منفی داخل transaction واقعی PostgreSQL materialize
   می‌کند؛ FK، CHECK، RLS و lookupها اجرا می‌شوند، سپس کل transaction rollback می‌شود.
3. dry-run هیچ sequence، target row یا ledger row ماندگاری مصرف نمی‌کند.
4. تمام writeهای apply در یک transaction واحد انجام می‌شوند.
5. هر source row یک digest و یک target fingerprint در ledger append-only می‌گیرد.
6. replay دقیق idempotent است؛ source تغییرکرده یا target دستکاری‌شده conflict است.
7. `source-id` برای یک تاریخچهٔ monotonic است؛ snapshot ناقص یا دیتابیس دیگر با همان
   source-id پذیرفته نمی‌شود.
8. هویت بیمار فقط از مرز accounting resolve می‌شود. ETL اجازهٔ ساخت یا تغییر
   دموگرافی accounting را ندارد.
9. رضایت پیامک از legacy استنباط نمی‌شود. opt-out محافظه‌کارانه قابل حفظ است، اما
   consent جدید ساخته نمی‌شود.
10. vital خوداظهاری با `verified=false` وارد می‌شود.
11. metadata آزمایش کاتالوگی فقط از کاتالوگ فعال tenant snapshot می‌شود.
12. گزارش‌ها به‌صورت پیش‌فرض نام، کد ملی و accounting patient ID را حذف می‌کنند.
13. reportها با directory mode `0700` و file mode `0600` و replace اتمیک نوشته می‌شوند.
14. symlink، فایل غیر regular و برخورد مسیر input/output رد می‌شود.
15. apply فقط از SQLite کاملاً quiesced مجاز است.

---

## ۳. پیش‌نیازهای release

پیش از rehearsal یا cutover:

- commit موردنظر باید شامل SQL sliceهای ledger، fingerprint و sequence sync باشد؛
- CI همان commit باید در هر سه gate سبز باشد:
  - PostgreSQL backend pytest؛
  - schema guard؛
  - Jest، TypeScript، ESLint و Next.js production build؛
- دسترسی اپراتور، maintenance window و rollback owner ثبت شده باشند؛
- backup مقصد گرفته و restore آن تمرین شده باشد؛
- storage artifactها رمزگذاری‌شده و دسترسی آن حداقلی باشد؛
- پزشک reviewer و تصمیم‌گیر مالی مشخص باشند؛
- commit SHA کامل و، در deployment کانتینری، image digest immutable ثبت شده باشد.

---

## ۴. ساخت snapshot قابل‌اعتماد SQLite

ابتدا برنامهٔ کلینیک تخصصی، scheduler و هر writer دیگر را متوقف کنید:

```bash
sqlite3 /srv/specialist/specialist.db "PRAGMA wal_checkpoint(TRUNCATE);"
sqlite3 /srv/specialist/specialist.db "PRAGMA quick_check;"
```

خروجی `quick_check` باید دقیقاً `ok` باشد.

از دیتابیس کپی خصوصی بسازید:

```bash
install -m 0600 /srv/specialist/specialist.db \
  /secure-migration/specialist-2026-07-14.db
sha256sum /secure-migration/specialist-2026-07-14.db \
  > /secure-migration/specialist-2026-07-14.db.sha256
```

این sidecarها را بررسی کنید:

```bash
ls -l /secure-migration/specialist-2026-07-14.db{-wal,-shm,-journal} 2>/dev/null || true
```

برای apply، هیچ‌یک از `-wal`، `-shm` یا `-journal` نباید غیرخالی باشند.

### سیاست `--allow-live-source`

این گزینه فقط یک استثنای تشخیصی برای **dry-run** است. فرمان در حالت زیر همیشه fail
می‌شود:

```text
--apply --allow-live-source
```

بنابراین apply روی SQLite زنده، WALدار یا rollback-journalدار ممکن نیست.

---

## ۵. backup مقصد و preflight

```bash
pg_dump --format=custom \
  --file=/secure-migration/halqe-before-record-import.dump \
  "$DATABASE_URL"
sha256sum /secure-migration/halqe-before-record-import.dump \
  > /secure-migration/halqe-before-record-import.dump.sha256
```

سپس:

```bash
python manage.py apply_schema
python manage.py dump_openapi --check
python manage.py check
```

ledgerهای قبلی source-id را ثبت کنید:

```sql
SELECT source_id, source_table, count(*) AS imported_rows
FROM clinical.record_import_ledger
WHERE tenant_id = 1
GROUP BY source_id, source_table
ORDER BY source_id, source_table;
```

---

## ۶. جداسازی مسیر artifactها

هیچ output نباید با SQLite یا report ورودی یکسان باشد. hard-link نیز برخورد محسوب
می‌شود.

ساختار پیشنهادی:

```text
/secure-migration/source/specialist.db
/secure-migration/reports/dry-run.json
/secure-migration/reports/apply.json
/secure-migration/reports/replay.json
/secure-migration/reports/verification.json
/secure-migration/reports/clinician-review.json
/secure-migration/reports/clinician-signoff.json
/secure-migration/reports/fresh-verification.json
/secure-migration/reports/release-manifest.json
```

هر command برخورد input/output را قبل از تغییر فایل رد می‌کند.

---

## ۷. اجرای dry-run

یک `source-id` پایدار انتخاب کنید که هرگز برای SQLite دیگری استفاده نشود:

```bash
python manage.py import_specialist_record \
  --sqlite /secure-migration/source/specialist.db \
  --source-id clinic-a-specialist-primary \
  --tenant-id 1 \
  --report /secure-migration/reports/dry-run.json
```

معیار پذیرش:

- `mode=dry-run`؛
- `transaction_status=validated_no_commit`؛
- `error=null`؛
- برای هر جدول `source_rows == accounted_rows`؛
- hash فایل با hash ثبت‌شده برابر باشد؛
- manifest hash معتبر باشد؛
- unresolved patient صفر باشد یا waiver رسمی داشته باشد؛
- `ledger_rows_after` تغییر نکند؛
- هشدار ناشناخته وجود نداشته باشد؛
- دادهٔ مالی out-of-scope بررسی شده باشد.

عدم write را دوباره بررسی کنید:

```sql
SELECT count(*)
FROM clinical.record_import_ledger
WHERE tenant_id = 1
  AND source_id = 'clinic-a-specialist-primary';
```

در اولین dry-run باید صفر باشد.

---

## ۸. بیمار resolve‌نشده

رفتار پیش‌فرض fail-closed است. اگر بیمار در accounting پیدا نشود، import متوقف و
تمام transaction rollback می‌شود.

`--skip-unresolved` فقط با waiver مکتوب مجاز است که شامل این موارد باشد:

- source patient rowهای حذف‌شده از wave؛
- تعداد child rowهای skip‌شده به تفکیک جدول؛
- owner و برنامهٔ wave بعدی؛
- تأیید پزشک/مالک داده؛
- حفظ همان source-id.

تطبیق تقریبی بر اساس نام یا شماره تلفن ممنوع است.

---

## ۹. apply واقعی rehearsal

فقط روی snapshot quiesced و بعد از dry-run موفق:

```bash
python manage.py import_specialist_record \
  --sqlite /secure-migration/source/specialist.db \
  --source-id clinic-a-specialist-primary \
  --tenant-id 1 \
  --apply \
  --imported-by migration-operator-2026-07-14 \
  --report /secure-migration/reports/apply.json
```

در صورت وجود wallet data و تصمیم مکتوب مبنی بر خارج‌بودن آن از این wave:

```text
--acknowledge-financial-data-out-of-scope
```

معیار پذیرش:

- `mode=apply`؛
- `transaction_status=committed`؛
- `error=null`؛
- ledger count با source rowهای skip‌نشده برابر باشد؛
- هیچ ردیف منفی ماندگار نباشد.

---

## ۱۰. اجرای دوم idempotency

همان apply را بدون تغییر source تکرار و report را جدا ذخیره کنید:

```bash
python manage.py import_specialist_record \
  --sqlite /secure-migration/source/specialist.db \
  --source-id clinic-a-specialist-primary \
  --tenant-id 1 \
  --apply \
  --imported-by migration-operator-2026-07-14 \
  --report /secure-migration/reports/replay.json
```

اجرای دوم باید:

- `inserted=0` داشته باشد؛
- `planned_*` نداشته باشد؛
- ردیف‌ها را `replayed` یا طبق waiver `skipped_unresolved` گزارش کند؛
- ledger count را تغییر ندهد؛
- file hash و manifest hash یکسان تولید کند.

---

## ۱۱. verifier دیتابیسی GO/NO_GO

```bash
python manage.py verify_specialist_record_import \
  --sqlite /secure-migration/source/specialist.db \
  --apply-report /secure-migration/reports/apply.json \
  --replay-report /secure-migration/reports/replay.json \
  --source-id clinic-a-specialist-primary \
  --tenant-id 1 \
  --report /secure-migration/reports/verification.json
```

برای rehearsal نهایی ترجیحاً `--strict-warnings` استفاده شود.

Verifier این موارد را خودکار کنترل می‌کند:

- source/apply/replay hash و manifest؛
- table accounting و idempotency؛
- ledger row shape، target existence و target content fingerprint؛
- orphanهای دارو، appointment، follow-up و prescription؛
- self-report تأییدشدهٔ ناخواسته؛
- visibility آزمایش در `clinical.observations`؛
- natural-keyهای `condition_lab_tests`؛
- target mutation پس از import.

خروجی باید `decision=GO` و `summary.failed=0` باشد.

---

## ۱۲. نمونه‌برداری و sign-off پزشک

نمونهٔ deterministic بسازید:

```bash
python manage.py generate_specialist_record_review_sample \
  --verification-report /secure-migration/reports/verification.json \
  --source-id clinic-a-specialist-primary \
  --tenant-id 1 \
  --per-scenario 1 \
  --max-patients 25 \
  --report /secure-migration/reports/clinician-review.json
```

پزشک packet را تکمیل می‌کند و سپس:

```bash
python manage.py verify_specialist_record_clinician_signoff \
  --review-packet /secure-migration/reports/clinician-review.json \
  --verification-report /secure-migration/reports/verification.json \
  --source-id clinic-a-specialist-primary \
  --tenant-id 1 \
  --report /secure-migration/reports/clinician-signoff.json
```

این gate علاوه بر hash فایل‌ها، هر بیمار را با ledger، clinical link فعال و UUID
accounting زنده تطبیق می‌دهد. packet دارای نام، تلفن، کد ملی یا PHI در free text،
حتی با ارقام فارسی/عربی، `NO_GO` می‌شود.

---

## ۱۳. manifest نهایی و fresh reconciliation

درست پیش از cutover:

```bash
python manage.py build_specialist_record_release_manifest \
  --sqlite /secure-migration/source/specialist.db \
  --apply-report /secure-migration/reports/apply.json \
  --replay-report /secure-migration/reports/replay.json \
  --verification-report /secure-migration/reports/verification.json \
  --review-packet /secure-migration/reports/clinician-review.json \
  --clinician-signoff-report /secure-migration/reports/clinician-signoff.json \
  --source-id clinic-a-specialist-primary \
  --tenant-id 1 \
  --git-commit 0123456789abcdef0123456789abcdef01234567 \
  --image-digest sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --fresh-verification-report /secure-migration/reports/fresh-verification.json \
  --report /secure-migration/reports/release-manifest.json
```

فرمان verifier دیتابیسی را دوباره اجرا می‌کند. گزارش stale پیش از اجرا حذف می‌شود و
hash و semantic fingerprint گزارش تازه وارد `release_id` می‌شوند.

فقط این وضعیت قابل قبول است:

```text
release-manifest.decision = GO
fresh_database_reconciliation = pass
```

---

## ۱۴. reconciliation دستی مکمل

### نبود ID منفی

```sql
SELECT 'conditions' AS table_name, count(*) FROM clinical.conditions WHERE id < 0
UNION ALL
SELECT 'patient_medications', count(*) FROM clinical.patient_medications WHERE id < 0
UNION ALL
SELECT 'lab_results', count(*) FROM clinical.lab_results WHERE id < 0;
```

تمام countها باید صفر باشند.

### MedicationEvent orphan

```sql
SELECT count(*)
FROM clinical.medication_events e
LEFT JOIN clinical.patient_medications m
  ON m.tenant_id=e.tenant_id AND m.id=e.medication_id
WHERE e.tenant_id=1
  AND e.medication_id IS NOT NULL
  AND m.id IS NULL;
```

باید صفر باشد.

### self-report

```sql
SELECT source, verified, count(*)
FROM clinical.vital_readings
WHERE tenant_id=1
GROUP BY source, verified
ORDER BY source, verified;
```

ردیف‌های واردشده با `source=patient_self` نباید بدون بازبینی verified باشند.

### sequence

```sql
SELECT max(id) FROM clinical.conditions;
SELECT last_value, is_called FROM clinical.conditions_id_seq;
```

درج عادی بعدی نباید شناسهٔ موجود را تکرار کند.

---

## ۱۵. cutover

پس از GO نهایی:

1. سامانهٔ تخصصی را read-only نگه دارید؛
2. dual-write ایجاد نکنید؛
3. تمام writeهای جدید پرونده فقط در حلقه انجام شوند؛
4. SQLite برای بازهٔ توافق‌شده فقط برای audit قابل‌خواندن بماند؛
5. audit log، error log و صف بازبینی self-report پایش شوند؛
6. پزشک مسئول نمایش شرایط، دارو، حساسیت، آزمایش و نسخه را تأیید کند؛
7. تیم حسابداری wallet/financial out-of-scope را مستقل ببندد؛
8. release_id و artifact hashها در change record ثبت شوند.

---

## ۱۶. rollback

### خطا حین import

transaction کامل rollback می‌شود. در این حالت:

- target و ledger ناقص نباید باقی بمانند؛
- source تغییر نمی‌کند؛
- report با `failed_no_commit` نگهداری می‌شود؛
- پس از اصلاح، همان source-id استفاده می‌شود.

### خطا پس از commit

حذف دستی بر اساس timestamp یا ID ممنوع است. مسیر استاندارد:

1. توقف writeهای حلقه؛
2. حفظ source، reportها و ledger برای forensic؛
3. restore کامل backup پیش از import؛
4. اجرای schema/health/smoke validation؛
5. ثبت incident، owner و علت rollback.

Undo انتخابی فقط با ابزار dependency-aware مجاز است؛ چند `DELETE` دستی جایگزین آن
نیست.

---

## ۱۷. نگهداری artifactها

این موارد باید private، write-protected و کنار change record نگهداری شوند:

- SQLite snapshot و hash؛
- backup PostgreSQL و hash؛
- dry-run، apply و replay report؛
- verification و fresh verification report؛
- clinician review packet و sign-off؛
- release manifest و release_id؛
- commit SHA و image digest؛
- evidence مربوط به backup/restore؛
- نام اپراتور، reviewer، migration window و rollback owner؛
- تصمیم wallet/accounting.

فایل دارای PHI نباید در Git، ticket عمومی، artifact عمومی CI یا پیام‌رسان قرار گیرد.

---

## ۱۸. چک‌لیست GO/NO_GO

### GO

- [ ] source quiesced، sidecarها خالی و `quick_check=ok`
- [ ] hash source ثبت شده
- [ ] backup مقصد restore شده و معتبر است
- [ ] CI commit deployشده کاملاً سبز است
- [ ] dry-run برابر `validated_no_commit` است
- [ ] unresolved patient صفر یا دارای waiver رسمی است
- [ ] financial exclusions تعیین تکلیف شده‌اند
- [ ] apply موفق و `committed` است
- [ ] replay idempotent است
- [ ] verifier دیتابیسی `GO` است
- [ ] نمونهٔ بالینی کامل و sign-off پزشک `GO` است
- [ ] fresh verifier `GO` است
- [ ] release manifest `GO` و release_id ثبت شده است
- [ ] cutover owner و rollback owner مشخص‌اند

### NO_GO قطعی

- apply همراه `--allow-live-source`؛
- WAL، SHM یا journal غیرخالی هنگام apply؛
- برخورد مسیر output با SQLite یا artifact ورودی؛
- source row conflict یا snapshot ناقص؛
- unresolved identity بدون waiver؛
- اختلاف count، manifest یا target fingerprint؛
- sequence/FK failure؛
- self-report تأییدشدهٔ ناخواسته؛
- metadata جعل‌پذیر آزمایش؛
- PHI در packet پزشک؛
- نبود backup قابل restore؛
- شکست هر gate CI؛
- نبود sign-off پزشک؛
- fresh reconciliation ناموفق؛
- نبود تصمیم مکتوب wallet/accounting.
