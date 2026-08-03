# ADA-02 — فهرست دوپاسی توصیه‌های بخش ۶ ADA 2026

## وضعیت

- بخش: Glycemic Goals, Hypoglycemia, and Hyperglycemic Crises
- تاریخ بررسی: 2026-07-30
- روش: استخراج Pass 1 و بازبینی خصمانه Pass 2 توسط همان ارزیاب
- تعداد Recommendation Record: 24
- Rule Candidate: 0
- Rule پذیرفته‌شده: 0
- Licensing: HOLD

هدف این مرحله ساخت Rule نبود. هر توصیه فقط با paraphrase مستقل، locator، Grade بندها، جمعیت، setting، dependencies، conflicts، data requirements و status ثبت شد. متن کامل محافظت‌شده در Git یا Drive مشترک کپی نشد.

## رکوردهای ثبت‌شده

6.1، 6.2، 6.3a، 6.3b، 6.3c، 6.4، 6.5، 6.6، 6.7، 6.8، 6.9، 6.10، 6.11، 6.12، 6.13، 6.14، 6.15، 6.16، 6.17، 6.18، 6.19، 6.20، 6.21 و 6.22.

## اصلاحات مهم Pass 2

### بندهای چندGrade

توصیه‌های 6.1، 6.11، 6.12، 6.16 و 6.18 دارای بندهایی با Grade متفاوت‌اند. ذخیرهٔ یک Grade واحد برای کل توصیه ممنوع است.

### فاصله‌های زمانی

- زمان مثال‌زده‌شده در 6.2 یک ساعت جهانی برای همهٔ بیماران نیست.
- زبان کیفی 6.20 عدد آمادهٔ محاسبه ایجاد نمی‌کند.
- ساخت Rule ثابت «هر 90 روز» یا ساعت مصنوعی مشابه ممنوع است.

### اهداف قندی

هدف A1C یا CGM بدون بررسی سلامت و عملکرد، سابقهٔ hypoglycemia، frailty، cognition، CKD و اعتبار A1C، درمان، کفایت دادهٔ CGM، preference، burden و منافع قلبی–کلیوی قابل تبدیل به Rule نیست.

### مالکیت اقدام

کاهش شدت درمان، تعویض کلاس، تجویز glucagon، تغییر هدف و مدیریت بحران‌ها clinician-owned هستند. هیچ اقدام دارویی خودکار از این توصیه‌ها مجاز نیست.

### مرز outpatient/inpatient

در Scope فعلی، بحران قندی فقط برای prevention، education، sick-day workflow، red-flag escalation و clinician review بررسی می‌شود. تشخیص و درمان DKA/HHS بیمارستانی خارج از Scope است.

## وابستگی‌های اجباری

پیش از formalization هر موضوع بخش 6، بررسی Sections 7، 9، 10، 11، 13، 15 و 16 و گایدلاین‌های مادر حوزه‌های قلبی، کلیوی و دارویی الزامی است.

## اولویت نخست

Recommendation 6.19 به‌عنوان نخستین Evidence Dossier انتخاب شد، زیرا یک رخداد مهم ایمنی را به medication review متصل می‌کند و خطر تعبیر اشتباه آن به اقدام خودکار وجود دارد.

## Gate

- `SECTION_6_INVENTORY = COMPLETE`
- `RULE_CANDIDATES = 0`
- `ACCEPTED_RULES = 0`
- `DIRECT_RULE_TRANSLATION = BLOCKED`
- `LICENSING = HOLD`

منبع رسمی:
https://diabetesjournals.org/care/article/49/Supplement_1/S132/163927/6-Glycemic-Goals-Hypoglycemia-and-Hyperglycemic
