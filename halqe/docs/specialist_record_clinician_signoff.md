# تأیید نهایی پزشک برای مهاجرت پروندهٔ کلینیک تخصصی

این مرحله بعد از dry-run، apply، replay و خروجی `GO` از
`verify_specialist_record_import` انجام می‌شود. هدف آن تبدیل بررسی انسانی نمونه‌ها
به یک artifact قابل‌ممیزی و یک تصمیم ماشین‌خوان `GO` یا `NO_GO` است.

این فرمان جایگزین بررسی پزشک نیست؛ فقط اثبات می‌کند بررسی تعیین‌شده کامل، به همان
snapshot و گزارش verifier متصل و بدون اختلاف حل‌نشده ثبت شده است.

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

هر دو فایل باید regular file، بدون symlink و owner-only باشند. mode پیشنهادی:

```text
directory: 0700
file:      0600
```

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

پس از تطبیق موفق به این حالت تغییر می‌کند:

```json
{
  "review_status": "approved",
  "review_notes": "بیماری‌ها، داروها و تاریخ‌ها با مبدأ تطبیق شد."
}
```

packet نباید با نام، کد ملی، تلفن، نشانی یا تاریخ تولد غنی شود. شناسه‌های مجاز:

- `source_patient_link_id`
- `target_patient_link_id`
- `patient_uuid`
- `cockpit_path`

Verifier وجود کلیدهای هویتی مستقیم را `NO_GO` می‌کند.

## ۳. تکمیل sign-off نهایی

در انتهای JSON، `signoff_template` باید تکمیل شود. نمونهٔ بدون اختلاف:

```json
{
  "reviewed_by": "doctor-reviewer",
  "reviewed_at": "2026-07-13T21:55:00+00:00",
  "decision": "approved",
  "acknowledged_warnings": [],
  "discrepancies": []
}
```

`reviewed_at` باید ISO-8601 و دارای timezone باشد. تصمیمی غیر از `approved` اجازهٔ
release نمی‌دهد.

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
- owner، description و timestamp حل برای همهٔ اختلاف‌ها الزامی است.

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
8. تمام سناریوهای موجود `covered` هستند؛
9. نمونه خالی نیست و شناسه‌ها/UUIDها یکتا و معتبرند؛
10. تمام بیماران `review_status=approved` دارند؛
11. تصمیم پزشک approved، timestamp timezone-aware و نام بررسی‌کننده ثبت شده است؛
12. تمام warningها acknowledge شده‌اند؛
13. تمام اختلاف‌ها طبق severity تعیین‌تکلیف شده‌اند.

## ۷. اتصال artifactها

فایل تصمیم نهایی این hashها را نگه می‌دارد:

- `review_packet_sha256`
- `verification_report_sha256`
- `source_file_sha256`
- `source_manifest_sha256`

پس از صدور `GO`، هیچ‌یک از packet، گزارش verifier یا SQLite snapshot نباید تغییر
کند. هر اصلاح بعدی مستلزم اجرای دوبارهٔ apply/replay/verifier/sample/sign-off با
artifactهای جدید است.

## ۸. معیار release

`GO` این فرمان فقط یکی از gateهاست. release نهایی هنوز به این موارد نیاز دارد:

- CI سبز روی commit نهایی؛
- backup و restore rehearsal؛
- تصمیم مکتوب دربارهٔ wallet/accounting خارج از دامنه؛
- تأیید مالک migration window و rollback owner؛
- نگهداری امن تمام reportها، hashها و sign-off.

هیچ فرمان این زنجیره به‌صورت خودکار PR را merge یا import production را اجرا
نمی‌کند.
