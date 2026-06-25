# Runbook — Engagement scheduler in production (Step 51, cluster L)

> این سند **چطور** و **چرا**ی اجرای زمان‌بندی‌شدهٔ `run_engagement` در production را مستند می‌کند.
> مخاطب: DevOps/SRE و هر کسی که tick را راه می‌اندازد یا عیب‌یابی می‌کند.

## مفهوم در یک خط

halqe یک اپِ ابریِ Django است و **daemon-threadِ in-process ندارد** (برخلافِ Flaskِ
دسکتاپ). tickِ تعامل باید از یک **scheduler بیرونی** بیاید که `python manage.py run_engagement`
را هر چند دقیقه صدا بزند. اجرای هم‌پوشان به‌لطفِ **advisory lockِ سراسری** امن است.

```
external scheduler (cron / Celery beat)
        │  every N minutes
        ▼
python manage.py run_engagement
        │  pg_try_advisory_lock(GLOBAL_KEY)   ← no-concurrent-run guard
        ├─ NOT acquired → status=skipped_locked, exit 0   (another run in progress)
        └─ acquired:
              per-tenant: set_tenant_guc(tid) → run_all(tid) → clear_tenant_guc()
                   worklist/both → followup_task + dispatch ledger row
                   sms/both      → enqueue approval (PENDING)  ← هرگز ارسال نمی‌کند
              release lock (finally)
```

**هیچ پیامکِ واقعی در این مسیر فرستاده نمی‌شود.** کانال SMS فقط یک ردیفِ approval با وضعیت
`pending` در صف می‌گذارد. ارسالِ واقعی فقط پس از **تأییدِ مدیر** via `POST /engagement/approvals/{id}/send`
انجام می‌شود — و آن هم به‌خاطرِ **گِیتِ KYCِ کاوه‌نگار (کد ۴۳۰)** فعلاً NullProvider است (شبیه‌سازی).

## گزینهٔ اصلی (ساختنیِ همین حالا): cronِ مدیریت‌شده

یک system/container cron که هر N دقیقه command را صدا می‌زند. به‌خاطرِ advisory lock،
tickهای هم‌پوشان امن‌اند — تیکِ دوم اگر تیکِ اول هنوز در جریان باشد، تمیز skip می‌شود.

### نمونهٔ crontab (هاستِ کانتینر یا VM)

```cron
# هر ۵ دقیقه — همهٔ مستأجرها
*/5 * * * *  cd /app && /usr/local/bin/python manage.py run_engagement >> /var/log/halqe/engagement.log 2>&1
```

### نمونهٔ sidecar cron (compose؛ بدونِ افزودنِ Redis)

سرویسِ web از همان imageِ `Dockerfile` استفاده می‌کند؛ یک سرویسِ جداگانهٔ `engagement-cron`
همان image را اجرا می‌کند ولی به‌جای gunicorn، یک حلقهٔ cron:

```yaml
  engagement-cron:
    image: halqe-backend:latest          # همان image وب
    entrypoint: ["/bin/sh", "-c"]
    command:
      - |
        while true; do
          python manage.py run_engagement || true
          sleep 300
        done
    environment:
      # همان env وب — PG_HOST/PG_PORT/PG_DB/PG_APP_USER/PG_APP_PASSWORD/SECRET_KEY/PRODUCTION=1
    depends_on:
      postgres:
        condition: service_healthy
```

> نکته: `apply_schema`/`ensure_app_role` فقط در سرویسِ وب (`entrypoint.sh`) اجرا می‌شوند؛
> سرویسِ cron نباید schema را دوباره اعمال کند — فقط command را صدا بزند. `|| true` تضمین
> می‌کند که خطای یک tick حلقه را نمی‌کشد (خطا در summaryِ ساخت‌یافته لاگ می‌شود).

## گزینهٔ آینده (گِیتِ infra): Celery beat + Redis

**چرا موکول است:** نیازمندِ افزودنِ **Redis** (یا broker دیگر) است که فعلاً در stack نیست،
و طبقِ ریسکِ فاز A (نشتِ tenant با pooling — ADR-0008) هیچ poolerِ transaction-mode یا
زیرساختِ اشتراکیِ کانکشن پیش از حلِ آن اضافه نمی‌شود. cron کافی و ساده‌تر است.

**seam وقتی Redis آمد:** یک taskِ Celery که دقیقاً همین `run_engagement` (یا `run_all`) را صدا
می‌زند؛ advisory lock همچنان لازم است (چند worker = چند اجرای هم‌زمانِ احتمالی). Celery beat
جای cron را می‌گیرد؛ بقیهٔ منطق (lock + per-tenant GUC + summary) بدونِ تغییر می‌ماند.

## مکانیزمِ no-concurrent-run (advisory lock)

- پیاده‌سازی: `clinical/advisory_lock.py` → `engagement_run_lock()` (context manager).
- کلیدِ سراسریِ واحد: `ENGAGEMENT_RUN_LOCK_KEY = 0x68616C71` (1751215217) — یک قفلِ سراسری
  برای کلِ خوشه، **نه per-tenant**. این یک گاردِ عملیاتیِ هم‌زمانی است و کاملاً مستقل از RLS/tenant.
- `pg_try_advisory_lock` **غیرمسدودکننده** است: اگر قفل گرفته نشود، command گزارش
  `status=skipped_locked` می‌دهد و با **exit 0** خارج می‌شود (نه خطا، نه انتظار).
- قفل تا پایانِ عمرِ command روی همان کانکشنِ `default` نگه داشته می‌شود و در `finally` با
  `pg_advisory_unlock` آزاد می‌شود (بستنِ کانکشن هم backstop است).
- **CONN_MAX_AGE=0 (ADR-0008):** فقط بر چرخهٔ request/response اثر دارد. داخلِ management
  command چرخهٔ request نیست؛ `django.db.connection` تا پایانِ command باز می‌ماند، پس قفلِ
  session-level روی همان کانکشن نگه داشته می‌شود.

ledgerِ `engagement_dispatch` با UNIQUE constraint همچنان backstopِ idempotency است؛ حتی
اگر دو اجرا به‌نحوی هم‌زمان شوند، درجِ تکراری رد می‌شود.

## RLS و per-tenant GUC

این command **خارج از چرخهٔ request** اجرا می‌شود، پس `JWTBearer` نیست که `app.current_tenant`
را ست کند. RLS (slice5) **fail-closed** است — بدونِ GUC هر کوئریِ `clinical.*` صفر ردیف می‌دهد.
بنابراین command **per-tenant** قبل از پردازشِ هر مستأجر `set_tenant_guc(tid)` را ست می‌کند
(همان مکانیزمِ `auth_bearer`) و در `finally` پاک می‌کند. کشفِ مستأجرها از `platform.tenants`
انجام می‌شود (که ستونِ `tenant_id` ندارد، پس slice5 آن را RLS نکرده → بدونِ GUC هم خوانا است).

## Observability — چه چیزی را مانیتور کنیم

هر اجرا یک خطِ لاگِ ساخت‌یافتهٔ تک‌خطی (هم‌سو با formatterِ production قدم ۲۸) می‌دهد:

```
engagement_run_summary status=ok tenants=3 patients=412 queued=18 worklist=27 \
  skipped=64 opt_out_skipped=9 cooldown_skipped=55 holdout=31 errors=0 dry_run=False worklist_only=False
```

و در صورتِ قفلِ هم‌زمان:

```
engagement_run_skipped status=skipped_locked reason=another_run_in_progress
```

شمارنده‌ها (همگی PII-free):
- `patients` — بیمارانِ فعالِ پردازش‌شده.
- `queued` — approvalهای SMS در صف (هرگز ارسال‌شده نیست).
- `worklist` — تسک‌های followup ساخته‌شده/dispatch‌شده.
- `skipped` — جمعِ کلِ skipهای SMS؛ زیرشاخه‌ها: `opt_out_skipped` (انصراف) + `cooldown_skipped` (در بازهٔ خنک‌سازی) + (no-phone که زیرشاخهٔ جدا ندارد).
- `holdout` — رویدادهای سرکوب‌شده برای بیمارانِ گروهِ کنترلِ علّی (قدم ۴۳)؛ ردیفِ auditable با `status='holdout'` ثبت می‌شود؛ مراقبتِ بالینی دریغ نمی‌شود.
- `errors` — خطاهای per-patient/per-tenant (هرکدام جدا لاگ می‌شوند؛ یک خطا کلِ اجرا را نمی‌کشد).

**هشدارِ ساده پیشنهادی (بدونِ over-engineering):** اگر چند tick پشت‌سرهم `errors>0` یا اگر
`skipped_locked` به‌طور مداوم (هر tick) دیده شود (نشانهٔ یک runِ گیرکرده) → بررسی شود.

## عیب‌یابی

| نشانه | علتِ محتمل | اقدام |
|------|-----------|------|
| همیشه `skipped_locked` | یک اجرای قبلی گیر کرده و قفل را رها نکرده | کانکشن‌های فعال را در PG ببین (`pg_locks` + `pg_stat_activity`)؛ اگر فرایندِ مرده قفل را دارد، آن backend را terminate کن یا کانکشنش بسته شود. |
| `patients=0` برای مستأجری که بیمار دارد | GUC ست نشده / RLS | مطمئن شو از کدِ این command استفاده می‌شود (per-tenant GUC)؛ نه فراخوانیِ مستقیمِ `run_all` بدونِ GUC. |
| `queued` زیاد ولی هیچ SMS نمی‌رود | **طبیعی** — KYC بلاک + گِیتِ تأییدِ مدیر | KYCِ کاوه‌نگار باید تکمیل شود؛ تا آن زمان NullProvider. |
| `errors>0` پایدار | خطای داده/کانکشن per-tenant | لاگِ `run_engagement: error for tenant_id=...` را ببین (exception کامل لاگ شده). |

## گِیتِ KYC (یادآوری)

کلیدِ کاوه‌نگار معتبر است اما حساب کد **۴۳۰ (احراز هویت/KYC ناقص)** برمی‌گرداند. تا تکمیلِ KYC
توسطِ مالک، **هیچ پیامکِ واقعی** فرستاده نمی‌شود (NullProvider در همه‌جا). این command هرگز
ارسال نمی‌کند — حتی پس از KYC، ارسال فقط با تأییدِ مدیر است.

## فایل‌های مرتبط

- `clinical/management/commands/run_engagement.py` — خودِ command (lock + per-tenant GUC + summary).
- `clinical/advisory_lock.py` — قفلِ no-concurrent-run.
- `clinical/engagement_service.py` — `run_all`/`dispatch_patient` (گاردریل‌ها + summary).
- `entrypoint.sh` — استارتِ کانتینرِ وب (apply_schema/ensure_app_role/gunicorn).
- ADR-0008 — چرخهٔ GUC/pooling و چراییِ `CONN_MAX_AGE=0`.
