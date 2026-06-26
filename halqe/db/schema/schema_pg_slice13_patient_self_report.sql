-- ============================================================================
-- schema_pg_slice13_patient_self_report.sql
-- برشِ ۱۳ — بک‌اندِ self-reportِ بیمار + گیتِ verified (خوشهٔ J — قدم ۴۵)
--
-- هدف:
--   بیمار می‌تواند از طریقِ لینکِ یک‌بارمصرف (report-token) داده‌های ساده
--   (fbs / bp_systolic / bp_diastolic) را گزارش دهد.
--   داده با verified=FALSE ذخیره می‌شود و هرگز وارد موتورِ قرارداد یا کارتِ
--   عمومی نمی‌شود تا پزشک آن را verify کند (قدم ۴۷).
--
-- اصلِ مقدس (قفل‌شده با security-privacy-advisor):
--   دادهٔ verified=FALSE هرگز در build_facts / کارت / پیشنهاد نیست.
--
-- تغییرات:
--   ۱) vital_readings.verified — ستونِ جدید (DEFAULT TRUE = داده‌های موجود verified)
--   ۲) clinical.observations VIEW — بازسازی با ستونِ verified + security_invoker=true
--   ۳) clinical.patient_report_tokens — جدولِ یک‌بارمصرف برای مسیرِ write بیمار
--   ۴) clinical.report_resolve_token(p_token text) — SECURITY DEFINER
--
-- وابستگی:
--   بعد از slice0 (نقش‌ها) + slice2 (vital_readings, lab_results, observations)
--   + slice5 (RLS) + slice12 (pattern SECURITY DEFINER).
--   ترتیب: numeric 13 → بعد از slice12 اعمال می‌شود.
--
-- idempotent:
--   ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT EXISTS /
--   CREATE OR REPLACE VIEW / CREATE OR REPLACE FUNCTION /
--   DROP POLICY IF EXISTS + CREATE POLICY /
--   CREATE INDEX IF NOT EXISTS.
-- ============================================================================

-- ###########################################################################
-- ۱) vital_readings.verified
--    دادهٔ موجود/کلینیک → DEFAULT TRUE (verified=TRUE = ایمن برای موتور).
--    دادهٔ self-report بیمار → verified=FALSE (منتظرِ تأییدِ پزشک).
--    NOT NULL اجباری: هیچ مقداری نباید NULL باشد (همه یا verified‌اند یا نه).
-- ###########################################################################

ALTER TABLE clinical.vital_readings
    ADD COLUMN IF NOT EXISTS verified BOOLEAN NOT NULL DEFAULT TRUE;

-- ###########################################################################
-- ۲) clinical.observations — بازسازیِ VIEW با ستونِ verified
--
--    تمامِ ستون‌های فعلی (از slice4a) حفظ می‌شوند + verified اضافه می‌شود:
--      شاخهٔ vital: v.verified AS verified
--      شاخهٔ lab:   TRUE AS verified (نتایجِ آزمایشگاه همیشه verified هستند)
--
--    security_invoker=true: پس از CREATE OR REPLACE، باید دوباره ست شود.
--    در PostgreSQL 16 و بالاتر می‌توان در بدنهٔ CREATE OR REPLACE نوشت؛
--    در PG13+ باید ALTER VIEW ... SET (security_invoker=true) استفاده کرد.
--    ما هر دو را برای سازگاری می‌آوریم.
-- ###########################################################################

CREATE OR REPLACE VIEW clinical.observations AS
    SELECT
        'vital'::text          AS source_table,
        v.id                   AS source_id,
        v.tenant_id            AS tenant_id,
        v.patient_link_id      AS patient_link_id,
        'vital:'::text || v.type  AS obs_key,
        NULL::text             AS test_name,
        v.value                AS value,
        v.unit                 AS unit,
        NULL::real             AS ref_low,
        NULL::real             AS ref_high,
        v.measured_at          AS observed_at,
        v.source               AS source,
        v.recorded_by          AS recorded_by,
        v.verified             AS verified
    FROM clinical.vital_readings v
    UNION ALL
    SELECT
        'lab'::text            AS source_table,
        l.id                   AS source_id,
        l.tenant_id            AS tenant_id,
        l.patient_link_id      AS patient_link_id,
        'lab:'::text || COALESCE(l.test_key, l.test_name)  AS obs_key,
        l.test_name            AS test_name,
        l.value                AS value,
        l.unit                 AS unit,
        l.ref_low              AS ref_low,
        l.ref_high             AS ref_high,
        l.taken_at             AS observed_at,
        'lab'::text            AS source,
        l.recorded_by          AS recorded_by,
        TRUE::boolean          AS verified
    FROM clinical.lab_results l;

-- security_invoker=true: VIEW با حقوقِ کوئری‌کنندهٔ واقعی اجرا می‌شود → RLS اعمال می‌شود.
-- این ست‌کردن بعد از CREATE OR REPLACE ضروری است (ممکن است reset شود).
ALTER VIEW clinical.observations SET (security_invoker = true);

-- ###########################################################################
-- ۳) clinical.patient_report_tokens — جدولِ یک‌بارمصرف برای مسیرِ self-report
--
--    طراحی:
--      - یک‌بارمصرف: used_at پس از اولین استفادهٔ موفق ست می‌شود.
--      - expires_at: توکن بعد از مدتِ کوتاه منقضی می‌شود (پیش‌فرض ۲۴ ساعت).
--      - RLS FORCE: staff فقط توکنِ tenantِ خودش را می‌بیند.
--      - SECURITY DEFINER: مسیرِ عمومیِ بدونِ GUC از report_resolve_token استفاده می‌کند.
--      - جدا از patient_card_tokens: scope و TTL متفاوت — مسیرِ write vs read.
-- ###########################################################################

CREATE TABLE IF NOT EXISTS clinical.patient_report_tokens (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       BIGINT NOT NULL,
    patient_link_id BIGINT NOT NULL,
    token           TEXT   NOT NULL,
    issued_at       TIMESTAMPTZ DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    used_at         TIMESTAMPTZ,                -- NULL = هنوز استفاده‌نشده
    issued_by       TEXT,                       -- نامِ کاربرِ staff (audit trail)
    CONSTRAINT uq_report_token UNIQUE (token),
    CONSTRAINT fk_report_token_patient_link
        FOREIGN KEY (patient_link_id)
        REFERENCES clinical.patient_links(id)
        ON DELETE CASCADE
);

-- ایندکسِ اصلی: lookup توکن در مسیرِ عمومی (O(log n))
CREATE INDEX IF NOT EXISTS idx_patient_report_tokens_token
    ON clinical.patient_report_tokens (token);

-- ایندکسِ کمکی: توکن‌های فعالِ یک بیمار (برای staff UI)
CREATE INDEX IF NOT EXISTS idx_patient_report_tokens_patient_active
    ON clinical.patient_report_tokens (tenant_id, patient_link_id)
    WHERE used_at IS NULL;

-- ###########################################################################
-- ۴) RLS روی clinical.patient_report_tokens
--    RLS + FORCE: مسیرِ staffِ issue که GUC دارد، policy را رعایت می‌کند.
--    مسیرِ عمومیِ بدونِ GUC از report_resolve_token (SECURITY DEFINER) استفاده می‌کند.
-- ###########################################################################

ALTER TABLE clinical.patient_report_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinical.patient_report_tokens FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON clinical.patient_report_tokens;
CREATE POLICY tenant_isolation ON clinical.patient_report_tokens
    FOR ALL
    USING      (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::bigint)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::bigint);

-- ###########################################################################
-- ۵) GRANTها — clinical.patient_report_tokens
-- ###########################################################################

GRANT SELECT, INSERT, UPDATE ON clinical.patient_report_tokens TO platform_app;
GRANT USAGE, SELECT ON SEQUENCE clinical.patient_report_tokens_id_seq TO platform_app;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'clinical_app') THEN
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON clinical.patient_report_tokens TO clinical_app';
        EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE clinical.patient_report_tokens_id_seq TO clinical_app';
    END IF;
END
$$;

-- ###########################################################################
-- ۶) clinical.report_resolve_token — SECURITY DEFINER
--
--    امضا:
--      clinical.report_resolve_token(p_token text)
--      RETURNS TABLE(patient_link_id bigint, tenant_id bigint)
--
--    هدف:
--      endpoint عمومیِ POST /patient-report/{token} (بدونِ JWT) می‌تواند این تابع
--      را صدا بزند تا patient_link_id و tenant_id را برای توکنِ معتبرِ استفاده‌نشده
--      به‌دست آورد.
--      تابع RLS را bypass می‌کند (SECURITY DEFINER = با هویتِ مالک / BYPASSRLS).
--      اما فقط ستون‌های کمینه و فقط برای توکنِ used_at IS NULL + expires_at > now().
--      اگر توکن وجود نداشته باشد، منقضی یا قبلاً استفاده‌شده باشد → صفر ردیف.
--
--    چرا SECURITY DEFINER:
--      همانِ chicken-and-egg slice7/slice12: برای ست‌کردنِ GUC نیاز به tenant_id
--      داریم؛ برای خواندنِ tenant_id از جدولِ توکن (که RLS دارد) نیاز به GUC داریم.
--
--    WHY STABLE:
--      فقط SELECT بدونِ تغییرِ داده → STABLE.
--
--    WHY SET search_path = clinical, pg_temp:
--      جلوگیری از injection از طریقِ تابع‌های trojan در schema دیگر.
-- ###########################################################################

CREATE OR REPLACE FUNCTION clinical.report_resolve_token(p_token TEXT)
RETURNS TABLE(patient_link_id BIGINT, tenant_id BIGINT)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = clinical, pg_temp
AS $$
    /*
        رزولوِ توکنِ self-reportِ بیمار — بدونِ GUC.

        چرا SECURITY DEFINER:
            endpoint عمومیِ POST /patient-report/{token} بدونِ JWT است →
            GUC ست نیست → RLS روی patient_report_tokens fail-closed → lookup صفر.
            این تابع با هویتِ مالک (BYPASSRLS) اجرا می‌شود و فقط
            (patient_link_id, tenant_id) را برمی‌گرداند.
            endpoint سپس set_tenant_guc(tenant_id) می‌زند و داده را
            تحتِ RLS (tenant-scoped) می‌نویسد.

        شرطِ اعتبار:
            - used_at IS NULL: هنوز استفاده‌نشده (یک‌بارمصرف)
            - expires_at > now(): منقضی‌نشده

        اگر هر یک نقض شود → صفر ردیف → endpoint 409/410 برمی‌گرداند.
    */
    SELECT
        t.patient_link_id,
        t.tenant_id
    FROM clinical.patient_report_tokens t
    WHERE t.token = p_token
      AND t.used_at IS NULL
      AND t.expires_at > now();
$$;

-- مدیریتِ دسترسیِ تابع — فقط platform_app (و clinical_app اگر وجود دارد)
REVOKE ALL ON FUNCTION clinical.report_resolve_token(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION clinical.report_resolve_token(TEXT) TO platform_app;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'clinical_app') THEN
        EXECUTE 'GRANT EXECUTE ON FUNCTION clinical.report_resolve_token(TEXT) TO clinical_app';
    END IF;
END
$$;

-- ============================================================================
-- معیارِ «انجام‌شدهٔ» برشِ ۱۳ (برای تستِ نگهبان):
--   ۱) vital_readings دارایِ ستونِ verified (BOOLEAN NOT NULL DEFAULT TRUE).
--   ۲) VIEW clinical.observations دارایِ ستونِ verified.
--   ۳) VIEW security_invoker=true (pg_class.relrowsecurity یا pg_views بررسی).
--   ۴) جدولِ clinical.patient_report_tokens با ستون‌های مشخص وجود دارد.
--   ۵) UNIQUE constraint روی token + FK به patient_links(id) + ON DELETE CASCADE.
--   ۶) RLS فعال + FORCE روی patient_report_tokens.
--   ۷) policy tenant_isolation روی patient_report_tokens.
--   ۸) ایندکس‌های idx_patient_report_tokens_token و idx_patient_report_tokens_patient_active.
--   ۹) clinical.report_resolve_token در pg_proc با SECURITY DEFINER + STABLE.
--   ۱۰) PUBLIC حقِ EXECUTE روی تابع ندارد؛ platform_app دارد.
--   ۱۱) idempotency: اجرای مجددِ این برش بدونِ خطا.
-- ============================================================================
