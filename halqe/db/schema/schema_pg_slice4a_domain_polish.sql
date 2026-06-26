-- ============================================================================
-- پلتفرمِ یکپارچه — Batch 4a (domain polish — low-risk, mostly additive)
-- PostgreSQL 13+
--
-- پیش‌نیاز: برش‌های ۰ / ۲_clinical / ۲b_fk_catalog / ۳_accounting / ۴_boundary
--           پیش از این فایل اعمال شده باشند.
--
-- تغییرات:
--   ۱) updated_at + auto-update trigger روی جداولِ MUTABLE (که status/lifecycle
--      دارند و فاقدِ updated_at بودند):
--      * clinical: appointments, followup_tasks, patient_conditions, patient_medications,
--                  sms_campaigns
--      * accounting: invoices
--      تابعِ set_updated_at() یک‌بار per-schema (clinical + accounting)؛ triggerها
--      idempotent (DROP TRIGGER IF EXISTS → CREATE TRIGGER).
--
--   ۲) observations VIEW: namespace obs_key
--      * vital rows:   'vital:'||type
--      * lab rows:     'lab:'||COALESCE(test_key, test_name)
--      این VIEW جدید/unused است — تغییرِ obs_key امن است.
--
--   ۳) clinical.allergies.severity CHECK
--      CHECK (severity IS NULL OR severity IN ('mild','moderate','severe','anaphylaxis'))
--
--   ۴) accounting.procedures.performer_id
--      * FOREIGN KEY مرکب (tenant_id, performer_id) → accounting.medical_staff(tenant_id, id)
--        ON DELETE SET NULL (performer_id nullable → SET NULL)
--      * performer_type CHECK موجود حفظ می‌شود (ستون‌ها حذف نمی‌شوند)
--
-- idempotency:
--   * ADD COLUMN IF NOT EXISTS (Pg13+) برای updated_at
--   * CREATE OR REPLACE FUNCTION برای set_updated_at()
--   * DROP TRIGGER IF EXISTS → CREATE TRIGGER برای triggerها
--   * DO $$ IF NOT EXISTS (pg_constraint) $$ برای CHECKها و FK
-- ============================================================================

-- ###########################################################################
-- ۱) updated_at + auto-update triggers
-- ###########################################################################

-- ---------------------------------------------------------------------------
-- تابعِ set_updated_at() برای schema clinical
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION clinical.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

-- ---------------------------------------------------------------------------
-- تابعِ set_updated_at() برای schema accounting
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION accounting.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

-- ---------------------------------------------------------------------------
-- clinical.appointments — اضافهٔ updated_at + trigger
-- ---------------------------------------------------------------------------
ALTER TABLE clinical.appointments
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

DROP TRIGGER IF EXISTS trg_appointments_updated_at ON clinical.appointments;
CREATE TRIGGER trg_appointments_updated_at
    BEFORE UPDATE ON clinical.appointments
    FOR EACH ROW EXECUTE FUNCTION clinical.set_updated_at();

-- ---------------------------------------------------------------------------
-- clinical.followup_tasks — اضافهٔ updated_at + trigger
-- ---------------------------------------------------------------------------
ALTER TABLE clinical.followup_tasks
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

DROP TRIGGER IF EXISTS trg_followup_tasks_updated_at ON clinical.followup_tasks;
CREATE TRIGGER trg_followup_tasks_updated_at
    BEFORE UPDATE ON clinical.followup_tasks
    FOR EACH ROW EXECUTE FUNCTION clinical.set_updated_at();

-- ---------------------------------------------------------------------------
-- clinical.patient_conditions — اضافهٔ updated_at + trigger
-- ---------------------------------------------------------------------------
ALTER TABLE clinical.patient_conditions
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

DROP TRIGGER IF EXISTS trg_patient_conditions_updated_at ON clinical.patient_conditions;
CREATE TRIGGER trg_patient_conditions_updated_at
    BEFORE UPDATE ON clinical.patient_conditions
    FOR EACH ROW EXECUTE FUNCTION clinical.set_updated_at();

-- ---------------------------------------------------------------------------
-- clinical.patient_medications — اضافهٔ updated_at + trigger
-- ---------------------------------------------------------------------------
ALTER TABLE clinical.patient_medications
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

DROP TRIGGER IF EXISTS trg_patient_medications_updated_at ON clinical.patient_medications;
CREATE TRIGGER trg_patient_medications_updated_at
    BEFORE UPDATE ON clinical.patient_medications
    FOR EACH ROW EXECUTE FUNCTION clinical.set_updated_at();

-- ---------------------------------------------------------------------------
-- clinical.sms_campaigns — اضافهٔ updated_at + trigger
-- ---------------------------------------------------------------------------
ALTER TABLE clinical.sms_campaigns
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

DROP TRIGGER IF EXISTS trg_sms_campaigns_updated_at ON clinical.sms_campaigns;
CREATE TRIGGER trg_sms_campaigns_updated_at
    BEFORE UPDATE ON clinical.sms_campaigns
    FOR EACH ROW EXECUTE FUNCTION clinical.set_updated_at();

-- ---------------------------------------------------------------------------
-- accounting.invoices — اضافهٔ updated_at + trigger
-- ---------------------------------------------------------------------------
ALTER TABLE accounting.invoices
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

DROP TRIGGER IF EXISTS trg_invoices_updated_at ON accounting.invoices;
CREATE TRIGGER trg_invoices_updated_at
    BEFORE UPDATE ON accounting.invoices
    FOR EACH ROW EXECUTE FUNCTION accounting.set_updated_at();

-- ###########################################################################
-- ۲) observations VIEW — namespace obs_key (Batch 4a)
--    'vital:'||type   برای vital rows
--    'lab:'||COALESCE(test_key, test_name)   برای lab rows
--    RLS-TODO همچنان پابرجاست (ببینید slice2 §6)
-- ###########################################################################
-- RLS-TODO (T1 / Finding 3): این VIEW در حالِ حاضر هیچ فیلترِ tenant/patient ندارد.
--   یک VIEWِ معمولی (نه security_barrier) می‌تواند از طریقِ JOIN‌های بالادست داده‌های
--   tenant دیگری را به‌صورتِ غیرمستقیم لیک کند. در T1 هنگامِ فعال‌سازیِ RLS:
--   ۱) این VIEW را DROP و با SECURITY BARRIER تعریف کن، یا
--   ۲) یک WHERE tenant_id = current_setting('app.current_tenant_id')::bigint اضافه کن.
CREATE OR REPLACE VIEW clinical.observations AS
    SELECT
        'vital'::text          AS source_table,
        v.id                   AS source_id,
        v.tenant_id            AS tenant_id,
        v.patient_link_id      AS patient_link_id,
        'vital:'::text || v.type  AS obs_key,   -- Batch 4a: namespace 'vital:<type>'
        NULL::text             AS test_name,
        v.value                AS value,
        v.unit                 AS unit,
        NULL::real             AS ref_low,
        NULL::real             AS ref_high,
        v.measured_at          AS observed_at,
        v.source               AS source,
        v.recorded_by          AS recorded_by
    FROM clinical.vital_readings v
    UNION ALL
    SELECT
        'lab'::text            AS source_table,
        l.id                   AS source_id,
        l.tenant_id            AS tenant_id,
        l.patient_link_id      AS patient_link_id,
        'lab:'::text || COALESCE(l.test_key, l.test_name)  AS obs_key,  -- Batch 4a: namespace 'lab:<key>'
        l.test_name            AS test_name,
        l.value                AS value,
        l.unit                 AS unit,
        l.ref_low              AS ref_low,
        l.ref_high             AS ref_high,
        l.taken_at             AS observed_at,
        'lab'::text            AS source,
        l.recorded_by          AS recorded_by
    FROM clinical.lab_results l;

-- ###########################################################################
-- ۳) clinical.allergies.severity CHECK
--    severity TEXT nullable (موجود در slice2، خطِ ۳۵۲) → اضافهٔ CHECK
-- ###########################################################################
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'clinical.allergies'::regclass
          AND conname   = 'chk_allergies_severity'
    ) THEN
        ALTER TABLE clinical.allergies
            ADD CONSTRAINT chk_allergies_severity
            CHECK (severity IS NULL OR severity IN ('mild','moderate','severe','anaphylaxis'));
    END IF;
END$$;

-- ###########################################################################
-- ۴) accounting.procedures.performer_id — FK مرکب به medical_staff
--    performer_id BIGINT nullable (بدونِ FK در slice3) → اکنون FK واقعی:
--    FOREIGN KEY (tenant_id, performer_id) REFERENCES accounting.medical_staff(tenant_id, id)
--    ON DELETE SET NULL  (performer_id nullable — هر وقت staff حذف شد performer NULL می‌شود)
--
--    پیش‌نیاز: accounting.medical_staff دارایِ UNIQUE(tenant_id, id) =
--              uq_medical_staff_tenant_id (slice3 خطِ ۷۲) ✓
--
--    performer_type CHECK (موجود در slice3):
--    CHECK (performer_type IN ('doctor','nurse'))  → همانِ قبل است؛ NULL-check در قراردادِ
--    Postgres ضمنی (NULLها در CHECKِ بدونِ IS NULL رد نمی‌شوند) — idempotent: دستِ نخورده.
-- ###########################################################################
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'accounting.procedures'::regclass
          AND conname   = 'fk_procedures_performer'
    ) THEN
        ALTER TABLE accounting.procedures
            ADD CONSTRAINT fk_procedures_performer
            FOREIGN KEY (tenant_id, performer_id)
            REFERENCES accounting.medical_staff (tenant_id, id)
            ON DELETE SET NULL;
    END IF;
END$$;

-- performer_type: CHECKِ slice3 فقط 'doctor'/'nurse' داشت؛ به‌صورتِ ضمنی NULL مجاز است.
-- Batch 4a: تصریحِ NULLability در قراردادِ schema (ستون nullable → NULL مجاز است،
-- بدونِ نیاز به تغییرِ CHECK موجود — CHECK (x IN (...)) در Postgres NULL را pass می‌دهد).

-- ###########################################################################
-- GRANTs — حفظِ مرزِ دسترسی بعد از ALTER TABLEها
-- ###########################################################################
-- clinical: updated_at و trigger روی جداولِ موجودِ grantedند → هیچ تغییری لازم نیست.
-- accounting: ستونِ updated_at به accounting.invoices اضافه شد؛ جدولِ invoices قبلاً
--             برای accounting_app fully grantشده (slice3) + clinical_app فقط SELECT.
--             هیچ GRANT اضافه‌ای لازم نیست.

-- ###########################################################################
-- معیارِ «انجام‌شدهٔ» Batch 4a (برای تستِ نگهبان):
--   ۱) این فایل روی Postgresی که برش‌های ۰/۲/۲b/۳/۴ اجرا شده‌اند بدونِ خطا اجرا شود.
--   ۲) idempotent: اجرای دوم هم سبز (ADD COLUMN IF NOT EXISTS + CREATE OR REPLACE
--      FUNCTION + DROP TRIGGER IF EXISTS + DO $$ IF NOT EXISTS $$).
--   ۳) updated_at trigger کار کند:
--      INSERT → updated_at = now()
--      UPDATE → updated_at تغییر کند (جلوتر از مقدارِ INSERT)
--   ۴) allergies.severity CHECK مقادیرِ نامعتبر را رد کند ('fatal' → CheckViolation).
--   ۵) procedures.performer_id FK مقادیرِ نامعتبر را رد کند (999999 → ForeignKeyViolation).
--   ۶) obs_key در observations VIEW با پیشوندِ 'vital:' یا 'lab:' شروع شود.
-- ###########################################################################
