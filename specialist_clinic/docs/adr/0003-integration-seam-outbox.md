# ADR-0003 — درزِ یکپارچگی: Transactional Outbox (مسیر A) + مصرف‌کنندهٔ read-only

- **وضعیت:** پذیرفته‌شده برای مسیر A؛ چند میکرو-تصمیمِ باز (پایین) — ۱۴۰۵/۰۳/۳۰ (۲۰۲۶-۰۶-۲۰)
- **ورودی:** `principal-architect` + `data-architect` + `backend-dev-advisor` + `security-privacy-advisor`
- **مرتبط:** [ADR-0002](0002-context-boundaries.md) · [Event Catalog v1](../architecture/event-catalog-v1.md)

## زمینه
نیاز داریم تریگرهای **«یک‌بار به‌ازای هر فاکتورِ بسته‌شده»** (پیامکِ تشکر، دعوتِ پروسیجر) از حسابداری به تخصصی برسند. حقایقِ کشف‌شده از کد:
- پل **read-only** است (`accounting_bridge.py` با `mode=ro`).
- `close_invoice` (`webapp/src/adapters/sqlite/invoices_repo.py:254-276`) **اتمیک نیست**: `update_invoice_totals` خودش commit می‌کند (~:292)، و `_ensure_shift_staff` (`procedures_repo.py:37`) هم زودتر commit می‌زند → «تراکنشِ کسب‌وکارِ واحد» عملاً وجود ندارد.
- **WAL روی `clinic_new.db` روشن نیست** (journalِ پیش‌فرضِ DELETE).
- تخصصی الگوی idempotent-ledgerِ آماده دارد (`engagement_dispatch` با UNIQUE + `INSERT OR IGNORE`، `engagement_repo.py:98-104`)؛ scheduler هر ۲ دقیقه tick می‌زند (`scheduler.py`).

## تصمیم
**Outbox pattern، مسیر A (inline best-effort + sweeper به‌عنوان safety-net).** نه مسیر B (تراکنشِ واحد — به‌خاطرِ pre-commitها اتمیسیتیِ توهمی می‌دهد و مسیرِ پولیِ تولیدی را دستکاری می‌کند)، نه polling صرف (معناشناسیِ «یک‌بار» نمی‌دهد)، نه CDC (over-engineering برای SQLite).

**سمتِ حسابداری (افزایشی، صفر تغییرِ جداولِ موجود):**
- جدولِ `invoice_outbox(id PK AUTOINCREMENT, invoice_id UNIQUE, national_id, work_date, total_amount, created_at)` با `CREATE TABLE IF NOT EXISTS` در `webapp` core migration.
- **inline:** بعد از `db.commit()` موجودِ `close_invoice` (`:275`)، یک `INSERT OR IGNORE INTO invoice_outbox` (best-effort، در `try/except`).
- **sweeper:** دوره‌ای فاکتورهای `status='closed'` بدونِ ردیفِ outbox را backfill می‌کند → **at-least-once بدونِ بازنویسیِ منطقِ پولی.**
- **WAL را روشن کن** (`PRAGMA journal_mode=WAL`، idempotent) برای هم‌زمانیِ خواندنِ پل (جلوگیری از `SQLITE_BUSY`).

**سمتِ تخصصی (هیچ نوشتنی در حسابداری):**
- مصرف‌کننده در `scheduler._tick()` (بعد از `_run_engagement()`).
- **cursor در `specialist.db`** (جدولِ `accounting_event_cursor` یا کلیدِ `settings`).
- خواندنِ outbox از پلِ read-only (`accounting_bridge.fetch_outbox_since(last_id)`, `... WHERE id > ? ORDER BY id LIMIT 100`).
- **اعمالِ idempotent** با لجرِ `processed_invoices(outbox_id UNIQUE, patient_link_id, applied_at)` و `INSERT OR IGNORE` (همان الگوی `engagement_dispatch`).
- **batch lookup** بیماران با `national_id IN (...)`؛ ردیفِ `national_id IS NULL` نادیده.
- **Fail-loud:** اگر فایلِ حسابداری قفل بود، cursor را **جلو نبر** و در tick بعد retry کن (برخلافِ بلعِ خطای فعلیِ پل).

**صفِ زندهٔ پزشک** = خواندنِ زندهٔ فاکتورهای **باز** از پل در زمانِ بارگذاریِ صفحه (نه رویداد/Outbox).

## ⚠️ تجدیدنظرِ پیش از اجرا — D1(Outbox) → D3+ (صفر نوشتن در حسابداری) · ۱۴۰۵/۰۳/۳۰
پیش از نوشتنِ اولین بایت، تیم (`data-architect` + `backend-dev-advisor`) محک زد و **هر دو D3+ را توصیه کردند**: چون «فاکتورِ بسته‌شده» یک **حالتِ ردیفیِ ماندگار و تغییرناپذیر** است (در کدِ `webapp` هیچ مسیرِ reopen/delete نیست — `invoices_repo.py:269-273` فقط `open→closed`)، نوشتنِ Outbox/hook/WAL/daemon در حسابداریِ تولیدی **لازم نیست**.

**تصمیمِ نهاییِ فاز ۱ = D3+ (مصرف‌کنندهٔ فقط‌خواندنی، صفر نوشتن در حسابداری):**
- مصرف‌کننده در `scheduler._tick` فاکتورهای بستهٔ اخیر را از پلِ read-only می‌خواند.
- **cursor = `MAX(accounting_invoice_id)` در `specialist.db`** (نه جدولِ جدا).
- **کوئریِ صحیح:** `WHERE status='closed' AND (i.id > :last_id OR i.closed_at >= :floor_date)` — شاخهٔ `id>cursor` برای حالتِ پایدارِ ارزان (ایندکسِ PK)، شاخهٔ `closed_at>=floor` (پیش‌فرض ۳۰ روز) برای گرفتنِ فاکتورهای **دیربسته‌شده با id کوچک**. لجرِ idempotent تکراری‌ها را خنثی می‌کند.
- **لجر:** `processed_invoices(accounting_invoice_id UNIQUE)` + `INSERT OR IGNORE`؛ `national_id` تهی → `status='pending_link'` (drop نمی‌شود).
- **fail-loud:** متدِ bridgeِ نو خطا را نمی‌بلعد؛ مصرف‌کننده با try/except می‌گیرد و در خطا cursor را **جلو نمی‌برد**.
- صفر تغییر در `webapp`. WAL/ایندکسِ حسابداری **لازم نیست** (پل با busy_timeout می‌خواند؛ روی specialist.db یک `PRAGMA busy_timeout=3000` افزوده می‌شود).

**Outbox (D1) برای آینده محفوظ:** فقط وقتی رویدادهای **گذرا** (reopen/حذفِ آیتم/تسویهٔ معوق) لازم شوند که حالتِ ماندگار ندارند. تخمینِ D3+: **~۱–۱.۵ روز** (در برابر ۲.۵–۳ روزِ D1 + ریسکِ تولید).

## گزینه‌های بررسی‌شده
- **مسیر B (تراکنشِ دربرگیرنده):** رد — اتمیسیتیِ واقعی به‌خاطرِ pre-commitِ `_ensure_shift_staff` حاصل نمی‌شود؛ لمسِ مسیرِ پولیِ تولیدی = ریسکِ بالاتر.
- **polling صرف:** رد — برای رویدادِ گذرا «یک‌بار» نمی‌دهد.
- **CDC/triggerِ DB:** رد فعلاً — over-engineering برای SQLite؛ هنگامِ Postgres بازنگری (همان Event Catalog آن‌جا با `SELECT … FOR UPDATE SKIP LOCKED`/`LISTEN-NOTIFY` پیاده می‌شود).

## پیامدها
- ✅ at-least-once + مصرف‌کنندهٔ idempotent؛ پل read-only دست‌نخورده؛ منطقِ پولی بازنویسی نمی‌شود؛ به Postgres مستقیماً منتقل می‌شود.
- ✅ ساده‌سازیِ مهم (`backend-dev-advisor`): `procedure.recorded` رویدادِ جدا لازم ندارد — sweeper روی فاکتورِ بسته همهٔ آیتم‌ها (ویزیت/تزریق/پروسیجر) را می‌برد.
- ⚠️ تخمینِ زحمت: **~۳.۷۵ روزِ توسعه** (جدول+sweeper+WAL سمتِ webapp؛ consumer+cursor+ledger سمتِ تخصصی؛ تستِ E2E).

## پروتکلِ ایمنیِ دیتا و دیپلوی (نگرانیِ شمارهٔ ۱ مالک)
- **فقط افزایشی:** هیچ `UPDATE/DELETE` روی جداولِ مالیِ موجود؛ فقط `INSERT` به جدولِ نو؛ صفر تغییرِ ستونی.
- **تست روی کپیِ دیتای واقعی:** `PRAGMA integrity_check` + شمارش/checksumِ هر جدولِ موجود **قبل/بعد باید یکسان** بماند؛ اجرای دوبارهٔ migration = صفر تغییر؛ بستنِ فاکتور = دقیقاً یک ردیفِ outbox، بستنِ دوباره = صفر.
- **بکاپ قبل از هر دیپلوی** (کپیِ فایلِ `clinic_new.db`).
- **گاتچای WAL/git:** قبل از کامیتِ `clinic_new.db` یک `PRAGMA wal_checkpoint(TRUNCATE)` بزن (وگرنه فایلِ کامیت‌شده ناقص است)؛ `-wal`/`-shm` در `.gitignore`؛ PyInstaller `datas` به‌روز شود.
- **گامِ staging** پیش از تعویضِ نسخهٔ لوکالِ درمانگاه.
- **حریمِ `national_id`:** داخلِ outbox لازم است (کلیدِ پیوند)، ولی **فقط داخلی** — در لاگِ ممیزی کامل ثبت نشود، در نمای بیمار نیاید، و در دنیای آیندهٔ چندمستأجره با `tenant_id`/surrogate همراه شود.

## میکرو-تصمیم‌های باز (نیازِ تأییدِ مالک/تیم)
1. جدولِ outbox در `clinic_new.db` (با سیاستِ purge/retention) **یا** یک DBِ جانبیِ غیرکامیت‌شده (git را تمیز نگه می‌دارد). پیشنهاد: درون‌DB + purge فعلاً.
2. v1 فقط `invoice.closed` یا `invoice.opened` هم لازم است؟ (پیشنهاد: فقط `closed`؛ صف از خواندنِ زنده.)
3. inline+sweeper یا فقط sweeper؟ (پیشنهاد: هر دو — latencyِ کم + تورِ ایمنی.)
