-- ============================================================================
-- schema_pg_slice4c_idempotency.sql
-- برشِ ۴c — کلیدِ طبیعیِ یکتا روی clinical.vital_readings
--
-- هدف:
--   اعمالِ قیدِ UNIQUE روی (tenant_id, patient_link_id, type, measured_at, source)
--   به‌گونه‌ای که ارسالِ مجددِ همان اندازه‌گیری (idempotency) فقط یک ردیف بسازد.
--
-- کلیدِ طبیعی:
--   (tenant_id, patient_link_id, type, measured_at, source)
--   - value در کلید نیست: یک ارسالِ مجدد با همان زمان/نوع/منبع یک رویدادِ واحد است
--     (نه دو اندازه‌گیری)؛ اگر مقدار اصلاح شود، row-level conflict مدیریتش می‌کند.
--
-- NULLS NOT DISTINCT (PG16):
--   source nullable است (پیش‌فرض 'clinic' ولی صریحاً NULL هم مجاز). با UNIQUE معمولی،
--   دو ردیفِ (t, p, type, ts, NULL) از هم متمایزند (هر NULL با NULL برابر نیست) →
--   می‌توان بی‌نهایت ردیفِ NULL-source تکراری درج کرد. NULLS NOT DISTINCT این رفتار را
--   تغییر می‌دهد: NULL = NULL برای اهدافِ این constraint → دو NULL-source با همان کلیدِ
--   دیگر با هم conflict می‌کنند.
--   مبادله: دو اندازه‌گیریِ واقعاً متفاوت با source=NULL در همان لحظه نمی‌توانند هر دو
--   ذخیره شوند. این قابلِ قبول است چون source=NULL عملاً منبعِ «نامشخص» است و
--   دو اندازه‌گیریِ یک نوع در یک لحظهٔ دقیق از یک منبعِ نامشخص باید اصلاح شوند.
--
-- Dedupe + Idempotency:
--   قبل از اعمالِ constraint، ردیف‌های تکراری با MAX(id) حفظ می‌شوند.
--   اگر هیچ تکراری وجود نداشته باشد، DELETE صفر ردیف حذف می‌کند (ایمن).
--   اجرای دوم: تکراری وجود ندارد، DO $$ ... IF NOT EXISTS → بدونِ تغییر.
--
-- وابستگی: بعد از slice2_clinical (که vital_readings را می‌سازد) و slice4b (encounter_id).
-- ============================================================================

-- ###########################################################################
-- ۱) Dedupe — حذفِ ردیف‌های تکراری با نگه‌داشتنِ MAX(id)
--    COALESCE(source,'') در گروه‌بندی تضمین می‌کند که NULL-sourceها هم
--    مانندِ constraint رفتار می‌کنند (یعنی NULLها با هم برابرند).
--    ایمنِ re-run: اگر تکراری نباشد، صفر ردیف حذف می‌شود.
-- ###########################################################################

DELETE FROM clinical.vital_readings
WHERE id NOT IN (
    SELECT MAX(id)
    FROM   clinical.vital_readings
    GROUP BY
        tenant_id,
        patient_link_id,
        type,
        measured_at,
        COALESCE(source, '')
);

-- ###########################################################################
-- ۲) افزودنِ قیدِ UNIQUE NULLS NOT DISTINCT
--    DO $$ ... IF NOT EXISTS: اجرای دوم بدونِ اثر (idempotent).
-- ###########################################################################

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE  conname = 'uq_vital_readings_natural_key'
    ) THEN
        ALTER TABLE clinical.vital_readings
            ADD CONSTRAINT uq_vital_readings_natural_key
            UNIQUE NULLS NOT DISTINCT
            (tenant_id, patient_link_id, type, measured_at, source);
    END IF;
END
$$;
