# مدلِ داده و چندمستأجری (Data Model & Multi-Tenancy)

> **نسخه ۰.۱ — خرداد ۱۴۰۵ — زنده.** بنیانِ پورتِ Postgres + اسکلتِ Django. مرجع: [`TECH_STACK.md`](TECH_STACK.md) · [`FEATURES.md`](FEATURES.md).
> طراحی‌شده با خواندنِ اسکیماهای واقعیِ هر دو اپ (`specialist_clinic` + `webapp`). اصلِ **Evolve نه Rewrite**: همان موجودیت‌ها، تنها tenant-aware و Postgres-ای.

## ۱. اصولِ طراحی (Conventions)
- **کلیدِ اصلی: UUID** (`gen_random_uuid()`) به‌جای `INTEGER AUTOINCREMENT` — برای multi-tenant، جلوگیری از enumerationِ بین‌مستأجری، و توزیع‌پذیری.
- **`clinic_id UUID NOT NULL` روی هر جدولِ دامنه** + **RLS** (بخش ۳). این ستون **leading column** در ایندکس‌های composite است.
- **زمان: `timestamptz` (ذخیرهٔ UTC)** نه TEXTِ تهران. نمایش با `Asia/Tehran` + تبدیلِ جلالی در لایهٔ اپ. (بهبود نسبت به «ذخیرهٔ محلیِ تهران» فعلی.)
- **تاریخِ روز (بدونِ ساعت): `DATE` (میلادی)**، نمایشِ جلالی در UI (مثلِ `onset_date`, `start_date`).
- **پول: `BIGINT` (ریال/تومان، صحیح)** نه `REAL` (اجتنابِ خطای ممیز شناور در مالی).
- **append-only برای حساس:** `wallet_transaction`, `suggestion_log`, `activity_log`, `prescription` تغییرناپذیر/نسخه‌دار.
- **کاتالوگ‌های بالینی (سراسری + override):** `clinical_indicator`, `clinical_rule`, `flag_catalog`, `drug_class`, `condition` به‌صورتِ **پیش‌فرضِ سراسری** seed می‌شوند، و کلینیک می‌تواند per-tenant ویرایش/override کند (مثلِ رفتارِ فعلیِ `clinical_rules_seed`).

## ۲. ماژول‌ها (مرزِ schemaها در modular monolith)
| ماژول | مسئولیت |
|---|---|
| `identity` | کلینیک (tenant)، کاربر، نقش، شیفت |
| `billing` | اشتراک، پلن، پرداخت (ZarinPal) |
| `patients` | بیمارِ یکپارچه |
| `chronic` | پروندهٔ مزمن: شاخص، دارو، آزمایش، نوبت، پیگیری، فلگ، کیف‌پول، موتورِ ADA |
| `accounting` | فاکتور، ویزیت، تزریق، کارِ عملی، مصرفی، حقوق، تعرفه |
| `rx` | نسخهٔ الکترونیک + رفرنسِ دارو + لاگِ اتصالِ بیمه |
| `messaging` | قالب/کمپین/پیامِ SMS |
| `platform` | لاگِ فعالیت، تنظیماتِ per-tenant |

## ۳. الگوی چندمستأجری: PostgreSQL RLS
هر جدولِ دامنه `clinic_id` دارد. اپ در ابتدای هر request زمینهٔ مستأجر را ست می‌کند:
```sql
-- در middleware، بعد از احراز هویت:
SET LOCAL app.current_clinic = '<clinic_uuid>';

-- روی هر جدول:
ALTER TABLE patient ENABLE ROW LEVEL SECURITY;
ALTER TABLE patient FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON patient
  USING (clinic_id = current_setting('app.current_clinic', true)::uuid)
  WITH CHECK (clinic_id = current_setting('app.current_clinic', true)::uuid);
```
- **deny-by-default:** اگر `app.current_clinic` ست نشود، هیچ ردیفی برنمی‌گردد.
- **تستِ CI اجباری:** کوئریِ بدونِ زمینه = صفر ردیف؛ کوئری با زمینهٔ A هرگز دادهٔ B را نبیند.
- اتصالِ DB با نقشِ غیرـ`BYPASSRLS`؛ کارهای پس‌زمینه (worker) صراحتاً `clinic_id` را ست می‌کنند.
- **مهاجرتِ بعدی:** اگر مشتریِ enterprise ایزولاسیونِ فیزیکی خواست → schema-per-tenant (چون `clinic_id` از روزِ اول همه‌جا هست، کم‌هزینه).

## ۴. جداولِ جدید (SaaS + نسخه) — DDL هسته
```sql
-- ── identity ──
CREATE TABLE clinic (                      -- tenant
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL DEFAULT 'trial',     -- trial|active|suspended|cancelled
  province TEXT, city TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE app_user (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id UUID NOT NULL REFERENCES clinic(id),
  username TEXT NOT NULL,
  password_hash BYTEA NOT NULL,             -- bcrypt (منطقِ موجود حفظ)
  role TEXT NOT NULL,                       -- clinic_manager|doctor|reception|nurse
  full_name TEXT,
  medical_license_no TEXT,                  -- شمارهٔ نظام‌پزشکی (گیتِ بخش‌های بالینی)
  is_active BOOLEAN NOT NULL DEFAULT true,
  failed_attempts INT NOT NULL DEFAULT 0,   -- قفلِ ۱۵دقیقه بعد ۵ تلاش (منطقِ موجود)
  locked_until TIMESTAMPTZ,
  last_login TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (clinic_id, username)
);

-- ── billing ──
CREATE TABLE plan (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code TEXT UNIQUE NOT NULL,                -- free|clinic|multi
  name TEXT NOT NULL, price_rial BIGINT NOT NULL,
  period TEXT NOT NULL DEFAULT 'yearly',    -- monthly|yearly
  features_json JSONB, is_active BOOLEAN NOT NULL DEFAULT true
);
CREATE TABLE subscription (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id UUID NOT NULL REFERENCES clinic(id),
  plan_id UUID NOT NULL REFERENCES plan(id),
  status TEXT NOT NULL DEFAULT 'active',    -- active|past_due|cancelled
  period_start DATE, period_end DATE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE payment (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id UUID NOT NULL REFERENCES clinic(id),
  subscription_id UUID REFERENCES subscription(id),
  amount_rial BIGINT NOT NULL,
  gateway TEXT NOT NULL DEFAULT 'zarinpal',
  authority TEXT, ref_id TEXT,
  status TEXT NOT NULL DEFAULT 'pending',   -- pending|paid|failed
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── patients (یکپارچهٔ patients + patient_links) ──
CREATE TABLE patient (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id UUID NOT NULL REFERENCES clinic(id),
  national_id TEXT,
  first_name TEXT, last_name TEXT,
  full_name TEXT GENERATED ALWAYS AS (coalesce(first_name,'')||' '||coalesce(last_name,'')) STORED,
  phone_number TEXT, gender TEXT, birthdate DATE, address TEXT,
  insurance_type TEXT, insurance_expiry DATE, is_foreign BOOLEAN DEFAULT false,
  wallet_balance BIGINT NOT NULL DEFAULT 0,    -- از patient_links
  is_active BOOLEAN NOT NULL DEFAULT true,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (clinic_id, national_id)              -- یکتا در سطحِ کلینیک
);
-- پلِ read-only فعلی (accounting_bridge) منسوخ می‌شود: بیمار یک موجودیت است.

-- ── rx (نسخهٔ الکترونیک) ──
CREATE TABLE drug (                          -- رفرنسِ ژنریک (دیتاستِ سورس‌شونده)
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  generic_name TEXT NOT NULL, irc_code TEXT, atc_code TEXT,
  form TEXT, strength TEXT, is_active BOOLEAN DEFAULT true
);
CREATE TABLE prescription (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id UUID NOT NULL REFERENCES clinic(id),
  patient_id UUID NOT NULL REFERENCES patient(id),
  doctor_id UUID NOT NULL REFERENCES app_user(id),
  insurer TEXT NOT NULL,                     -- tamin|ihio|armed
  status TEXT NOT NULL DEFAULT 'draft',      -- draft|submitted|registered|failed
  tracking_code TEXT,                        -- کدِ رهگیریِ بیمه
  channel TEXT NOT NULL DEFAULT 'webview',   -- webview|api (Epic 1 مسیر A→B)
  issued_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE prescription_item (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id UUID NOT NULL REFERENCES clinic(id),
  prescription_id UUID NOT NULL REFERENCES prescription(id),
  kind TEXT NOT NULL,                        -- drug|paraclinical|service
  drug_id UUID REFERENCES drug(id), item_name TEXT,
  dose TEXT, count INT, instruction TEXT
);
CREATE TABLE insurer_log (                   -- ردگیریِ اتصال (WebView/API)
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id UUID NOT NULL, prescription_id UUID,
  insurer TEXT, action TEXT, status TEXT, payload JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## ۵. نگاشتِ جداولِ موجود → مدلِ یکپارچه (همه + `clinic_id`)
| منبع (SQLite) | جدولِ جدید | تغییراتِ کلیدی |
|---|---|---|
| `specialist.patient_links` + `webapp.patients` | **`patient`** | ادغام؛ UUID؛ `accounting_patient_id` حذف؛ national_id یکتا per-clinic |
| `webapp.medical_staff` (+ `users`) | **`app_user`** | ادغامِ هویت؛ نقش‌ها یکپارچه؛ `medical_license_no` |
| `wallet_transactions` | `wallet_transaction` | پول BIGINT |
| `conditions` / `patient_conditions` | `condition` / `patient_condition` | condition کاتالوگِ سراسری+seed |
| `patient_medications` / `medication_events` | `patient_medication` / `medication_event` | `drug_class` حفظ؛ event تایم‌لاین |
| `allergies` | `allergy` | — |
| `vital_readings` | `vital_reading` | value `NUMERIC`؛ measured_at `timestamptz` |
| `lab_results` | `lab_result` | — |
| `appointments` | `appointment` | `scheduled_at timestamptz` |
| `followup_tasks` (+`source_rule`) | `followup_task` | منطقِ due-only و dedup حفظ |
| `care_protocols` | `care_protocol` | + پروتکلِ قابلِ‌تعریفِ پزشک (Epic 3) |
| `clinical_indicators` | `clinical_indicator` | سراسری+override per-clinic |
| `clinical_rules` (~۵۷ قاعده) | `clinical_rule` | `trigger_json`→`JSONB`؛ seed حفظ |
| `flag_catalog` / `patient_flags` | `flag_catalog` / `patient_flag` | — |
| `drug_classes` | `drug_class` | کاتالوگِ سراسری |
| `suggestion_log` | `suggestion_log` | append-only، accountability |
| `sms_templates`/`sms_campaigns`/`sms_messages` | `sms_template`/`sms_campaign`/`sms_message` | per-tenant کلیدِ مدیانا |
| `webapp.invoices`/`visits`/`visit_items` | `invoice`/`visit`/`visit_item` | پول BIGINT؛ `work_date`+`shift` حفظ |
| `injections`/`procedures`/`consumables_ledger` | `injection`/`procedure`/`consumable_ledger` | `work_date`+`shift` حفظ |
| `invoice_item_payments` | `invoice_item_payment` | — |
| تعرفه‌ها (`*_tariffs`, `services`, `nursing_services`, …) | کاتالوگ‌های per-tenant | — |
| `payroll_settings` | `payroll_setting` | — |
| `user_active_shift` | `user_shift` | شیفتِ دستی حفظ (مرزِ خودکار ندارد) |
| `settings` (هر دو) | `clinic_setting` | per-tenant key/value (JSONB value) |
| `activity_logs` (هر دو) | `activity_log` | per-tenant، append-only |

## ۶. ایندکس‌گذاری (multi-tenant)
- هر ایندکسِ پرکاربرد با `clinic_id` به‌عنوانِ **ستونِ اول**: مثلِ `(clinic_id, national_id)`, `(clinic_id, patient_id, measured_at DESC)` روی `vital_reading`, `(clinic_id, status, due_date)` روی `followup_task`, `(clinic_id, work_date, shift)` روی `invoice`.
- `pgvector` (فاز۲) روی جداولِ دانش، نه این ماژول‌ها.

## ۷. نکاتِ مهاجرت (ETL از SQLite)
1. اسکریپتِ ETL: برای هر کلینیکِ موجود یک `clinic` ساخته، `clinic_id` تزریق می‌شود (دیتای فعلی = یک tenant).
2. ادغامِ `patients` و `patient_links` با کلیدِ `national_id` (دادهٔ مزمن به patientِ یکپارچه FK می‌خورد).
3. تبدیلِ TIMESTAMPِ تهرانی → `timestamptz` UTC (کسرِ +۳:۳۰).
4. `REAL` پول → `BIGINT` (گِرد به ریال).
5. seedهای بالینی (indicators/rules/flags/drug_classes) از `clinical_rules_seed` به‌صورتِ سراسری بازتولید.

## ۸. تصمیماتِ باز
- [ ] منبعِ دیتاستِ **`drug`** (ژنریک + IRC): از دارویاب/تیتک/فهرستِ رسمی — برای کمپوزرِ نسخه (Epic 1).
- [ ] کاربرِ چندکلینیکی (یک پزشک در چند کلینیک): فعلاً `clinic_id` روی user (تک‌کلینیک)؛ membership جدا در آینده.
- [ ] نگه‌داشتنِ `clinical_rule.trigger_json` به‌صورت `JSONB` (کوئری‌پذیر) — تأیید با موتورِ `rule_engine`.
- [ ] دامنهٔ accounting در فاز۱: کامل یا سبک؟ (تصمیمِ باز در [`FEATURES.md`](FEATURES.md)).
