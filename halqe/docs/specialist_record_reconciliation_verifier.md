# Verifier خودکار مهاجرت پروندهٔ کلینیک تخصصی

این سند مکمل `specialist_record_migration_runbook.md` است. فرمان verifier هیچ تغییر ماندگاری در داده‌های بالینی یا حسابداری ایجاد نمی‌کند؛ برای بازتولید manifest، dry-run رابطه‌ای با IDهای منفی اجرا می‌شود و transaction آن همیشه rollback می‌شود.

## خروجی‌های موردنیاز

برای یک `source-id` ثابت، ابتدا dry-run، سپس apply و بلافاصله apply دوم را اجرا کنید:

```bash
python manage.py import_specialist_record \
  --sqlite /secure-migration/specialist.db \
  --source-id clinic-a-specialist-primary \
  --tenant-id 1 \
  --report /secure-migration/reports/dry-run.json

python manage.py import_specialist_record \
  --sqlite /secure-migration/specialist.db \
  --source-id clinic-a-specialist-primary \
  --tenant-id 1 \
  --apply \
  --imported-by migration-operator \
  --report /secure-migration/reports/apply.json

python manage.py import_specialist_record \
  --sqlite /secure-migration/specialist.db \
  --source-id clinic-a-specialist-primary \
  --tenant-id 1 \
  --apply \
  --imported-by migration-operator \
  --report /secure-migration/reports/replay.json
```

اگر source دارای wallet data است، تصمیم حسابداری باید مکتوب باشد و در دو اجرای apply گزینهٔ زیر صریحاً ارائه شود:

```text
--acknowledge-financial-data-out-of-scope
```

## اجرای verifier

```bash
python manage.py verify_specialist_record_import \
  --sqlite /secure-migration/specialist.db \
  --apply-report /secure-migration/reports/apply.json \
  --replay-report /secure-migration/reports/replay.json \
  --source-id clinic-a-specialist-primary \
  --tenant-id 1 \
  --report /secure-migration/reports/go-no-go.json
```

خروجی موفق نمونه:

```text
Specialist record reconciliation GO: source_id=clinic-a-specialist-primary,
tenant=1, passed=..., warnings=..., failed=0
```

در صورت هر failure، فرمان با exit code غیرصفر و `CommandError` پایان می‌یابد. گزارش خصوصی، حتی در حالت `NO_GO`، قابل نگهداری است.

## بررسی‌های verifier

### قرارداد گزارش apply

- `mode=apply`
- `transaction_status=committed`
- `error` خالی
- hash فایل و manifest معتبر
- تمام source rowها accounted
- نبود counterهای dry-run در apply report
- تطابق `ledger_rows_after` با source rowهای skip‌نشده

### replay idempotent

apply دوم باید:

- همان file hash و manifest را داشته باشد؛
- هیچ `inserted`، `reused` یا `planned_*` نداشته باشد؛
- همهٔ source rowها را `replayed` یا، در صورت waiver، `skipped_unresolved` گزارش کند؛
- تعداد ledger را تغییر ندهد.

نبود replay report به‌صورت پیش‌فرض `NO_GO` است. گزینهٔ زیر فقط برای بررسی ناقص آزمایشگاهی است و برای release توصیه نمی‌شود:

```text
--allow-missing-replay
```

### بازتولید مستقل منبع

Verifier dry-run را دوباره روی همان SQLite اجرا می‌کند و این موارد را با apply report مقایسه می‌کند:

- SHA-256 فایل؛
- SHA-256 manifest منطقی؛
- جدول‌های موجود و غایب؛
- تعداد source rowهای هر جدول؛
- تعداد rowهای out-of-scope؛
- وضعیت unresolved/skip.

تغییر SQLite، استفادهٔ مجدد از `source-id` برای دیتابیس دیگر، snapshot ناقص یا target حذف‌شده این مرحله را fail می‌کند.

### ledger و targetها

- یک ledger row برای هر source row skip‌نشده؛
- count هر source table برابر apply report؛
- digest معتبر ۶۴ کاراکتری؛
- target ID مثبت؛
- وجود target در همان tenant؛
- resolveشدن natural key جدول `condition_lab_tests`؛
- بازسازی manifest از digestهای ledger و مقایسه با source manifest.

### invariantهای بالینی

- MedicationEvent orphan وجود ندارد؛
- MedicationEvent و Medication به یک patient link تعلق دارند؛
- self-report واردشده verified نیست؛
- هر lab واردشده در `clinical.observations` دیده می‌شود؛
- parent appointment حذف نشده است؛
- follow-up به appointment مفقود اشاره نمی‌کند؛
- prescription به follow-up مفقود اشاره نمی‌کند.

## warning و strict mode

موارد زیر معمولاً warning هستند و نیازمند بررسی انسانی‌اند:

- جدول اختیاری غایب؛
- out-of-scope table موجود؛
- wallet data که با تصمیم مکتوب خارج از دامنه نگه داشته شده؛
- report file با permission گسترده‌تر از owner-only؛
- unresolved row دارای waiver صریح.

برای تبدیل هر warning به `NO_GO` از گزینهٔ زیر استفاده کنید:

```bash
python manage.py verify_specialist_record_import ... --strict-warnings
```

برای rehearsal نهایی پیش از cutover، استفاده از `--strict-warnings` توصیه می‌شود. اگر وجود جدول اختیاری غایب یا دادهٔ out-of-scope مورد انتظار است، ابتدا علت و waiver در change record ثبت شود؛ سپس خروجی non-strict همراه با sign-off نگهداری شود.

## سیاست unresolved patient

رفتار پیش‌فرض verifier این است که هر unresolved patient یا child row باعث `NO_GO` شود. گزینهٔ زیر فقط بعد از waiver رسمی قابل استفاده است:

```text
--allow-skipped-unresolved
```

گزارش verifier شناسهٔ بالینی مستقیم، نام و کد ملی را چاپ نمی‌کند؛ صرفاً count و source row IDهای غیرمستقیم در گزارش import redacted نگهداری می‌شوند.

## امنیت artifact

فایل‌های import و verifier:

- با `0600` نوشته می‌شوند؛
- دایرکتوری جدید را با `0700` می‌سازند؛
- به‌صورت atomic جایگزین می‌شوند؛
- symlink را نمی‌پذیرند؛
- به‌طور پیش‌فرض JSON کامل را روی stdout چاپ نمی‌کنند.

گزینهٔ `--print-report` فقط در terminal کنترل‌شده و فاقد log اشتراکی استفاده شود.

## تفسیر تصمیم

### `GO`

تمام checkهای سخت pass شده‌اند. ممکن است warning وجود داشته باشد، مگر اینکه `--strict-warnings` فعال باشد. `GO` جایگزین sign-off پزشک، تصمیم مالی و backup/restore rehearsal نیست.

### `NO_GO`

حداقل یک failure وجود دارد یا strict mode warning دیده است. cutover و merge release باید متوقف شوند تا علت رفع و apply/replay/verifier با همان snapshot دوباره اجرا شود.
