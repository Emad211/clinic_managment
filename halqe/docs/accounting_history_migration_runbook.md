# راهنمای اجرای مهاجرت تاریخی حسابداری به حلقه

این راهنما برای انتقال **snapshot خواندنی و متوقف‌شدهٔ** پایگاه SQLite برنامهٔ
حسابداری قدیمی به PostgreSQL حلقه است. اجرای مستقیم روی `clinic_new.db` فعال، فایل
دارای WAL، یا دیتابیس تولید بدون backup ممنوع است.

## اصول غیرقابل‌تغییر

- برنامهٔ قدیمی و تمام writerهای SQLite باید پیش از snapshot متوقف شوند.
- فایل اصلی هرگز ورودی `--apply` نیست؛ فقط یک کپی مستقل و immutable استفاده شود.
- preflight، dry-run، apply و verify باید همگی روی **همان فایل و همان SHA-256** باشند.
- dry-run با writer role واقعی و constraintهای واقعی PostgreSQL اجرا می‌شود، ولی کل
  transaction rollback می‌شود.
- apply یک transaction واحد است؛ هر خطا تمام ردیف‌ها و ledger را rollback می‌کند.
- فاکتورهای مهاجرتی با `pricing_version=legacy` ثبت می‌شوند تا pricing/close جدید
  نتواند تاریخ را بازتفسیر کند.
- گزارش verification جای بازبینی انسانی و reconciliation صندوق را نمی‌گیرد.
- در صورت verification ناموفق، حذف دستی ردیف‌ها ممنوع است؛ دیتابیس PostgreSQL باید
  از backup پیش از import بازگردانی و علت بررسی شود.

## ۱. آماده‌سازی محیط

متغیرهای اتصال PostgreSQL باید برای نقش superuser و writer حسابداری فراهم باشند:

```bash
export PG_HOST=127.0.0.1
export PG_PORT=5432
export PG_USER=postgres
export PG_PASSWORD='...'
export PG_ACCOUNTING_USER=accounting_app_login
export PG_ACCOUNTING_PASSWORD='...'
```

نقش writer را idempotent آماده کنید:

```bash
python manage.py ensure_accounting_role \
  --login-role "$PG_ACCOUNTING_USER" \
  --login-password "$PG_ACCOUNTING_PASSWORD"
```

## ۲. ساخت snapshot متوقف‌شده

1. برنامهٔ Flask، taskها و تمام workstationهایی که SQLite را باز می‌کنند متوقف شوند.
2. وجود writer فعال با هماهنگی عملیاتی بررسی شود.
3. در صورت استفاده از WAL، checkpoint کامل انجام شود.
4. با SQLite backup API یا فرمان `.backup` یک فایل جدید ساخته شود؛ copy سادهٔ فایل
   هنگام فعالیت برنامه قابل قبول نیست.
5. برنامهٔ قدیمی تا پایان ساخت snapshot خاموش بماند.

نمونه:

```bash
mkdir -p /secure/migration/accounting
chmod 700 /secure/migration/accounting
sqlite3 /legacy/clinic_new.db \
  ".backup '/secure/migration/accounting/clinic_new.snapshot.db'"
chmod 400 /secure/migration/accounting/clinic_new.snapshot.db
sha256sum /secure/migration/accounting/clinic_new.snapshot.db
```

کنار snapshot نباید فایل غیرخالی با پسوندهای زیر وجود داشته باشد:

```text
-wal
-shm
-journal
```

## ۳. preflight فقط‌خواندنی

```bash
python manage.py inspect_legacy_accounting \
  --sqlite /secure/migration/accounting/clinic_new.snapshot.db \
  --source-id clinic-accounting-production-v1 \
  --report /secure/migration/accounting/preflight.json
```

خروجی باید `decision=GO` داشته باشد. preflight موارد زیر را قفل می‌کند:

- `PRAGMA quick_check`
- جدول‌ها و ستون‌های ضروری
- FKهای داخلی و orphanها
- paymentهایی که به آیتم همان invoice متصل نیستند
- count و digest هر جدول
- SHA-256 کل فایل و manifest
- aggregateهای پولی منبع
- ثابت‌ماندن فایل در طول بررسی

وجود هر `FAIL` یک `NO_GO` قطعی است.

## ۴. تصمیم صریح برای نوع کاتالوگ خدمات

SQLite ممکن است در `services.service_type` مقدارهایی خارج از enum عملیاتی حلقه داشته
باشد. importer هیچ نگاشت حدسی انجام نمی‌دهد. مقادیر ناشناخته باید پس از بررسی داده و
تأیید مالک حسابداری به یکی از این نوع‌ها نگاشت شوند:

```text
visit
injection
procedure
consumable
```

literal اصلی در `accounting.services.legacy_service_type` حفظ می‌شود. مثال نحوی:

```bash
--map-service-type SOURCE_VALUE=APPROVED_TARGET
```

نام target در این راهنما عمداً تعیین نشده است؛ تصمیم باید از دادهٔ واقعی و معنای
خدمت گرفته شود.

## ۵. dry-run اجباری

```bash
python manage.py import_legacy_accounting \
  --sqlite /secure/migration/accounting/clinic_new.snapshot.db \
  --source-id clinic-accounting-production-v1 \
  --tenant-id 1 \
  --imported-by migration-operator \
  --report /secure/migration/accounting/dry-run.json \
  --map-service-type SOURCE_VALUE=APPROVED_TARGET
```

معیار پذیرش dry-run:

- `mode=dry-run`
- `transaction_status=rolled_back`
- `source_money` دقیقاً برابر `target_money`
- `ledger_rows_before` برابر `ledger_rows_after`
- هیچ ردیف جدیدی در tenant مقصد باقی نماند
- هر canonical reuse در گزارش قابل توضیح باشد
- هیچ conflict، unsupported type یا source mutation وجود نداشته باشد

## ۶. backup و ثبت baseline PostgreSQL

پیش از apply:

- backup قابل‌بازیابی PostgreSQL گرفته شود.
- restore rehearsal آن backup قبلاً موفق شده باشد.
- count و aggregate مالی tenant مقصد ثبت شود.
- source SHA، preflight SHA و dry-run SHA در change ticket ثبت شوند.
- پنجرهٔ تغییر و rollback owner مشخص باشد.

## ۷. apply با تأیید SHA

SHA فعلی snapshot دوباره محاسبه شود:

```bash
SOURCE_SHA="$(sha256sum /secure/migration/accounting/clinic_new.snapshot.db | awk '{print $1}')"
```

سپس apply:

```bash
python manage.py import_legacy_accounting \
  --sqlite /secure/migration/accounting/clinic_new.snapshot.db \
  --source-id clinic-accounting-production-v1 \
  --tenant-id 1 \
  --imported-by migration-operator \
  --apply \
  --confirm-source-sha256 "$SOURCE_SHA" \
  --report /secure/migration/accounting/apply.json \
  --map-service-type SOURCE_VALUE=APPROVED_TARGET
```

معیار پذیرش اولیه:

- `transaction_status=committed`
- `source_money == target_money`
- افزایش ledger برابر تعداد source rowهای داخل دامنه باشد
- فاکتورهای imported دارای `pricing_version=legacy` باشند
- اجرای مجدد بدون تغییر source فقط `replayed` تولید کند و row جدید نسازد

## ۸. verification مستقل و فقط‌خواندنی

```bash
python manage.py verify_legacy_accounting_import \
  --sqlite /secure/migration/accounting/clinic_new.snapshot.db \
  --source-id clinic-accounting-production-v1 \
  --tenant-id 1 \
  --report /secure/migration/accounting/verification.json
```

verification فقط وقتی `VERIFIED` است که همهٔ موارد زیر برقرار باشند:

- مجموعهٔ source keyها و ledger keyها دقیقاً برابر باشد.
- source digest تمام ردیف‌ها بدون تغییر باشد.
- target table هر source family همان mapping مصوب باشد.
- تمام targetها وجود داشته و fingerprint آن‌ها با ledger برابر باشد.
- فاکتورهای imported دقیقاً همان child/paymentهای ledger را داشته باشند؛ نه کمتر، نه بیشتر.
- aggregateهای پولی imported scope با snapshot SQLite برابر باشد.
- snapshot در طول verification byte-identical بماند.

## ۹. بازبینی انسانی و dual-run

پیش از cutover:

- نمونهٔ فاکتورهای باز و بسته در هر بیمه بررسی شود.
- چهار نوع آیتم و payment typeها نمونه‌برداری شوند.
- جمع صندوق، درآمد عملیاتی، مصرفی، بدهی بیمه و payroll در بازه‌های منتخب با legacy
  مقایسه شوند.
- حداقل یک چرخهٔ dual-run بدون اختلاف توضیح‌نداده اجرا شود.
- backup/restore و rollback عملیاتی مجدداً مرور شود.

## ۱۰. وضعیت cutover

وجود `VERIFIED` فقط گیت فنی import تاریخی است. خاموش‌کردن برنامهٔ قدیمی نیازمند این
موارد مستقل است:

- تأیید مالک حسابداری
- reconciliation صندوق و بیمه
- تأیید payroll
- موفقیت dual-run
- backup/restore rehearsal
- ثبت تصمیم GO در change ticket

تا آن زمان PR و مسیر مهاجرت باید Draft و برنامهٔ legacy قابل‌بازگشت باقی بمانند.
