-- ============================================================================
-- پلتفرمِ یکپارچه — برشِ ۴ (اتصالِ مرزِ clinical → accounting)  ·  PostgreSQL 13+
-- مرجع: ADR-0007 (مرزِ یک‌طرفهٔ cross-schema) · ADR-0005/0003 (پلِ حسابداری→بالینی)
--
-- این برش، FKهای مرزیِ *معوقِ* برشِ ۲ را وصل می‌کند — حالا که بدنهٔ accounting (برشِ ۳)
-- ساخته شده. تنها جهتِ FKِ cross-schema مجاز: clinical → accounting (ADR-0007 §۲.۳).
-- هیچ ستون/جدولِ جدیدی اینجا ساخته نمی‌شود؛ فقط CONSTRAINT روی لجرهای موجودِ بالینی.
--
-- لجرهای مرزی (در برشِ ۲ با snapshotِ literal و بدونِ FK ساخته شدند):
--   * clinical.processed_invoices.accounting_invoice_id  (NOT NULL) → accounting.invoices
--   * clinical.doctor_visit_log.accounting_invoice_id    (NOT NULL) → accounting.invoices
--   * clinical.campaign_audience.accounting_patient_id    (NULLABLE) → accounting.patients
--
-- تصمیم‌های قفل‌شده:
--   * دو لجرِ فاکتور: FKِ *مرکب* (tenant_id, accounting_invoice_id) → accounting.invoices
--     (tenant_id, id) — از uq_invoices_tenant_idِ برشِ ۳ استفاده می‌کند؛ ضمانت می‌کند که
--     ردیفِ بالینی به فاکتورِ همان مستأجر اشاره کند (نه cross-tenant).
--   * campaign_audience: FKِ *تک‌ستونی* accounting_patient_id → accounting.patients(id)
--     (patients در برشِ ۰ قفل است و UNIQUE(tenant_id,id) ندارد؛ id خودش PK یکتاست).
--   * ON DELETE NO ACTION: فاکتور/بیمار در این سیستم hard-delete نمی‌شوند؛ این مرز نباید
--     اجازه دهد رکوردی که سمتِ بالینی روی آن اقدام کرده، حذف شود (یکپارچگیِ مالی-بالینی).
--   * DEFERRABLE INITIALLY DEFERRED: در ETL می‌توان ردیفِ بالینی را پیش از ردیفِ accounting
--     در همان تراکنش درج کرد؛ بررسی در commit. (وابستگیِ schema همچنان یک‌طرفه است —
--     accounting به clinical اشاره نمی‌کند؛ FK روی جدولِ بالینی می‌نشیند.)
--   * idempotent: هر ALTER با گاردِ pg_constraint (اجرای دوم بی‌اثر).
-- ============================================================================

-- ---------------------------------------------------------------------------
-- processed_invoices → accounting.invoices  (مرکب، tenant-safe)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_processed_invoices_acct') THEN
        ALTER TABLE clinical.processed_invoices
            ADD CONSTRAINT fk_processed_invoices_acct
            FOREIGN KEY (tenant_id, accounting_invoice_id)
            REFERENCES accounting.invoices (tenant_id, id)
            ON DELETE NO ACTION
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
END$$;

-- ---------------------------------------------------------------------------
-- doctor_visit_log → accounting.invoices  (مرکب، tenant-safe)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_doctor_visit_log_acct') THEN
        ALTER TABLE clinical.doctor_visit_log
            ADD CONSTRAINT fk_doctor_visit_log_acct
            FOREIGN KEY (tenant_id, accounting_invoice_id)
            REFERENCES accounting.invoices (tenant_id, id)
            ON DELETE NO ACTION
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
END$$;

-- ---------------------------------------------------------------------------
-- campaign_audience → accounting.patients  (تک‌ستونی؛ accounting_patient_id nullable)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_campaign_audience_acct_patient') THEN
        ALTER TABLE clinical.campaign_audience
            ADD CONSTRAINT fk_campaign_audience_acct_patient
            FOREIGN KEY (accounting_patient_id)
            REFERENCES accounting.patients (id)
            ON DELETE NO ACTION
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
END$$;

-- ============================================================================
-- معیارِ «انجام‌شدهٔ» برشِ ۴ (برای تستِ نگهبان):
--   ۱) روی Postgresی که برش‌های ۰/۲/۳ اجرا شده‌اند بدونِ خطا اجرا شود (idempotent).
--   ۲) درجِ ردیفِ processed_invoices/doctor_visit_log با accounting_invoice_id نامعتبر و
--      commit → خطای FK (مرزِ یک‌طرفه اثبات؛ snapshot دیگر یتیم نمی‌ماند).
--   ۳) جهتِ وابستگی یک‌طرفه می‌ماند: هیچ FKی از accounting به clinical اضافه نمی‌شود.
--   ۴) به‌خاطرِ DEFERRABLE، در یک تراکنش می‌توان فاکتور و لجرِ بالینی را با هر ترتیبی درج کرد.
-- ============================================================================
