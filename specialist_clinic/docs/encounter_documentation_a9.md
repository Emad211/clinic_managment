# A9 — سند ساختاریافته Encounter

## هدف

ویزیت جدید صف پزشک باید علاوه بر حضور و خدمت مالی، یک سند بالینی صریح داشته باشد. A9 برای هر Encounter جدید Doctor Queue یک requirement تغییرناپذیر می‌سازد و تکمیل Encounter را به latest document امضاشده وابسته می‌کند.

## ساختار سند

هر نسخه می‌تواند شامل این فیلدها باشد:

- شکایت اصلی / دلیل مراجعه؛
- یافته‌های عینی و معاینه؛
- مسائل فعال، هر مورد به‌صورت ورودی صریح پزشک؛
- assessment؛
- plan؛
- دستور پیگیری؛
- outcome محدود و کدگذاری‌شده.

برای امضا، `assessment`، `plan` و `outcome_code` الزامی‌اند. نام line item حسابداری، مبلغ، عنوان تزریق یا پروسیجر هیچ‌کدام خودکار به assessment، problem یا outcome تبدیل نمی‌شوند.

## lifecycle سند

```text
DRAFT_SAVED → DRAFT_SAVED → SIGNED → AMENDED → AMENDED
```

- Draft قابل بازنویسی نیست؛ هر ذخیره یک event جدید می‌سازد.
- Signed با Encounter فعال ثبت می‌شود.
- Signed document، queue completion و `care_encounter_events.COMPLETED` در یک transaction محلی ثبت می‌شوند.
- Amendment فقط بعد از completion مجاز است، متن کامل نسخه جدید و دلیل اصلاح را نگه می‌دارد و نسخه قبلی را حذف یا update نمی‌کند.
- optimistic concurrency با `expected_current_event_id` از overwrite هم‌زمان جلوگیری می‌کند.

## legacy cutover

در اولین migration، Encounterهای موجود یک‌بار `LEGACY_EXEMPT` می‌شوند. marker `A9_LEGACY_CUTOFF_V1` مانع می‌شود که اجرای بعدی health یا startup، Encounterهای تازه را legacy اعلام کند. فقط مسیر Doctor Queue جدید requirement=`REQUIRED` می‌سازد؛ مسیرهای programmatic قدیمی تا زمان مهاجرت جداگانه رفتار قبلی را حفظ می‌کنند.

## UI/UX

- دکمه مستقیم پایان از صف حذف شده است.
- ویزیت در حال اجرا فقط گزینه «ادامه مستندسازی» دارد.
- فرم ویزیت دو اقدام روشن دارد: ذخیره پیش‌نویس، و امضا و پایان ویزیت.
- صفحه مستقل سند، نسخه جاری و تاریخچه را نشان می‌دهد.
- اصلاحیه فقط با مجوز `clinical.document.amend` ثبت می‌شود.
- latest signed document در timeline پرونده بیمار لینک می‌شود.

## مرز حسابداری

A9 هیچ فایل، schema، status، invoice یا payment را در `webapp` تغییر نمی‌دهد. تمام عملیات سند در دیتابیس `specialist_clinic` است و تست‌ها SHA فایل حسابداری را پیش و پس از start/draft/sign/amend مقایسه می‌کنند.
