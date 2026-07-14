# تأیید نهایی پزشک برای مهاجرت پروندهٔ کلینیک تخصصی

این مرحله بعد از dry-run، apply، replay و خروجی `GO` از
`verify_specialist_record_import` انجام می‌شود. هدف آن تبدیل بررسی انسانی نمونه‌ها
به یک artifact قابل‌ممیزی و یک تصمیم ماشین‌خوان `GO` یا `NO_GO` است.

این فرمان جایگزین بررسی پزشک نیست. علاوه بر hash artifactها، هنگام اجرا هر بیمار
منتخب را دوباره با زنجیرهٔ زیر تطبیق می‌دهد:

```text
source_patient_link_id
        ↓
clinical.record_import_ledger
        ↓
clinical.patient_links
        ↓
accounting.patients.uuid
        ↓
patient_uuid و cockpit_path داخل packet
```

در نتیجه تغییر UUID، target ID، حذف enrollment یا نبود ledger با تکمیل دستی
`review_status=approved` قابل دورزدن نیست.

## ۱. پیش‌نیازها

قبل از شروع باید این فایل‌های خصوصی وجود داشته باشند:

```text
/secure-migration/reports/go-no-go.json
/secure-migration/reports/clinician-review.json
```

فایل اول خروجی موفق این فرمان است:

```bash
python manage.py verify_specialist_record_import \
  --sqlite /secure-migration/specialist.db \
  --apply-report /secure-migration/reports/apply.json \
  --replay-report /secure-migration/reports/replay.json \
  --source-id clinic-a-specialist-primary \
  --tenant-id 1 \
  --report /secure-migration/reports/go-no-go.json
```

فایل دوم با نمونه‌بردار deterministic ساخته می‌شود:

```bash
python manage.py generate_specialist_record_review_sample \
  --verification-report /secure-migration/reports/go-no-go.json \
  --source-id clinic-a-specialist-primary \
  --tenant-id 1 \
  --per-scenario 1 \
  --max-patients 25 \
  --report /secure-migration/reports/clinician-review.json
```

هر دو فایل باید regular file، بدون symlink و owner-only باشند:

```text
directory: 0700
file:      0600
```

مسیر خروجی sign-off باید از هر دو فایل ورودی متفاوت باشد. برخورد مستقیم path یا
hard-link پیش از اجرای verifier رد می‌شود.

## ۲. تکمیل packet توسط پزشک

برای هر بیمار انتخاب‌شده، پزشک مسیر `cockpit_path` را در حلقه باز می‌کند و تمام
موارد `review_checklist` را با snapshot امن مبدأ مقایسه می‌کند.

فیلد هر بیمار از حالت اولیه:

```json
{
  "review_status": "pending",
  "review_notes": null
}
```

پس از تطبیق موفق:

```json
{
  "review_status": "approved",
  "review_notes": "بیماری‌ها، داروها و تاریخ‌ها با مبدأ تطبیق شد."
}
```

packet نباید با نام، کد ملی، تلفن، نشانی یا تاریخ تولد غنی شود. شناسه‌های عملیاتی
مجاز عبارت‌اند از:

- `source_patient_link_id`
- `target_patient_link_id`
- `patient_uuid`
- `cockpit_path`

Verifier نام‌های snake_case، camelCase و برچسب‌های فارسی متداول برای اطلاعات
هویتی را رد می‌کند. علاوه بر نام کلید، متن `review_notes` و متن اختلاف‌ها برای
موارد زیر اسکن می‌شود:

- شماره موبایل ایرانی؛
- کد ملی معتبر ایرانی؛
- اعداد نوشته‌شده با رقم لاتین، فارسی یا عربی.

بنابراین متن‌هایی مانند شمارهٔ `۰۹۱۲...` یا کد ملی فارسی نیز `NO_GO` می‌شوند.

## ۳. تکمیل sign-off نهایی

در انتهای JSON، `signoff_template` باید تکمیل شود:

```json
{
  "reviewed_by": "doctor-reviewer",
  "reviewed_at": "2026-07-13T21:55:00+00:00",
  "decision": "approved",
  "acknowledged_warnings": [],
  "discrepancies": []
}
```

`reviewed_at` باید ISO-8601 و دارای timezone باشد. همچنین:

- نباید قبل از `generated_at` packet باشد؛
- نباید بیش از پنج دقیقه در آینده باشد؛
- تصمیمی غیر از `approved` اجازهٔ release نمی‌دهد.

اگر packet دارای warning است، `acknowledged_warnings` باید دقیقاً همان رشته‌ها را
شامل شود. حذف، تغییر متن یا acknowledge ناقص warning باعث `NO_GO` می‌شود.

## ۴. ثبت اختلاف‌ها

هر اختلاف باید شناسهٔ یکتا و تعیین‌تکلیف کامل داشته باشد:

```json
{
  "id": "D-001",
  "severity": "minor",
  "domain": "medication",
  "description": "ترتیب نمایش دو رویداد دارویی متفاوت بود.",
  "disposition": "fixed",
  "owner": "migration-team",
  "resolution_note": "ترتیب اصلاح و دوباره توسط پزشک بررسی شد.",
  "resolved_at": "2026-07-13T22:10:00+00:00"
}
```

مقادیر مجاز severity:

```text
minor
major
critical
```

مقادیر مجاز disposition:

```text
fixed
accepted_risk
false_positive
deferred
```

قواعد fail-closed:

- `deferred` همیشه `NO_GO` است؛
- اختلاف `major` یا `critical` فقط با `fixed` قابل پذیرش است؛
- `accepted_risk` و `false_positive` برای اختلاف minor به `resolution_note` نیاز دارند؛
- owner، description و timestamp حل برای همهٔ اختلاف‌ها الزامی است؛
- `resolved_at` نباید قبل از تولید packet یا بعد از زمان sign-off باشد؛
- description و resolution_note نباید PHI مستقیم داشته باشند.

## ۵. اجرای verifier نهایی

```bash
python manage.py verify_specialist_record_clinician_signoff \
  --review-packet /secure-migration/reports/clinician-review.json \
  --verification-report /secure-migration/reports/go-no-go.json \
  --source-id clinic-a-specialist-primary \
  --tenant-id 1 \
  --report /secure-migration/reports/clinician-signoff-decision.json
```

خروجی موفق:

```text
Specialist clinician sign-off GO: source_id=..., tenant=..., patients=...,
scenarios=..., discrepancies=..., passed=..., warnings=0, failed=0
```

در `NO_GO` نیز فایل تصمیم خصوصی نوشته می‌شود، ولی فرمان با exit code غیرصفر پایان
می‌یابد.

## ۶. بررسی‌های اجباری فرمان

Verifier این موارد را کنترل می‌کند:

1. هر دو artifact regular، غیر symlink، حداکثر ۲۰ MiB و owner-only هستند؛
2. source-id و tenant در packet، گزارش verifier و آرگومان فرمان یکی است؛
3. hash کامل گزارش verifier با `verification_report_sha256` داخل packet برابر است؛
4. file hash و manifest hash منبع در هر دو artifact یکسان و معتبر است؛
5. گزارش پایه `decision=GO` و `summary.failed=0` دارد؛
6. check list گزارش پایه موجود است و هیچ check ناموفق ندارد؛
7. packet هیچ کلید هویتی مستقیم بیمار ندارد؛
8. free text فاقد شماره موبایل یا کد ملی معتبر در هر سه شکل رقم است؛
9. تمام سناریوهای موجود واقعاً توسط `patients[].scenarios` پوشش داده شده‌اند؛
10. `selected_samples`/`selected_patients` و statusهای sampler به واژگان canonical تبدیل و بازشماری می‌شوند؛
11. نمونه خالی نیست و شناسه‌ها/UUIDها یکتا و معتبرند؛
12. هر نمونه با ledger، clinical link فعال و UUID accounting زنده تطبیق دارد؛
13. تمام بیماران `review_status=approved` دارند؛
14. تصمیم پزشک approved، timestamp timezone-aware و نام بررسی‌کننده ثبت شده است؛
15. تمام warningها acknowledge شده‌اند؛
16. تمام اختلاف‌ها طبق severity تعیین‌تکلیف شده‌اند.

اگر lookup دیتابیس یا accounting port شکست بخورد، verifier traceback یا اتصال حساس
را منتشر نمی‌کند؛ یک check ناموفق `patient_database_binding` و تصمیم `NO_GO`
می‌سازد.

## ۷. اتصال artifactها

فایل تصمیم نهایی این hashها را نگه می‌دارد:

- `review_packet_sha256`
- `verification_report_sha256`
- `source_file_sha256`
- `source_manifest_sha256`

پس از صدور `GO`، هیچ‌یک از packet، گزارش verifier یا SQLite snapshot نباید تغییر
کند. تغییر targetهای PostgreSQL نیز در مرحلهٔ release manifest با fresh
reconciliation تشخیص داده می‌شود.

هر اصلاح بعدی مستلزم اجرای دوبارهٔ زنجیرهٔ verifier/sample/sign-off و manifest با
artifactهای جدید است.

## ۸. معیار release

`GO` این فرمان فقط یکی از gateهاست. release نهایی هنوز به این موارد نیاز دارد:

- CI سبز روی commit نهایی؛
- fresh database reconciliation در زمان ساخت release manifest؛
- backup و restore rehearsal؛
- تصمیم مکتوب دربارهٔ wallet/accounting خارج از دامنه؛
- تأیید مالک migration window و rollback owner؛
- نگهداری امن تمام reportها، hashها و sign-off.

هیچ فرمان این زنجیره به‌صورت خودکار PR را merge یا import production را اجرا
نمی‌کند.
