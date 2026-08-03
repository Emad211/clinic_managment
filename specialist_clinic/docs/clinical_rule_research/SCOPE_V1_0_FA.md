# Scope پژوهش برای بازسازی کامل کتابخانهٔ قواعد بالینی

## مشخصات سند

- نسخه: `1.0`
- وضعیت: `APPROVED_RESEARCH_SCOPE`
- محصول مقصد: `Specialist Clinic Clinical Engine v2`
- محیط هدف: مراقبت سرپایی بزرگسالان در ایران
- نخستین Workstream: `ADA Standards of Care in Diabetes—2026`
- نوع محصول: پشتیبان تصمیم بالینی، suggestion-only و تحت تصمیم نهایی پزشک

این سند مجوز استفادهٔ بالینی از هیچ Rule، threshold، توصیه یا بستهٔ قدیمی نیست. تمام Ruleهای موجود در سامانه از نظر بالینی بی‌اعتبارند و کتابخانهٔ جدید از صفر ساخته می‌شود.

## ۱. اصول غیرقابل‌تغییر

### ۱.۱ منبع اصلی

منبع مادر هر Rule باید یک گایدلاین بین‌المللی درجه‌یک، جاری، روش‌مند و متناسب با جمعیت و محیط هدف باشد. منابع ایرانی فقط برای شناخت دسترسی دارویی، آزمایش، هزینه، بیمه، مسیر ارجاع، فرهنگ و قابلیت اجرا خوانده می‌شوند و منبع اصلی threshold، درمان یا قدرت توصیه نیستند.

### ۱.۲ مطالعهٔ مقاله‌به‌مقاله

اعتماد به خلاصهٔ گایدلاین، Abstract، صفحهٔ وب یا خلاصهٔ هوش مصنوعی کافی نیست. برای هر Rule Candidate باید Recommendation دقیق، متن کامل بخش، Evidence Review/Table، مطالعات کلیدی، متن کامل مقالات واجد شرایط، Risk of Bias، شواهد جدیدتر از تاریخ جست‌وجوی گایدلاین و نقش دقیق هر مقاله ثبت شود.

### ۱.۳ تعارض

- thresholdها و فاصله‌ها میانگین‌گیری نمی‌شوند.
- از چند گایدلاین عدد مصنوعی ساخته نمی‌شود.
- اختلاف ظاهری ناشی از جمعیت، setting، endpoint، تاریخ یا تعریف ابتدا تفکیک می‌شود.
- تعارض واقعی در Conflict Matrix ثبت می‌شود.
- تعارض حل‌نشده برابر `CONFLICT` یا `HOLD` است.

### ۱.۴ واحد پژوهش

واحد پژوهش هر Rule Candidate است، نه کل بیماری یا کل PDF. موعد HbA1c، پایش eGFR، پایش UACR، هیپوگلیسمی، ایمنی دارو، مراقبت چشم و پا و سایر موضوعات هرکدام Evidence Dossier مستقل دارند.

### ۱.۵ No-pass gate

هیچ موردی به دلیل شهرت سازمان، رایج‌بودن عدد، وجود در کد قبلی یا موفقیت تست فنی معتبر تلقی نمی‌شود. عبور نیازمند locator، متن کامل، evidence chain، quality appraisal، conflict analysis، computability، licensing، validation و approval است.

### ۱.۶ مرز اقدام

موتور می‌تواند هشدار، care gap، نیاز به مرور پزشک، task داخلی و مشکل داده را نشان دهد. موتور نمی‌تواند تشخیص، نسخه، قطع یا تغییر دارو، ارجاع، آزمایش یا پیام درمانی خودکار ایجاد کند. فقدان داده نیز به معنی نبود بیماری یا خطر نیست.

## ۲. هدف

تولید یک کتابخانهٔ versioned، قابل ردیابی، بازتولیدپذیر و قابل حسابرسی که در آن هر Rule:

- به Recommendation و locator دقیق متصل باشد؛
- زنجیرهٔ مقالات پشتیبان آن استخراج شده باشد؛
- قطعیت شواهد و قدرت توصیه را جدا نگه دارد؛
- با گایدلاین‌های هم‌پوشان و multimorbidity تعارض‌سنجی شود؛
- زمینهٔ ایران را بدون جایگزینی شواهد اصلی لحاظ کند؛
- حقوق استفاده و اقتباس آن روشن باشد؛
- به منطق fail-closed و قابل تست تبدیل شود؛
- پیش از استفادهٔ بالینی تأیید Clinical و Technical بگیرد.

## ۳. سؤال اصلی

چگونه Recommendationهای معتبر بین‌المللی با حفظ منشأ شواهد، جمعیت، استثناها، تعارض‌ها، عدم قطعیت و محدودیت‌های محلی به Ruleهای ایمن و قابل اجرا در مراقبت سرپایی بزرگسالان تبدیل شوند؟

## ۴. جمعیت و setting

### داخل Scope مرحلهٔ اول

- سن ۱۸ سال و بالاتر؛
- بزرگسال غیرباردار؛
- primary care و specialty clinic؛
- ویزیت، follow-up، chronic-care review، medication review و telehealth؛
- بیماران تک‌بیماری و چندبیماری؛
- CKD غیر دیالیزی؛
- دادهٔ ساخت‌یافته و قابل audit.

### خارج از Scope مرحلهٔ اول

- کودکان؛
- بارداری و شیردهی؛
- بستری، ICU و درمان اورژانس بیمارستانی؛
- دیالیز و پیوند؛
- سرطان و بیماری‌های نادر؛
- فوریت روان‌پزشکی و جراحی؛
- تشخیص بیماری حاد از متن آزاد؛
- اقدام دارویی یا ارجاع خودکار.

خروجی مناسب برای خارج از Scope یکی از `NOT_APPLICABLE`، `NEEDS_DATA` یا `CLINICIAN_REVIEW` است.

## ۵. حوزه‌های بیماری

### دیابت نوع ۲

گایدلاین مادر کاندیدا: ADA 2026، پس از appraisal. حوزه‌ها شامل پایش قند، اهداف فردی، هیپوگلیسمی، CGM، کلیه، چشم، پا، ایمنی دارو، خطر قلبی–کلیوی، سالمندی و care gaps است. KDIGO، گایدلاین‌های قلبی و labeling رسمی دارو منابع هم‌پوشان‌اند.

### CKD

گایدلاین‌های مادر کاندیدا: KDIGO جاری برای CKD و diabetes in CKD. موضوعات: chronicity، G/A staging، eGFR/UACR، افت سریع عملکرد، AKI risk، potassium/creatinine monitoring، referral review و renal medication safety.

### پرفشاری خون

گایدلاین مادر کاندیدا: AHA/ACC جاری پس از appraisal. ESC، KDIGO و ADA منابع مقایسه‌ای حوزه‌های هم‌پوشان‌اند.

### اختلالات چربی

گایدلاین مادر کاندیدا: ACC/AHA جاری پس از appraisal. موضوعات شامل risk، LDL/non-HDL، Lp(a)، ApoB، پایش درمان، پیشگیری اولیه/ثانویه، عدم تحمل استاتین و hypertriglyceridemia است.

### کم‌کاری اولیه تیروئید

NICE NG145 نقطهٔ شروع appraisal است، نه منبع تأییدشدهٔ پیشاپیش. بستهٔ اول محدود به primary/subclinical hypothyroidism، TSH/FT4، پایش levothyroxine، سالمندی، بیماری قلبی، تداخل جذب و overtreatment است.

### حوزهٔ قلبی–کلیوی–متابولیک

گایدلاین مشترک معتبر برای هماهنگی حوزهٔ مشترک استفاده می‌شود، اما خودکار جایگزین گایدلاین مادر هر تخصص نیست.

## ۶. مراقبت عمومی

در مرحلهٔ اول فقط Red Flagهای ساخت‌یافته، medication safety، allergy/contraindication، monitoring، care gaps، preventive prompts و مشکلات داده بررسی می‌شوند. بیماری‌های حاد مانند عفونت تنفسی، UTI، درد شکم، سردرد، کمردرد، بیماری پوستی و انتخاب آنتی‌بیوتیک تا ساخت مدل ساخت‌یافتهٔ Symptom–Timeline–Examination–Test–Assessment خارج از Scope هستند.

## ۷. خانواده‌های Rule

- Safety / Red Flag
- Medication Safety
- Monitoring / Care Gap
- Risk Stratification
- Treatment Review Prompt
- Data Quality / Conflict
- Preventive Care Prompt

سطح autonomous action وجود ندارد.

## ۸. اولویت‌بندی

- Priority A: خطر بالا، توصیه روشن، Fact معتبر، استثنای قابل مدل‌سازی.
- Priority B: monitoring و care gap معتبر.
- Priority C: preference-sensitive یا resource-dependent؛ فقط prompt پزشک.
- HOLD: شواهد ناکافی، دادهٔ نامناسب، تعارض، مجوز نامشخص یا خطر alert burden.

## ۹. انتخاب گایدلاین

هر گایدلاین از نظر تازگی، روش جست‌وجو، تاریخ cutoff، پنل، بیمار/ذی‌نفع، COI، grading، Evidence Table، تطابق جمعیت، computability و licensing ارزیابی می‌شود. ابزارها شامل AGREE II، AGREE-REX، RIGHT و GLIA هستند. نام سازمان به‌تنهایی معیار پذیرش نیست.

## ۱۰. فرایند پژوهش مقاله‌به‌مقاله

1. Recommendation Inventory با locator و grade.
2. ردیابی Evidence Review و مطالعات محوری.
3. جست‌وجوی تکمیلی از پایان search window گایدلاین.
4. غربالگری PRISMA-compatible.
5. استخراج متن کامل شامل design، population، intervention، comparator، outcomes، effect، CI، harms، subgroup، funding و COI.
6. Risk of Bias با ابزار متناسب: RoB 2، ROBINS-I، AMSTAR 2، QUADAS-2، PROBAST یا CASP.
7. GRADE برای بدنهٔ شواهد.
8. بازبینی Pass 1 و Pass 2 توسط همان ارزیاب، با ثبت صریح اینکه معادل دو ارزیاب انسانی مستقل نیست.

ADA A/B/C/E به‌طور خودکار به GRADE یا recommendation strength تبدیل نمی‌شود.

## ۱۱. مدیریت تعارض و multimorbidity

انواع تعارض شامل جمعیت، setting، outcome، search date، risk model، grade، threshold، interval، resource و multimorbidity است. حل تعارض با مقایسهٔ نسخه، سؤال، methodology، directness، harms، evidence update و داوری تخصصی انجام می‌شود.

حداقل Interaction Matrix:

- diabetes × CKD؛
- diabetes × cardiovascular disease؛
- diabetes × frailty/hypoglycemia؛
- hypertension × CKD/orthostasis؛
- dyslipidemia × liver disease؛
- thyroid × cardiac disease؛
- medication × renal function/allergy/concomitant drugs.

در runtime اولویت با red flag، contraindication، out-of-scope، critical missing/conflict، preference، evidence و در نهایت clinician review است.

## ۱۲. نقش منابع ایرانی

منابع ایرانی فقط برای formulary، بیمه، آزمایش، referral، هزینه، epidemiology، زبان، فرهنگ، مقررات و موانع اجرا استخراج می‌شوند. آن‌ها threshold یا certainty اصلی را تعیین نمی‌کنند. بومی‌سازی ممکن است workflow، مسئول اقدام، پیام UI یا feasibility را تغییر دهد، نه واقعیت علمی را ساکت بازنویسی کند.

## ۱۳. Google Drive و Excel

هر guideline، recommendation، article، evidence unit، conflict و Rule ID یکتا دارد. PDF اصل با metadata و checksum نگهداری می‌شود؛ workbook منبع وضعیت پژوهش است، نه جایگزین متن مقاله. هر استخراج به locator و source URL متصل است. نسخه‌های مصوب Scope، protocol و dossier در Git versioned می‌شوند و PDFهای محافظت‌شده بدون مجوز در Git یا Drive مشترک منتشر نمی‌شوند.

## ۱۴. Evidence Dossier هر Rule

هر dossier حداقل شامل سؤال بالینی، PICO/PECO، منبع مادر، locator، search cutoff، base evidence، update search، extraction، RoB، GRADE، benefits، harms، subgroups، guideline conflict، multimorbidity conflict، Iranian context، licensing، Facts، unit/verification/freshness، eligibility، logic، exclusions، missing/conflict behavior، output wording، golden cases، retrospective validation، silent/pilot evidence، approvals و review date است.

## ۱۵. قابلیت تبدیل به Rule

Formalization فقط وقتی آغاز می‌شود که population، age/sex، setting، eligibility، Facts، source/verification، unit، time، freshness، condition، exception، contraindication، missing behavior، conflict behavior، suppression، action type، urgency، owner، evidence locator، certainty، adaptation، licensing و review date روشن باشند.

Computability levels:

- `C0_NOT_COMPUTABLE`
- `C1_INFORMATION_ONLY`
- `C2_REVIEW_OR_CARE_GAP`
- `C3_SAFETY_ALERT`

## ۱۶. تست و اعتبارسنجی

Golden Cases شامل positive، negative، borderline، missing، conflict، historical-as-of، contraindication، suppression، out-of-scope، wrong unit، stale/unverified data، multimorbidity، medication combination و idempotency است.

مراحل validation:

1. content validation؛
2. technical review؛
3. golden cases؛
4. multimorbidity scenarios؛
5. retrospective de-identified validation؛
6. SILENT/shadow؛
7. limited pilot؛
8. controlled activation.

هر اختلاف ایمنی باید جداگانه adjudicate شود.

## ۱۷. حاکمیت و وضعیت‌ها

برای هر Rule approval بالینی و فنی مستقل لازم است. نویسنده، استخراج‌کننده، ارزیاب و تأییدکننده و COI باید ثبت شوند.

وضعیت‌ها:

`IDENTIFIED`, `GUIDELINE_APPRAISAL`, `EVIDENCE_RETRIEVAL`, `FULL_TEXT_REVIEW`, `EVIDENCE_INCOMPLETE`, `CONFLICT`, `NOT_COMPUTABLE`, `LICENSING_HOLD`, `CLINICAL_HOLD`, `FORMALIZATION_READY`, `DRAFT`, `VALIDATED`, `SILENT`, `PILOT`, `ACTIVE`, `SUSPENDED`, `RETIRED`, `REJECTED`.

هیچ promotion خودکاری وجود ندارد.

## ۱۸. Licensing و Living Review

رایگان‌بودن PDF مجوز اقتباس نرم‌افزاری نیست. وضعیت نامشخص برابر `LICENSING_HOLD` است. برای هر Rule نسخهٔ منبع، تاریخ انتشار، search cutoff، update search، approval، next review و supersession ثبت می‌شود. safety updates فوری، guideline releases فصلی و ruleset حداقل سالانه بازبینی می‌شوند.

## ۱۹. ترتیب Workstreamها

1. ADA / Type 2 Diabetes؛
2. Safety و Red Flags مشترک؛
3. diabetes + CKD و renal medication safety؛
4. hypertension؛
5. CKD non-dialysis؛
6. dyslipidemia؛
7. primary hypothyroidism؛
8. cardiometabolic multimorbidity؛
9. preventive care؛
10. general acute care پس از structured-data readiness.

## ۲۰. تعریف موفقیت

موفقیت با تعداد Rule سنجیده نمی‌شود. موفقیت یعنی منشأ و locator دقیق، متن کامل، نبود threshold ساختگی، حفظ grading، جلوگیری از ورود تعارض حل‌نشده، عدم تبدیل unknown به false، trace قابل مشاهده، replay/audit/supersede/rollback و fail-closed behavior.

> تعداد کم Ruleهای عمیقاً پژوهش‌شده و ایمن بر صدها Rule سطحی برتری دارد.

## ۲۱. اثر بر Ruleهای فعلی

تمام Ruleهای موجود فقط نمونهٔ فنی محسوب می‌شوند. compile و test فنی هیچ اعتبار علمی ایجاد نمی‌کند. هیچ Rule قدیمی grandfather نمی‌شود و تمام کتابخانه بر اساس این Scope از صفر ساخته خواهد شد.
