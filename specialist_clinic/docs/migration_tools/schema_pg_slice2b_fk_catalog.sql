-- ============================================================================
-- پلتفرمِ یکپارچه — Batch 2b (FKهای catalog-by-key + id-based + cross-schema)
-- PostgreSQL 13+
--
-- این برش، ستون‌های «FK منطقی» (free-text/bigint بدونِ FK واقعی) را به
-- FKِ واقعیِ مرکبِ tenant-safe تبدیل می‌کند — همانِ قراردادِ Batch 2c.
--
-- پیش‌نیاز: برش‌های ۰ + ۲_clinical + ۳_accounting + ۴_boundary قبلاً اعمال شده باشند.
--
-- منطقِ گزینش (selectivity):
--   * FKهای اضافه‌شده: ستون‌هایی که مقادیرِ seedشان دقیقاً در parentِ کاتالوگ وجود دارند.
--   * FKهای حذف‌شده / نگه‌داشته‌شده به‌عنوانِ soft:
--       - clinical_rules.condition_code: سنتینلِ 'all' (cross-disease) → soft می‌ماند
--       - condition_lab_tests.condition_code: conditions دارایِ UNIQUE(tenant_id,code) نیست
--         (فقط UNIQUE(tenant_id,name) و UNIQUE(tenant_id,id)) → اضافه‌کردنِ unique ریسکِ
--         تضادِ migration دارد + seed جداگانه در Python bootstrap است → skip + report
--       - clinical_indicators.conditions: فیلدِ comma-list → نمی‌توان FK زد → soft
--
-- قراردادِ ON DELETE:
--   * ستون‌های nullable (FK اختیاری) → ON DELETE SET NULL
--   * ستون‌های NOT NULL (FK اجباری) → ON DELETE RESTRICT (پیش‌فرض، حذف نشده)
--
-- idempotency: همهٔ ALTER TABLEها درونِ DO $$ IF NOT EXISTS ... END$$ گارد شده‌اند.
-- ============================================================================

-- ###########################################################################
-- بخش ۱ — اضافه‌کردنِ UNIQUE(tenant_id, id) به parentهایی که هنوز ندارند
--   (پیش‌نیازِ FKِ مرکبِ child-tableها؛ قراردادِ Batch 2c)
-- ###########################################################################

-- patient_medications: هدفِ FK از medication_events.medication_id
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'clinical.patient_medications'::regclass
          AND conname   = 'uq_patient_medications_tenant_id'
    ) THEN
        ALTER TABLE clinical.patient_medications
            ADD CONSTRAINT uq_patient_medications_tenant_id
            UNIQUE (tenant_id, id);
    END IF;
END$$;

-- appointments: هدفِ FK از appointments.parent_appointment_id (self-ref) +
--               followup_tasks.appointment_id + engagement_approvals.appointment_id
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'clinical.appointments'::regclass
          AND conname   = 'uq_appointments_tenant_id'
    ) THEN
        ALTER TABLE clinical.appointments
            ADD CONSTRAINT uq_appointments_tenant_id
            UNIQUE (tenant_id, id);
    END IF;
END$$;

-- followup_tasks: هدفِ FK از prescriptions.followup_task_id
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'clinical.followup_tasks'::regclass
          AND conname   = 'uq_followup_tasks_tenant_id'
    ) THEN
        ALTER TABLE clinical.followup_tasks
            ADD CONSTRAINT uq_followup_tasks_tenant_id
            UNIQUE (tenant_id, id);
    END IF;
END$$;

-- ###########################################################################
-- بخش ۲ — گروه A: Catalog-by-KEY FKها
--   FOREIGN KEY (tenant_id, <col>) REFERENCES parent(tenant_id, <key>)
-- ###########################################################################

-- ---------------------------------------------------------------------------
-- A1: lab_results.test_key → lab_test_catalog(tenant_id, test_key)
--   test_key nullable (NULL = free-text/legacy ADR-0005) → ON DELETE SET NULL
--   lab_test_catalog دارایِ UNIQUE(tenant_id, test_key) = uq_lab_test_catalog_tenant_key ✓
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_lab_results_test_key'
    ) THEN
        ALTER TABLE clinical.lab_results
            ADD CONSTRAINT fk_lab_results_test_key
            FOREIGN KEY (tenant_id, test_key)
            REFERENCES clinical.lab_test_catalog (tenant_id, test_key)
            ON DELETE SET NULL;
    END IF;
END$$;

-- ---------------------------------------------------------------------------
-- A2: condition_lab_tests.lab_test_key → lab_test_catalog(tenant_id, test_key)
--   lab_test_key NOT NULL (بخشی از PK مرکب) → ON DELETE RESTRICT (پیش‌فرض)
--   lab_test_catalog دارایِ UNIQUE(tenant_id, test_key) = uq_lab_test_catalog_tenant_key ✓
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_condition_lab_tests_test_key'
    ) THEN
        ALTER TABLE clinical.condition_lab_tests
            ADD CONSTRAINT fk_condition_lab_tests_test_key
            FOREIGN KEY (tenant_id, lab_test_key)
            REFERENCES clinical.lab_test_catalog (tenant_id, test_key)
            ON DELETE RESTRICT;
    END IF;
END$$;

-- ---------------------------------------------------------------------------
-- A3: patient_flags.flag_key → flag_catalog(tenant_id, flag_key)
--   flag_key NOT NULL (بخشی از UNIQUE(tenant_id,patient_link_id,flag_key)) → RESTRICT
--   flag_catalog دارایِ UNIQUE(tenant_id, flag_key) = uq_flag_catalog_tenant_key ✓
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_patient_flags_flag_key'
    ) THEN
        ALTER TABLE clinical.patient_flags
            ADD CONSTRAINT fk_patient_flags_flag_key
            FOREIGN KEY (tenant_id, flag_key)
            REFERENCES clinical.flag_catalog (tenant_id, flag_key)
            ON DELETE RESTRICT;
    END IF;
END$$;

-- ---------------------------------------------------------------------------
-- A4: patient_medications.drug_class → drug_classes(tenant_id, class_key)
--   drug_class nullable (additive از migration core.py؛ قدیمی‌ها NULL دارند) → SET NULL
--   drug_classes دارایِ UNIQUE(tenant_id, class_key) = uq_drug_classes_tenant_key ✓
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_patient_medications_drug_class'
    ) THEN
        ALTER TABLE clinical.patient_medications
            ADD CONSTRAINT fk_patient_medications_drug_class
            FOREIGN KEY (tenant_id, drug_class)
            REFERENCES clinical.drug_classes (tenant_id, class_key)
            ON DELETE SET NULL;
    END IF;
END$$;

-- ---------------------------------------------------------------------------
-- A5: drug_catalog.drug_class_key → drug_classes(tenant_id, class_key)
--   drug_class_key nullable → ON DELETE SET NULL
--   drug_classes دارایِ UNIQUE(tenant_id, class_key) = uq_drug_classes_tenant_key ✓
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_drug_catalog_drug_class_key'
    ) THEN
        ALTER TABLE clinical.drug_catalog
            ADD CONSTRAINT fk_drug_catalog_drug_class_key
            FOREIGN KEY (tenant_id, drug_class_key)
            REFERENCES clinical.drug_classes (tenant_id, class_key)
            ON DELETE SET NULL;
    END IF;
END$$;

-- ---------------------------------------------------------------------------
-- A6: engagement_dispatch.event_key → engagement_events(tenant_id, event_key)
--   event_key NOT NULL → ON DELETE RESTRICT (پیش‌فرض)
--   engagement_events دارایِ UNIQUE(tenant_id, event_key) = uq_engagement_events_tenant_key ✓
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_engagement_dispatch_event_key'
    ) THEN
        ALTER TABLE clinical.engagement_dispatch
            ADD CONSTRAINT fk_engagement_dispatch_event_key
            FOREIGN KEY (tenant_id, event_key)
            REFERENCES clinical.engagement_events (tenant_id, event_key)
            ON DELETE RESTRICT;
    END IF;
END$$;

-- ###########################################################################
-- بخش ۳ — گروه B: Id-based FKها (parent باید UNIQUE(tenant_id,id) داشته باشد)
-- ###########################################################################

-- ---------------------------------------------------------------------------
-- B1: medication_events.medication_id → patient_medications(tenant_id, id)
--   medication_id nullable → ON DELETE SET NULL
--   patient_medications.uq_patient_medications_tenant_id اضافه شد بالا ✓
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_medication_events_medication_id'
    ) THEN
        ALTER TABLE clinical.medication_events
            ADD CONSTRAINT fk_medication_events_medication_id
            FOREIGN KEY (tenant_id, medication_id)
            REFERENCES clinical.patient_medications (tenant_id, id)
            ON DELETE SET NULL;
    END IF;
END$$;

-- ---------------------------------------------------------------------------
-- B2: appointments.parent_appointment_id → appointments(tenant_id, id)  [self-ref]
--   parent_appointment_id nullable → ON DELETE SET NULL
--   appointments.uq_appointments_tenant_id اضافه شد بالا ✓
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_appointments_parent_id'
    ) THEN
        ALTER TABLE clinical.appointments
            ADD CONSTRAINT fk_appointments_parent_id
            FOREIGN KEY (tenant_id, parent_appointment_id)
            REFERENCES clinical.appointments (tenant_id, id)
            ON DELETE SET NULL;
    END IF;
END$$;

-- ---------------------------------------------------------------------------
-- B3: followup_tasks.appointment_id → appointments(tenant_id, id)
--   appointment_id nullable → ON DELETE SET NULL
--   appointments.uq_appointments_tenant_id اضافه شد بالا ✓
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_followup_tasks_appointment_id'
    ) THEN
        ALTER TABLE clinical.followup_tasks
            ADD CONSTRAINT fk_followup_tasks_appointment_id
            FOREIGN KEY (tenant_id, appointment_id)
            REFERENCES clinical.appointments (tenant_id, id)
            ON DELETE SET NULL;
    END IF;
END$$;

-- ---------------------------------------------------------------------------
-- B4: engagement_approvals.appointment_id → appointments(tenant_id, id)
--   appointment_id nullable → ON DELETE SET NULL
--   appointments.uq_appointments_tenant_id اضافه شد بالا ✓
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_engagement_approvals_appointment_id'
    ) THEN
        ALTER TABLE clinical.engagement_approvals
            ADD CONSTRAINT fk_engagement_approvals_appointment_id
            FOREIGN KEY (tenant_id, appointment_id)
            REFERENCES clinical.appointments (tenant_id, id)
            ON DELETE SET NULL;
    END IF;
END$$;

-- ---------------------------------------------------------------------------
-- B5: prescriptions.followup_task_id → followup_tasks(tenant_id, id)
--   followup_task_id nullable → ON DELETE SET NULL
--   followup_tasks.uq_followup_tasks_tenant_id اضافه شد بالا ✓
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_prescriptions_followup_task_id'
    ) THEN
        ALTER TABLE clinical.prescriptions
            ADD CONSTRAINT fk_prescriptions_followup_task_id
            FOREIGN KEY (tenant_id, followup_task_id)
            REFERENCES clinical.followup_tasks (tenant_id, id)
            ON DELETE SET NULL;
    END IF;
END$$;

-- ---------------------------------------------------------------------------
-- B6: wallet_transactions.campaign_id → sms_campaigns(tenant_id, id)
--   campaign_id nullable → ON DELETE SET NULL
--   sms_campaigns دارایِ UNIQUE(tenant_id, id) = uq_sms_campaigns_tenant_id (slice2) ✓
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_wallet_transactions_campaign_id'
    ) THEN
        ALTER TABLE clinical.wallet_transactions
            ADD CONSTRAINT fk_wallet_transactions_campaign_id
            FOREIGN KEY (tenant_id, campaign_id)
            REFERENCES clinical.sms_campaigns (tenant_id, id)
            ON DELETE SET NULL;
    END IF;
END$$;

-- ###########################################################################
-- بخش ۴ — گروه C: clinical → platform (cross-schema مجاز)
-- ###########################################################################

-- ---------------------------------------------------------------------------
-- C1: prescriptions.prescriber_user_id → platform.users(tenant_id, id)
--   prescriber_user_id nullable → ON DELETE SET NULL
--   platform.users دارایِ UNIQUE(tenant_id, id) = uq_users_tenant_id (slice0) ✓
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_prescriptions_prescriber_user_id'
    ) THEN
        ALTER TABLE clinical.prescriptions
            ADD CONSTRAINT fk_prescriptions_prescriber_user_id
            FOREIGN KEY (tenant_id, prescriber_user_id)
            REFERENCES platform.users (tenant_id, id)
            ON DELETE SET NULL;
    END IF;
END$$;

-- ============================================================================
-- گرنتِ تکمیلی (جداولِ clinical این برش تغییر ساختاری دارند؛ گرنت حفظ می‌شود)
-- ============================================================================
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA clinical TO clinical_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA clinical TO clinical_app;

-- ============================================================================
-- FKهایِ حذف‌شده (soft — گزارشِ اجباریِ selectivity):
--
-- 1. clinical_rules.condition_code
--    دلیل: سنتینلِ 'all' (cross-disease) در seedهای production. اگر FK زده شود،
--    هر rule با condition_code='all' → ForeignKeyViolation (مگر 'all' در conditions.code
--    seed شود که معنای بالینی‌اش از بین می‌رود). → soft می‌ماند.
--
-- 2. condition_lab_tests.condition_code
--    دلیل: conditions دارایِ UNIQUE(tenant_id,code) نیست (فقط UNIQUE(tenant_id,name)
--    و UNIQUE(tenant_id,id)) — افزودنِ unique constraint روی conditions.code ریسکِ
--    تضادِ migration دارد (مقادیرِ NULL یا تکراری ممکن‌اند). seed این جدول در
--    Python bootstrap است (نه inline SQL) پس اثباتِ تمیزیِ seed ممکن نیست اینجا.
--    → skip. اگر معمارِ داده تأیید کند condition.code یکتاست و seed تمیز است،
--    می‌توان UNIQUE(tenant_id,code) به conditions اضافه کرد و سپس FK زد.
--
-- 3. clinical_indicators.conditions
--    دلیل: فیلدِ comma-list ('diabetes,hypertension', 'all') — FK از نوعِ
--    مقدارِ scalar ممکن نیست. → soft می‌ماند (پارسِ Python-side).
-- ============================================================================

-- ============================================================================
-- معیارِ «انجام‌شدهٔ» Batch 2b (برای تستِ نگهبان):
--   ۱) روی Postgresی که برش‌های ۰/۲/۳/۴ اجرا شده‌اند بدونِ خطا اجرا شود (idempotent).
--   ۲) اجرای دوم هم سبز (DO $$...IF NOT EXISTS گارد کرده).
--   ۳) درجِ medication_events.medication_id نامعتبر → ForeignKeyViolation (B1 اثبات).
--   ۴) درجِ patient_flags.flag_key نامعتبر → ForeignKeyViolation (A3 اثبات).
--   ۵) درجِ lab_results با test_key=NULL → مجاز (nullable FK با ON DELETE SET NULL).
--   ۶) درجِ prescriptions.prescriber_user_id نامعتبر → ForeignKeyViolation (C1 اثبات).
--   ۷) self-ref appointments.parent_appointment_id نامعتبر → ForeignKeyViolation (B2).
-- ============================================================================
