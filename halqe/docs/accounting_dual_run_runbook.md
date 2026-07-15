# راهنمای dual-run حسابداری قدیمی و حلقه

این فرایند برای مقایسهٔ روزانهٔ سیستم Flask/SQLite با حسابداری حلقه است. ابزار فقط
snapshot متوقف‌شدهٔ SQLite و PostgreSQL حلقه را می‌خواند و هیچ write انجام نمی‌دهد.

## دامنهٔ مقایسه

گزارش بدون PHI این موارد را به‌صورت دقیق و بدون tolerance مقایسه می‌کند:

- تعداد و مبلغ فاکتورهای باز، بسته و کل؛
- تعداد و مبلغ ویزیت، پرستاری/تزریق، پروسیجر و مصرفی؛
- درآمد عملیاتی فقط از آیتم‌های بسته؛
- مصرفی مرکز و مصرفی آوردهٔ بیمار/exception؛
- تعداد paymentهای paid و unpaid؛
- breakdown بر اساس روز، شیفت و بیمه؛
- تعداد شیفت کادر، gross، tax، net و اجزای payroll؛
- mapping کادر فقط از `accounting.accounting_import_ledger`.

نام بیمار، کد ملی، تلفن و شرح فاکتور وارد artifact نمی‌شود.

## ۱. آماده‌سازی snapshot روزانه

پس از پایان روز یا در maintenance window، writerهای برنامهٔ قدیمی را متوقف کنید و:

```bash
sqlite3 /srv/legacy/clinic_new.db "PRAGMA wal_checkpoint(TRUNCATE);"
sqlite3 /srv/legacy/clinic_new.db "PRAGMA quick_check;"
```

خروجی `quick_check` باید دقیقاً `ok` باشد. سپس یک کپی owner-only بسازید:

```bash
umask 077
mkdir -p /secure/dual-run
chmod 700 /secure/dual-run
cp /srv/legacy/clinic_new.db /secure/dual-run/clinic-YYYY-MM-DD.db
chmod 600 /secure/dual-run/clinic-YYYY-MM-DD.db
```

وجود فایل غیرخالی با پسوندهای زیر به معنی NO-GO است:

```text
-wal
-shm
-journal
```

## ۲. مقایسهٔ کل روز

```bash
python manage.py compare_accounting_dual_run \
  --sqlite /secure/dual-run/clinic-YYYY-MM-DD.db \
  --source-id clinic-main-accounting \
  --tenant-id 1 \
  --date-from YYYY-MM-DD \
  --date-to YYYY-MM-DD \
  --report /secure/dual-run/reports/YYYY-MM-DD-all.json
```

## ۳. مقایسهٔ تک‌تک شیفت‌ها

```bash
for shift in morning evening night; do
  python manage.py compare_accounting_dual_run \
    --sqlite /secure/dual-run/clinic-YYYY-MM-DD.db \
    --source-id clinic-main-accounting \
    --tenant-id 1 \
    --date-from YYYY-MM-DD \
    --date-to YYYY-MM-DD \
    --shift "$shift" \
    --report "/secure/dual-run/reports/YYYY-MM-DD-${shift}.json"
done
```

بازهٔ یک اجرای command حداکثر ۳۱ روز است؛ برای cutover، گزارش روزانه و شیفتی خواناتر
و قابل‌ردیابی‌تر است.

## ۴. معیار GO

فرمان باید با exit code صفر تمام شود و گزارش داشته باشد:

```json
{
  "decision": "GO",
  "differences": []
}
```

این شرایط نیز الزامی‌اند:

- SHA فایل و source manifest مقدار داشته باشند؛
- financial source و target دقیقاً برابر باشند؛
- payroll source و target دقیقاً برابر باشند؛
- mapping تمام کادرهای legacy از ledger موجود باشد؛
- گزارش با permission برابر `0600` و دایرکتوری `0700` نوشته شده باشد؛
- گزارش کل روز و هر سه شیفت GO باشند.

تعداد روزهای متوالی لازم برای cutover باید پیش از rehearsal در change plan تصویب شود؛
هر روز این بازه باید بدون استثنا GO باشد.

## ۵. رفتار NO_GO

در هر اختلاف، command ابتدا گزارش خصوصی را می‌نویسد و سپس با exit غیرصفر پایان می‌یابد.
هر اختلاف شامل مسیر دقیق و در موارد عددی delta است؛ نمونه:

```text
financial.totals.invoice_amount
financial.by_day.2026-07-15.payment_paid_count
payroll.rows.12.net_salary
```

هیچ tolerance پیش‌فرضی وجود ندارد. حتی اختلاف یک تومان یا یک payment باعث NO_GO می‌شود.

## ۶. بررسی اختلاف

در NO_GO:

1. writeهای هر دو سامانه برای دورهٔ مورد بررسی متوقف بماند؛
2. snapshot و report تغییر داده نشوند؛
3. مسیرهای اختلاف دسته‌بندی شوند: invoice، item، payment، بیمه یا payroll؛
4. source row و target ledger در محیط امن بررسی شوند؛
5. اصلاح دستی گزارش یا ledger ممنوع است؛
6. علت در change record ثبت شود؛
7. پس از اصلاح کد یا داده با فرایند مصوب، snapshot جدید و مقایسهٔ جدید تولید شود.

از update مستقیم target برای سبزکردن گزارش استفاده نشود. هر اصلاح تاریخی باید transaction،
ledger و verifier مهاجرت را رعایت کند.

## ۷. Reconciliation صندوق و بیمه

علاوه بر گزارش خودکار، برای هر روز این موارد توسط مسئول مالی تأیید شوند:

- جمع نقد، کارت، بیمه و سایر روش‌های پرداخت؛
- تعداد آیتم‌های paid/unpaid؛
- فاکتورهای باز پایان روز؛
- سهم بیمار و بیمه برای نمونه‌های انتخابی؛
- جمع خدمات ویزیت، پرستاری، پروسیجر و مصرفی؛
- payroll پزشک و پرستار برای نمونه‌های شیفتی.

تأیید انسانی جای گزارش خودکار را نمی‌گیرد؛ هر دو لازم‌اند.

## ۸. Artifactهای موردنیاز

برای هر روز نگهداری شود:

- hash و مسیر snapshot SQLite؛
- گزارش all-shifts؛
- گزارش morning، evening و night؛
- commit SHA و image digest حلقه؛
- نتیجهٔ verification مهاجرت تاریخی؛
- امضای مسئول صندوق/بیمه/payroll؛
- discrepancyها و تصمیم اصلاحی؛
- زمان snapshot و نام اپراتور.

Artifactها دارای اطلاعات مالی حساس‌اند و نباید در Git، CI عمومی یا پیام‌رسان ذخیره شوند.

## ۹. شرایط پایان dual-run

dual-run فقط وقتی قابل پایان است که:

- تعداد روزهای مصوب همگی GO باشند؛
- همهٔ شیفت‌ها GO باشند؛
- هیچ discrepancy باز یا deferred وجود نداشته باشد؛
- نمونه‌های فاکتور، payment، بیمه و payroll تأیید انسانی شده باشند؛
- backup/restore rehearsal برابر VERIFIED باشد؛
- rollback owner و cutover owner مشخص باشند؛
- تصمیم رسمی GO/NO-GO ثبت شده باشد.

تا آن زمان برنامهٔ قدیمی منبع قابل‌مقایسه باقی می‌ماند و خاموش‌کردن آن مجاز نیست.
