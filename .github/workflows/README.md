# CI Workflows

## ci.yml — سه‌گانهٔ CI

### سه job
| job | suite | عدد |
|-----|-------|-----|
| `backend` | pytest halqe (Django + Postgres) | 301 passed + 1 skipped |
| `schema-guard` | pytest test_pg_schema.py | 79 passed |
| `web` | jest halqe/web | 122 passed |

شکستِ هر job = قرمزشدنِ کل pipeline. PR بدون سبزشدنِ هر ۳ merge نمی‌شود.

### ایمنی دیتا
- Postgres سرویسِ throwaway است — فقط درون runner می‌زید و با پایانِ job نابود می‌شود.
- `clinic_new.db` (دیتای تولیدیِ حسابداری) **هرگز لمس نمی‌شود** — CI از SQLite استفاده نمی‌کند.
- هیچ SMS واقعی فرستاده نمی‌شود: کلیدِ Kavenegar ست نشده → NullProvider فعال.

### گیتِ مالک (قبل از اولین اجرای ابری)
1. **فعال‌کردنِ GitHub Actions:** `github.com/Emad211/clinic_managment` → Settings → Actions → General → "Allow all actions" را تأیید کن.
2. **دسترسیِ runner از ایران:** runner‌های `ubuntu-latest` در زیرساختِ GitHub (آمریکا) هستند؛ اتصالِ آن‌ها به Postgres سرویسِ داخلیِ همان runner است — مسدودیتِ اینترنتِ ایران اثری ندارد. تنها اگر بخواهی runner لوکال (self-hosted) داشته باشی این بند مطرح می‌شود.
3. **Self-hosted runner (اختیاری):** اگر Actions در دسترس نیست یا محدودیتِ پهنا وجود دارد، همین `ci.yml` روی Gitea/GitLab runner لوکال هم کار می‌کند — فقط `runs-on: ubuntu-latest` را به `runs-on: self-hosted` تغییر بده و مطمئن شو Docker روی ماشینِ runner دارد.

### env varهای CI
همهٔ credentialها dummy هستند (Postgres throwaway، SECRET_KEY تستی، بدون کلیدِ SMS). هیچ secret واقعی نیاز نیست تا زمانی که deploy target اضافه نشده باشد.
