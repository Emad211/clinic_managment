# دور دوم پژوهش عمیق — PRD پرتال بیمار و همراه حلقه

**تاریخ:** ۲۰۲۶-۰۷-۱۵  
**وضعیت:** Product Requirements Document پژوهشی؛ پیش‌نیاز طراحی و معماری، نه مجوز پیاده‌سازی production  
**دامنه:** حساب احراز‌شدهٔ بیمار، داشبورد «امروز»، برنامهٔ مراقبت، self-monitoring، پیام امن، همراه/مراقب، دسترس‌پذیری و workflow پاسخ کلینیک

---

## ۱. تصمیم پایه

سطح روبه‌بیمار فعلی باید به سه محصول با مرز امنیتی متفاوت تفکیک شود:

| سطح | وضعیت فعلی/آینده | هدف | سطح داده و اقدام |
|---|---|---|---|
| **Public Patient Card** | موجود و حفظ می‌شود | نمایش حداقل اطلاعات با token محدود | read-only، minimum necessary، بدون حساب بیمار |
| **One-time Self-report Link** | موجود و حفظ می‌شود | ثبت سریع چند اندازه‌گیری بدون نصب/ثبت‌نام | write محدود، یک‌بارمصرف، دادهٔ تأییدنشده |
| **Authenticated Patient Portal** | باید ساخته شود | مدیریت مستمر مراقبت، برنامه، درخواست‌ها و همراه | حساب مستقل، consent، session، audit و دسترسی طولی |

گسترش کارت عمومی به پرتال کامل ممنوع است؛ زیرا کارت فعلی عمداً بدون JWT، read-only و دارای payload کمینه است. پرتال بیمار یک bounded context مستقل با مدل هویت، رضایت و مجوز متفاوت خواهد بود.

---

## ۲. مسئلهٔ محصول

بیمار مزمن بین ویزیت‌ها با چند ابهام تکراری روبه‌روست:

- نمی‌داند امروز دقیقاً چه کاری مهم است؛
- نمی‌داند دادهٔ ثبت‌شده به دست تیم درمان رسیده یا دیده شده است؛
- زمان بعدی آزمایش، اندازه‌گیری، تمدید نسخه یا ویزیت روشن نیست؛
- اطلاعات در پیامک، برگه، تماس و حافظهٔ خانواده پراکنده است؛
- بیمار سالمند یا کم‌سواد ممکن است بدون همراه عملاً نتواند از ابزار دیجیتال استفاده کند؛
- تماس‌های تکراری برای سؤال‌های اداری و بالینی، بار تیم کلینیک را افزایش می‌دهد؛
- ثبت داده بدون workflow پاسخ می‌تواند حس امنیت کاذب ایجاد کند.

### Job-to-be-done اصلی بیمار

> «وقتی از کلینیک خارج می‌شوم، می‌خواهم بدانم قدم بعدی چیست، چگونه انجامش دهم و آیا تیم درمان نتیجه را دیده است؛ بدون اینکه مجبور باشم پرونده پزشکی پیچیده را بفهمم.»

### Job-to-be-done همراه

> «می‌خواهم فقط در بخش‌هایی که بیمار اجازه داده به او کمک کنم، بدون استفاده از رمز او و بدون اینکه مسئولیت یا حریم خصوصی مبهم باشد.»

### Job-to-be-done تیم کلینیک

> «می‌خواهم درخواست و دادهٔ بیمار به صف مناسب، مسئول مشخص و SLA قابل‌اندازه‌گیری برسد؛ نه اینکه یک کانال پیام جدید و بی‌صاحب ساخته شود.»

---

## ۳. اهداف و عدم‌اهداف

### اهداف نسخهٔ اول

1. ایجاد حساب مستقل و امن برای بیمار.
2. نمایش حداکثر سه اقدام اولویت‌دار و مصوب در صفحهٔ «امروز».
3. نمایش برنامهٔ مراقبت و موعدها با زبان ساده.
4. ثبت اندازه‌گیری خانگی protocol-aware و نمایش وضعیت review.
5. ایجاد درخواست ساختاریافته برای نوبت، تمدید نسخه و سؤال.
6. route کردن درخواست به role مناسب در کلینیک.
7. دسترسی رسمی و scope-based همراه/مراقب.
8. notification preference و consent قابل بازبینی.
9. دسترس‌پذیری برای سالمند، گوشی ضعیف و سواد سلامت محدود.
10. ثبت audit برای login، grant، مشاهدهٔ حساس، submission و پیام.

### عدم‌اهداف نسخهٔ اول

- تشخیص یا تجویز خودکار برای بیمار؛
- تغییر دوز توسط موتور یا بیمار بدون plan مصوب پزشک؛
- chat بلادرنگ ۲۴ساعته؛
- جایگزینی اورژانس یا تریاژ تلفنی؛
- social network یا forum بیماران؛
- نمایش تمام جزئیات پروندهٔ پزشک در صفحهٔ اول؛
- اتصال هم‌زمان به همهٔ deviceها؛
- نسخهٔ native؛ PWA/وب responsive نقطهٔ شروع است؛
- billing پیچیدهٔ پیام یا remote care قبل از تعریف سیاست تجاری و حقوقی.

---

## ۴. اصل‌های UX

### ۴.۱ Action-first، نه chart-first

صفحهٔ اول با «کارهای امروز» شروع می‌شود. نمودار و تاریخچه در سطح دوم قرار می‌گیرند.

### ۴.۲ حداکثر سه اولویت

نمایش بیش از سه CTA اصلی در صفحهٔ اول ممنوع است. موارد دیگر در «همهٔ کارها» قرار می‌گیرند.

### ۴.۳ وضعیت قابل فهم

هر submission/request یکی از وضعیت‌های قابل مشاهدهٔ زیر را دارد:

```text
ثبت نشده
→ ارسال شد
→ دریافت شد
→ در انتظار بررسی
→ بررسی شد
→ نیاز به اقدام بیشتر
→ تکمیل شد
```

کاربر نباید از تیک «خوانده شد» نتیجهٔ بالینی بگیرد؛ وضعیت‌ها باید semantic و متصل به workflow باشند.

### ۴.۴ Progressive disclosure

سه سطح محتوا:

1. **ساده:** یک جمله و اقدام.
2. **توضیح بیشتر:** چرا این کار مهم است و چگونه انجام شود.
3. **جزئیات:** مقدار، تاریخ، source، verification و روند.

### ۴.۵ مسیر جایگزین غیر دیجیتال

هر feature حیاتی باید fallback داشته باشد:

- تماس با کلینیک؛
- پیام صوتی/راهنمای شنیداری؛
- همراه رسمی؛
- برگه یا QR در کلینیک؛
- ثبت توسط کارکنان به نمایندگی از بیمار با audit.

### ۴.۶ اعتماد قابل مشاهده

در UI صریحاً نمایش داده شود:

- چه کسی پاسخ‌گوست؛
- زمان تقریبی پاسخ؛
- کدام داده تأیید نشده است؛
- آخرین مشاهده/اقدام تیم چه زمانی بوده؛
- چه دسترسی‌هایی به همراه داده شده؛
- چگونه دسترسی یا رضایت لغو می‌شود.

---

## ۵. کاربران و نقش‌ها

### ۵.۱ بیمار مستقل

- گوشی شخصی؛
- خودپایش و مدیریت نوبت؛
- ترجیح حداقل اصطکاک و اطلاعات قابل فهم.

### ۵.۲ بیمار سالمند یا کم‌سواد

- احتمال نیاز به تماس، voice و همراه؛
- خطر خطای login، navigation و تفسیر داده؛
- نیاز به font/target بزرگ و task flow کوتاه.

### ۵.۳ همراه/مراقب غیررسمی

- فرزند، همسر یا عضو خانواده؛
- ممکن است بخشی از مراقبت را انجام دهد؛
- نیازمند scope مستقل و آموزش است.

### ۵.۴ پرستار/هماهنگ‌کنندهٔ مراقبت

- triage داده و پیام؛
- آموزش و پیگیری؛
- escalation موارد نیازمند پزشک.

### ۵.۵ پذیرش/منشی

- نوبت، اطلاعات اداری و تماس؛
- نباید به‌صورت پیش‌فرض محتوای بالینی غیرضروری را ببیند.

### ۵.۶ پزشک

- review exceptionهای بالینی؛
- approve/update care plan؛
- پاسخ به مواردی که نیازمند تصمیم پزشکی‌اند.

### ۵.۷ مدیر tenant

- تنظیم ساعات، SLA، routing و templates؛
- مشاهدهٔ متریک‌های aggregate؛
- بدون حق تغییر آزاد knowledge بالینی global.

---

## ۶. معماری اطلاعات پرتال

### Navigation سطح اول

```text
امروز
برنامهٔ مراقبت
ثبت اندازه‌گیری
داروها و درخواست‌ها
نوبت‌ها
پیام‌ها
آموزش من
نتایج و پرونده
همراهان و حریم خصوصی
حساب و تنظیمات
```

در موبایل، bottom navigation حداکثر پنج مقصد پرتکرار دارد:

```text
امروز | ثبت | برنامه | پیام‌ها | بیشتر
```

---

## ۷. صفحهٔ «امروز»

### ۷.۱ ترتیب محتوا

1. **سلام و وضعیت اتصال به کلینیک**
2. **اقدام‌های امروز** — حداکثر سه مورد
3. **وضعیت داده/درخواست اخیر**
4. **نوبت یا تماس بعدی**
5. **دارو/refill نزدیک**
6. **پیشرفت یک هدف منتخب**
7. **مسیر کمک/تماس**

### ۷.۲ Action Card

هر کارت باید داشته باشد:

```text
title_fa
due_at / due_window
plain_reason
instructions
estimated_effort
responsible_party
completion_method
status
safety_note
source_care_plan_activity_id
```

نمونه‌های مجاز:

- «فشار خون صبح را ثبت کنید»
- «برای آزمایش HbA1c وقت بگیرید»
- «درخواست تمدید نسخه را تکمیل کنید»
- «نوبت هفتهٔ آینده را تأیید کنید»

### ۷.۳ الگوریتم ترتیب

در نسخهٔ اول ranking هوش مصنوعی نیست. ترتیب deterministic و قابل توضیح است:

1. safety instruction مصوب پزشک؛
2. activity امروز/overdue بر اساس care plan فعال؛
3. درخواست منتظر اقدام بیمار؛
4. refill یا appointment نزدیک؛
5. education مرتبط با activity جاری.

موارد `pending_review` نباید به‌عنوان نتیجهٔ قطعی یا «وضعیت سلامت» نمایش داده شوند.

---

## ۸. برنامهٔ مراقبت

### ۸.۱ تمایز مهم

- **Protocol/Template:** برنامهٔ عمومی بیماری یا tenant؛
- **CarePlan:** برنامهٔ مصوب همین بیمار؛
- **Goal:** نتیجهٔ موردنظر؛
- **Activity:** کار زمان‌دار؛
- **Task:** اجرای عملیاتی توسط بیمار یا تیم؛
- **Recommendation:** پیشنهاد موتور که هنوز plan نیست.

### ۸.۲ CarePlan state machine

```text
draft
→ proposed
→ clinician_approved
→ active
→ paused
→ completed
→ superseded
→ cancelled
```

فقط planهای `active` و `clinician_approved` می‌توانند action بیمار بسازند.

### ۸.۳ Goal

Goal باید شامل این موارد باشد:

```text
clinical_or_behavioral_type
description_patient_fa
target representation
start / target date
owner
status
measurement source
individualization rationale
```

هدف عددی فقط وقتی به بیمار نشان داده می‌شود که پزشک آن را برای بیمار تأیید کرده باشد؛ target عمومی guideline جای target فردی را نمی‌گیرد.

### ۸.۴ Activity

```text
measure
lab
medication_adherence
refill_request
appointment
education
symptom_check
care_team_call
lifestyle_action
```

هر activity باید owner، cadence، completion evidence، escalation policy و patient-facing wording داشته باشد.

---

## ۹. ثبت اندازه‌گیری خانگی

### ۹.۱ lifecycle داده

```text
local_draft
→ submitted
→ received
→ syntactic_valid
→ pending_review
→ verified | rejected | needs_clarification
→ incorporated_into_record
```

### ۹.۲ provenance اجباری

```text
patient / caregiver / device / staff
manual / connected device
measured_at
submitted_at
device metadata if available
protocol context
verification actor/time
rejection/clarification reason
```

### ۹.۳ فشارخون

نسخهٔ اول باید بتواند این contextها را بگیرد، بدون تحمیل همه در هر submission:

- صبح/شب؛
- قبل یا بعد دارو؛
- نشسته/استراحت کافی؛
- reading اول/دوم؛
- علائم همراه؛
- دستگاه دستی یا متصل.

UX باید امکان ثبت جفت reading و محاسبهٔ summary را در backend فراهم کند، ولی نباید یک reading منفرد را «کنترل‌شده/خطرناک» قطعی اعلام کند مگر بر اساس rule ایمنی مصوب.

### ۹.۴ دیابت

contextهای اولیه:

```text
fasting
pre_meal
post_meal
bedtime
symptomatic
other
```

برای hypoglycemia یا مقدار بسیار خارج از محدوده، UI فقط safety instruction مصوب و کانال تماس را نشان می‌دهد؛ تغییر دوز خودکار ممنوع است.

### ۹.۵ قلب/HF در فاز بعد

وزن، علائم، فشار و ضربان فقط برای بیمارانی فعال می‌شوند که care program و تیم پاسخ‌گو دارند. جمع‌آوری روزانهٔ داده بدون capacity پاسخ ممنوع است.

---

## ۱۰. پیام امن و درخواست ساختاریافته

### ۱۰.۱ تصمیم محصول

نسخهٔ اول «صندوق درخواست ساختاریافته با thread» است، نه chat آزاد بدون مرز.

### ۱۰.۲ دسته‌ها

```text
appointment
refill_renewal
medication_question
measurement_question
new_or_worsening_symptom
lab_or_result_question
care_plan_question
administrative
technical_support
complaint_or_feedback
```

### ۱۰.۳ routing پیشنهادی

| دسته | مقصد اولیه | escalation |
|---|---|---|
| appointment | reception queue | care coordinator در conflict |
| refill renewal | nurse/refill queue | physician approval |
| administrative | reception | manager |
| measurement | verification inbox | nurse سپس physician |
| clinical question | clinical queue | physician |
| symptom update | clinical triage | urgent protocol/phone |
| technical | support | tenant admin |
| complaint | customer support/manager | compliance |

### ۱۰.۴ Message thread state machine

```text
submitted
→ received
→ triaged
→ assigned
→ acknowledged
→ waiting_for_patient | waiting_for_team
→ resolved
→ closed
```

### ۱۰.۵ SLA

SLA tenant-scoped و category-specific است. بیمار باید پیش از ارسال بداند:

- این کانال برای اورژانس نیست؛
- پاسخ در چه بازه‌ای انتظار می‌رود؛
- برای چه موضوعی تماس یا مراجعه لازم است؛
- پیام به «تیم» می‌رود، نه الزاماً پزشک مشخص.

### ۱۰.۶ کنترل بار

- form ساختاریافته قبل از متن آزاد؛
- FAQ/contextual education پیش از ارسال، بدون جلوگیری از تماس لازم؛
- duplicate detection در یک window؛
- thread به جای پیام‌های جدا؛
- quick response templates با امکان ویرایش؛
- nurse/admin triage؛
- routing بر پایهٔ category و care team؛
- ساعات کاری و out-of-office؛
- queue depth و aging metrics؛
- هیچ notification interruptive برای هر پیام به پزشک.

AI می‌تواند category یا draft پیشنهاد دهد، اما تصمیم route و پاسخ clinical در نسخهٔ اول deterministic/human-reviewed است.

---

## ۱۱. همراه و proxy access

### ۱۱.۱ اصل

هر همراه حساب و credential مستقل دارد. استفاده از credential بیمار ممنوع و در آموزش صریحاً منع می‌شود.

### ۱۱.۲ CaregiverGrant

```text
grant_id
tenant_id
patient_id
griver_identity_id
relationship
caregiver_type
scopes
consent_record_id
valid_from
expires_at
status
issued_by
revoked_by / revoked_at / reason
last_used_at
```

### ۱۱.۳ scopeهای نسخهٔ اول

```text
view_today
view_care_plan
view_results_summary
manage_appointments
submit_measurements
request_refill
send_messages
view_medications
manage_notifications
```

دسترسی مالی، diagnosis کامل، notes و export به‌طور پیش‌فرض جدا و خاموش‌اند.

### ۱۱.۴ state machine grant

```text
invited
→ identity_verified
→ patient_consent_pending
→ active
→ suspended | expired | revoked
```

### ۱۱.۵ سناریوهای خاص

- بیمار قادر به consent دیجیتال نیست؛ نیازمند workflow حقوقی/حضوری و evidence است.
- چند caregiver می‌توانند scope متفاوت داشته باشند.
- بیمار باید بتواند همهٔ دسترسی‌ها و last access را ببیند.
- revocation فوری است و sessionهای مرتبط را invalid می‌کند.
- caregiver در هر submission/message با هویت خودش ثبت می‌شود.
- محتوای حساس می‌تواند per-item visibility policy داشته باشد؛ این تصمیم نیازمند review حقوقی و بالینی است.

### ۱۱.۶ حمایت از caregiver

پرتال فقط دسترسی نیست. باید امکان این موارد را در backlog نگه دارد:

- راهنمای وظایف واگذار‌شده؛
- آموزش اندازه‌گیری/دارو؛
- درخواست کمک؛
- مشخص‌بودن مرز مسئولیت؛
- ارزیابی burden در programهای پیچیده.

---

## ۱۲. هویت، ورود و بازیابی

### ۱۲.۱ تفکیک identity

```text
Accounting Patient Identity
Clinical Enrollment
Portal Identity
Portal Account
Caregiver Identity
Consent / Grant
```

یک بیمار می‌تواند در چند tenant پرونده داشته باشد؛ محصول باید تصمیم بگیرد آیا یک login سراسری با انتخاب سازمان دارد یا حساب tenant-bound. فرضیهٔ دور دوم: **identity مرکزی + membership/grant tenant-scoped** برای تجربهٔ بهتر، ولی این نیازمند threat model و تصمیم حقوقی است.

### ۱۲.۲ onboarding اولیه

برای پایلوت:

1. دعوت توسط کلینیک؛
2. identity proofing حضوری یا با دادهٔ از قبل تأییدشده؛
3. فعال‌سازی با channel مجاز؛
4. تعریف روش recovery؛
5. نمایش consent و حریم خصوصی به زبان ساده؛
6. انتخاب notification؛
7. آموزش ۳ دقیقه‌ای صفحهٔ امروز و ثبت داده.

Self-service onboarding عمومی تا زمانی که identity proofing و abuse controls روشن نشده، defer می‌شود.

### ۱۲.۳ session security

- short-lived access + rotating refresh/session؛
- revoke on password/recovery/grant changes؛
- device/session list؛
- rate limiting و lockout متناسب؛
- generic error برای جلوگیری از enumeration؛
- step-up authentication برای export، caregiver grant و تغییر اطلاعات حساس؛
- notification ورود جدید؛
- audit بدون ذخیرهٔ secret/token خام.

### ۱۲.۴ recovery

Recovery نباید فقط به شماره موبایل قدیمی وابسته باشد. گزینه‌ها باید پس از بررسی حقوقی/عملیاتی انتخاب شوند:

- recovery حضوری؛
- تماس تأییدشده با workflow کارکنان؛
- کد recovery؛
- caregiver کمکی بدون امکان takeover؛
- مدارک/شناسه رسمی فقط با data minimization.

---

## ۱۳. رضایت، ترجیحات و notification

### ۱۳.۱ ConsentRecord

```text
purpose
scope
channel
text_version
captured_at
captured_by
method
expires_at
withdrawn_at
proof reference
```

رضایت پردازش، پیامک، push، research و caregiver access یکی نیستند.

### ۱۳.۲ Notification preference

بیمار برای هر دسته می‌تواند channel و quiet hours را تنظیم کند:

```text
care_plan_due
appointment
new_message
review_completed
refill
education
administrative
```

red-flag safety communication policy جداست و باید با رضایت/قانون و protocol کلینیک هماهنگ شود؛ preference نباید emergency duty را مبهم کند.

### ۱۳.۳ delivery states

```text
queued → sent → delivered | failed | suppressed
```

delivery برابر understood یا acted نیست. completion فقط با event واقعی ثبت می‌شود.

---

## ۱۴. Accessibility و طراحی برای سواد محدود

### معیار پایه

WCAG 2.2 AA + usability test انسانی با سالمند، کم‌سواد و کاربر دارای محدودیت بینایی/حرکتی.

### قرارداد UI

- متن پایه حداقل خوانا و قابل بزرگ‌نمایی تا ۲۰۰٪؛
- target لمسی بزرگ و فاصله‌دار؛
- focus-visible؛
- label ثابت، نه placeholder-only؛
- خطا کنار field با راه اصلاح؛
- رنگ + متن + icon؛
- تاریخ جلالی و زمان ایران، با فرمت گفتاری ساده؛
- اعداد فارسی قابل انتخاب، ولی data entry پذیرای فارسی/لاتین؛
- voice instruction برای taskهای منتخب؛
- animation حداقلی و reduced-motion؛
- low-bandwidth و offline-friendly shell؛
- هیچ CAPTCHA پیچیده یا آزمون شناختی برای login؛
- help در محل همان task؛
- زبان بالینی ساده و glossary اختیاری.

### UX پژوهش‌محور

قبل از implementation نهایی:

1. expert heuristic review؛
2. task-based test با prototype؛
3. test واقعی با حداقل دو سطح سواد دیجیتال؛
4. caregiver-assisted scenario؛
5. screen reader و keyboard؛
6. گوشی کوچک/قدیمی و اینترنت ضعیف؛
7. comprehension test، نه فقط task completion.

---

## ۱۵. ایمنی بالینی

### ۱۵.۱ اصل ارائه به بیمار

بیمار پیشنهاد خام موتور را نمی‌بیند. او یکی از این‌ها را می‌بیند:

- care plan مصوب پزشک؛
- instruction مصوب program؛
- education بررسی‌شده؛
- status خنثی دادهٔ در انتظار review؛
- safety instruction با منبع و مالک بالینی.

### ۱۵.۲ red flag

هر program باید تعریف کند:

```text
trigger
required context
patient wording
immediate action
clinic routing
response SLA
fallback channel
false-positive handling
logging and audit
```

keyword detection یا مدل AI تنها می‌تواند کمک‌هشدار باشد؛ نباید تنها مرز ایمنی باشد.

### ۱۵.۳ منع اطمینان کاذب

عبارت‌های ممنوع مگر در context مصوب:

- «همه‌چیز خوب است» بر اساس یک reading؛
- «نیازی به مراجعه نیست»؛
- «دارو را تغییر دهید»؛
- «پزشک فوراً خواهد دید» بدون SLA واقعی؛
- «پیام شما بررسی شد» اگر فقط تحویل شده باشد.

---

## ۱۶. مدل مفهومی داده

```text
PortalIdentity
PortalAccount
PortalMembership
PatientPortalProfile
CaregiverGrant
ConsentRecord
NotificationPreference
PortalSession
CarePlan
CareGoal
CareActivity
PatientTask
PatientSubmission
SubmissionReview
MessageThread
Message
MessageAssignment
ServiceLevelPolicy
EducationAssignment
PortalAuditEvent
```

### قواعد tenant

- هر membership/grant/activity/thread tenant-scoped است.
- identity مرکزی نباید اجازهٔ cross-tenant data access بدهد.
- cache، search، notification و export نیز tenant key اجباری دارند.
- caregiver می‌تواند برای بیماران چند tenant grant جدا داشته باشد؛ data merge خودکار نمی‌شود.

---

## ۱۷. قرارداد API مفهومی

نام endpointها هنوز تصمیم نهایی نیست؛ قابلیت‌های لازم:

```text
POST   portal invitations / activate / login / logout / recovery
GET    portal me / organizations / sessions
GET    today / care-plan / tasks / medications / appointments / results
POST   observations / symptom-checks
GET    submissions/{id}/status
POST   requests / messages
GET    threads / thread detail
POST   caregiver invitations / accept / revoke
GET    consents / preferences / audit-summary
PATCH  notification preferences / accessibility preferences
```

تمام writeها idempotency key و audit event دارند. responseهای patient-facing باید text version و locale را قابل ردیابی کنند.

---

## ۱۸. معیارها

### Activation

- دعوت صادرشده → حساب فعال؛
- زمان تا first value؛
- completion آموزش اولیه؛
- activation با/بدون caregiver.

### Engagement مفید

- درصد کاربران دارای task واقعی، نه login خام؛
- action completion؛
- submission موفق؛
- status viewed؛
- appointment/refill request completion؛
- caregiver grant استفاده‌شده.

### Workflow

- time to triage؛
- time to acknowledge؛
- time to resolve؛
- queue aging؛
- reassignment؛
- duplicate contact؛
- phone fallback.

### Safety

- unreviewed high-priority submission؛
- red-flag response delay؛
- wrong-tenant access attempt؛
- message misrouting؛
- false reassurance complaint؛
- credential sharing signal؛
- revoked grant session use؛
- accessibility failure.

### Equity

metricها بر اساس این عوامل، در حد مجاز و privacy-safe، segment شوند:

- سن؛
- caregiver use؛
- device/connection class؛
- assisted vs self-service onboarding؛
- language/accessibility mode؛
- location/tenant type.

هدف شناسایی شکاف است، نه رتبه‌بندی یا محروم‌کردن بیمار.

---

## ۱۹. User stories و acceptance criteria منتخب

### Story A — اقدام امروز

**As a patient**, می‌خواهم مهم‌ترین کار امروز را ببینم تا مراقبت را فراموش نکنم.

```text
Given یک CarePlan فعال و approved دارد
And چند activity سررسید شده است
When صفحهٔ امروز باز می‌شود
Then حداکثر سه اقدام با موعد، دلیل ساده و CTA نمایش داده می‌شود
And هر اقدام به activity واقعی لینک است
And هیچ recommendation تأییدنشده نمایش داده نمی‌شود
```

### Story B — وضعیت self-report

```text
Given بیمار فشار را ثبت کرده است
When submission در verification inbox قرار می‌گیرد
Then بیمار «دریافت شد — در انتظار بررسی» را می‌بیند
And مقدار به‌عنوان verified در trend اصلی نمایش داده نمی‌شود
When پزشک/پرستار مجاز آن را verify می‌کند
Then وضعیت و زمان بررسی به‌روز می‌شود
```

### Story C — همراه مستقل

```text
Given بیمار برای فرزندش scope manage_appointments داده است
When همراه با credential خودش وارد می‌شود
Then فقط نوبت‌ها و عملیات مجاز را می‌بیند
And هر اقدام با هویت همراه audit می‌شود
And دسترسی به diagnosis/notes/finance رد می‌شود
When بیمار grant را revoke می‌کند
Then session همراه فوراً دسترسی بیمار را از دست می‌دهد
```

### Story D — پیام ساختاریافته

```text
Given بیمار درخواست refill ثبت می‌کند
When درخواست ارسال می‌شود
Then category و tenant care team آن را به refill queue route می‌کنند
And بیمار SLA و status را می‌بیند
And پزشک تنها زمانی notification می‌گیرد که protocol نیازمند approval است
```

### Story E — emergency boundary

```text
Given بیمار دستهٔ symptom update را انتخاب می‌کند
When فرم باز می‌شود
Then پیام واضح «برای اورژانس نیست» و کانال فوری نمایش داده می‌شود
And submission همچنان قابل ارسال است مگر protocol خلاف آن را بگوید
And keyword/AI detection تنها یک escalation کمکی ایجاد می‌کند
And هیچ پیام موفقیت، پاسخ فوری پزشک را تضمین نمی‌کند
```

### Story F — accessibility

```text
Given کاربر با keyboard یا screen reader کار می‌کند
When جریان ثبت فشار را انجام می‌دهد
Then تمام کنترل‌ها label، focus order و error announcement صحیح دارند
And بدون اتکا به رنگ task کامل می‌شود
And zoom 200% باعث از دست‌رفتن محتوا یا اقدام نمی‌شود
```

---

## ۲۰. Threat model اولیه

| تهدید | نمونه | کنترل پایه |
|---|---|---|
| Account takeover | SIM swap، password reuse | step-up، session/device list، recovery حضوری، rate limit |
| Patient enumeration | login/recovery response | generic response و timing-safe flow |
| Cross-tenant leak | cache/search/export | tenant key در همهٔ layers + adversarial tests |
| Caregiver overreach | scope بیش از رضایت | explicit grants، default deny، revoke، audit |
| Shared credential | همراه با حساب بیمار | proxy onboarding آسان، detection و آموزش |
| Token leakage | public card/report link | short TTL، scope، revoke، no PHI URL beyond opaque token |
| Message safety failure | urgent symptom در admin queue | structured category، triage rules، escalation، SLA |
| False reassurance | delivery به‌جای review | semantic states و wording contract |
| Notification privacy | PHI در lock screen/SMS | minimum-necessary content و preferences |
| Device data spoofing | forged source/measurement | provenance، device trust level، verification |
| AI hallucination | پاسخ یا explanation نادرست | human review، source citation، restricted use |
| Support impersonation | admin view | break-glass/impersonation audit و reason |

Threat model نهایی نیازمند security/privacy و legal review است.

---

## ۲۱. Rollout پیشنهادی

### Phase 0 — Research and prototype

- service blueprint؛
- prototype صفحهٔ امروز؛
- identity/recovery threat model؛
- caregiver consent workshop؛
- ظرفیت inbox و SLA؛
- usability test.

### Phase 1 — Authenticated read-only

- account، login، care plan، tasks، appointments، verified results؛
- caregiver view-only؛
- audit و accessibility.

### Phase 2 — Structured actions

- self-monitoring؛
- refill/appointment requests؛
- status tracking؛
- verification inbox integration.

### Phase 3 — Messaging and team routing

- structured threads؛
- category queues؛
- SLA؛
- templates؛
- workload dashboards.

### Phase 4 — Connected care

- device adapters؛
- richer program protocols؛
- personalized education؛
- secure asynchronous care models.

هر phase باید tenant opt-in، feature flag، rollback و metric review داشته باشد.

---

## ۲۲. گیت‌های پیش از کدنویسی production

1. تصمیم identity model و recovery در ایران؛
2. privacy/legal review consent و caregiver؛
3. تعریف operational owner و SLA هر queue؛
4. clinical sign-off red-flag wording؛
5. ظرفیت staff برای review داده؛
6. accessibility prototype test؛
7. data retention/export policy؛
8. tenant/location model؛
9. API threat model؛
10. acceptance criteria نهایی برای Phase 1.

---

## ۲۳. شواهد این دور

- patient portal feature review: [Norouzi Aval et al., 2025](https://doi.org/10.1002/hsr2.70520)
- portal adoption/self-efficacy/privacy: [Son et al., 2021](https://doi.org/10.1111/jnu.12633)
- inclusive older-adult symptom reporting: [Reading Turchioe et al., 2020](https://doi.org/10.1111/jgs.16403)
- portal use by older adults/caregivers: [Burgdorf et al., 2022](https://doi.org/10.1111/jgs.18187)
- caregiver communication/training: [Howe et al., 2023](https://doi.org/10.1111/jgs.18686)
- caregiver portal design needs: [Portz et al., 2022](https://doi.org/10.1111/jgs.17818)
- secure message taxonomy: [Heisey-Grove et al., 2021](https://doi.org/10.1002/hsr2.295)
- messaging workload/high utilizers: [Ahmad et al., 2026](https://doi.org/10.1002/lary.70465)
- secure messaging human factors: [Aziz et al., 2022](https://doi.org/10.1002/jhm.12953)
- digital inequality risk: [Price & Simpson, 2022](https://doi.org/10.1002/cld.1171)

شواهد عمدتاً خارج از ایران و heterogeneous هستند؛ PRD باید با مصاحبه و usability test محلی اعتبارسنجی شود.

---

## ۲۴. نتیجهٔ دور دوم

پرتال بیمار یک «صفحهٔ جذاب» نیست؛ یک سیستم socio-technical است که هم‌زمان identity، consent، care plan، queue، staffing، SLA، ایمنی و accessibility می‌خواهد. ساخت UI پیش از تثبیت این قراردادها، احتمالاً محصولی زیبا ولی ناامن یا پرهزینه برای کلینیک می‌سازد.

فرضیهٔ قوی این دور:

> **نسخهٔ اول پرتال باید action-first، plan-backed، caregiver-aware و team-routed باشد؛ نه chart-heavy، chat-first یا AI-first.**
