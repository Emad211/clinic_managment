# نقشهٔ فاز ۳ — پنلِ پزشک: صفِ زنده + نمای سادهٔ ویزیت + «مرحله بعد»

> برگرفته از مشورتِ تیم (`clinical-product-advisor` + `frontend-dev-advisor` + `backend-dev-advisor`، ۱۴۰۵/۰۳/۳۱). هم‌خانواده: [`record_redesign_plan.md`](record_redesign_plan.md).

## هدف (جریانِ پزشک)
پذیرش فاکتورِ **ویزیت** را باز می‌کند → بیمار به **صفِ زندهٔ پزشک** (در نوبت/انجام‌شده) می‌رود → پزشک انتخاب می‌کند → **پروندهٔ سادهٔ ویزیت** (اطلاعاتِ قبلی + ورودِ جدید) → دکمهٔ **«مرحله بعد»**.

## معماری (هم‌راستا با ADR-0002/0003)
- **صف = خواندنِ زندهٔ فاکتورهای بازِ ویزیت از پلِ read-only** (نه رویداد/Outbox). **صفر نوشتن در حسابداری.**
- **وضعیتِ در‌نوبت/انجام‌شده = جدولِ نوِ `doctor_visit_log` در `specialist.db`** (نه آلودنِ `processed_invoices`؛ جدا نگه‌داشتنِ مسئولیت‌ها).
- **«انجام‌شده» در پنلِ پزشک = پزشک دکمه زد** (state تخصصی)؛ **بستنِ فاکتورِ حسابداری را انجام نمی‌دهد** (کارِ پذیرش). این تفکیک باید در UI صریح باشد. اگر پذیرش زودتر فاکتور را بست → بَجِ «فاکتور بسته شد» (نه ناپدیدشدنِ سایلنت).
- **نمای سادهٔ ویزیت = `visit_quick.html`ِ نوِ سبک** (نه `detail.html`ِ غنیِ ~۱۳۶۸‌خطی). بازاستفاده از `pt-head`، `vital-row` (بدونِ sparkline)، فرمِ «ثبت سریع شاخص‌ها»، یادداشت.
- **ورودِ داده در جداولِ موجود:** شاخص‌های امروز → `vital_readings` (`VitalsRepository.add_reading`، که موتورِ بالینی را هم تغذیه می‌کند)؛ یادداشت → `clinical_notes` (`RecordRepository.add_note(kind='exam')`). **هیچ جدولِ نوِ داده‌ای جز `doctor_visit_log` لازم نیست.**
- **walk-inِ غیرِ‌enrolled:** نمای کمینه (نام + ساعتِ پذیرش + یادداشتِ آزاد + لینکِ «ثبت‌نام»)؛ **هیچ پیشنهادِ موتور/هشدارِ بالینی/داروی آخرین** (اصلِ «پزشک نمی‌داندش = صفحه هم نمی‌داند» — بدون توهم).
- **«مرحله بعد» = اتصال به اقدام‌های موجود:** نوبت (`AppointmentService.schedule`)، پیگیری (`FollowupRepository.create`)، دعوت (`EngagementService.enqueue_invite`)، نسخهٔ آزاد (`RecordRepository.add_prescription`). برای walk-in (بدونِ `patient_link_id`) این گزینه‌ها گیت شوند.

## جدولِ داده (افزایشی، idempotent)
```sql
CREATE TABLE IF NOT EXISTS doctor_visit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    accounting_invoice_id INTEGER NOT NULL UNIQUE,  -- idempotency؛ از invoices.id پل
    patient_link_id INTEGER,                         -- NULL برای walk-in
    national_id TEXT,
    full_name TEXT NOT NULL,
    work_date TEXT NOT NULL,                          -- YYYY-MM-DD
    status TEXT NOT NULL DEFAULT 'waiting',           -- waiting | in_progress | done
    started_at TIMESTAMP, done_at TIMESTAMP,
    physician_notes TEXT, done_by TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now','+3 hours','+30 minutes')),
    FOREIGN KEY (patient_link_id) REFERENCES patient_links(id)
);
```

## زیرتسک‌ها (~۶.۵–۹ روز)
| # | زیرتسک | فایل‌ها | زحمت |
|---|---|---|---|
| ۱ | `fetch_open_visit_invoices(work_date, doctor?, limit)` (read-only) | `accounting_bridge.py` | ۰.۵ |
| ۲ | جدولِ `doctor_visit_log` (schema + `_run_migrations`) | `schema.sql`, `core.py` | ۰.۵ |
| ۳ | `doctor_queue_repo.py` (SQLِ صف/state) | adapters | ۰.۵ |
| ۴ | `DoctorQueueService` (واکشیِ صف با LEFT JOIN لجر + start/done) | services | ۱ |
| ۵ | بلوپرینتِ `doctor_queue.py` (`/doctor-queue`, `/start`, `/done`) + قالبِ صف + ورودیِ سایدبار | api، templates، base.html | ۱.۵ |
| ۶ | `visit_quick.html` (اطلاعاتِ قبلیِ فشرده + فرمِ شاخص/یادداشت، wiring به repos موجود) | templates، api | ۱ |
| ۷ | «مرحله بعد» (MVP: انجام‌شد + نوبتِ بعدی؛ بقیه از پروندهٔ کامل) | templates، api | ۱ |
| ۸ | تستِ `test-engineer` روی کپی (صف، start/done idempotent، walk-in بدونِ توهم، صفر نوشتن sha256) | tests | ۰.۵ |

## تصمیم‌های باز (پیشنهادِ تیم؛ نیازِ تأییدِ مالک/پزشک)
1. **دامنهٔ صف:** فقط فاکتورهای دارای ویزیت (پیشنهاد) یا همهٔ فاکتورهای باز؟
2. **«انجام‌شده»:** پزشک دکمه زد (پیشنهاد) یا فاکتور بسته شد؟
3. **MVPِ «مرحله بعد»:** حداقل (انجام+نوبت، پیشنهاد) یا منوی کامل؟
4. **پیش‌فرض‌های تصمیم‌گرفته (قابلِ‌تغییر):** ورودِ شاخص‌ها → `vital_readings` (تغذیهٔ موتور)؛ walk-in = نمای کمینه + لینکِ ثبت‌نام؛ نقش = همان `staff` (بدونِ نقشِ جدید)؛ ترتیبِ صف = FIFO روی `opened_at`؛ فیلترِ «فقط بیمارانِ این پزشک» موکول (چون `visits.doctor_name` متنِ آزاد است؛ `invoices.doctor_id` مطمئن‌تر ولی نیازِ تأییدِ پرشدنش در عمل).

## ایمنی و گاردریل
صفر نوشتن در حسابداری (پل `mode=ro`) · migrationِ افزایشیِ idempotent · تست روی کپی + اثباتِ sha256 · «انجام‌شده»≠بستنِ فاکتور (UI شفاف) · walk-in بدونِ توهمِ بالینی · Jalali/وقتِ ایران · بدونِ CDN.

## نامعلوم‌های نیازمندِ بررسی
- آیا `invoices.doctor_id` در عمل توسطِ پذیرش پر می‌شود (برای فیلترِ پزشک)؟
- حجمِ فاکتورهای بازِ روزانه (برای رفرشِ زنده؛ زیرِ ~۵۰، رفرشِ ۳۰ثانیه/دستی کافی است).
