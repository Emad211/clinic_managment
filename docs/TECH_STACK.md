# استکِ فنی (Tech Stack) — تصمیمِ معماریِ مرجع

> **نسخه ۱.۰ — خرداد ۱۴۰۵ — قفل‌شده با تحقیق + چرخهٔ تفکرِ مستقل.**
> این سند، تصمیمِ نهاییِ استکِ فنی است و دلیلِ هر انتخاب را نگه می‌دارد تا «همیشه یادمان بماند».
> مرجعِ استراتژی: [`MASTER_PLAN.md`](MASTER_PLAN.md). تحقیقِ بازار: [`MARKET_RESEARCH.md`](MARKET_RESEARCH.md).

## اصلِ راهنما
دو واقعیت استک را تعیین می‌کنند:
1. **مهاجرت اجتناب‌ناپذیر است:** اپ‌های فعلی desktop + SQLite‌اند؛ محصول باید **SaaS ابریِ multi-tenant** شود. SQLite سقفِ سخت دارد.
2. **ولی rewrite-from-zero ممنوع:** کدِ فعلی **لایه‌ای** است (`api → services → adapters/sqlite → domain`). منطقِ دامنه/سرویس (به‌خصوص موتورِ ADA: `rule_engine`, `followup_engine`, ~۵۷ قاعده) **حفظ** می‌شود؛ فقط **لبه‌ها** عوض می‌شوند (SQLite→Postgres، Flask→Django، UIِ بازطراحی‌شده منتقل می‌شود). **Evolve، نه Rewrite.**

---

## ۱. خلاصهٔ تصمیم (TL;DR)
- **بک‌اند:** Python · **Django + django-ninja** (هستهٔ SaaS) · **FastAPI + arq** (سرویسِ پایپ‌لاینِ AI، فاز۲+)
- **داده:** **PostgreSQL + pgvector** · **Redis** · Neo4j (معوق تا فاز۲+)
- **Multi-tenancy:** **PostgreSQL RLS** با `tenant_id` و deny-by-default، از روزِ اول
- **صف:** **Celery** (فاز۱) → **arq** (پایپ‌لاینِ LLM)
- **فایل:** **S3-compatible Object Storage** (آروان‌کلاد/لیارا)
- **فرانت:** فاز۱ **Django templates + HTMX** → فاز۲+ **Next.js (React) + Tailwind/shadcn**
- **موبایل:** **Flutter** (+ **PWA** برای آفلاینِ B2B)
- **میزبانی:** **لیارا** (شروع) → **آروان‌کلاد** (مقیاس) — هر دو داخلِ ایران
- **DevOps:** Docker از آینهٔ ایرانی · GitLab self-hosted CI · آینهٔ PyPI/npm
- **LLM:** **AvalAI** (سازگار با OpenAI) پشتِ لایهٔ انتزاع
- **معماری:** **Modular Monolith** (webapp + specialist_clinic → ماژول‌های یک پروژه) + سرویسِ پایپ‌لاینِ جدا
- **رصد:** Prometheus + Grafana + Sentry

---

## ۲. بک‌اند

### ۲.۱ زبان: Python — قفل
تیم بلد است · پایپ‌لاینِ AI پایتون‌محور است · **دومین بازارِ استخدامِ بک‌اندِ ایران** بعد از PHP، با رشدِ سریع در AI/SaaS · health-techِ ایران (پذیرش۲۴) همین را به‌کار می‌برد. حقوق رقابتی، نه نجومی مثلِ Go.
منبع: irantalent.com/blog/computer-programmer-salary · jobinja.ir (آگهی‌های Django/DRF).

### ۲.۲ فریم‌ورک: Django + django-ninja — قفل
- **چرا Django:** پنلِ ادمین + Auth + ORM + migrations آماده = **سریع‌ترین مسیر تا فاز۱** (CRUDِ مطب). Instagram روی Django مقیاس گرفته.
- **چرا django-ninja (نه فقط DRF):** async بومی + Pydantic + OpenAPIِ خودکار (تجربهٔ FastAPI) **در همان کدبیسِ Django** → بدونِ سربارِ دو فریم‌ورک. «An optimised Django+Ninja setup matched FastAPI for expected load.»
- **جایگزینِ محافظه‌کار:** DRF (بالغ‌تر، بازارِ استخدامِ بزرگ‌تر) — اگر تیم async نمی‌خواهد.
- **Flask (فعلی):** برای SaaSِ جدید کنار گذاشته می‌شود؛ micro-frameworkِ بدونِ async و بدونِ batteries.
منبع: buildmvpfast.com/blog/fastapi-vs-django-ai-saas-2026 · capsquery.com (FastAPI vs Django 2025).

### ۲.۳ سرویسِ پایپ‌لاینِ AI: FastAPI + arq (سرویسِ جدا، فاز۲+) — قفل
بارِ LLM ذاتاً **async و I/O-bound** است (هر فراخوان ۲–۳۰ ثانیه). FastAPI + arq یک استکِ کاملاً async می‌دهد (بدونِ gevent/thread-pool). arq را Samuel Colvin (پدرِ Pydantic) نوشته. این سرویس همان Postgres را با هستهٔ Django share می‌کند.
منبع: dangquan1402.github.io (arq over Celery for LLM) · stevenyue.com (task-queue benchmark).

### ۲.۴ سبکِ API: REST + OpenAPI — قفل
برای پزشکی/regulatory، REST قابلِ audit‌تر و ساده‌تر است؛ caching و ابزارِ بالغ. GraphQL فقط اگر بعداً multi-clientِ پیچیده شد (به‌صورتِ gateway روی REST). django-ninja خودش OpenAPI تولید می‌کند.

---

## ۳. لایهٔ داده

### ۳.۱ PostgreSQL + pgvector — قفل (منبعِ حقیقت)
جایگزینِ SQLite. مدیریت‌شده روی آروان‌کلاد (HA با نودِ Standby) یا لیارا. **pgvector** برای جست‌وجوی معناییِ پایپ‌لاین (تا ~۵M بردار کافی؛ بعد Qdrant). ⚠️ **برای تأیید:** ارائهٔ extensionِ `pgvector` روی Postgresِ مدیریت‌شدهٔ آروان/لیارا باید چک شود؛ اگر نبود، Postgresِ self-managed روی VPS.
منبع: news.arvancloud.ir/fa/dbaas-1403 · dev.to (pgvector vs Qdrant vs Milvus 2026).

### ۳.۲ Redis — قفل
کش + session + brokerِ صف. مدیریت‌شده روی لیارا/آروان.

### ۳.۳ Neo4j — معوق تا فاز۲+ (گرافِ دانش)
برای multi-hop traversalِ گرافِ دانش، Neo4j **۳۶–۹۸۱× سریع‌تر** از Postgres است. ولی تا فاز پلتفرم لازم نیست؛ **فاز۱ فقط pgvector**. جایگزینِ «یک‌سرویس‌کمتر»: Apache AGE (extensionِ Postgres) اگر خواستیم پیچیدگی کم کنیم. در ایران managed Neo4j نیست → روی VPS.
منبع: academic.oup.com (graph DB for clinical) · dev.to (Apache AGE vs Neo4j).

### ۳.۴ Multi-tenancy: PostgreSQL RLS — قفل
**Shared-schema + `tenant_id` + Row-Level Security، deny-by-default، از روزِ اول.** حتی اگر کد `WHERE tenant_id` را فراموش کند، DB نشت نمی‌دهد. `tenant_id` باید **leading column در ایندکسِ composite** باشد. تستِ CI برای policy. **مهاجرت به schema-per-tenant** فقط وقتی مشتریِ enterprise/بیمارستانی ایزولاسیونِ فیزیکی خواست (~۵–۷ هفته اگر از اول `tenant_id` همه‌جا بود).
منبع: propelius.tech (RLS vs schema, PG16) · hunchbite.com (multi-tenant SaaS).

---

## ۴. صف و ارکستراسیون
- **فاز۱ (کارهای عملیاتی: کمپینِ پیامک، تولیدِ recall، بکاپ):** **Celery** — بالغ، Django-idiomatic، بازارِ استخدامِ آشنا.
- **فاز۲+ (پایپ‌لاینِ چندعاملیِ LLM):** **arq** — async بومی، در سرویسِ FastAPIِ پایپ‌لاین. ارکستریتورِ Orchestrator–Worker (idempotent + resumable + observable) اینجا می‌نشیند.
- اصل: دو پارادایمِ متفاوت در دو سرویس؛ یکی‌کردنِ زورکی ارزش ندارد.

---

## ۵. ذخیرهٔ فایل: S3-compatible — قفل
Object Storageِ آروان‌کلاد یا لیارا (سازگار با S3). برای PDFِ گایدلاین، تصویرِ آزمایش/مدارکِ بیمار، ورودیِ OCR، و آبجکت‌استوریجِ پایپ‌لاین.

---

## ۶. فرانت‌اند

### ۶.۱ فاز۱ (داشبوردِ مطب، B2B): Django templates + HTMX — قفل
داشبوردِ کلینیک ذاتاً **CRUD** است؛ تحقیق تأیید کرد HTMX دقیقاً اینجا برنده است («admin panel… 8 lines of HTML vs 25+ lines of React»). **UIِ بازطراحی‌شدهٔ ui-ux-pro-max (Jinja) منتقل می‌شود** → صفرْ کارِ هدررفته، صفرْ ریسکِ مهاجرت، سریع‌ترین تا درآمد. (محدودیت: HTMX آفلاین‌first نیست — بخش ۷.)
منبع: dev.to/pockit_tools (htmx in 2026).

### ۶.۲ فاز۲+ (پلتفرمِ محتوا + patient-facing): Next.js (React) + Tailwind/shadcn — قفل
- **چرا React/Next:** **غالبِ بازارِ استخدامِ ایران** (دیوار/دیجی‌کالا/اسنپ/پذیرش۲۴ همه React)؛ استخدام آسان.
- **RTL/جلالی بالغ:** `react-multi-date-picker` (ساختِ ایران)، تقویمِ جلالیِ shadcn، MUI v9 RTLِ رسمی.
- **SEO:** App Router (RSC) برای پلتفرمِ آموزشی.
- **پیوستگیِ طراحی:** ui-ux-pro-max همین حالا **Tailwind/shadcn** خروجی می‌دهد → توکن‌ها منتقل می‌شوند.
- **تحریم:** Next.js را روی VPSِ داخلی self-host می‌کنیم (وابستهٔ Vercel نمی‌شویم).
منبع: mui.com (RTL) · shahabyazdi.github.io/react-multi-date-picker · ui.shadcn.com (Jalali calendar).

---

## ۷. آفلاین و موبایل

### ۷.۱ آفلاین: PWA + Workbox v7 + Dexie.js (IndexedDB) — فاز۲
بازار نشان داد «ابری با فال‌بکِ آفلاین» برای شهرهای کوچک کم‌خدمت مانده. ولی **پایلوت‌های اولِ فاز۱ عمدتاً شهریِ آنلاین‌اند** → آفلاین‌first را به فاز۲ موکول می‌کنیم (هم‌زمان با حرکت به Next.js/Flutter). PWA تحریمِ Play Store را هم دور می‌زند.
منبع: wellally.tech (Workbox+Dexie offline) · nadinsoft.com (PWA برای ایران).

### ۷.۲ موبایل: Flutter — فاز۲+
اکوسیستمِ موبایلِ ایران **Flutter-first** است؛ کافه‌بازار **SDK رسمیِ Flutter (پولکی/Poolakey)** برای پرداختِ درون‌برنامه‌ای دارد؛ Myket هم AAB می‌پذیرد؛ RTL/فارسی **بومی**؛ ZarinPal از طریقِ WebView. (React Native Expo فقط اگر اشتراکِ کدِ web+mobile اولویت شد.)
منبع: developers.cafebazaar.ir (پولکی فلاتر) · appwrk.com (Flutter vs RN, Statista 2025).

---

## ۸. زیرساخت، میزبانی و DevOps (ویژهٔ ایران)

### ۸.۱ میزبانی: لیارا → آروان‌کلاد — قفل (هر دو داخلِ ایران)
- **شروع/MVP: لیارا** — بهترین DX، Postgres+Redis+ObjectStorage مدیریت‌شده در یک پنل، ارزان و قابل‌پیش‌بینی، بیشترین مستند/آینهٔ فارسی.
- **مقیاس: آروان‌کلاد** — **HA Managed PostgreSQL** (نودِ Standby، حیاتی برای دادهٔ بیمار)، CDNِ قوی، Cloud Container (k8s)، Object Storage.
- **چرا داخلِ ایران (نه AWS/GCP):** تحریم (حساب‌های خارجی بسته می‌شوند)؛ latency؛ و **اقامتِ دادهٔ سلامت** (الزامِ قانونیِ صریح تأیید نشد، ولی عملاً/ریسکی ضروری؛ اتصال به **سپاس** برای مراکزِ متصل به شبکهٔ بهداشت اجباری است).
منبع: liara.ir/pricing · news.arvancloud.ir/fa/dbaas-1404 · pmc.ncbi.nlm.nih.gov/articles/PMC11542451 (سپاس).

### ۸.۲ تحریم و DevOps — قفل
- **Docker Hub از IP ایران بلاک است (ژانویه ۲۰۲۵).** → آینهٔ ایرانی: `docker.arvancloud.ir`، `registry.docker.ir` (پارس‌پک)، آینهٔ لیارا. در `daemon.json`: `{"registry-mirrors": ["https://docker.arvancloud.ir"]}`.
- **PyPI/npm:** در دسترس؛ آینهٔ داخلی هم هست (لیارا/Runflare).
- **CI/CD:** **GitLab self-hosted روی VPSِ ایرانی** (یا HamGit) — بدونِ وابستگیِ تحریمی. جایگزین: GitHub برای کد + **self-hosted runner** روی زیرساختِ داخلی برای مرحلهٔ deploy.
- **رجیستریِ private image:** لیارا یا آروان‌کلاد.
منبع: github.com/Gozargah/Marzban/discussions/987 (بلاکِ Docker) · hamgit.ir · liara.ir/mirrors.

### ۸.۳ رصد (Observability)
Prometheus + Grafana (استانداردِ شرکت‌های ایرانی) + Sentry (خطاها). ردگیریِ هزینهٔ LLM به‌تفکیکِ ایستگاهِ پایپ‌لاین.

---

## ۹. LLM Gateway: AvalAI — قفل
دسترسی به مدل‌های بزرگ از طریقِ واسطِ **AvalAI** (Base URL سازگار با OpenAI) پشتِ یک **لایهٔ انتزاعِ داخلی** (Model Gateway در پایپ‌لاین) → عدمِ قفل به مدل یا واسط؛ مدلِ متفاوت/ارزان‌تر برای هر وظیفه.

---

## ۱۰. معماریِ کلان: Modular Monolith — قفل
- **یک Repository، چند Process:** پروسهٔ web (Django+ninja) + پروسهٔ worker (Celery/arq)، کدِ مشترک، دیپلویِ مجزا. **نه microservices** (Fowler: «با microservices شروع نکن»؛ ترندِ ۲۰۲۵–۲۶ بازگشت به modular monolith).
- **ادغامِ دو اپ:** `webapp` (حسابداری) و `specialist_clinic` در معماریِ جدید **ماژول‌های یک پروژهٔ واحد** می‌شوند (Auth مشترک، `patient` یک موجودیت، Postgres مشترک). این، تصمیمِ بازِ «ادغام یا جدا» را حل می‌کند: **ادغام، به‌شکلِ ماژول.** پلِ read-only فعلی یک workaroundِ دورانِ desktop بود.
- **سرویسِ پایپ‌لاینِ AI** سرویسِ جداست (FastAPI+arq) ولی همان Postgres را share می‌کند؛ اگر inference سنگین شد، مستقل می‌شود.

---

## ۱۱. نقشهٔ مهاجرت (Evolve، نه Rewrite)
۱. **اسکیمای Postgres** از `schema.sql`های موجود (دو اپ) + `tenant_id` همه‌جا برای RLS.
۲. **پورتِ adapterها:** SQL repos → Django ORM/migrations (یا raw SQL با psycopg).
۳. **حفظِ services/domain:** موتورِ ADA، followup، analytics، jalali/utils — تقریباً بی‌تغییر منتقل می‌شوند.
۴. **پورتِ routes:** Flask blueprints → django-ninja routers + viewها.
۵. **پورتِ UI:** قالب‌های بازطراحی‌شده → Django templates (Jinja2 در Django پشتیبانی می‌شود) + HTMX.
۶. **Auth:** منطقِ bcrypt/lockout موجود → Django auth (یا حفظِ سرویسِ فعلی).
۷. **deploy** روی لیارا (Docker از آینهٔ ایرانی).
> در حینِ پورت، اپِ Flaskِ فعلی برای **دمو/پایلوتِ زودهنگام** قابل‌استفاده می‌ماند (de-risk).

---

## ۱۲. Decision Log
| تاریخ | تصمیم | وضعیت |
|---|---|---|
| خرداد۱۴۰۵ | Python + Django/django-ninja؛ FastAPI+arq برای پایپ‌لاین | قفل |
| خرداد۱۴۰۵ | PostgreSQL+pgvector؛ Redis؛ Neo4j معوق | قفل |
| خرداد۱۴۰۵ | Multi-tenancy = RLS از روزِ اول | قفل |
| خرداد۱۴۰۵ | فرانت: HTMX (فاز۱) → Next.js/shadcn (فاز۲+) | قفل |
| خرداد۱۴۰۵ | موبایل Flutter + PWA؛ میزبانی لیارا→آروان | قفل |
| خرداد۱۴۰۵ | Modular Monolith؛ ادغامِ webapp+specialist به ماژول | قفل |

## ۱۳. موارد نیازمندِ تأیید (قبل از کد)
- [ ] ارائهٔ `pgvector` روی Postgresِ مدیریت‌شدهٔ لیارا/آروان (وگرنه self-managed).
- [ ] الزامِ حقوقیِ اقامتِ دادهٔ سلامت + اجباری‌بودنِ اتصالِ سپاس برای کلینیکِ خصوصیِ مستقل.
- [x] **feasibilityِ نسخهٔ الکترونیک — انجام شد** (`EPRESCRIPTION.md`): مسیرِ Aِ WebView به‌عنوان MVP، گواهی موازی. گردشِ کارِ MVP در `platform` ساخته و تأیید شد.
- [x] **DRF vs django-ninja — حل شد:** **django-ninja** انتخاب و در `platform` پیاده شد (Pydantic، سریع، schema-first).
- [x] **تأییدِ RLS روی Postgresِ واقعی — انجام شد:** دستورِ `manage.py verify_rls` روی pgvector/pg16 اجرا شد و **ایزولاسیونِ مستأجری اثبات شد** (deny-by-default بَرای GUCِ unset و خالی، تفکیکِ A/B، ردِ نوشتنِ بین‌مستأجری). **یک باگِ واقعیِ سیاست کشف و رفع شد:** کستِ مستقیمِ `::uuid` روی GUCِ خالی `''` خطا می‌داد → اصلاح به `nullif(current_setting(...), '')::uuid`.
