# Clinical Engine clean cut

> دامنه: runtime، activation، presentation، decision، task و تست‌ها  
> وضعیت داده در این مرحله: seed / synthetic؛ هیچ migration سازگاری برای تصمیم‌های v1 لازم نیست.

## تصمیم معماری

برنامه از این نسخه به بعد فقط یک قرارداد current-run دارد:

```text
patient_link_id
+ clinical_data_revision
+ CURRENT_ENGINE_VERSION
+ exact ruleset_id
+ valid build-bound activation seal
```

هیچ استثنای `TESTING`، label قدیمی `2.x`، snapshot بدون revision یا raw setting write نمی‌تواند این قرارداد را دور بزند.

## رفتار fail-closed

هرکدام از موارد زیر presentation، decision و clinical task را متوقف می‌کند:

- engine version متفاوت
- ruleset متفاوت یا بدون ruleset
- revision متفاوت یا مفقود
- تغییر پرونده پس از evaluation
- حذف approval
- تغییر report
- تغییر یا حذف seal
- rollback mode
- recommendation متعلق به run یا بیمار دیگر

Audit تاریخی قابل خواندن باقی می‌ماند، اما هرگز به‌عنوان current output مصرف نمی‌شود.

## حذف compatibility قدیمی

موارد زیر بازنشسته شده‌اند:

- `LegacyDecisionImporter`
- فرمان `import-legacy-clinical-decisions`
- پذیرش test-only runهای قدیمی ۲.x
- پذیرش snapshot بدون `clinical_data_revision`
- facade مبتنی بر fake audit/facts
- clinical-task write داخل repository عمومی worklist
- v1 clinical follow-up fallback
- coupling engagement اداری به rule/follow-up engine بالینی

تست‌ها نیز report، دو approval و seal واقعی می‌سازند و همان مسیر production را مصرف می‌کنند.

## seed reset

چون دادهٔ فعلی عملیاتی نیست، upgrade نصب توسعه می‌تواند به‌صورت clean rebuild انجام شود:

1. برنامه متوقف شود.
2. فایل دیتابیس seed حذف یا به نام archive منتقل شود.
3. برنامه با schema جدید بالا بیاید.
4. seedهای catalog اجرا شوند.
5. cohort مصنوعی با نسخهٔ جاری rebuild شود.
6. package قواعد آماده و بازبینی شود.
7. report activation از ابتدا ساخته شود.
8. approval و rollout جدید ثبت شود.

هیچ decision، presentation یا suggestion state قدیمی import نمی‌شود.

## cohort مصنوعی

هر داروی active در cohort باید به یک concept یکتای فعال در `drug_catalog` متصل باشد. نگاشت fuzzy ممنوع است. labelهای تاریخی seed فقط از طریق aliasهای صریح و versioned در `demo_cohort_vocabulary.py` canonical می‌شوند. repository در صورت concept مفقود یا duplicate، کل rebuild را متوقف می‌کند.

## مرز engagement

این دو مسیر مستقل‌اند:

```text
ClinicalV2FollowupService
  -> current audited recommendation
  -> strict ClinicalFollowupRepository
  -> inert internal task

EngagementService
  -> appointment/refill/lapsed/invoice outreach
  -> worklist or approved informational SMS
```

Engagement هرگز fallback بالینی v1 نیست و خاموشی موتور بالینی نباید پیام‌های اداری را متوقف کند.

## کار بعدی

در PR مستقل بعدی، منطق‌های بالینی موازی قدیمی حذف یا طبقه‌بندی می‌شوند:

- `services/rule_engine.py`
- runtime جدول `clinical_rules`
- dosage guidance قدیمی
- suggestion log قدیمی
- route/templateهای rule management v1
- uncontrolled thresholds موازی، پس از تعیین منبع descriptive یا v2

این حذف با Rule Library جدید مخلوط نمی‌شود؛ ابتدا تنها source of truth و governance یکپارچه می‌شود.
