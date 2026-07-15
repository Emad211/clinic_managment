# Release manifest نهایی حسابداری

این فرمان آخرین گیت نرم‌افزاری پیش از تصمیم cutover است. فرمان هیچ merge، deploy یا
cutover انجام نمی‌دهد؛ فقط evidenceها را دوباره بررسی، fresh verification اجرا و یک
manifest خصوصی GO/NO_GO تولید می‌کند.

## evidenceهای ورودی

- SQLite اصلی مهاجرت تاریخی؛
- SQLite snapshot آخرین روز dual-run؛
- packet و report امضای مالی؛
- import verification؛
- restore verification؛
- تمام dual-run reportهای روزهای امضاشده؛
- backup manifest و custom-format dump؛
- full Git commit SHA؛
- immutable container image digest.

تمام فایل‌های JSON و SQLite باید owner-only، regular file و غیر symlink باشند.

## اجرای فرمان

```bash
python manage.py build_accounting_release_manifest \
  --import-sqlite /secure/migration/clinic-import-source.db \
  --latest-dual-run-sqlite /secure/dual-run/clinic-latest.db \
  --packet /secure/signoff/accounting-packet.json \
  --signoff-report /secure/signoff/accounting-signoff.json \
  --import-verification /secure/migration/import-verification.json \
  --restore-verification /secure/backup/restore-verification.json \
  --dual-run-report /secure/dual-run/reports/*.json \
  --backup-manifest /secure/backup/halqe-manifest.json \
  --backup-file /secure/backup/halqe.dump \
  --source-id clinic-main-accounting \
  --tenant-id 1 \
  --git-commit "$GIT_COMMIT_SHA" \
  --image-digest "$CONTAINER_IMAGE_DIGEST" \
  --fresh-import-report /secure/release/fresh-import.json \
  --fresh-dual-run-directory /secure/release/fresh-dual \
  --report /secure/release/accounting-release-manifest.json
```

`--git-commit` باید SHA کامل ۴۰کاراکتری lowercase باشد. `--image-digest` باید digest
تغییرناپذیر `sha256:` باشد؛ branch name، tag یا `latest` پذیرفته نمی‌شود.

## کارهایی که فرمان دوباره انجام می‌دهد

1. sign-off ذخیره‌شده را از packet و evidenceهای اصلی بازسازی می‌کند؛
2. backup bytes را با backup manifest تطبیق می‌دهد؛
3. import verifier را روی SQLite اصلی و PostgreSQL فعلی دوباره اجرا می‌کند؛
4. آخرین تاریخ dual-run را از evidence امضاشده پیدا می‌کند؛
5. ثابت می‌کند SQLite آخرین روز همان snapshot امضاشده است؛
6. all، morning، evening و night را دوباره محاسبه می‌کند؛
7. fresh reportها را با mode برابر `0600` می‌نویسد؛
8. همه hashها، commit، image و check statusها را در release ID قطعی وارد می‌کند.

## معیار GO

داخل manifest باید:

```json
{
  "decision": "GO"
}
```

و تمام checkها PASS باشند:

- `signed_evidence_chain`
- `import_source_identity`
- `fresh_import_verification`
- `latest_dual_run_snapshot_identity`
- `fresh_latest_dual_run`

همچنین:

- `release_id` دارای ۶۴ کاراکتر hex باشد؛
- fresh import report و چهار fresh dual-run report موجود و private باشند؛
- fresh dual-runها هیچ difference یا error نداشته باشند؛
- commit و image دقیقاً با artifact deployشده برابر باشند.

## رفتار NO_GO

این موارد NO_GO هستند:

- تغییر SQLite اصلی یا snapshot آخرین روز؛
- تغییر target database پس از sign-off؛
- تغییر backup، packet یا reportهای امضاشده؛
- شکست fresh import verifier؛
- اختلاف حتی یک تومان، یک payment یا یک payroll component؛
- استفاده از branch/tag به‌جای commit/image immutable؛
- نبود یکی از scopeهای آخرین روز.

Manifest یا fresh reportها نباید دستی ویرایش شوند. پس از NO_GO، علت در change record
ثبت و کل فرایند evidence از مرحلهٔ مربوطه تکرار شود.

## تصمیم cutover

حتی manifest برابر GO به‌تنهایی مجوز cutover نیست. موارد زیر نیز باید تکمیل باشند:

- maintenance window و ownerها؛
- backup/restore واقعی برابر VERIFIED؛
- تعداد روزهای dual-run مصوب؛
- sign-off صندوق، بیمه، payroll و نمونه فاکتورها؛
- rollback rehearsal و ارتباطات عملیاتی؛
- تأیید رسمی GO/NO_GO توسط مالک کسب‌وکار و مسئول فنی.

PR تا زمان وجود این evidenceهای واقعی Draft باقی می‌ماند.
