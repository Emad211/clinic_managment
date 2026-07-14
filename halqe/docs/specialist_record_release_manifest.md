# manifest نهایی release برای مهاجرت پروندهٔ تخصصی

این مرحله آخرین gate ماشینی پیش از cutover است. فرمان، snapshot مبدأ و تمام artifactهای
apply، replay، reconciliation، بررسی پزشک و sign-off را دوباره می‌خواند و hash
می‌کند؛ سپس reconciliation دیتابیس را همان لحظه دوباره اجرا می‌کند. خروجی `GO`
فقط زمانی صادر می‌شود که artifactها تغییر نکرده باشند و وضعیت جاری PostgreSQL
هنوز با گزارش تأییدشده برابر باشد.

## artifactهای موردنیاز و خروجی تازه

```text
specialist.db                       snapshot quiesced و owner-only
apply.json                          گزارش apply موفق
replay.json                         گزارش اجرای دوم idempotent
verification.json                   خروجی GO از verify_specialist_record_import
clinician-review.json               packet تکمیل‌شدهٔ پزشک
clinician-signoff.json              خروجی GO از verify_specialist_record_clinician_signoff
fresh-verification.json             reconciliation تازه که همین فرمان تولید می‌کند
release-manifest.json               تصمیم نهایی GO/NO_GO
```

همهٔ فایل‌های ورودی باید regular file، بدون symlink و owner-only باشند. فایل‌های
JSON حداکثر ۲۰ MiB و snapshot حداکثر ۱۰۰ GiB پذیرفته می‌شوند. مسیر دو خروجی
`fresh-verification.json` و `release-manifest.json` باید از یکدیگر و از تمام
ورودی‌ها متفاوت باشد؛ command برخورد path و hard-link را پیش از اجرا رد می‌کند.

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
  --fresh-verification-report /secure-migration/reports/fresh-verification.json \
  --report /secure-migration/reports/release-manifest.json
```

اگر `--fresh-verification-report` حذف شود، فایل تازه کنار verification report و
با پسوند `.fresh-verification.json` ساخته می‌شود. پیش از اجرای verifier، هر فایل
قدیمی در همان مسیر حذف می‌شود؛ بنابراین گزارش stale نمی‌تواند پس از شکست اجرای
جدید مورد استفاده قرار گیرد.

`--git-commit` باید SHA کامل ۴۰ کاراکتری commit deployشده باشد. `--image-digest`
اختیاری است، اما در deployment کانتینری باید digest immutable ارائه شود.

## بررسی‌هایی که اجرا یا تکرار می‌شوند

1. source-id و tenant هر artifact با آرگومان فرمان برابر است؛
2. apply و replay هر دو `mode=apply` و `transaction_status=committed` هستند؛
3. اجرای replay هیچ ردیف جدیدی درج نکرده است؛
4. apply و replay یک manifest hash دارند؛
5. hash فعلی snapshot با hash داخل تمام artifactها برابر است؛
6. تمام artifactها یک source manifest hash دارند؛
7. گزارش reconciliation ذخیره‌شده `GO` است؛
8. review packet به hash دقیق همان گزارش reconciliation متصل است؛
9. verifier تأیید پزشک دوباره روی packet فعلی اجرا و `GO` می‌شود؛
10. packet دوباره با ledger، clinical patient link و UUID حسابداری تطبیق می‌شود؛
11. گزارش sign-off ذخیره‌شده به hash دقیق packet و verifier فعلی متصل است؛
12. تعداد بیماران و اختلاف‌های گزارش sign-off با اجرای تازه برابر است؛
13. پوشش سناریوها مستقل از فیلد `coverage` از روی `patients[].scenarios` بازشماری می‌شود؛
14. `verify_specialist_record_import` دوباره روی دیتابیس جاری اجرا می‌شود؛
15. source hash، manifest hash و status map تمام checkهای fresh با گزارش ذخیره‌شده برابر است؛
16. hash فایل fresh report و semantic fingerprint آن در manifest نهایی ثبت می‌شود؛
17. source snapshot و همهٔ reportها private regular file هستند.

اگر fresh verifier با خطای اتصال یا اجرای غیرمنتظره متوقف شود، exception خام یا
اطلاعات اتصال وارد خروجی عمومی نمی‌شود؛ final manifest با check ناموفق و تصمیم
`NO_GO` ساخته می‌شود.

## جلوگیری از استفادهٔ sign-off یا reconciliation قدیمی

اگر پس از sign-off حتی یک فاصله یا یادداشت در packet تغییر کند، hash packet تغییر
می‌کند و manifest `NO_GO` می‌شود. همین قاعده برای verifier report و snapshot مبدأ
نیز اعمال می‌شود.

علاوه بر hash artifactها، fresh verifier وضعیت فعلی ledger و targetها را دوباره
می‌خواند. در نتیجه تغییر یک ردیف PostgreSQL پس از sign-off نیز به `NO_GO` منجر
می‌شود، حتی اگر فایل‌های قبلی دست‌نخورده باشند.

برای هر اصلاح باید زنجیرهٔ زیر دوباره اجرا شود:

```text
apply/replay verification
        ↓
clinician sample
        ↓
clinician sign-off verifier
        ↓
fresh database reconciliation
        ↓
release manifest
```

## release_id

خروجی دارای `release_id` است. این شناسه به‌طور قطعی به موارد زیر متصل است:

- source-id و tenant؛
- commit SHA و image digest؛
- source file hash و source manifest hash؛
- hash گزارش apply و replay؛
- hash verification report؛
- hash clinician review packet؛
- hash clinician sign-off report؛
- hash fresh verification report؛
- semantic fingerprint تصمیم و status checkهای fresh verification.

تغییر هر ورودی یا وضعیت تازهٔ دیتابیس، `release_id` جدیدی می‌سازد. این شناسه باید
در change record، maintenance ticket و صورت‌جلسهٔ cutover ثبت شود.

## خروجی موفق

```text
Specialist record release manifest GO: release_id=..., source_id=...,
tenant=1, commit=..., passed=..., warnings=0, failed=0,
fresh_report=/secure-migration/reports/fresh-verification.json
```

هر دو فایل fresh verification و release manifest با mode `0600` نوشته می‌شوند و
نباید شامل نام، کد ملی یا تلفن بیمار باشند.

## NO_GO

موارد زیر از نمونه‌های قطعی `NO_GO` هستند:

- تغییر snapshot پس از apply؛
- تغییر review packet پس از sign-off؛
- تغییر target یا ledger پس از reconciliation ذخیره‌شده؛
- replay دارای insert جدید؛
- ادعای پوشش سناریو بدون بیمار منتخب متناظر؛
- sign-off قدیمی، فاقد live patient binding یا دارای failed check؛
- fresh verifier ناموفق، فاقد report تازه یا دارای status map متفاوت؛
- hash یا manifest ناسازگار؛
- commit کوتاه/نامعتبر یا image digest نامعتبر؛
- فایل عمومی، symlink یا غیر regular-file؛
- یکسان‌بودن مسیر خروجی با SQLite یا هر artifact ورودی.

در `NO_GO` نیز release manifest خصوصی نوشته می‌شود، اما فرمان با exit code غیرصفر
پایان می‌یابد و cutover ممنوع است.

## نگهداری

این فایل‌ها باید با هم و به‌صورت write-protected نگهداری شوند:

```text
source hash
apply report
replay report
saved verification report
clinician review packet
clinician sign-off decision
fresh verification report
release manifest
commit SHA
image digest
backup/restore evidence
```

manifest ابزار merge یا deployment نیست و هیچ عملیات production را خودکار انجام
نمی‌دهد.
