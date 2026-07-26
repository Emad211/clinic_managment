# ADR-0005 — مرز قطعی درآمد مطب تخصصی

## وضعیت

پذیرفته‌شده — Tranche A0

## زمینه

دیتابیس حسابداری درمانگاه حدود شش ماه دادهٔ عملیاتی واقعی دارد. هنگام ورود یک بیمار به
برنامهٔ کلینیک تخصصی، تاریخچهٔ گذشتهٔ او برای تصمیم‌گیری و مشاهده در پرونده مفید است؛
اما مراجعه‌ها و فاکتورهای گذشته، و همچنین مراجعه‌های عمومی آینده، درآمد کلینیک تخصصی
محسوب نمی‌شوند.

اپ کلینیک تخصصی حق تغییر schema، داده یا lifecycle اپ حسابداری را ندارد. تمام خواندن‌ها
از SQLite حسابداری با `mode=ro` انجام می‌شوند.

## تصمیم

### ۱. تاریخچه و درآمد دو دامنهٔ متفاوت‌اند

```text
Accounting history visibility
    ≠
Specialist revenue attribution
```

تمام تاریخچهٔ accounting patient می‌تواند در پرونده دیده شود، ولی هیچ مبلغی فقط به علت
تاریخ پس از enrollment، کد ملی، شماره موبایل یا شباهت زمانی وارد درآمد تخصصی نمی‌شود.

### ۲. enrollment یک cutover تغییرناپذیر دارد

اولین ورود بیمار از حسابداری، در یک transaction تخصصی این دو رکورد را ایجاد می‌کند:

```text
patient_links
specialist_program_enrollments
```

cutover شامل accounting patient ID، زمان مؤثر، زمان snapshot و بالاترین invoice ID موجود
در همان لحظه است. cutoff صرفاً evidence تاریخی است و به‌تنهایی revenue eligibility ایجاد
نمی‌کند.

### ۳. attribution فقط از Journey/Encounter می‌آید

یک فاکتور فقط وقتی در KPI تخصصی قرار می‌گیرد که آخرین event آن برابر `ATTRIBUTED` باشد و
به هویت دقیق زیر متصل شود:

```text
specialist enrollment
→ CareJourney
→ CareEncounter
→ accounting invoice
```

شروع ویزیت از صف پزشک، Journey، Encounter، attribution و doctor-queue state را در یک
transaction در دیتابیس تخصصی ایجاد می‌کند.

### ۴. منبع حقیقت مالی همچنان حسابداری است

کلینیک تخصصی فقط invoice IDهای واجد scope را نگهداری می‌کند. مبلغ صورتحساب و وصول از
جداول فعلی حسابداری read-only خوانده می‌شوند. اگر accounting DB یا payment schema قابل
خواندن نباشد، داشبورد `unavailable` می‌شود و عدد صفر حدسی تولید نمی‌کند.

### ۵. campaign attribution تا اتصال Journey متوقف است

مدل قدیمی «هر درآمد بیمار در پنجرهٔ ۶۰ روز بعد از SMS» می‌توانست درآمد عمومی نامرتبط را
به campaign نسبت دهد و یک فاکتور را چند بار بشمارد. تا زمان ایجاد مسیر صریح زیر، KPI
کمپین جمع‌پذیر نیست:

```text
campaign audience
→ delivered communication
→ patient response
→ CareJourney
→ Encounter
→ invoice attribution
```

## پیامدها

- داده‌های تاریخی حسابداری حذف یا تغییر نمی‌شوند.
- webapp و دیتابیس حسابداری هیچ migration یا write دریافت نمی‌کنند.
- بیمار دستی local-only است و اتصال حسابداری حدس زده نمی‌شود.
- Control Room فقط collected revenue فاکتورهای attributed را برای value dimension می‌بیند.
- linked patient قدیمی بدون cutover وضعیت readiness را fail-closed می‌کند؛ دیتابیس تست
  کلینیک تخصصی باید reset یا با migration بازبینی‌شده اصلاح شود.
- مراحل بعدی Journey می‌توانند task، تماس، پیام، نوبت، حضور و outcome را به همین هویت
  متصل کنند.

## موارد خارج از A0

- پرداخت جزئی و refund
- تفکیک وصول بیمار و بیمه
- هزینهٔ SMS و نیروی انسانی
- campaign ROI
- ContactAttempt events
- Unified Follow-up Projection
- اتصال canonical observationها به Encounter
