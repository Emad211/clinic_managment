# بررسی لوکال گام نهایی موتور بالینی

## اجرای سریع محیط جداگانهٔ بررسی

از ریشهٔ مخزن:

### Windows PowerShell

```powershell
cd specialist_clinic
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py run_step7_review.py --reset
```

### Linux / macOS

```bash
cd specialist_clinic
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run_step7_review.py --reset
```

صفحه به‌طور خودکار باز می‌شود. در صورت بازنشدن مرورگر:

```text
http://127.0.0.1:5057/manager/clinical-engine?step=3#engine-actions
```

ورود دیتابیس review:

```text
username: admin
password: admin
```

این credential فقط در محیط development و دیتابیس جداگانهٔ review استفاده می‌شود.
production با رمز پیش‌فرض بالا نمی‌آید.

## محل دیتابیس review

```text
specialist_clinic/instance/step7-review/clinic-step7-review.db
```

`--reset` فقط همین پوشه را حذف و بازسازی می‌کند و به دیتابیس اصلی مطب دست نمی‌زند.

## مواردی که باید در UI بررسی شوند

1. بخش «اعتبارسنجی Golden Case و دروازهٔ انتشار» نمایش داده شود.
2. وضعیت validation برابر PASS باشد.
3. False Positive، False Negative و Error همگی صفر باشند.
4. تطابق Ruleset برابر «بله» باشد.
5. هشت کیس در ماتریس دیده شوند.
6. جست‌وجوی `conflict` فقط کیس تعارض را نگه دارد.
7. برای هر rule حداقل یک کنترل مثبت و یک کنترل منفی وجود داشته باشد.
8. تأیید بالینی و فنی با دو reviewer متفاوت نمایش داده شوند.
9. hashهای report، package، case bundle و rule identity قابل مشاهده باشند.
10. هیچ دکمه‌ای دارو، نسخه، تشخیص، پیامک یا ارجاع خارجی را خودکار اعمال نکند.

## اجرای عادی برنامه

```bash
python start.py
```

پورت پیش‌فرض:

```text
http://127.0.0.1:8090
```
