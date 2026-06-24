# ADR-0007 — هویتِ بیمار، مرزِ cross-schema، و طرحِ مدلِ دادهٔ یکپارچه

- **وضعیت:** پیشنهادی (Proposed) — ۱۴۰۵/۰۳/۳۱. نیازمندِ تصمیمِ مالک روی «پرسش‌های بازِ بلوکه‌کننده» (§۷).
- **تصمیم‌گیرنده:** مالک + `data-architect` + `principal-architect` (طرحِ همگرا، مبتنی بر کد).
- **مرتبط:** [ADR-0006](0006-cloud-unification-and-data-trust.md) (تصمیمِ ابریِ یکپارچه؛ این ADR لایهٔ دادهٔ آن را قطعی می‌کند) · [ADR-0002](0002-context-boundaries.md) (مالکیتِ هویت/وابستگیِ یک‌طرفه — این ADR آن را از فایل‌محور به schema-محور می‌برد) · [ADR-0005](0005-observation-canonical-concept.md) · [`migration_plan.md`](../migration_plan.md) (ARCH-01/02/04/08).

> **این ADR چه را قطعی می‌کند:** ADR-0006 «یک Postgres با دو schema» را تصمیم گرفت ولی **هویتِ بیمار را باز گذاشت** (§۱۴). اینجا آن را + مرزِ cross-schema + اولین برشِ ساخت‌شدنی + پاسخِ صریح به «آیا داریم زیادی زود می‌سازیم؟» قطعی می‌کنیم. **هیچ کدِ schema تا تصمیم‌های §۷ نوشته نمی‌شود.**

---

## ۱. زمینه

برای پلتفرمِ یکپارچه (ADR-0006) باید دو schemaِ SQLiteِ امروز (`webapp` حسابداری · `specialist_clinic` بالینی) در یک PostgreSQL ادغام شوند. سه پرسشِ بنیادی که ADR-0006 باز گذاشت و قبل از نوشتنِ هر schema باید قطعی شوند:
1. **هویتِ بیمار:** امروز حسابداری `patients` دارد (مالکِ دموگرافی، `webapp/.../schema.sql:26-42`) و تخصصی `patient_links` (آینهٔ keyed by `national_id` + `accounting_patient_id`، `specialist/.../schema.sql:19-35`). در یک DB واحد، رابطه چیست؟
2. **مرزِ Context در تک‌DB:** وقتی مرزِ «دو پروسهٔ جدا» از بین می‌رود، چه چیزی جلوی فروپاشیِ مونولیتِ ماژولار به Big Ball of Mud را می‌گیرد؟
3. **آیا زیادی زود می‌سازیم؟** (پرسشِ صریحِ مالک) — کدام بخشِ مدلِ داده الان لازم است و کدام باید موکول شود؟

---

## ۲. تصمیم

### ۲.۱ سه schema منطقی (نه دو)
`platform` (مشترکِ چندمستأجره) · `accounting` (مالکِ هویت + پول) · `clinical`. سه schema، **یک DB، یک Django project، چند Django app**. schemaِ سومِ `platform`، جداسازیِ permissionِ مجزای `accounting` (که ADR-0006 §۶ می‌خواهد) را ممکن می‌کند.

- **`platform`:** `tenants` (تنها جدولِ بدونِ `tenant_id`)، `users` (سوپرستِ دو اپ)، `settings`، `activity_logs`.
- **`accounting`:** `patients` (هویتِ canonical)، `invoices`/`visits`/`injections`/`procedures`/`consumables_ledger`/`invoice_item_payments`، تعرفه‌ها (`visit_tariffs`/…)، `medical_staff`، `payroll_settings`.
- **`clinical`:** `patient_links` (enrollment نازک)، `vital_readings`/`lab_results`/کاتالوگ‌ها، موتورِ قاعده/تعامل، `followup_*`/`appointments`/`prescriptions`/`engagement_*`/`sms_*`/`wallet_*`، لجرهای مرزی (`processed_invoices`/`doctor_visit_log`).

### ۲.۲ هویتِ بیمار = الگوی Registry + Enrollment (تصمیمِ محوری)
**`accounting.patients` منبعِ حقیقتِ canonicalِ دموگرافی می‌ماند** (همان نقشِ امروز). **`clinical.patient_links` به یک رکوردِ enrollment/link نازک تبدیل می‌شود** با FKِ واقعی به `accounting.patients(id)` — **نه ادغامِ کامل، نه کپیِ هویت.**

```sql
clinical.patient_links (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id   BIGINT NOT NULL DEFAULT 1,
  patient_id  BIGINT NOT NULL REFERENCES accounting.patients(id),  -- جایگزینِ accounting_patient_id: FK واقعی + NOT NULL
  -- فقط داده‌های صرفاً بالینی می‌مانند (که در accounting نیستند):
  wallet_balance, sms_opt_out, sms_consent, is_active, enrolled_by, enrolled_at, notes,
  UNIQUE(tenant_id, patient_id)
);
```

- **ستون‌های حذف‌شده از `patient_links`** (چون در `accounting.patients` تکرارند و امروز فقط mirror بودند): `national_id`, `full_name`, `phone_number`, `gender`, `birthdate`, `address`. دموگرافی از طریقِ FK خوانده می‌شود (همان کاری که پل امروز با کوئریِ زنده می‌کند).
- **دلیل:** مالکیتِ یک‌طرفهٔ `national_id` توسطِ حسابداری (ADR-0002) **حفظ** می‌شود؛ `accounting_patient_id` از یک عددِ شکننده به FKِ تضمین‌شده ارتقا می‌یابد.
- **گزینهٔ ردشده — ادغامِ کامل** (یک‌جدولِ `patients` واحد): مرزِ permissionِ مالی و read-onlyبودنِ مسیرِ بالینی و RLSِ per-domain را می‌شکند.

> ⚠️ **لجرهای snapshot دست‌نخورده می‌مانند:** `processed_invoices.national_id`/`.total_amount`، `doctor_visit_log.national_id`، `campaign_audience.accounting_patient_id` **کپیِ denormalizedِ عمدی** هستند (انتساب مستقل از تغییرِ منبع). در ETL **literal کپی می‌شوند، FK نمی‌شوند** — وگرنه id-remap آن‌ها را می‌شکند. (می‌توان FKِ کمکی هم اضافه کرد، ولی ستونِ snapshot حذف نشود.)

### ۲.۳ مرزِ cross-schema = دفاعِ سه‌لایه (یک‌طرفه: clinical → accounting)
وقتی مرزِ «دو پروسه» از بین می‌رود، مرز در **سه لایهٔ هم‌زمان** بازسازی می‌شود (هیچ‌کدام به‌تنهایی کافی نیست):

| لایه | ابزار | چه را قفل می‌کند |
|---|---|---|
| **DB / FK** | فقط `clinical.*` → `accounting.patients(id)`؛ هیچ FKِ `accounting → clinical` | یکپارچگیِ ارجاعیِ یک‌طرفه |
| **کد / import** | `import-linter`: `apps.clinical` می‌تواند `apps.accounting` را import کند، برعکس **هرگز** | نشتِ تدریجیِ منطق (تنها چیزی که مونولیت را از فروپاشی نگه می‌دارد) |
| **دسترسی** | **`AccountingReadPort`** (Protocol/ABCِ پایتونی، تنها دروازهٔ خواندنِ مالی از بالینی) + **GRANT فقط `SELECT`** روی schemaِ `accounting` برای رولِ DBِ بالینی + **fail-loud** | read-only + جداسازیِ مالی، حتی اگر کد اشتباه کند |

- **`AccountingReadPort` نه view است نه سرویسِ شبکه‌ای** — یک method-callِ درون‌پروسه‌ای که زیرش کوئریِ مستقیمِ Postgres روی schemaِ `accounting` می‌زند. (view در runtime مرز را نشان نمی‌دهد و قابلِ تستِ نگهبان نیست — درسِ `ext.py`؛ میکروسرویس در ADR-0006 §۳ ردشده.)
- **fail-loud اجباری** (ADR-0006 §۴.۲): توابعِ revenue در خطا `raise` می‌کنند نه `return []/0`؛ توابعِ display/lookup با `None`+log degrade می‌کنند.
- **GRANT فقط-SELECT** همان چیزی است که `mode=ro`ِ فایل امروز رایگان می‌داد؛ در Postgres باید صریح GRANT شود.
- **تستِ نگهبانِ سه‌لایه** (هم‌سبکِ نگهبانِ کارت در ADR-0004): (الف) اسکنِ استاتیک — هیچ SQLِ خامِ `clinical` رشتهٔ `accounting.` نداشته باشد جز از طریقِ Port؛ (ب) رولِ DB فقط SELECT؛ (ج) تستِ zero-write.

### ۲.۴ هویتِ tenant-aware + surrogate
- `UNIQUE(national_id)` → **`UNIQUE(tenant_id, national_id)`** روی `accounting.patients` (و کلیدِ مرکب روی `patient_links`). رجیستریِ مرکزیِ cross-tenant **موکول به T1**.
- یک **`uuid` surrogate** به `patients` افزوده می‌شود که در URL/توکنِ سمتِ بیمار به‌جای `national_id` می‌آید (پاسخِ ADR-0006 §۵: «national_id دیگر credential نیست»). `national_id` فقط درونِ مرزِ authenticated.
- `patients.id` PKِ سراسریِ یکتا می‌ماند (preserve-id با `setval`)؛ `accounting_patient_id`/`patient_links.patient_id` به همان لینک می‌زنند؛ `tenant_id` فقط برای ایزولاسیونِ آینده (T1)، نه برای join.

### ۲.۵ Observationِ کانونیک (ADR-0005) = دو جدول + یک VIEW
`vital_readings` و `lab_results` **دو جدولِ فیزیکیِ جدا می‌مانند** + یک `clinical.observations` **VIEW** کانونیک روی هر دو (UNION با کلیدِ مشترک `COALESCE(test_key, type)`). نه ادغامِ فیزیکی (ریسکِ پایین‌تر، افزایشی، صفر-خرابی؛ آیندهٔ Timescale: همین دو جدول hypertable می‌شوند، VIEW دست‌نخورده).

---

## ۳. معماریِ ساخت — اولین برشِ runnable + توالی

**اصل (ADR-0006 §۷): clinical اول، accounting آخر.** ترتیبِ topological بر مبنای FKهای واقعی:

- **برشِ ۰ (کمینه‌ترین هستهٔ اثبات‌پذیر):** `platform.tenants` → `platform.users` → `accounting.patients` (با `full_name` STORED + `UNIQUE(tenant_id, national_id)` + جدولِ نگاشتِ id) → `clinical.patient_links` (FK + GRANT فقط-SELECT). **روی همین می‌توان تستِ migration + تستِ نگهبانِ مرز زد — بدونِ ساختِ ۵۰ جدولِ دیگر.** این برش مرزِ cross-schema را اثبات می‌کند.
- **سپس (فاز B):** کلِ schemaِ `clinical` (۳۰+ جدول، همه FK به `patient_links`)؛ ۲۲۲ تستِ تخصصی روی Postgres سبز شوند (QA-16).
- **آخر (فاز C، پرریسک‌ترین):** بدنهٔ `accounting` (`invoices`/items/تعرفه‌ها) با golden-master (ARCH-12) + گیتِ سه-oracle (DATA-09) + literal-copy (DATA-07). **این برش تا عددِ DEVI-04 روی DBِ تولیدی قفل نمی‌شود.**

---

## ۴. ⭐ ضدِ over-engineering — پاسخِ صریح به «آیا زیادی زود می‌سازیم؟»

**نه — اگر این انضباط رعایت شود.** فقط **سه چیز** الان ساخته می‌شود (چون ارزانند الان، گران‌اند اگر دیر):
1. **`tenant_id NOT NULL DEFAULT 1` ساختاری** روی همهٔ جداول + UNIQUEهای مرکب. افزودنِ ستون الان رایگان؛ بعداً = migration روی میلیون‌ها ردیف.
2. **`AccountingReadPort` fail-loud + نگهبانِ سه‌لایه.** هستهٔ مرز، نه over-engineering.
3. **import-linter یک‌جهت.** یک فایلِ config؛ بدونش مونولیت می‌پوسد.

**هر چیزِ دیگر موکول به تریگرِ صریح** (هیچ‌چیزِ زودرسی ساخته نمی‌شود):

| موکول | چرا زودرس | تریگر |
|---|---|---|
| RLS policy + `WHERE tenant_id=?` + بازبینیِ خط‌به‌خط | تک‌مستأجر؛ افزودنِ WHERE الان false-safety و ریسکِ leak | **T1** (کلینیکِ دوم) |
| رجیستریِ مرکزیِ هویت | `UNIQUE(tenant_id, national_id)` ساده‌تر/امن‌تر | T1 |
| TimescaleDB (`vital_readings`/`lab_results`) | حجمِ تک‌کلینیکی نیاز ندارد | **T3** (کوئری >۵۰۰ms یا >۱۰M ردیف) |
| DB-per-tenant / sharding / per-tenant key | یک Postgresِ دو-schema کافی | رشدِ tenant |
| ORMِ کاملِ معنایی (~۵۹ `db.execute`) | Strangler؛ بازنویسیِ یکجا دیباگِ oracle را می‌شکند | پساٰ-cutover، repo-by-repo |
| رویدادِ معکوس `patient.registered` / Event Catalog v2 | هویت یک‌جهت از accounting می‌آید | **T2** (PWA بیمار) |
| پروتکلِ syncِ آفلاینِ نوشتنی | تصادمِ id، LWWِ خطرناکِ پول | T2 / G-B=(ج) |

---

## ۵. ضمیمه A — جدولِ قواعدِ ترجمه (SQLite → Postgres)

| SQLite (مبنا) | Postgres | یادداشت |
|---|---|---|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGINT GENERATED ALWAYS AS IDENTITY` | BIGINT برای رشد |
| `password_hash BLOB` | `BYTEA` | bcrypt بایتِ خام |
| `full_name … GENERATED … VIRTUAL` (`webapp:30`) | `GENERATED … STORED` | Postgres فقط STORED دارد — **در برشِ ۰ لازم** |
| `REAL` (همهٔ پول) | `NUMERIC(14, ?)` | مقیاس = **تصمیمِ مالک §۷**؛ literal کپی، بدونِ بازمحاسبه |
| `DEFAULT (datetime('now','+3h','+30m'))` | `TIMESTAMPTZ DEFAULT now()` + `Asia/Tehran` | لحظه‌ها؛ `iran_now()` سمتِ app معتبر |
| `work_date/onset_date/... TEXT` (تقویمی) | `DATE` | **بدونِ timezone-shift** |
| `INSERT OR IGNORE` | `INSERT … ON CONFLICT DO NOTHING` | نیازِ UNIQUE/PK صریح |
| `UNIQUE(x)` | `UNIQUE(tenant_id, x)` | همه مرکب |
| `is_paid/is_active INTEGER` | `SMALLINT` (فاز ۱)، `BOOLEAN` بعداً | کدِ زیادی `=1` مقایسه می‌کند (`accounting_bridge.py:353`) → تبدیلِ BOOLEAN نیازِ بازبینیِ هر کوئری |
| `*_json TEXT` (`trigger_json`, `items`) | `JSONB` | کوئری‌پذیر |
| FK implicit | FK صریح + `ON DELETE RESTRICT` | هیچ cascade روی مالی |

## ضمیمه C — گرافِ وابستگیِ schema (DAG واقعیِ سه‌سطحی)

وابستگیِ FKِ واقعی (نه مفهومی) سه‌سطحی است، نه دو‌سطحی:

```
platform
  ^          ^
  |          |
accounting  clinical
  ^
  |
clinical
```

به‌صورتِ صریح:

| فرزند | والد | نمونه FK واقعی |
|---|---|---|
| `accounting` → `platform` | accounting.patients.tenant_id → platform.tenants(id) | slice0 |
| `accounting` → `platform` | accounting.activity_logs.user_id → platform.users(tenant_id, id) | slice3 |
| `clinical` → `platform` | clinical.patient_links.tenant_id → platform.tenants(id) | slice0 |
| `clinical` → `platform` | clinical.activity_logs.user_id → platform.users(tenant_id, id) | slice2 |
| `clinical` → `platform` | clinical.prescriptions.prescriber_user_id → platform.users(tenant_id, id) | slice2b |
| `clinical` → `accounting` | clinical.patient_links(tenant_id, patient_id) → accounting.patients(tenant_id, id) | slice0 |
| `clinical` → `accounting` | clinical.processed_invoices(tenant_id, accounting_invoice_id) → accounting.invoices(tenant_id, id) | slice4 |
| `clinical` → `accounting` | clinical.campaign_audience(tenant_id, accounting_patient_id) → accounting.patients(tenant_id, id) | slice4 |

**قاعدهٔ یک‌طرفه (اجباری):**
- هیچ FKی از `accounting` به `clinical` وجود ندارد و نباید وجود داشته باشد.
- هیچ FKی از `platform` به `accounting` یا `clinical` وجود ندارد.
- `platform` برگِ ریشه است (والدِ هر دو schema)؛ `clinical` و `accounting` هر دو به آن FK می‌زنند.
- این DAG تستِ نگهبانِ `test_no_reverse_fk_from_accounting_to_clinical` در `tests/test_pg_schema.py` آن را اثبات می‌کند.

## ضمیمه B — سه تعریفِ درآمد (literal حفظ شوند)
۱) **raw** `visits.price+injections.total_price+procedures.price` (closed) — `accounting_bridge.py:253-276`. ۲) **total_amount** `Σ patient_share` — `invoices_repo.py:283-286`. ۳) **collected** `Σ(is_paid=1)` — `accounting_bridge.py:347-361`. ستون‌های پولیِ ذخیره‌شده **بیت‌به‌بیت** مهاجرت می‌شوند؛ `update_invoice_totals` در ETL **صدا زده نمی‌شود**.

---

## ۶. پیامدها
**+** مرزِ Context structural و قابلِ‌تست (نه فایل‌محورِ شکننده) · هویتِ بیمارِ تضمین‌شده با FK · آمادهٔ T1 بدونِ هزینهٔ زودرس · پاسخِ روشن به over-engineering. **−** نیازِ انضباطِ import-linter + GRANT؛ id-remap بحرانی (ترتیبِ اجباری: patients اول)؛ تصمیم‌های §۷ بلوکه‌کننده‌اند.

---

## ۷. 🔴 پرسش‌های بازِ بلوکه‌کننده (پیش از نوشتنِ هر schema)
1. **واحدِ پول: ریال یا تومان؟** + مقیاسِ `NUMERIC(14,0|2)` + سیاستِ rounding. کد ناهمگون است (`wallet_balance` تومان، تعرفه‌ها نامشخص). **بلوکه‌کنندهٔ کلِ schemaِ پول.**
2. **برخوردِ نامِ `users`/`settings`/`activity_logs`** بین دو اپ: سوپرستِ واحد + ستونِ `app` (توصیه)، یا دو جدولِ per-app؟
3. **مدلِ هویت** (§۲.۲/۲.۴) را تأیید می‌کنی؟ `UNIQUE(tenant_id, national_id)` یا رجیستریِ مرکزی؟
4. **manual-enroll بالینی:** بیمارِ تخصصیِ بدونِ رکوردِ حسابداری — آیا upsert به `accounting.patients` مجاز است (نقضِ احتمالیِ read-only)، یا `patient_links.patient_id` باید nullable بماند؟
5. **DEVI-04 روی DBِ تولیدی** (نه seed) — برشِ accounting تا این عدد قفل نمی‌شود.
6. **کلِ تاریخچه مهاجرت شود یا از go-live؟**

---

## مبنا (ارجاعِ کد — راستی‌آزمایی‌شده توسطِ data + architect)
`webapp/.../schema.sql:26-42` (patients, full_name VIRTUAL, national_id UNIQUE)، `:59-79,82-104,144-190,247-256` (invoices/items/پول REAL) · `specialist/.../schema.sql:19-35` (patient_links mirror, accounting_patient_id:22)، `:107-134` (vital/lab، ADR-0005)، `:675-711` (لجرهای snapshot) · `accounting_bridge.py:253-276,347-361` (raw/collected) · `invoices_repo.py:278-292,113-136` (total_amount/patient_share) · `webapp/core.py:8-62` + `manager.py:2388,2971` (ALTERهای inline — baseline diff) · ADR-0002/0005/0006.
