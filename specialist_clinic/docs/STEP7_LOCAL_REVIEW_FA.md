# بررسی لوکال گام ۷

## اجرا

### PowerShell

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

مرورگر را در این مسیر باز کنید:

```text
http://127.0.0.1:5057/manager/clinical-engine/validation
```

ورود توسعه:

```text
admin / admin
```

دیتابیس این runner مستقل است و در `instance/step7-review` قرار می‌گیرد. گزینهٔ
`--reset` فقط همین دیتابیس بررسی را پاک می‌کند.

## ترتیب بررسی

1. اجرای golden cases
2. مشاهدهٔ checkها، metrics و نتیجهٔ تک‌تک caseها
3. ثبت تأیید بالینی
4. ثبت تأیید فنی با کاربر/نام متفاوت
5. بازگشت به صفحهٔ راه‌اندازی و اجرای cohort ده‌بیماری

هیچ‌یک از این مراحل دارو، تشخیص، نسخه یا ارجاع خارجی را خودکار اعمال نمی‌کند.
