# نقشهٔ مهاجرت — پلتفرمِ ابریِ یکپارچه (ADR-0006)

> **سند مرجعِ اجرایی.** این نقشه، تجزیهٔ شش‌حوزه‌ای (architecture · data · security · ops · backend · frontend · qa · clinical-product · marketing · devils-advocate) را در یک بک‌لاگِ واحدِ ریز ادغام کرده و **تضادهای دورِ دومِ بحثِ متقابل را حل‌شده** منعکس می‌کند. مبنا: [`adr/0006-cloud-unification-and-data-trust.md`](../../halqe/docs/adr/0006-cloud-unification-and-data-trust.md) · [`data_trust_story.md`](data_trust_story.md) · [`owner_inputs_needed.md`](owner_inputs_needed.md) · ADRهای 0001..0005.
>
> هر تسک با `id` حوزه‌ای حفظ شده (ARCH/DATA/SECU/OPS/BACK/FRON/QA/PROD/MARK/DEVI). تسک‌های هم‌موضوعِ چندحوزه‌ای **ادغام** شده‌اند (مالکِ واحد + ارجاع به idهای آینه).

---

## ۱. خلاصهٔ اجرایی

ما دو اپِ مستقلِ **Flask + SQLite لوکال** (`webapp` حسابداری/پورت ۸۰۸۰ · `specialist_clinic` بالینی/پورت ۸۰۹۰) را به یک **مونولیتِ ماژولارِ ابری** روی **یک PostgreSQL با دو schema** (`accounting` · `clinical`)، **Django/DRF + Celery/Redis**، روی **خاکِ ایران**، با **اپ بیمارِ PWA**، مهاجرت می‌دهیم. اصلِ حاکم: **Evolve-not-Rewrite + copy-forward** — `clinic_new.db`ِ لوکال تا cutoverِ نهایی منبعِ حقیقت و fallbackِ دست‌نخورده می‌ماند.

**شش یافتهٔ بحرانیِ راهنمای کل نقشه (تأییدشده با کد):**

1. **سه تعریفِ پولی، نه دو.** علاوه بر (الف) قیمتِ خامِ آیتمی پل (`accounting_bridge.py:253-276`) و (ب) `total_amount = Σ patient_share` (`invoices_repo.py:278-292`)، یک تعریفِ سوم هم هست: (ج) **`collected = SUM(CASE WHEN invoice_item_payments.is_paid=1)`** که Control Room و انتسابِ کمپین روی آن کار می‌کنند (`accounting_bridge.py:353,411,492`). oracleِ مهاجرت باید **سه‌گانه** باشد نه دوگانه.
2. **`total_amount` مشتقِ تعرفهٔ زندهٔ امروز است، نه snapshot.** فراخوانیِ `get_invoice_items` روی فاکتورِ تاریخی، چون از `visit_tariffs` زنده می‌خواند (`invoices_repo.py:92-95,121-130`)، عددی **متفاوت** از ستونِ ذخیره‌شده می‌دهد → ETL **هرگز** نباید بازمحاسبه کند؛ فقط `invoices.total_amount` را literal کپی کند.
3. **وارونگیِ ریسکِ تست.** `specialist_clinic` ۱۶۸ تستِ سبز دارد ولی **`webapp` صفر تست** دارد (تأییدشده با Glob). منطقِ پیچیدهٔ سهمِ بیمار (`invoices_repo.py:114-217`) هیچ شبکهٔ ایمنی ندارد و دیرترین مهاجرت می‌شود. **پیش از فاز C، یک golden-master characterization suite روی منطقِ پولیِ webapp اجباری است** (DEVI-02/ARCH-12).
4. **شکستِ خاموشِ مالی.** الگوی `except: return []` در توابعِ درآمدِ `accounting_bridge.py` خطا را می‌بلعد — بدتر از آن، `revenue_for_accounting_ids:279` در خطا `out`ِ نیمه‌تجمیع‌شده (نه صفر) برمی‌گرداند که در داده‌های کوچک invisible است. `AccountingReadPort`ِ fail-loud اجباری است.
5. **decoupleِ فاز ۰.** سخت‌سازیِ امنیتی (SECRET_KEY/DEBUG/CSRF/کوکی/توکن ext) هیچ وابستگی به ابر ندارد و روی همین Flask قابل اجراست؛ باید **مستقل و non-blocking** مرج شود — حتی اگر مالک هرگز به ابر نرود.
6. **اندازه‌گیری پیش از طراحی.** اختلافِ واقعیِ تعاریفِ درآمد هنوز روی دادهٔ زنده اندازه‌گیری نشده. یک اسکریپتِ read-onlyِ ۱-روزه (DEVI-04/DATA-06) باید **اولین کارِ کل پروژه** باشد چون scopeِ oracle/canonical و ده‌ها روزِ کارِ پایین‌دست را تعیین می‌کند.

**تعداد تسک:** ۸۲ تسکِ فعال در ۶ فاز + ۸ آیتمِ بک‌لاگِ دوربردِ معوق.

---

## ۲. گِیت‌های تصمیمِ مالک (بلوکه‌کننده — پیش از هر کدنویسیِ وابسته)

| گِیت | پرسش (ADR-0006 §۱۴) | چه چیزی را بلاک می‌کند | پیش‌فرضِ توصیه‌شده |
|---|---|---|---|
| **G0** | تأییدِ مسیرِ تک‌مستأجرِ ابری اول | کلِ پلتفرم (ARCH-00) | بله (مسیر ۱) |
| **G-A** | DevOps تمام‌وقت یا PaaS ایرانی؟ | OPS-16, SLA/PITR, کفِ قیمت (MARK-A-PRICE) | PaaS ایرانیِ دارای PITR |
| **G-B** | سطحِ آفلاین: خواندن / +پذیرش / +بستنِ فاکتور | OPS-17, ARCH-11, فاز E | خواندنِ کامل + صفِ نوشتنِ پذیرش |
| **G-C** | تعریفِ canonicalِ درآمد + واحدِ پول + گردکردن | oracle §۸, DATA-05/06, NUMERIC scale, ROIِ بازاریابی | `total_amount`/سهمِ بیمار (پس از دیدنِ عددِ DEVI-04) |
| **G-KYC** | تکمیلِ KYC کاوه‌نگار (کد ۴۳۰ فعلی) | کلِ ارزشِ پیامک‌محور، MARK-A-KYC، moتورِ recall | — (اقدامِ مالک، lead-time دارد) |
| **G-VENDOR** | انتخابِ vendorِ ابریِ ایرانی + تستِ restore واقعی | کلِ فاز A، اگر شکست → مسیرِ ۰ روی میز | spike پیش از اولین کدِ پلتفرم (DEVI-06) |
| **G-HIST** | کلِ تاریخچه مهاجرت شود یا از go-live به بعد؟ | حجمِ ETL، oracle، id-remap | — |
| **G-STALE** | سیاستِ staleness هر شاخصِ کنترلی (chand ماه) | PROD-07, DATA-04 schema | ورودیِ پزشک |

> **اصلِ کلیدی (DEVI-01):** هیچ‌یک از این گِیت‌ها نباید **فاز ۰** را بلاک کند. فاز ۰ مستقل و موازی پیش می‌رود.

---

## ۳. تسکِ صفرِ مطلق (پیش از هر طراحی)

| id | شرح | حوزه | effort | معیار پذیرش |
|---|---|---|---|---|
| **DEVI-04 / DATA-06** | اسکریپتِ read-only روی کپیِ `clinic_new.db` زنده (پس از `wal_checkpoint(TRUNCATE)`): **سه** عدد per work_date/insurance — (الف) `Σ raw item` پل، (ب) `Σ total_amount`، (ج) سهمِ `consumable.patient_share` در total_amount، و (د) **drift تعرفه**: فاکتورهایی که `get_invoice_items` امروز total_amountِ متفاوت از ستونِ ذخیره‌شده می‌دهند. خروجی CSV per-invoice + per-day به مالک. | data | ۱.۵ | SHA-256 فایل قبل/بعد یکسان (zero-write)؛ سه عدد + drift گزارش شد؛ مالک canonical را امضا کرد (G-C). |

> **چرا اول:** کلِ گیتِ دو/سه-oracleِ §۸ و scaleِ NUMERIC و روایتِ ROIِ بازاریابی به این عدد وابسته‌اند. اگر اختلاف ناچیز بود، پیچیدگیِ oracle ساده می‌شود؛ اگر بزرگ بود، احتمالاً یک باگِ تولیدیِ موجود در webapp است که باید اول بررسی شود. **حل تضاد دور دوم:** ادعای DEVI-04 که «برای آزاد دو تعریف یکسان‌اند» با کد رد شد (پل از `v.price`، total_amount از `base_visit_price` زندهٔ `visit_tariffs:92-95` — دو منبعِ متفاوت حتی برای آزاد). پس فرضِ کاری: «اختلاف ساختاری و قابل‌توجه است».

---

## ۴. فاز ۰ — سخت‌سازیِ امنیتی (مستقل، non-blocking، روی همین Flask)

> این فاز هیچ وابستگی به تصمیمِ ابر/vendor/KYC ندارد و باید در یک شاخهٔ مستقل از کلِ مهاجرت مرج شود. **CSRF به‌صورتِ per-app و با deployment window جداگانه** فعال می‌شود (specialist اول، webapp بعد) نه یک commit مشترک.

| id | شرح | حوزه | effort | وابستگی | معیار پذیرش | ریسک |
|---|---|---|---|---|---|---|
| **SECU-01 / OPS-01a / BACK-01a** | `SECRET_KEY` از env با **fail-fast** (`raise RuntimeError` اگر مقدار پیش‌فرض و `not TESTING` و `not sys.frozen`). هر دو اپ (`settings.py:6`). | security | ۰.۵ | — | اجرا با کلیدِ پیش‌فرض در non-test/non-frozen crash کند؛ گیت CI grep. | بحرانی |
| **SECU-02** | `DEBUG=False` env-gated + حذف `host=0.0.0.0`→`127.0.0.1` (`settings.py:34`, `app.py:137`). | security | ۰.۵ | SECU-01 | DEBUG=False تأیید؛ traceback کامل در production نیست؛ CI gate. | بحرانی (Werkzeug debugger = RCE) |
| **SECU-03 / FRON-01a** | CSRF (Flask-WTF) روی همهٔ POSTهای HTML. ext blueprint صریحاً exempt. | security | ۲ | SECU-01 | POST بدون token → 400؛ ext exempt. | بالا |
| **FRON-01b** | **X-CSRFToken برای fetch/Ajax POST** (commit جدا از HTML form): `campaigns.html:164` و سایر JSON POSTها از meta tag بخوانند. | frontend | ۱ | SECU-03 | fetch POST با JSON body بدون header → 403؛ با meta → 200. | متوسط (silent break) |
| **SECU-04** | flagهای کوکی: `HttpOnly`/`Secure`/`SameSite=Lax` + `PERMANENT_SESSION_LIFETIME` (~۸h). | security | ۰.۵ | SECU-02 | Set-Cookie دارای HttpOnly;Secure;SameSite؛ session منقضی. | بالا |
| **SECU-05 / BACK-02 / FRON-02** | **توکن ext.py سخت‌سازی:** جدول `ext_tokens` با `expires_at`+`physician_user_id`(scope)+`revoked_at`؛ فقط `Authorization` header (حذف `?token=`)؛ **حذف `national_id` از `/pending`** (surrogate `patient_link_id`)؛ scope به پزشک صاحب (`WHERE` filter روی followup)؛ rate-limit (Flask-Limiter `memory://`)؛ pagination. **/captured هم به `patient_link_id` migrate شود.** | security | ۳ | SECU-01 | توکن منقضی→401؛ توکن پزشک A به بیمار B دسترسی ندارد؛ national_id در هیچ پاسخ ext نیست؛ >N req→429. | بحرانی (تنها سطح حملهٔ بیرونی) |
| **SECU-06 / OPS-02 / BACK-03** | **بکاپ رمزنگاری‌شده AES-256-GCM** جایگزین plaintext (`scheduler.py:111-145`)؛ پسوند `.db.enc`؛ کلید از env مستقل از SECRET_KEY با key-versioning. اسکریپت `restore_backup.py`. | security | ۲ | SECU-01 | بکاپ `.db.enc`؛ بدون کلید ناخوانا؛ restore→`integrity_check` سبز. | بالا |
| **DATA-14a / OPS-06a / QA-12** | **تستِ restoreِ واقعی روی همان SQLite لوکالِ امروز** (نه پشت Alembic): backup→decrypt→open→`integrity_check`→row-count match. | data | ۱ | SECU-06 | تستِ pytest سبز؛ row-count با اصل برابر. | بالا (بکاپ بدون restore = توهم) |
| **SECU-13** | rate-limit روی `/card/<token>` (۱۰/min) + لاگ دسترسی کارت (IP+timestamp). همین الان در LAN/QR در دسترس است. | security | ۱ | SECU-10 (لاگ) | >۱۰ req→429؛ هر دسترسی موفق لاگ. | متوسط |
| **SECU-14a / PROD-08a** | **رضایتِ صریح SMS (opt-in):** فیلد `sms_consent INTEGER NOT NULL DEFAULT 0`+timestamp در `patient_links`؛ چک‌باکس در فرم پذیرش؛ تابع `wrap_message` با footer لغو. **به فاز ۰/A ارتقا یافت** (پیش از KYC آماده باشد). | security | ۲ | — | بیمار با consent=0 پیامک campaign نمی‌گیرد؛ متن لغو در هر پیامک. | متوسط (حقوقی) |
| **QA-15** | تستِ sentinelِ deal-breaker در CI: SECRET_KEY default→raise؛ DEBUG=True در non-test→fail؛ POST بدون CSRF→400. | qa | ۱ | SECU-01..04 | CI با هر نقضِ deal-breaker قرمز. | بحرانی |
| **SECU-18 / QA-13** | **اثباتِ immutability فاکتورِ بسته:** grep `UPDATE.*invoices.*status` در `webapp/src` + تستِ runtime (set closed → اثبات هیچ path آن را به open برنمی‌گرداند). نکته: `update_invoice_totals` بدون شرطِ status است → باید guard اضافه شود. | security | ۱ | — | گزارش مکتوب: هیچ reopen؛ تست runtime سبز. | بحرانی (oracle precondition) |

**خروجیِ «انجام‌شده» فاز ۰:** همهٔ deal-breakerهای §۹ روی هر دو اپ رفع و با تست/grep اثبات؛ بکاپ رمز + restore تست‌شده؛ immutability فاکتور بسته اثبات‌شده.

---

## ۵. فاز A — پایه‌گذاریِ پلتفرمِ خالی

> پیش‌نیازِ سختِ کل فاز: **G-VENDOR spike** باید پیش از اولین کدِ پلتفرم بسته شود.

| id | شرح | حوزه | effort | وابستگی | معیار پذیرش | ریسک |
|---|---|---|---|---|---|---|
| **OPS-16 / DEVI-06** | **spike انتخاب vendor + تستِ restore واقعی:** مقایسهٔ Liara/ArvanCloud/Hamravesh بر PITR/SLA/قیمت/data-residency؛ یک restoreِ واقعی روی محیط مدیریت‌شده. **اگر شکست → مسیرِ ۰ لوکالِ سخت‌شده دوباره ارزیابی.** | ops | ۳ | G-A | گزارش مقایسه + امضای مالک + staging روی vendor؛ restore موفق. | بالا (single point of failure) |
| **ARCH-00** | **ارتقای ADR-0006 به Accepted + C4 Container Diagram** در `docs/architecture/` (یک Postgres دو schema، Celery+Redis، reverse-proxy، عاملِ لوکال، مرزِ AccountingReadPort). | architecture | ۲ | G0, G-C, DEVI-04 | ADR Accepted؛ ۴ پرسش §۱۴ امضا؛ دیاگرام ثبت. | بالا |
| **OPS-03** | reverse proxy (nginx/Caddy) + TLS + firewall (فقط 80/443) + HSTS؛ Flask روی `127.0.0.1`. اگر PaaS، بررسی capability. | ops | ۲ | OPS-16 | curl `<ip>:8080` بیرونی timeout؛ `https://<domain>`→200؛ TLS grade A. | بالا |
| **QA-01 / OPS-10 / SECU-19 / BACK-04** | **اسکریپتِ واحدِ مقایسهٔ درآمد** (مالکیت: data؛ ارجاع از qa/ops/security/backend — نه ۴ اسکریپت موازی). خروجیِ DEVI-04 را رسمی می‌کند: سه oracle + per-invoice. security/qa نگهبانِ tolerance، ops در CI اجرا. | data | ۰ (ادغام در DEVI-04) | DEVI-04 | یک اسکریپت، نه چهار؛ خروجی به همهٔ حوزه‌ها. | — |
| **DATA-01 / QA-04 / OPS-11** | **پروفایلِ دادهٔ کثیف** روی فایلِ زنده: NULL/تکراریِ national_id؛ `work_date` غیرمنطبق (شاملِ **آلودگیِ backfillِ `substr(opened_at)` در شیفتِ شب — `core.py:36`**)؛ FK یتیم؛ پولِ NULL/منفی؛ status آشغال. هر مورد با مالک تعیین‌تکلیف. | data | ۳ | — | گزارش شمارشی هر anomaly؛ هیچ drop خاموش؛ sign-off مالک. | بالا |
| **DATA-02 / QA-14 / DEVI-09** | **baseline از فایلِ زنده + diff کامل** (گِیتِ سختِ مقدماتی): `PRAGMA table_info` هر جدولِ هر دو DB زنده vs `schema.sql`+migrations. drift شناخته‌شده: `webapp/core.py:27-32,62`, `manager.py:2388-2392,2971-2975`؛ `specialist/core.py:137-169` (~۲۰ `_ensure_column`). **هیچ طراحیِ ETL پیش از بستنِ این.** | data | ۲ | DATA-01 | diff ستون/ایندکس صفر-gap؛ baseline_v0 = schema+drift. | بالا (baseline ناقص = داده گم می‌شود) |
| **DATA-03 / BACK-08 / OPS-05** | **Alembic baseline از فایلِ زنده** (نه git): `alembic stamp head` روی DB پر؛ idiom translate (REAL→NUMERIC، TEXT-date→DATE، AUTOINCREMENT→IDENTITY، INSERT OR IGNORE→ON CONFLICT، `full_name` VIRTUAL→GENERATED STORED، BLOB→BYTEA). migration fail-loud (نه `except:pass`). | data | ۴ | DATA-02 | `migrate` از صفر = baseline_v0؛ idempotent روی DB مهاجرت‌شده؛ هیچ drop؛ fail در CI. | بالا |
| **ARCH-01** | **Module/Schema Boundary Map:** دو app جنگو (`accounting`/`clinical`) + قانونِ وابستگیِ یک‌طرفه (import-linter)؛ `patient_links` به‌عنوان mirror می‌ماند (نه shared-kernel). | architecture | ۲ | ARCH-00 | Module Map per-table؛ import-linter ممنوع accounting→clinical؛ تأیید data-architect. | متوسط |
| **ARCH-04 / DATA-04 / SECU-08 / BACK-09** | **tenant_id ساختاری** (`NOT NULL DEFAULT 1`) همهٔ جداول هر دو schema؛ هر `UNIQUE(national_id)`→`UNIQUE(tenant_id,national_id)`؛ لجرهای idempotency به کلیدِ مرکب (`processed_invoices`, `engagement_dispatch`, `suggestion_log`, `doctor_visit_log`, `engagement_approvals`, `settings.key`). **RLS صریحاً موکول به T1.** | architecture | ۴ | ARCH-01, DATA-03 | همهٔ ۳۰+ جدول tenant_id دارند؛ هیچ UNIQUE تک‌ستونیِ national_id؛ تصمیمِ امضاشدهٔ «RLS تا T1 نه». | متوسط |
| **ARCH-04-guard** | **(حل تضاد DEVI-03):** guardrailِ معماری — تستِ نگهبان/lint که **هیچ کوئریِ جدید نباید `WHERE tenant_id=?` بگذارد تا T1** (با DEFAULT 1 و تک tenant، حذف WHERE امن است؛ افزودنش false-safety و ریسکِ leak می‌سازد). | architecture | ۱ | ARCH-04 | تستِ نگهبان: کوئریِ tenant-blind مجاز، tenant-aware تا T1 مردود. | متوسط (false-safety) |
| **ARCH-02 / DATA-10 / BACK-07 / QA-02 / SECU-09** | **AccountingReadPort fail-loud:** interface (Protocol/ABC) با امضای صریحِ خطا. **تمایز:** توابعِ revenue (revenue_for_accounting_ids:279, revenue_for_enrolled:376, revenue_by_patient:424, daily_*:460, revenue_windowed:515) → raise؛ توابعِ display/lookup (search, get_patient, history) → graceful-degrade با None و لاگ. `collected`/`invoice_item_payments` هم پوشش. الگوی `_chunks(ids,400)` در Postgres → `ANY(array)`/temp-join. تستِ نگهبان: DB-available+query-fail→exception نه 0. | architecture | ۳ | ARCH-01 | revenue در خطا raise؛ صفرِ واقعی بدون exception؛ تستِ zero-write روی schema accounting. | بالا |
| **ARCH-06 / OPS-04 / BACK-11** | **Celery + Redis** جایگزینِ schedulerِ thread (`scheduler.py:41`). نگاشتِ هر pass (engagement/invoice-sync/campaign/backup) به beat task. **(حل تضاد DEVI):** **distributed-lock (Redlock) الزامی حتی روی تک-instance** (rolling-restart دو scheduler می‌سازد)؛ خودِ Celery به اولین نیازِ مقیاسِ افقی موکول. `TESTING`→`CELERY_TASK_ALWAYS_EAGER`. هر task `with app.app_context()`. | architecture | ۵ | OPS-03 | دو worker همزمان engagement یک‌بار؛ retry/backoff؛ TESTING worker راه‌اندازی نمی‌شود؛ backup تک‌اجرا (lock-by-date). | متوسط (double-SMS) |
| **DEVI-07 / QA-07 / OPS-09** | **harness تستِ dual-DB در فاز A (نه B/C):** سوئیتِ موجود را هم روی SQLite و هم Postgres اجرا و هر اختلافِ خروجی (گردکردن، تفسیر تاریخ، NULL ordering) fail کند. **زیربنای فنیِ کلِ §۸ — بدون آن shadow بی‌معناست.** | qa | ۴ | OPS-16 | CI matrix SQLite+Postgres؛ تستِ نگهبان AccountingReadPort. | بالا |
| **DATA-14b / OPS-07 / SECU-07** | **PITR + WAL archiving + at-rest encryption:** WAL به object storage؛ base backup روزانه؛ کلید per-tenant یا platform (G-encryption)؛ کلید در ≥۲ محلِ امن. | data | ۳ | OPS-16, DATA-03 | PITR در staging تست (restore به T-2h)؛ RPO اندازه‌گیری؛ Postgres روی volume رمز. | بالا |
| **OPS-08** | **CI/CD pipeline** با گیت‌های اجباری: DEBUG=False، SECRET_KEY از env، همهٔ تست‌ها سبز، `alembic check`، docker build، staging auto-deploy، production با approve، rollback ≤۵min. | ops | ۳ | SECU-01, DATA-03 | PR با DEBUG=True یا SECRET_KEY hardcode→fail؛ alembic check سبز. | بالا |
| **OPS-15** | `GET /health` (DB/Celery/Redis ping) + uptime monitor + alert به مالک + error tracking (Glitchtip/Sentry). | ops | ۲ | OPS-04 | DB down→503 در ≤۵s؛ alert فعال. | متوسط |
| **SECU-12** | **MFA/TOTP کارکنان** (pyotp+qrcode): `totp_secret`/`totp_enabled` در users؛ enforce توسط manager؛ backup codes. | security | ۳ | SECU-04 | login بدون TOTP پس از enforce→setup؛ TOTP اشتباه→رد. | بالا (phishing) |
| **PROD-05** | انتخابِ «شریکِ تغییر» از کارکنانِ پذیرش (توافقِ کتبی، نه فقط اطلاع). | clinical | ۰.۵ | G0 | نام + توافق ثبت؛ نقش در dual-run/cutover روشن. | — |
| **PROD-02** | واژه‌نامهٔ مشترکِ مهاجرت (یک‌صفحه فارسی): درآمدِ canonical، بیمارِ فعال، فاکتورِ بسته، shadow — تأیید پزشک+پذیرش. | clinical | ۱ | PROD-01 | پزشک و یک کارمند خوانده و تأیید. | — |

**خروجیِ «انجام‌شده» فاز A:** vendor انتخاب + restore اثبات؛ ADR Accepted + C4؛ baseline از فایلِ زنده با diff صفر-gap؛ Alembic idempotent؛ AccountingReadPort fail-loud؛ Celery+lock؛ harness dual-DB سبز؛ PITR+at-rest؛ CI/CD با گیت‌های امنیتی؛ tenant_id ساختاری + guardrail.

---

## ۶. فاز B — مهاجرتِ بالینی + خواندنِ آفلاین + شبکهٔ ایمنیِ مالی

| id | شرح | حوزه | effort | وابستگی | معیار پذیرش | ریسک |
|---|---|---|---|---|---|---|
| **ARCH-12 / DEVI-02** | **🔴 golden-master characterization suite روی منطقِ پولیِ webapp** (پیش‌نیازِ سختِ فاز C): snapshot/قفلِ خروجیِ `get_invoice_items`/`update_invoice_totals` روی نمونهٔ معنادار (آزاد/بیمه‌ای/پوششی/پرستاری-مستثنا/مصرفی). webapp صفر تست دارد و این صحتِ منطقِ go-liveِ بعدی را قفل می‌کند — چیزی که oracleِ §۸ (فقط جمعِ تاریخی) پوشش نمی‌دهد. | architecture | ۶ | DEVI-07 | golden-master سبز روی demo + داده واقعی؛ Postgres همان اعداد را بازتولید. | بحرانی (بزرگ‌ترین شکافِ صحتِ پساٰ-go-live) |
| **ARCH-07 / DATA-12 / BACK-06** | **(حل تضاد DEVI-05):** فقط **idiomهای ناسازگارِ Postgres** پورت شوند (INSERT OR IGNORE→ON CONFLICT، `datetime('now','+3:30')`→app-side، `control_room_service.py:42-51` f-string→**LATERAL/DISTINCT ON + whitelistِ ستون**) **+ توابعِ مرزِ مالیِ accounting_bridge** (همراه AccountingReadPort). ORMِ کاملِ معنایی → roadmapِ تدریجیِ پساٰ-cutover repo-by-repo. ~۳۷ db.execute در services، ~۲۲ در api. | architecture | ۳ | DATA-04 | idiomهای ناسازگار + مرزِ مالی پورت؛ control_room با whitelist؛ تستِ dual-DB معادل. | متوسط |
| **SECU-17** | whitelist `ALLOWED_VITAL_KEYS` در `control_room_service.py` **پیش از** BACK-06 (وگرنه نام ستون در ORM string interpolation می‌ماند). | security | ۱ | — (پیش از BACK-06) | key خارج از whitelist→ValueError. | پایین فعلی/بالا اگر user-controlled |
| **ARCH-05 / DATA-13** | **🔴 رفعِ تضادِ نیمه‌ابری:** snapshot/replicaِ read-onlyِ دوره‌ای از `clinic_new.db` در ابر (تخصصیِ ابری پلِ فایلیِ لوکال را نمی‌خواند). `ACCOUNTING_DB_PATH` از فایل‌پث به connection string؛ `_connect_ro` از sqlite3 به psycopg2. **معیارِ کهنگیِ snapshot fail-loud (نه صفر).** وابسته به ARCH-12 (منبعِ تست‌نشده). | architecture | ۳ | ARCH-02, ARCH-12 | تخصصی در فاز B فایلِ لوکال نمی‌خواند؛ شاخصِ تازگی؛ کهنگیِ زیاد→fail-loud؛ مسیرِ حذف در cutover. | بالا |
| **OPS-17 / ARCH-11** | **خواندنِ آفلاینِ کامل + صفِ نوشتنِ پذیرش** (gateِ pre-go-live فاز B، نه nice-to-have): cache خواندنی + صفِ یک‌جهتهٔ append-only برای پذیرش (idempotency key، نه LWW). **بستنِ فاکتورِ آفلاین صریحاً out-of-scope** (ADR sync جدا). | ops | ۷ | OPS-04, ARCH-05 | قطع اینترنت: جستجو+ویزیت کار می‌کنند؛ sync پس از اتصال؛ بدون duplicate؛ دمو برای مالک. | بالا (قطعی ایران واقعی) |
| **ARCH-03 / DATA-11 / BACK-12** | **رویدادِ invoice.closed درون‌تراکنشی:** `close_invoice` تک‌تراکنشی (رفعِ دو commit جدا `invoices_repo.py:275,292` — **قابل اجرا در SQLite هم، prioritize**)؛ رویداد in-transaction یا LISTEN/NOTIFY؛ مصرف Celery+lock؛ cursor/`processed_invoices` به‌عنوان تورِ ایمنیِ دوم. ARCH-03 طراحی، DATA-11/BACK-12 پیاده. | architecture | ۴ | ARCH-02, ARCH-06 | close اتمیک؛ task ≤۵s پس از COMMIT؛ at-least-once+idempotent حفظ. | متوسط |
| **QA-16** | ۱۶۸ تستِ موجود روی Postgres adapter سبز بمانند؛ idiomهای SQLite manifest شوند؛ control_room با LATERAL/whitelist. **(حل تضاد DEVI-05):** بخشِ idiom-incompatible بلاکرِ فاز B، ORM coverage کامل → فاز C. | qa | ۵ | QA-07 | همهٔ ۱۶۸ + تست‌های Postgres سبز؛ هیچ SQLiteism در service/repo. | بالا |
| **SECU-10 / OPS-19 / FRON-12** | **لاگِ دسترسیِ READ:** `before_request` روی blueprintهای حساس (patients/vitals/lab_results/control_room)؛ نمای مدیر `/manager/access-log` با فیلتر جلالی؛ pagination + انقضا ۹۰ روز (Celery beat). لاگِ دسترسیِ ادمینِ پلتفرم→alert مالک. | security | ۲ | ARCH-04 | GET پرونده→ردیف READ؛ نمای مدیر کار می‌کند. | متوسط (تعهد قراردادی) |
| **PROD-07** | سیاستِ staleness: ستونِ `staleness_months` در `clinical_indicators` (**نیازِ migration صریح — در schema فعلی نیست؛ ارجاع به BACK**)؛ پزشک N_stale هر ۷ شاخص (hba1c/fbs/bp_sys/bp_dia/ldl/egfr/uacr) را می‌دهد. | clinical | ۱ | G-STALE, DATA-04 | هر شاخص N_stale دارد؛ seed شد؛ شاخصِ کهنه→«نامشخص» در اتاق کنترل. | متوسط (تصمیم روی داده نامعتبر) |
| **PROD-11** | ممیزیِ PHI همهٔ ۷ قالبِ پیامک (هیچ تشخیص/دارو/بیماری) + تأیید پزشک. **پیش از حلِ KYC** (وگرنه اولین ارسالِ واقعی تأییدنشده است). | clinical | ۱ | SECU-14a | جدول [event, template, آیا PHI دارد؟, تأیید پزشک] همه «خیر»؛ compliance اصلاح. | بالا (حریم) |
| **PROD-06** | wireframe جریانِ یکپارچهٔ پذیرش+ویزیت+پرونده (پیش‌نیازِ FRON-09b). | clinical | ۳ | PROD-01, PROD-05 | ۳ صفحهٔ کلیدی با پزشک مرور+امضا؛ جریانِ ثبتِ ویزیتِ یکپارچه. | متوسط (redesign پس از go-live) |

**خروجیِ «انجام‌شده» فاز B:** golden-master منطقِ پولیِ webapp سبز؛ idiomها پورت؛ replicaِ ابریِ accounting با fail-loud؛ خواندنِ آفلاین تست‌شده با دموی قطعی؛ ۱۶۸ تست روی Postgres سبز؛ لاگ READ؛ ممیزیِ PHI.

---

## ۷. فاز C — حسابداری dual-run / shadow

> لوکالِ فعلی **منبعِ حقیقت می‌ماند**. هیچ ورودی به Postgres تأثیرِ تولیدی ندارد. **پیش‌نیازِ سخت: ARCH-12 (golden-master) سبز.**

| id | شرح | حوزه | effort | وابستگی | معیار پذیرش | ریسک |
|---|---|---|---|---|---|---|
| **ARCH-09 / DATA-05 / BACK-10 / SECU-15** | **سیاستِ نوعِ داده:** پول REAL→`NUMERIC` با tolerance صفر؛ **literal-copy با `Decimal(str(sqlite_value))` در Python** (نه CAST مستقیم — float→NUMERIC ممکن است گرد کند)؛ تاریخِ تقویمی (`work_date`/`visit_date`/`onset_date`) → `DATE` **بدون timezone-shift**؛ timestamp Tehran→`timestamptz` با تفسیر صریحِ Asia/Tehran. | architecture | ۲ | DATA-04 | جدولِ نگاشتِ نوع؛ NUMERIC tolerance صفر؛ work_date بدون shift؛ نمونهٔ منجمد روز جابه‌جا نشد. | بالا |
| **DEVI-08 / QA-10 / BACK-16** | **تفسیرِ زمانِ Asia/Tehran (تسکِ مجزای پرریسک):** `iran_now()`→`datetime.now(tz=ZoneInfo('Asia/Tehran'))`؛ تستِ مرزیِ ۲۳:۴۵ تهران؛ `work_date` تقویمی timezone-shift نمی‌شود (وگرنه درآمدِ روزِ اشتباه + per-day false-green). | qa | ۲ | ARCH-09 | رکوردِ ۲۳:۴۵ تهران در Postgres همان work_date؛ هیچ شیفتِ ۳:۳۰/یک‌روزه. | بالا |
| **DATA-07** | **ETL copy-forward:** همهٔ ستون‌های پول بیت‌به‌بیت (total_amount, visits.price, injections.*, procedures.price, consumables_ledger.total_cost, wallet_transactions.*). **تستِ نگهبان: ETL هرگز `get_invoice_items`/`update_invoice_totals` را روی ردیفِ تاریخی صدا نمی‌زند**؛ منطقِ patient_share فقط فاکتورهای جدید. ترتیبِ توپولوژیکِ بار + تراکنشِ all-or-nothing per-table. | data | ۴ | DATA-05, DEVI-04 | هیچ بازمحاسبه؛ بیت‌به‌بیت با منبع؛ تستِ نگهبانِ ممنوعیتِ بازمحاسبه. | بحرانی (بازمحاسبهٔ پولِ تاریخی) |
| **ARCH-08 / DATA-08 / BACK-13 / OPS-12** | **(حل تضاد دور دوم — preserve-id پیش‌فرض):** حفظِ idهای اصلی با `INSERT صریح + setval` روی sequence (silent-bug را کاملاً حذف می‌کند)؛ جدولِ remap فقط fallback اگر تصادمِ tenant مانع شد. **طراحیِ مشترک با ARCH-04** (اگر UNIQUE به (tenant_id,national_id) رفت، `accounting_patient_id` که tenant ندارد مبهم می‌شود). | architecture | ۲ | ARCH-04, ARCH-05 | idها حفظ (ترجیح) یا remap اثبات‌شده؛ هر patient_link پس از remap به همان national_id؛ صفر orphan در JOIN. | بالا (silent: درآمدِ بیمار اشتباه) |
| **§۸.۴ snapshot freeze** | **(گپ دور دوم):** snapshotِ منجمدِ §۸.۴ باید **جداولِ پیکربندیِ زنده** را هم freeze کند (`visit_tariffs`, `insurance_nursing_exclusions`, `base_visit_price`) نه فقط invoices — وگرنه ناهمگامیِ تعرفه با لحظهٔ محاسبه oracle را false-red می‌کند. | data | ۱ | DATA-07 | جداولِ پیکربندی در snapshot منجمد. | متوسط |
| **DATA-09 / QA-08 / OPS-13 / BACK-14** | **گیتِ سه-oracle tolerance-صفر:** (الف) Σ آیتمی پل، (ب) Σ total_amount، (ج) collected per work_date/insurance/status + **تطبیقِ per-invoice** (تا اختلافِ علامت‌مخالف false-green ندهد). سه دورهٔ مالیِ کامل، اختلافِ بیت‌به‌بیت صفر، امضاکنندهٔ مشخص. **دو رژیمِ tolerance:** صفر برای فاکتورِ تاریخیِ منجمد؛ round-off (≤۱ واحد per-invoice) برای منطقِ بازتولیدشدهٔ پساٰ-go-live. | qa | ۴ | DATA-07, DATA-08, ARCH-12 | سه oracle + per-invoice روی snapshot منجمد، سه دوره، صفر؛ امضای مالک؛ هر اختلاف→cutover معوق. | بحرانی (غیرقابل عبور) |
| **PROD-03** | spec گزارشِ مقایسهٔ shadow: فرمت، واحد پول، **(اصلاح)** tolerance صفر برای نقدی؛ برای بیمه‌ای canonical انتخاب و مقایسه فقط با خودِ oracle (نه cross-definition، چون ذاتاً متفاوت)؛ فرکانس روزانه؛ امضاکننده. | clinical | ۲ | DATA-06 | spec با پزشک تأیید. | بالا |
| **PROD-04** | پروتکلِ تداومِ کارِ کلینیک در dual-run (**فقط پس از تستِ موفقِ آفلاین OPS-17**): جریانِ صبح، رفتار در قطعِ Postgres، چک روزانهٔ oracle، مسیرِ ارجاعِ اختلاف. | clinical | ۲ | PROD-02, PROD-03, OPS-17 | پروتکل یک‌صفحه؛ کارمند role-play کرد. | بالا (شکستِ رایجِ dual-run) |
| **PROD-14** | معیارِ توقفِ انسانیِ فاز (آستانهٔ tolerance + سه دوره + امضاکننده) **پیش از OPS-13** — آستانهٔ انسانی آستانهٔ اسکریپت را تعریف می‌کند. | clinical | ۱ | PROD-03 | سند با اعداد tolerance + امضای مالک. | بحرانی |

**خروجیِ «انجام‌شده» فاز C:** سیاستِ نوع با tolerance صفر؛ زمانِ Tehran با تستِ مرزی؛ ETL بدون بازمحاسبه؛ preserve-id اثبات؛ گیتِ سه-oracle صفر در سه دوره با امضا.

---

## ۸. فاز D — cutoverِ مشروط

| id | شرح | حوزه | effort | وابستگی | معیار پذیرش | ریسک |
|---|---|---|---|---|---|---|
| **ARCH-10 / OPS-14** | **runbook cutover:** روزِ آرام، اطلاع‌رسانیِ پیشین، **freeze/read-only حسابداریِ لوکال** در پنجره، بکاپِ pre-cutover در ۲ محل، ETL نهایی + اجرای سه-oracle (ثابت از فاز C)، switch، smoke test، معیارِ توقفِ هر فاز. | architecture | ۳ | DATA-09, ARCH-09 | runbook امضاشده با freeze + بکاپ + معیار توقف؛ smoke test موفق. | بالا (بالاترین ریسک پروژه) |
| **DATA-15 / QA-18 / DEVI-10** | **(حل تضاد دور دوم):** reverse-ETL Postgres→SQLite **یا** اثبات با round-trip در staging (checksum با pre-cutover)، **یا** صادقانه محدود به «freeze + restore بکاپِ pre-cutover با از‌دست‌دادنِ نوشته‌های پنجره» و **point-of-no-return جلوتر کشیده شود**. توصیهٔ معمار: گزینهٔ دوم امن‌تر (reverse-ETLِ پول خود نقطهٔ شکستِ جدید است). مالک انتخابِ صریح. | data | ۳ | DATA-07, DATA-09 | یا reverse-ETL round-trip تست‌شده، یا rollback محدود + point-of-no-return جلوکشیده. | بالا |
| **PROD-13** | اطلاع‌رسانیِ پیشین (≥۲ روز) + تقویمِ cutover (پنجشنبه شب/ابتدای هفته) + چک‌لیست go/no-go. | clinical | ۰.۵ | PROD-04, PROD-05 | تاریخ ثبت؛ شریکِ تغییر آگاه؛ چک‌لیست موجود. | بالا |
| **QA-17** | اسکریپتِ go/no-go خودکار: integrity_check، row-count، سه-oracle صفر، id-remap verify، restore، reverse-ETL، بکاپ pre-cutover، freeze، اطلاع‌رسانی. | qa | ۲ | DATA-09, DATA-14a, ARCH-08 | هر fail→توقف؛ امضای مالک برای تمام-pass. | بحرانی |

**خروجیِ «انجام‌شده» فاز D:** cutover با freeze + بکاپ ۲-محل؛ smoke test؛ rollback مسیرِ صریح (reverse-ETL تست‌شده یا restore محدود)؛ point-of-no-return امضاشده.

---

## ۹. فاز E — آفلاینِ نوشتنی + PWAِ بیمار (آخر، با ADR جدا)

| id | شرح | حوزه | effort | وابستگی | معیار پذیرش | ریسک |
|---|---|---|---|---|---|---|
| **SECU-11** | auth بیمار OTP موبایل (نه national_id): `patient_otp_sessions`؛ rate-limit ۳/۱۰min؛ JWT کوتاه‌عمر bind به patient_link_id. | security | ۵ | SECU-04, SECU-05 | OTP منقضی→401؛ ۳ خطا→قفل؛ national_id در هیچ endpoint بیمار. | بالا |
| **FRON-07** | کارت بیمار PWA-ready (manifest + service worker، **Network-first برای /card/<token>، هرگز token را cache نکن**). | frontend | ۳ | SECU-13, G-VENDOR | Lighthouse PWA ≥۸۰؛ offline cache؛ national_id هیچ‌جا. | بالا (وابسته VPS+HTTPS) |
| **FRON-10** | Web Push: VAPID مستقیم (نه FCM، فیلتر ایران)؛ `push_subscriptions`؛ ارسال از Celery؛ احترام به ساعت آرام. | frontend | ۵ | FRON-07, FRON-09 | push روی Android/iOS 16.4+؛ opt-out؛ ساعت آرام. | بالا |
| **FRON-11 / SECU-11b** | PWA بیمار self-report + رزرو نوبت (تریگرِ T2): `source='patient'` vs `'clinic'`؛ row-level filter روی patient_id حتی بدون RLS. | frontend | ۸ | FRON-07, FRON-09, FRON-10 | OTP login؛ self-report در پروندهٔ پزشک؛ بیمار فقط داده خودش. | بالا |
| **ARCH-11-defer** | عاملِ لوکالِ نوشتنیِ کامل + پروتکلِ sync → **ADR جداگانه** (بستنِ فاکتورِ آفلاین). | architecture | — (ADR جدا) | G-B, ARCH-10 | سندِ مرزِ آفلاین؛ بستنِ فاکتور صریحاً خارج. | بالا |

**خروجیِ «انجام‌شده» فاز E:** auth بیمار OTP؛ PWA installable؛ Web Push بدون FCM؛ self-report با تفکیک منبع.

---

## ۱۰. ویژگی‌های گِیتِ قراردادیِ پیش‌از-اولین-مشتری (مالکیتِ متمرکز)

> data_trust_story.md:71 این‌ها را تعهدِ پیش‌از-قرارداد می‌نامد. **مالکِ متمرکز (MARK-A-EXPORT) + تاریخِ مشترک در تقویمِ فروش** تا «همه فکر نکنند دیگری می‌سازد».

| id | شرح | حوزه | effort | وابستگی | فاز گِیت |
|---|---|---|---|---|---|
| **SECU-16 / BACK-17 / OPS-18 / FRON-03** | **دکمهٔ «خروجیِ کاملِ داده»:** `/manager/export/full`→ZIP (مالی=CSV با BOM برای Excel، بالینی=JSON). فقط manager. در قطعِ پرداخت export فعال بماند. تعهدِ ۴۸h. تستِ export→import→هیچ داده گم. **مالکیتِ واحد لازم.** | backend | ۴ | DATA-03 | A |
| **PROD-15** | ماتریسِ مالکیتِ ۵ موردِ پیش‌از-قرارداد (export, READ-log, MFA, at-rest, vendor) → هر یک به SECU/BACK/OPS تخصیص؛ گِیتِ فاز D. | clinical | ۱ | — | A→D |
| **PROD-09** | spec «دسترسی در قطعِ پرداخت» (N روز، آیا پذیرشِ جدید، آیا SMS) → بندِ قراردادی. | clinical | ۱ | G-payment | D |
| **MARK-A-EXPORT** | مالکیتِ تاریخِ سررسیدِ قراردادیِ export + acceptance مشتری‌محور (فایل در Excel باز شود). | marketing | ۱ | SECU-16 | A |

---

## ۱۱. مسیرِ بحرانی و توالی

```
DEVI-04 (اندازه‌گیری ۳-گانه درآمد، روز ۱)
   ↓
[فاز ۰ موازی و مستقل: SECU-01..18, QA-15 — هیچ وابستگی به بقیه]
   ↓
G-VENDOR spike (OPS-16/DEVI-06) ── اگر شکست → مسیر ۰ دوباره ارزیابی
   ↓
ARCH-00 (ADR Accepted + C4)
   ↓
DATA-01 (پروفایل کثیف) → DATA-02 (baseline از فایل زنده، گِیت سخت) → DATA-03 (Alembic)
   ↓
ARCH-01 (Module Map) → ARCH-04 (tenant_id + guardrail)
   ↓
ARCH-02 (AccountingReadPort) + DEVI-07 (harness dual-DB) ← هر دو فاز A
   ↓
ARCH-12 (golden-master منطق پولی webapp) ← پیش از فاز C، نه آخر
   ↓
ARCH-06 (Celery+lock) → ARCH-05 (replica ابری) → ARCH-03 (رویداد درون‌تراکنشی)
   ↓
[فاز C] ARCH-09 (نوع/پول) + DEVI-08 (زمان Tehran) → DATA-07 (ETL) → ARCH-08 (preserve-id)
   ↓
گیتِ سه-oracle (DATA-09/QA-08) ── سه دوره مالی، صفر، امضا
   ↓
[فاز D] ARCH-10 (runbook) + DATA-15 (rollback صادقانه) → QA-17 (go/no-go)
   ↓
[فاز E] SECU-11 (OTP) → FRON-07/10/11 (PWA) + ARCH-11 (ADR sync جدا)
```

**اصلاحاتِ کلیدیِ توالی (از دورِ دوم):**
- **DEVI-04 اولین کارِ مطلق** — scope را تعیین می‌کند.
- **فاز ۰ کاملاً decouple** — non-blocking، حتی بدون تصمیمِ ابر.
- **DEVI-07 (harness) و DATA-14a (restore) به فاز A** — نه B/C.
- **ARCH-12 (golden-master) پیش از فاز C** — وارونگیِ ریسک؛ پرریسک‌ترین منطق زودترین شبکهٔ ایمنی.
- **ARCH-04 و ARCH-08 طراحیِ مشترک** — تقاطعِ tenant_id × id-remap.
- **OPS-17 (آفلاین) gateِ pre-go-live فاز B** — نه nice-to-have.

---

## ۱۲. گاتچاهای بحرانی (مبنا بگیر)

| # | گاتچا | شاهدِ کد | مهار |
|---|---|---|---|
| ۱ | **سه تعریفِ درآمد** (raw / total_amount / collected) | `accounting_bridge.py:253-276,353` · `invoices_repo.py:278-292` | oracleِ سه‌گانه (DATA-09)؛ canonical امضاشده (G-C) |
| ۲ | **`total_amount` مشتقِ تعرفهٔ زنده** (نه snapshot) | `invoices_repo.py:92-95,121-130` | literal-copy، تستِ نگهبانِ ممنوعیتِ بازمحاسبه (DATA-07) |
| ۳ | **webapp صفر تست** + منطقِ پیچیدهٔ patient_share | Glob webapp/tests=∅ · `invoices_repo.py:114-217` | golden-master (ARCH-12) پیش از فاز C |
| ۴ | **شکستِ خاموشِ مالی** (partial-sum نه صفر) | `accounting_bridge.py:279,376,424,460,515` | AccountingReadPort fail-loud (ARCH-02) |
| ۵ | **id-remap** accounting_patient_id | `specialist/schema.sql:22` | preserve-id با setval (ARCH-08) |
| ۶ | **زمانِ Tehran / work_date** | `core.py:36 substr(opened_at)` shift شب | DATE بدون shift، تستِ مرزی ۲۳:۴۵ (DEVI-08) |
| ۷ | **close غیراتمیک** + scheduler دوبار-اجرا | `invoices_repo.py:275,292` · `scheduler.py:41` | تک‌تراکنش (ARCH-03) + Celery+lock (ARCH-06) |
| ۸ | **پولِ REAL + float** | `invoices_repo.py:283-286` · `schema.sql:48,67,92` | NUMERIC با `Decimal(str(v))` tolerance صفر (ARCH-09) |
| ۹ | **baseline ناقص از git** | inline ALTER در `manager.py`، `_ensure_column` | baseline از فایلِ زنده (DATA-02) |
| ۱۰ | **consumable در total_amount ولی نه در پل** | `invoices_repo.py:237,284-296` | DATA-06 جدا گزارش؛ canonical روشن کند |
| ۱۱ | **API key کاوه‌نگار در URL path** | `kavenegar_provider.py:73` | log sanitization در reverse proxy (OPS-03) |
| ۱۲ | **`tenant_id` نیمه‌کاره = false-safety** | — | guardrail: بدون WHERE tenant_id تا T1 (ARCH-04-guard) |

---

## ۱۳. بک‌لاگِ دوربردِ دائمی (معوق — با تریگرِ بازبینی)

| آیتم | چرا معوق | تریگرِ بازبینی |
|---|---|---|
| **RLS policy + بازبینیِ خط‌به‌خط + تستِ cross-tenant** | over-engineering پیش از مشتری دوم؛ tenant_id ساختاری آماده | **T1** — امضای قراردادِ کلینیکِ دوم |
| **ADRِ پروتکلِ syncِ آفلاینِ نوشتنی (بستنِ فاکتورِ آفلاین)** | تصادمِ id، LWWِ خطرناک روی پول، skewِ ساعت | **T2** یا تصمیم مالک روی G-B = (ج) |
| **DB-per-tenant / sharding / per-tenant encryption key** | یک Postgres دو schema کافی؛ کلید per-tenant ریسکِ recovery | رشدِ tenant یا کلینیکِ حساس یا الزامِ تنظیم‌گری |
| **TimescaleDB برای vital_readings/lab_results** | حجمِ تک‌کلینیکی نیاز ندارد؛ index موجود کافی | **T3** — کندیِ کوئریِ تحلیلی >۵۰۰ms یا >۱۰M ردیف |
| **رجیستریِ مرکزیِ هویتِ بیمارِ cross-tenant** | per-tenant UNIQUE امن‌تر تا چندکلینیکی | T1 + تصمیم مالک روی مدلِ هویت |
| **پلِ نسخه‌نویسی (MV3 extension) — یکپارچه‌سازی** | بلاک تا دسترسیِ زندهٔ پنل بیمه؛ Context مستقل می‌ماند | گِیتِ E1 — HTML/دسترسیِ ep.tamin.ir از مالک |
| **نوشتنِ معکوس به accounting (writable bridge)** | جهتِ یک‌طرفه مرز را تمیز نگه می‌دارد | **T4** — تسویهٔ نسخهٔ بیمه‌ای |
| **pen-test سالانهٔ شخص ثالث + CQRS audit trail** | پیش از مشتری دوم بودجه/ارزش ندارد | T1 یا >۵۰۰ بیمار در ابر یا الزامِ ممیزی |
| **ORMِ کامل (پساٰ-cutover repo-by-repo)** | Strangler؛ بازنویسیِ یکجا دیباگِ oracle را می‌شکند | پس از cutoverِ پایدار + harness dual-DB سبز |

---

## ۱۴. معیارِ «انجام‌شده» کل مهاجرت

1. **G-VENDOR موفق** — vendorِ ایرانی با PITR + restoreِ واقعیِ اثبات‌شده.
2. **فاز ۰ کامل** — همهٔ deal-breakerهای §۹ روی هر دو اپ، با تست/grep.
3. **canonical درآمد امضاشده** (G-C) + سه-oracle صفر در سه دورهٔ مالی.
4. **golden-master منطقِ پولیِ webapp** سبز + ۱۶۸ تست روی Postgres سبز.
5. **AccountingReadPort fail-loud** + تستِ نگهبانِ zero-write.
6. **preserve-id اثبات‌شده** — هر patient_link به همان national_id.
7. **خواندنِ آفلاین** تست‌شده با دموی قطعیِ اینترنت.
8. **cutover با runbook امضاشده** + rollback صادقانه + point-of-no-return.
9. **دکمهٔ export + لاگ READ + MFA + at-rest** پیش از اولین قرارداد.
10. **KYC کاوه‌نگار حل** — ارسالِ پیامکِ واقعی فعال.
