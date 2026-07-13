# manifest نهایی release برای مهاجرت پروندهٔ تخصصی

این مرحله آخرین gate ماشینی پیش از cutover است. فرمان، snapshot مبدأ و تمام artifactهای
apply، replay، reconciliation، بررسی پزشک و sign-off را دوباره می‌خواند و hash
می‌کند. خروجی `GO` فقط زمانی صادر می‌شود که هیچ artifact پس از تولید یا تأیید
تغییر نکرده باشد.

## artifactهای موردنیاز

```text
specialist.db                       snapshot quiesced و owner-only
apply.json                          گزارش apply موفق
replay.json                         گزارش اجرای دوم idempotent
verification.json                   خروجی GO از verify_specialist_record_import
clinician-review.json               packet تکمیل‌شدهٔ پزشک
clinician-signoff.json              خروجی GO از verify_specialist_record_clinician_signoff
```

همهٔ فایل‌ها باید regular file، بدون symlink و owner-only باشند. فایل‌های JSON
حداکثر ۲۰ MiB و snapshot حداکثر ۱۰۰ GiB پذیرفته می‌شوند.

## اجرای فرمان

```bash
python manage.py build_specialist_record_release_manifest \
  --sqlite /secure-migration/specialist.db \
  --apply-report /secure-migration/reports/apply.json \
  --replay-report /secure-migration/reports/replay.json \
  --verification-report /secure-migration/reports/verification.json \
  --review-packet /secure-migration/reports/clinician-review.json \
  --clinician-signoff-report /secure-migration/reports/clinician-signoff.json \
  --source-id clinic-a-specialist-primary \
  --tenant-id 1 \
  --git-commit 0123456789abcdef0123456789abcdef01234567 \
  --image-digest sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --report /secure-migration/reports/release-manifest.json
```

`--git-commit` باید SHA کامل ۴۰ کاراکتری commit deployشده باشد. `--image-digest`
اختیاری است، اما در deployment کانتینری باید digest immutable ارائه شود.

## بررسی‌هایی که دوباره اجرا می‌شوند

1. source-id و tenant هر artifact با آرگومان فرمان برابر است؛
2. apply و replay هر دو `mode=apply` و `transaction_status=committed` هستند؛
3. اجرای replay هیچ ردیف جدیدی درج نکرده است؛
4. apply و replay یک manifest hash دارند؛
5. hash فعلی snapshot با hash داخل تمام artifactها برابر است؛
6. تمام artifactها یک source manifest hash دارند؛
7. گزارش reconciliation هنوز `GO` است؛
8. review packet به hash دقیق همان گزارش reconciliation متصل است؛
9. verifier تأیید پزشک دوباره روی packet فعلی اجرا و `GO` می‌شود؛
10. گزارش sign-off ذخیره‌شده به hash دقیق packet و verifier فعلی متصل است؛
11. تعداد بیماران و اختلاف‌های گزارش sign-off با اجرای تازه برابر است؛
12. پوشش سناریوها مستقل از فیلد `coverage` از روی `patients[].scenarios` بازشماری می‌شود؛
13. source snapshot و همهٔ reportها private regular file هستند.

## جلوگیری از استفادهٔ sign-off قدیمی

اگر پس از sign-off حتی یک فاصله یا یادداشت در packet تغییر کند، hash packet تغییر
می‌کند و manifest `NO_GO` می‌شود. همین قاعده برای verifier report و snapshot مبدأ
نیز اعمال می‌شود.

برای هر اصلاح باید زنجیرهٔ زیر دوباره اجرا شود:

```text
apply/replay verification
        ↓
clinician sample
        ↓
clinician sign-off verifier
        ↓
release manifest
```

## release_id

خروجی دارای `release_id` است که از این موارد ساخته می‌شود:

- source-id و tenant؛
- commit SHA؛
- image digest؛
- source file hash؛
- source manifest hash؛
- hash هر پنج artifact JSON.

تغییر هر ورودی، `release_id` جدیدی می‌سازد. این شناسه باید در change record،
maintenance ticket و صورت‌جلسهٔ cutover ثبت شود.

## خروجی موفق

```text
Specialist record release manifest GO: release_id=..., source_id=...,
tenant=1, commit=..., passed=..., warnings=0, failed=0
```

فایل خروجی با mode `0600` نوشته می‌شود و شامل نام، کد ملی یا تلفن بیمار نیست.

## NO_GO

موارد زیر از نمونه‌های قطعی `NO_GO` هستند:

- تغییر snapshot پس از apply؛
- تغییر review packet پس از sign-off؛
- replay دارای insert جدید؛
- ادعای پوشش سناریو بدون بیمار منتخب متناظر؛
- sign-off قدیمی یا دارای failed check؛
- hash یا manifest ناسازگار؛
- commit کوتاه/نامعتبر یا image digest نامعتبر؛
- فایل عمومی، symlink یا غیر regular-file.

در `NO_GO` نیز manifest خصوصی نوشته می‌شود، اما فرمان با exit code غیرصفر پایان
می‌یابد و cutover ممنوع است.

## نگهداری

این فایل‌ها باید با هم و به‌صورت write-protected نگهداری شوند:

```text
source hash
apply report
replay report
verification report
clinician review packet
clinician sign-off decision
release manifest
commit SHA
image digest
backup/restore evidence
```

manifest ابزار merge یا deployment نیست و هیچ عملیات production را خودکار انجام
نمی‌دهد.
