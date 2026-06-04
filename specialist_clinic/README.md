# کلینیک تخصصی (Specialist Clinic)

اپلیکیشن مدیریت بیماری‌های مزمن (دیابت، فشار خون و ...) — مستقل از اپ حسابداری،
با پل **فقط-خواندنی** به دیتابیس حسابداری برای دریافت زنده‌ی اطلاعات بیمار.

## امکانات
- **ثبت‌نام بیمار**: از سامانه حسابداری (بر اساس کدملی) یا ثبت دستی.
- **پرونده مزمن**: بیماری‌ها، داروها، آلرژی‌ها.
- **پایش شاخص‌ها**: قند، HbA1c، فشار خون، وزن + نمودار روند + هشدار مقادیر خطرناک.
- **آزمایش‌ها**: ثبت نتایج با محدوده مرجع.
- **نوبت‌دهی**: شامل نوبت‌های دوره‌ای خودکار + یادآوری پیامکی.
- **پیگیری (worklist)**: تجدید دارو، بیماران کنترل‌نشده، بدون مراجعه اخیر، موعد ویزیت.
- **کمپین پیامکی**: گروه‌بندی هدفمند بیماران + ارسال با مدیانا (Mediana) + لاگ تحویل.
- **داشبورد مدیریتی**: نرخ کنترل بیماری، آمار بیماری‌ها، اثربخشی کمپین.
- **پشتیبان تصمیم بالینی**: چکاپ‌های دوره‌ای استاندارد.

## اجرا (حالت توسعه)
```powershell
cd specialist_clinic
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe start.py
```
مرورگر روی `http://127.0.0.1:8090` باز می‌شود. ورود اولیه: `admin` / `admin`.

## اتصال به دیتابیس حسابداری
به‌صورت پیش‌فرض دیتابیس حسابداری در `../webapp/clinic_new.db` خوانده می‌شود
(فقط-خواندنی؛ هرگز نوشته نمی‌شود). برای مسیر دیگر، متغیر محیطی تنظیم کنید:
```powershell
$env:ACCOUNTING_DB_PATH = "C:\path\to\clinic_new.db"
```

## تنظیم پیامک (مدیانا)
از منوی **مدیریت → تنظیمات**، `API Key` پنل مدیانا را وارد کنید (هدر `X-API-KEY`).
به‌صورت اختیاری می‌توانید «شماره ارسال اختصاصی» و «نوع پیام پیش‌فرض» را تعیین کنید.
- یادآوری نوبت → نوع «اطلاع‌رسانی» (Informational)
- کمپین‌های پیشنهادی → نوع «تبلیغاتی به مشتریان» (PromotionalToCustomers)
ارسال از طریق `POST https://api.mediana.ir/sms/v1/send/sms` انجام می‌شود (فقط stdlib، بدون پکیج اضافه).
تا قبل از وارد کردن کلید، پیامک‌ها در حالت شبیه‌سازی ثبت می‌شوند (ارسال واقعی انجام نمی‌شود).

## ساخت فایل اجرایی (.exe)
```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\pyinstaller --noconfirm --onefile --noconsole `
  --add-data "src/templates;src/templates" `
  --add-data "src/adapters/sqlite/schema.sql;src/adapters/sqlite" `
  --name SpecialistClinic start.py
```
دیتابیس `specialist.db` و پوشه `backups` کنار فایل exe ساخته می‌شوند.
مسیر دیتابیس حسابداری را با متغیر `ACCOUNTING_DB_PATH` تنظیم کنید.

## معماری
```
clinic_new.db (حسابداری)  ──ro──►  Specialist Clinic (Flask, پورت 8090)  ──►  specialist.db
```
- لایه‌بندی: `api/` → `services/` → `adapters/sqlite/`
- پل read-only: `src/adapters/accounting_bridge.py`
- اتصال با `sqlite3 mode=ro` — تضمین عدم تغییر دیتابیس حسابداری.
