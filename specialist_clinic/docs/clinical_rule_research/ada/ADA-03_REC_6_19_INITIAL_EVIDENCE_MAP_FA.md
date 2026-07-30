# ADA-03 — نقشهٔ شواهد Recommendation 6.19

## وضعیت v0.4

- مطالعات غربال‌شده: `11`
- استخراج متن کامل: `9`
- Article-level appraisal: `9`
- ارزیابی رسمی روش‌شناختی: `3`
- تعارض‌های باز: `12`
- Rule Candidate: `0`
- Accepted Rule: `0`
- Licensing: `HOLD`

این نقشه سه نوع شواهد را جدا نگه می‌دارد:

1. شواهد شکاف اجرای مراقبت پس از رویداد؛
2. شواهد اثربخشی علی یک اقدام مشخص؛
3. شواهد یا سیگنال احتمالی آسیب.

هیچ‌یک از این دسته‌ها نباید به دستهٔ دیگر تبدیل یا تعمیم داده شود.

## توصیهٔ مادر

ADA 2026 Recommendation 6.19 می‌گوید یک یا چند رخداد سطح ۲ یا ۳ باید موجب بازنگری طرح درمان شود و، در صورت مناسب‌بودن، کاهش شدت یا تعویض دارو بررسی شود. Grade توصیه `B` است. متن توصیه نوع اقدام واحد، دارو، دوز، زمان یا automation را تعیین نمی‌کند.

منبع رسمی:
https://diabetesjournals.org/care/article/49/Supplement_1/S132/163927/6-Glycemic-Goals-Hypoglycemia-and-Hyperglycemic

## تعریف رویداد

- Level 2 بر اساس glucose پایین‌تر از آستانهٔ تعریف‌شده است.
- Level 3 بر اساس نیاز به کمک فرد دیگر تعریف می‌شود و الزاماً به یک عدد glucose وابسته نیست.
- Rule یا workflow آینده نباید این دو را یکی کند.
- event verification باید شامل زمان، منبع، مقدار glucose در صورت وجود، علائم، نیاز به کمک و وضعیت تأیید باشد.

## شکاف اجرای مستقیم پس از رویداد

Alexopoulos 2021 و Vijayakumar 2020 نشان می‌دهند که پس از severe hypoglycemia، کاهش شدت یا اصلاح درمان در بسیاری از بیماران انجام نمی‌شود یا در داده‌ها ثبت نمی‌شود. این مطالعات process evidence هستند و اثربخشی یک تغییر خاص را ثابت نمی‌کنند.

Rode 2024 تعداد `1,977` رویداد EMS در `1,028` بزرگسال را بررسی کرد. گفت‌وگو دربارهٔ هیپوگلیسمی و تغییر دارو بر اساس سطح مراقبت تفاوت بزرگی داشت. عدم انتقال و عدم بستری با عود بیشتر همراه بود، اما گفت‌وگو یا تغییر درمان در مدل مشاهده‌ای اثر محافظتی معنادار نشان نداد. این نتیجه به‌علت confounding نباید به بی‌اثر بودن مرور یا تغییر درمان تعبیر شود.

منابع:

- https://pmc.ncbi.nlm.nih.gov/articles/PMC8564578/
- https://doi.org/10.2337/dc20-0458
- https://pmc.ncbi.nlm.nih.gov/articles/PMC11530891/

## شواهد مستقیم اثربخشی

تا نسخهٔ v0.4، هیچ مطالعهٔ مستقیم و کم‌سوگیری در مجموعهٔ بررسی‌شده پیدا نشده است که یک medication action استاندارد را پس از یک رویداد تأییدشدهٔ Level 2/3 آزمایش کند و کاهش recurrence یا net harm را نشان دهد.

- medication-specific Rule: `BLOCKED`
- automatic deintensification/switch/stop: `BLOCKED`
- direct causal evidence status: `NOT FOUND`

## شواهد غیرمستقیم مداخله‌ای

مطالعات simplification، مقایسهٔ regimenهای کم‌خطرتر و interventionهای clinician-facing نشان می‌دهند که در جمعیت‌های منتخب می‌توان بار درمان یا هیپوگلیسمی را کاهش داد یا deprescribing را افزایش داد. این مطالعات prior-event triggered نیستند و نمی‌توانند برای همهٔ بیماران پس از یک رویداد، اقدام واحد تعریف کنند.

## مرور Seidu 2019

ارزیابی رسمی AMSTAR 2:

`CRITICALLY LOW` برای استفاده به‌عنوان سنتز اصلی benefit–harm.

دلایل اصلی:

- نبود فهرست فردی مطالعات حذف‌شده؛
- RoB ناکافی برای NRSIهای مداخله‌ای؛
- نتیجه‌گیری بیش از حد قطعی نسبت به ناهمگونی و کیفیت شواهد؛
- نبود funding map مطالعه‌به‌مطالعه.

این مرور فقط برای citation mapping و یافتن مطالعات اولیه استفاده می‌شود.

## سیگنال تعارض Christiaens 2025

مطالعهٔ target-trial emulation افزایش کوتاه‌مدت مرگ/بستری را پس از deintensification گزارش کرد. `88.8%` مواجهه‌ها توقف کامل داروهای هیپوگلیسمی‌زا بودند.

ROBINS-I رسمی:

`CRITICAL`

این مطالعه به‌دلیل confounding by indication، acute decline، end-of-life goals و reverse causation اثبات علی نیست؛ اما به‌عنوان safety-conflict signal نادیده گرفته نمی‌شود و blanket deintensification را مسدود می‌کند. اصلاحیهٔ منتشرشده فقط acknowledgement نویسندگان را تغییر داد.

منابع:

- https://pmc.ncbi.nlm.nih.gov/articles/PMC12156012/
- https://pmc.ncbi.nlm.nih.gov/articles/PMC10660441/
- https://pmc.ncbi.nlm.nih.gov/articles/PMC12413510/

## وابستگی‌های حل‌نشده

- Section 9: pharmacologic indications و class-specific risks
- Section 13: سالمندی، cognition، function و life expectancy
- CKD/KDIGO: clearance، hypoglycemia risk و cardiorenal benefit
- Section 7: CGM data validity و detection
- local workflow: owner، SLA، task burden و availability
- Licensing: ADA adaptation/software reuse

## نتیجهٔ فعلی

فقط یک مفهوم محدود برای پژوهش باقی می‌ماند:

> رخداد تأییدشدهٔ Level 2 یا 3 می‌تواند یک درخواست مرور پزشک ایجاد کند، بدون پیشنهاد خودکار نوع تغییر درمان.

اما این مفهوم هنوز Rule Candidate نیست، زیرا event schema، required facts، exclusions، owner/SLA، cross-guideline dependencies، local validation، licensing و approvals بسته نشده‌اند.

- Rule candidates: `0`
- Accepted Rules: `0`
- Licensing: `HOLD`
