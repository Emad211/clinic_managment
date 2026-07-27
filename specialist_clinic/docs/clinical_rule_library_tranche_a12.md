# A12 — اولین tranche کنترل‌شدهٔ کتابخانهٔ قواعد دیابت

## وضعیت انتشار

این tranche با شناسهٔ `2026.1-draft.3` فقط یک بستهٔ **DRAFT / NOT_APPROVED / NOT_REVIEWED** است. عبور تست فنی به‌معنی تأیید بالینی یا اجازهٔ نمایش به کاربر نیست.

## قواعد افزوده‌شده

- `T2-MON-A1C-DUE`: نبودن HbA1c یا نداشتن نتیجهٔ تأییدشده در ۱۸۳ روز اخیر.
- `T2-MON-EGFR-DUE`: نبودن eGFR یا نداشتن نتیجهٔ تأییدشده در ۳۶۵ روز اخیر.
- `T2-MON-UACR-DUE`: نبودن UACR یا نداشتن نتیجهٔ تأییدشده در ۳۶۵ روز اخیر.
- `T2-SAFE-MET-REVIEW`: بازبینی غیرتجویزی متفورمین در eGFR از ۳۰ تا کمتر از ۴۵.

## مرزهای ایمنی

- سررسیدها فقط با Factهای canonical و زمان `as_of_at` محاسبه می‌شوند.
- نتیجهٔ تازه اما تأییدنشده، وضعیت را به `NEEDS_DATA` می‌برد و task کاذب ایجاد نمی‌کند.
- Ruleهای سررسید فقط پس از تصمیم `ACCEPTED` پزشک task می‌سازند.
- تکمیل هر task به نتیجهٔ canonical، تأییدشده و دقیقاً هم‌نوع با آزمایش موردنیاز وابسته است.
- هشدار متفورمین هیچ نسخه، تغییر دوز یا قطع خودکار ایجاد نمی‌کند.
- هشدار فوری فعال، Ruleهای روتینِ درحال fire را با دلیل `ACTIVE_REDFLAG` suppress می‌کند.
- Rule هیپوگلیسمی تا زمانی که Factهای عمومی glucose/CGM و نیاز به کمک خارجی به‌صورت canonical ساخته نشوند، وارد بسته نمی‌شود.

## شواهد مبنا

- ADA Standards of Care in Diabetes — 2026، توصیهٔ 6.2 برای ارزیابی وضعیت قند حداقل دوبار در سال.
- ADA Standards of Care in Diabetes — 2026، توصیهٔ 11.1a برای UACR و eGFR حداقل سالانه در همهٔ افراد مبتلا به دیابت نوع ۲.
- همان بخش CKD برای مرز بازبینی فایده/خطر متفورمین زیر eGFR 45 و ممنوعیت زیر 30.

## گام‌های لازم پیش از shadow

1. بازبینی متن منبع و locator توسط پزشک مالک Rule.
2. تأیید مستقل Fact، unit، eligibility، threshold و exclusionها.
3. اجرای golden matrix و dependency analysis روی دادهٔ de-identified محلی.
4. امضای clinical و technical attestation به‌صورت append-only.
5. اجرای SILENT، تحلیل failure/NEEDS_DATA و سپس pilot محدود با seal دقیق.
