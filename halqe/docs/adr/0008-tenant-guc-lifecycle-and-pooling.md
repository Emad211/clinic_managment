# ADR-0008 — چرخهٔ حیاتِ GUCِ tenant و سخت‌سازی در برابرِ pooling

- **وضعیت:** Accepted (گزینهٔ B سخت‌شده) — ۱۴۰۵/۰۴/۰۴ (۲۰۲۶-۰۶-۲۵).
- **بخشِ transaction-pooler:** Proposed / Deferred (تریگرِ T1 + pooler).
- **تصمیم‌گیرنده:** مالک + `security-privacy-advisor` + `data-architect` (گردهماییِ خوشهٔ G، قدم ۲۳).
- **مرتبط:** [ADR-0006](0006-cloud-unification-and-data-trust.md) (چندمستأجریِ یکپارچه) · [ADR-0007](0007-patient-identity-and-unified-data-model.md) (مرزِ cross-schema) · `halqe/platform_core/tenant_context.py` · `halqe/platform_core/middleware.py` · `halqe/config/settings.py` · `halqe/config/env.py` · `halqe/tests/test_guc_leak.py` · `halqe/tests/test_prod_config.py` (کلاسِ `TestResolveConnMaxAge`).

---

## ۱. زمینه

### حقیقتِ کلیدی: امروز نشت ممکن نیست

`halqe/config/settings.py` در حالتِ کنونی **بدونِ `CONN_MAX_AGE`** است (پیش‌فرضِ Django = 0). این یعنی هر request یک کانکشنِ تازهٔ Postgres باز می‌کند و پس از پایانِ request آن را می‌بندد. GUCِ `app.current_tenant` (که با `set_config(false)` = session-scoped ست می‌شود) با بستنِ کانکشن می‌میرد. در نتیجه:

> **با تنظیمِ فعلی (`CONN_MAX_AGE=0`) هیچ نشتِ GUC بین requestها ممکن نیست — GUC به‌محضِ بستنِ کانکشن از بین می‌رود.**

### ریسک #۱۱ — بمبِ ساعتیِ آینده

RLS (slice5) روی GUCِ `app.current_tenant` تکیه دارد. وقتی پروژه به T1 (کلینیکِ دوم) برسد، به احتمال زیاد نیاز به connection pooler (PgBouncer/Supavisor) یا `CONN_MAX_AGE>0` خواهد داشت. این تغییر بدونِ آگاهی از معنایِ آن می‌تواند:
1. با **session-mode pooler**: کانکشن بینِ requestها زنده می‌ماند → GUCِ کهنه از requestِ قبلی باقی است → middleware باید آن را در ابتدای هر request پاک کند (فعلاً انجام می‌شود). **امن با احتیاط.**
2. با **transaction-mode pooler** (مثلِ PgBouncer در حالتِ پیش‌فرض): pooler کانکشن را در وسطِ request برمی‌گرداند → `clear()` در middleware روی کانکشنِ قبلی اجرا شده، view روی کانکشنِ جدیدی کار می‌کند که GUC آن تنظیم نشده → **RLS صفر ردیف برمی‌گرداند** (fail-closed از نگاهِ امنیت، ولی همهٔ endpointهای authed می‌شکنند). **ناامن.**

---

## ۲. مکانیکِ Postgres — Session vs Transaction

| روش | حوزهٔ حیات | در transaction-mode pooler |
|-----|-----------|---------------------------|
| `SET app.current_tenant = '1'` | Session | بعد از برگشتِ کانکشن به pooler باقی است |
| `set_config('app.current_tenant', '1', false)` | Session (همان بالا) | همان |
| `SET LOCAL app.current_tenant = '1'` | Transaction | بیرونِ تراکنشِ صریح فوراً commit/rollback و **گم** می‌شود |
| `set_config('app.current_tenant', '1', true)` | Transaction (همان بالا) | همان — اگر تراکنشی نباشد بلافاصله از بین می‌رود |

**کدِ فعلی:** `halqe/platform_core/tenant_context.py:48` — `set_config('app.current_tenant', tid, false)` (session-scoped). این **تغییر نمی‌کند.**

### رفتارِ PgBouncer

| حالت | رفتار با GUCِ session-scoped | امنیت |
|------|------------------------------|-------|
| **session-mode** | کانکشن تا پایانِ «session» (نه request) به یک client اختصاص دارد. GUC باقی است → `TenantGucMiddleware.clear()` در ابتدای request مؤثر است. | **امن** با middleware |
| **transaction-mode** | کانکشن بعد از هر تراکنش به pool برمی‌گردد. GUCِ session-scoped روی آن باقی است ولی `clear()` ممکن است روی کانکشنِ متفاوتی اجرا شود. | **ناامن — ممنوع تا تغییرِ policy** |
| **statement-mode** | شدیدترین حالت — حتی تراکنش‌های چندبیانی را نمی‌شود. با Django ناسازگار است. | **ناسازگار** |

---

## ۳. گزینه‌ها و حکم

### گزینهٔ الف — `SET LOCAL` + `ATOMIC_REQUESTS=True`

**توضیح:** GUCِ transaction-scoped (`set_config(true)`) + `ATOMIC_REQUESTS=True` که هر request را در یک تراکنش می‌پوشاند → `SET LOCAL` در محدودهٔ تراکنش اثر می‌کند.

**مشکلات:**
- بدونِ `ATOMIC_REQUESTS=True`، `SET LOCAL` خارجِ تراکنش فوراً گم می‌شود → **همهٔ endpointهای authed با صفر ردیف شکست می‌خورند** (اثباتِ data-architect).
- `ATOMIC_REQUESTS=True` یعنی هر request یک تراکنش باز می‌کند — حتی GETها. این نیازِ refactorِ `JWTBearer.authenticate()` دارد (باید داخلِ atomicِ view باشد، نه در authenticate که خارج از view‌ است).
- سربارِ تراکنش روی هر request + بازآزمونِ ۳۳۴ تست.
- **سودِ صفر امروز** (poolerِ transaction-mode نداریم).

**حکم: Deferred** — موکول به تریگرِ «pooler/T1».

### گزینهٔ ب — Session-scoped فعلی + قرارداد + گاردِ بوت (گزینهٔ انتخابی)

**توضیح:** مکانیزمِ `set_config(false)` تغییر نمی‌کند. سه لایهٔ صریح اضافه می‌شود:
1. **`CONN_MAX_AGE=0` به‌صورتِ invariantِ صریح** در `settings.py` (کامنتِ ADR).
2. **گاردِ بوتِ fail-fast** در `config/env.py:resolve_conn_max_age()` — در `PRODUCTION=1` اگر `CONN_MAX_AGE>0` بدونِ ACKِ صریح، `ImproperlyConfigured` با پیامِ روشن.
3. **تستِ نگهبان** در `tests/test_guc_leak.py` — شبیه‌سازیِ کانکشنِ آلوده + تأییدِ RLSِ fail-closed.
4. **قرارداد:** halqe باید مستقیم به Postgres یا PgBouncer در **session-mode** وصل شود. transaction-pooling ممنوع تا تغییرِ policy.
5. **defense-in-depth middleware:** `clear_tenant_guc()` در `try/finally` (هم ابتدا هم انتهای request).

**حکم: Accepted.**

### جدولِ trade-off

| معیار | گزینهٔ الف | گزینهٔ ب |
|-------|-----------|---------|
| پیچیدگیِ فوری | بالا (refactor + بازآزمون) | صفر |
| سازگاریِ با transaction-pooler | بله | خیر (ممنوع) |
| ریسکِ شکستنِ تست‌ها | بالا | صفر |
| صادقانه‌بودن | نه (هزینهٔ زودرس) | بله |
| قابلیتِ upgrade | بله (seam موجود) | بله (seam مستند) |

---

## ۴. قرارداد (الزام — نقضِ آن = شکستِ RLS)

> **halqe باید مستقیم به Postgres یا PgBouncer/Supavisor در session-mode وصل شود. transaction-mode pooling ممنوع است تا policy به گزینهٔ الف تغییر کند.**

این قرارداد با موارد زیر اجرا می‌شود:
- **`CONN_MAX_AGE=0` پیش‌فرضِ invariant** — `halqe/config/settings.py` + `DATABASES[...]["CONN_MAX_AGE"] = _CONN_MAX_AGE`.
- **گاردِ بوت** — `config/env.py:resolve_conn_max_age()`: در `PRODUCTION=1` اگر `CONN_MAX_AGE>0` و `TENANT_GUC_POOLING_ACK != 'session-mode-only'` → `ImproperlyConfigured`.
- **تستِ نگهبان** — `tests/test_prod_config.py:TestResolveConnMaxAge` (۱۴ تست) + `tests/test_guc_leak.py` (۶ تست).

---

## ۵. seamِ موکول — مسیرِ آیندهٔ transaction-pooler

وقتی تریگرِ «pooler/T1» رخ داد (نیاز به PgBouncer transaction-mode یا Supavisor):

**گامِ ۱ — `ATOMIC_REQUESTS=True` در `settings.py`:**
```python
# settings.py
ATOMIC_REQUESTS = True  # هر request در یک تراکنش؛ prerequisite برای SET LOCAL
```

**گامِ ۲ — انتقالِ `set_tenant_guc` به داخلِ atomicِ view:**
مشکل فعلی: `JWTBearer.authenticate()` در `halqe/platform_core/auth_bearer.py:36` خارج از view-level atomic اجرا می‌شود. با `ATOMIC_REQUESTS=True` هر request خودش یک تراکنش دارد، اما authenticate قبل از ورودِ به view است — باید verify شود که در محدودهٔ `ATOMIC_REQUESTS` قرار می‌گیرد یا نیاز به `transaction.atomic()` صریح دارد.

**گامِ ۳ — تغییرِ `set_config` به transaction-scoped:**
```python
# platform_core/tenant_context.py
cursor.execute(
    "SELECT set_config('app.current_tenant', %s, true)",  # true = transaction-scoped
    [str(tenant_id)],
)
```

**گامِ ۴ — حذفِ trailing clear از middleware** (دیگر لازم نیست چون GUC transaction-scoped است).

**گامِ ۵ — بازآزمونِ کلِ سوئیت** + تستِ ایزولاسیون با poolerِ واقعی.

**نکتهٔ مهم:** `fixtureِ autouseِ set_default_tenant_guc(1)` در `halqe/tests/conftest.py` باید با انتقال به transaction-scoped بازبینی شود — ممکن است نیاز به `transaction=True` روی تست‌های service-level داشته باشد.

---

## ۶. پیاده‌سازیِ این ADR (قدم ۲۳ — چه ساخته شد)

| فایل | تغییر |
|------|-------|
| `halqe/config/env.py` | `resolve_conn_max_age()` + `TENANT_GUC_POOLING_ACK_VALUE` constant |
| `halqe/config/settings.py` | `CONN_MAX_AGE = _CONN_MAX_AGE` در هر دو `DATABASES` entry + import |
| `halqe/platform_core/middleware.py` | `try/finally` — trailing `clear_tenant_guc()` defense-in-depth |
| `halqe/tests/test_guc_leak.py` | ۶ تستِ نشت (شبیه‌سازیِ کانکشنِ آلوده + RLS causal proof) |
| `halqe/tests/test_prod_config.py` | ۱۴ تستِ گاردِ بوت (`TestResolveConnMaxAge`) |

**نتیجهٔ سوئیت بعد از این قدم:** 354 passed، 1 skipped (قبل: 334).

---

## ۷. تضمینِ اینکه مکانیزم تغییر نکرد

بررسیِ کدِ `halqe/platform_core/tenant_context.py`:
- `set_tenant_guc` در خطِ 47: همچنان `set_config('app.current_tenant', %s, false)` (session-scoped). **تغییر نکرد.**
- `clear_tenant_guc` در خطِ 71: همچنان `set_config('app.current_tenant', '', false)`. **تغییر نکرد.**

بررسیِ کدِ `halqe/platform_core/auth_bearer.py`:
- خطِ 36: `set_tenant_guc(user.tenant_id)` — **خارج از هر atomic، پیش از بدنهٔ view**. تغییر نکرد.

---

## ۸. نامعلوم‌ها و ریسک‌های باقیمانده

- **vendor ابریِ ایران** — اکثرِ managed Postgres ایرانی PgBouncer را در حالتِ پیش‌فرضِ transaction قرار می‌دهند. هنگامِ انتخابِ vendor باید حالتِ pooler صریحاً بررسی شود.
- **Supavisor** (poolerِ Supabase) — session-mode را پشتیبانی می‌کند ولی باید با پروتکلِ Postgres wire روی port 5432 نه port 6543 وصل شود (transaction-mode). مستندِ vendor را در قدمِ M بررسی کن.
- **`CONN_MAX_AGE=None`** (persistent اما با هر thread متفاوت) — در گاردِ بوت به‌درستی رد می‌شود (int conversion خطا می‌دهد). اگر آینده نیاز شد، به ADR-0008 اضافه کن.

---

## مبنا (ارجاعِ کد — راستی‌آزمایی‌شده)

`halqe/platform_core/tenant_context.py:48,73` (set/clear با `false`) · `halqe/platform_core/middleware.py:47-60` (leading+trailing clear) · `halqe/platform_core/auth_bearer.py:36` (set در authenticate، خارجِ atomic) · `halqe/config/settings.py:108-165` (DATABASES بدونِ CONN_MAX_AGE قبل، با بعد) · `halqe/config/env.py:resolve_conn_max_age` · `halqe/tests/test_guc_leak.py` · `halqe/tests/test_prod_config.py:TestResolveConnMaxAge` · `halqe/db/schema/schema_pg_slice5_rls.sql` (FORCE RLS + NULLIF).
