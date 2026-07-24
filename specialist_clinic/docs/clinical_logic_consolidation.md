# مرز نهایی منطق بالینی و تحلیل توصیفی

## اصل واحد

فقط Clinical Engine v2 مجاز است خروجی‌های زیر را تولید کند:

- recommendation یا safety alert؛
- target درمانی؛
- طبقه‌بندی actionable مانند controlled، uncontrolled، high-risk یا danger؛
- task بالینی ناشی از یک یافته؛
- پیشنهاد آزمایش، غربالگری، واکسن یا تغییر درمان.

هر خروجی v2 باید از rule version و ruleset immutable، snapshot داده، evaluation context،
audit run و activation seal معتبر قابل بازسازی باشد.

## سطوح توصیفی

صفحهٔ بیمار، فهرست بیماران، کارت عمومی، داشبورد و اتاق پیگیری فقط می‌توانند این
اطلاعات را نمایش دهند:

- مقدار ثبت‌شده، واحد و زمان؛
- delta عددی و سری زمانی؛
- diagnosis و medication ثبت‌شده بدون تفسیر؛
- نوبت، تجدید نسخه، وقفهٔ ثبت داده و follow-up از قبل موجود؛
- تعدادها و صف‌های اداری.

این سطوح نباید threshold بخوانند، مقدار را grade کنند، بیمار را بر اساس مقدار مرتب
کنند یا از مقدار بالینی SMS/worklist بسازند.

## بازنشستگی مسیرهای قدیمی

در این tranche موارد زیر غیرقابل‌اجرا شده‌اند:

- evaluator و control status مبتنی بر `clinical_indicators`؛
- weighted risk و per-disease risk؛
- uncontrolled cohort و threshold-driven engagement؛
- target line و progress-to-danger در نمودارها؛
- medication-effect judgment به شکل improved/worsened؛
- suggested-lab chips مبتنی بر تشخیص؛
- care protocolهای دوره‌ای pre-v2 و ساخت follow-up از آن‌ها؛
- ویرایش threshold، target و risk weight در manager UI.

جدول `clinical_indicators` فقط catalog توصیفی نام، واحد، دسته، ترتیب و applicability
است. migration startup دیتابیس‌های کپی‌شده را به همین schema بازسازی می‌کند و
ستون‌های threshold، target و risk weight را به‌صورت اتمیک حذف می‌کند.

## سازگاری دادهٔ قدیمی

reason یا event قدیمی `uncontrolled` فقط با برچسب «پیگیری قدیمی» قابل مشاهده است و
هرگز دوباره از یک measurement ساخته نمی‌شود. رویدادهای clinical engagement قدیمی خاموش و از UI مدیریتی حذف می‌شوند؛ approval
در انتظارِ متعلق به آن‌ها نیز پیش از ارسال رد می‌شود. Task بالینی جدید فقط از
recommendation audit‌شدهٔ v2 ساخته می‌شود.

## دروازهٔ انتشار

این مرحله فقط روی commitی قابل پذیرش است که CI canonical همان commit را اجرا کند؛
موفقیت workflow انتقال یا commit تولیدشده با `GITHUB_TOKEN` به‌تنهایی مدرک انتشار
نیست. هر دو suite مستقل Specialist Clinic و Accounting باید روی head نهایی اجرا شوند
و گزارش JUnit آن‌ها بدون failure، error یا skip ناخواسته ثبت شود.
