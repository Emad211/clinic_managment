# CI Workflows

## `ci.yml` — production Flask applications

| job | suite |
|---|---|
| `specialist-clinic` | تمام تست‌های `specialist_clinic/tests/` |
| `accounting` | تمام تست‌های `webapp/tests/` |

شکست هر job کل pipeline را قرمز می‌کند. CI روی Python 3.13 اجرا می‌شود.

### ایمنی داده

- تست‌ها از SQLite موقت یا کپی‌های موقت استفاده می‌کنند.
- `webapp/clinic_new.db` نباید تغییر کند.
- scheduler در حالت تست اجرا نمی‌شود و هیچ کلید واقعی پیامکی در CI تنظیم نمی‌شود.
- هیچ سرویس Postgres یا درخت حذف‌شدهٔ `halqe/` در این workflow وجود ندارد.

### اجرای محلی

```powershell
cd specialist_clinic
.\.venv\Scripts\python.exe -m pytest tests -q --tb=short

cd ..\webapp
python -m pytest tests -q --tb=short
```
