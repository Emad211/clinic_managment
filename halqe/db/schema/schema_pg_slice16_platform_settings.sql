-- ============================================================================
-- schema_pg_slice16_platform_settings.sql
-- برشِ ۱۶ — جدولِ key/value تنظیماتِ هر-مستأجر (platform.settings) — قدم ۵۲ (خوشهٔ L)
--
-- هدف:
--   جدولِ عمومیِ tenant-scopedِ key/value برای تنظیماتِ cross-cutting که جدولِ
--   اختصاصیِ خود را ندارند. جایگزینِ جدولِ تک‌اپِ `settings` در specialist_clinic
--   در مدلِ چندمستأجریِ ابری.
--
--   استفاده‌ها:
--     * card_projection_service کلیدِ 'clinic_name' را می‌خواند (تا پیش از این
--       برش، جدول غایب بود و read با try/except بی‌صدا None برمی‌گرداند؛ این برش
--       آن مسیر را فعال می‌کند — graceful وقتی ردیف نباشد، باز هم None).
--     * قدم ۵۲: کلیدهای engagement_quiet_start / engagement_quiet_end /
--       engagement_daily_cap (تنظیماتِ گاردریلِ تعامل، manager-editable) via
--       platform_core.platform_settings_service + clinical.engagement_settings.
--
-- مدلِ tenant-scoping (به‌روزرسانیِ قدم ۷۳ — دفاع‌در‌عمق):
--   دو لایه: (۱) scopingِ سطحِ اپلیکیشن (WHERE tenant_id=%s) که در سرویس همیشه
--   اعمال می‌شود، و (۲) **RLS+FORCE+tenant_isolation** که در همین برش (بخشِ ۳)
--   inline فعال می‌شود — مثلِ هر جدولِ tenant_id‌دارِ بعد از slice5 (slices ۸/۹/۱۰/۱۲/۱۳).
--   چون این جدول بعد از slice5 ساخته می‌شود، حلقهٔ apply-timeِ slice5 آن را نمی‌گیرد؛
--   پس RLS را خودِ برش فعال می‌کند (الگوی «هر برش مسئولِ RLSِ خودش»).
--   تصمیمِ قدم ۷۳ (security + من): چون `platform.users` از قبل RLS دارد، schema
--   platform خالص app-scoped نیست؛ و settings دادهٔ پیکربندیِ هر-مستأجر است
--   (clinic_name، گاردریل‌های تعامل) که نشتِ cross-tenantِ آن نقضِ ایزولاسیون است.
--   همهٔ مسیرهای read/write پیش از دسترسی GUC را ست می‌کنند (راستی‌آزمایی‌شده:
--   patient_card→set_tenant_guc، endpointهای engagement با auth، run_engagement
--   صریحاً set_tenant_guc؛ provision_tenant به settings دست نمی‌زند) → fail-closed
--   هیچ مسیری را نمی‌شکند. بدونِ policyِ FOR SELECT USING true (برخلافِ users که
--   برای login bootstrap لازم بود — settings همیشه با GUCِ ست‌شده خوانده می‌شود).
--   لایهٔ WHERE tenant_id در سرویس به‌عنوانِ سدِ دوم حفظ می‌شود (بی‌ضرر).
--
--   PK مرکب (tenant_id, key) → upsert با ON CONFLICT (tenant_id, key) DO UPDATE.
--   tenant_id BIGINT NOT NULL DEFAULT 1 REFERENCES platform.tenants(id) — همان
--   کنوانسیونِ FKِ سایرِ جداولِ platform در slice0.
--
-- وابستگی / ترتیب:
--   platform.tenants در slice0 ساخته می‌شود (FK target). نام‌گذاریِ numeric ادامه
--   دارد (slice15 آخرین موجود بود) → conftest و apply_schema و test_pg_schema
--   برش‌ها را numeric-aware (major,suffix) مرتب می‌کنند، پس slice16 پس از
--   slice15 و slice0 اعمال می‌شود.
--
-- idempotent:
--   CREATE TABLE IF NOT EXISTS + GRANTهای امن (re-runنِ بی‌خطا، هرگز فرضِ DBِ تازه).
--
-- امنیت / GRANT:
--   platform_app (رولِ اپِ halqe) به این جدول SELECT/INSERT/UPDATE نیاز دارد
--   (engagement_settings می‌نویسد، card_projection می‌خواند). slice0 از طریقِ
--   ALTER DEFAULT PRIVILEGES IN SCHEMA platform ... TO platform_app این جدولِ
--   آینده را پوشش می‌دهد، اما برای صراحت + استقلالِ برش GRANTِ روشن هم می‌آید.
--   clinical_app هم در slice0 SELECT روی همهٔ platform می‌گیرد؛ گرنتِ صریحِ آن
--   اینجا با گاردِ pg_roles می‌آید (مطابقِ الگوی سایرِ برش‌ها — رول ممکن است در
--   داربستِ خاصی موجود نباشد).
-- ============================================================================

-- ###########################################################################
-- ۱) جدول — platform.settings (tenant-scoped K/V)
-- ###########################################################################
CREATE TABLE IF NOT EXISTS platform.settings (
    tenant_id   BIGINT NOT NULL DEFAULT 1 REFERENCES platform.tenants(id),
    key         TEXT NOT NULL,
    value       TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by  TEXT,
    CONSTRAINT pk_platform_settings PRIMARY KEY (tenant_id, key)
);

-- ###########################################################################
-- ۲) GRANT — platform_app (اپِ halqe) می‌نویسد و می‌خواند روی این جدول.
--    scoping دو لایه است (بخشِ ۳): RLS+FORCE + لایهٔ WHERE tenant_id در سرویس.
--    بدونِ UPDATE/DELETE-revoke (این یک جدولِ تنظیماتِ قابلِ ویرایش است، نه
--    append-only؛ بنابراین مثلِ slice10 محدود نمی‌شود).
-- ###########################################################################
GRANT SELECT, INSERT, UPDATE ON platform.settings TO platform_app;

-- clinical_app هم — با گاردِ pg_roles (الگوی سایرِ برش‌ها؛ رول ممکن است در یک
-- داربستِ minimal موجود نباشد، پس CREATE/GRANT را مشروط می‌کنیم).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'clinical_app') THEN
        GRANT SELECT, INSERT, UPDATE ON platform.settings TO clinical_app;
    END IF;
END$$;

-- ###########################################################################
-- ۳) RLS — فعال‌سازیِ inline (قدم ۷۳، دفاع‌در‌عمق).
--    این جدول بعد از slice5 ساخته می‌شود، پس حلقهٔ apply-timeِ slice5 آن را
--    نمی‌گیرد؛ خودِ برش RLS را فعال می‌کند — همان الگوی idempotentِ slices
--    ۸/۹/۱۰/۱۲/۱۳ (ENABLE + FORCE + DROP POLICY IF EXISTS + CREATE POLICY).
--    FORCE: رولِ مالک/app هم تابعِ policy باشد (سوپریوزرِ واقعی BYPASSRLS دارد →
--    seed/apply با postgres کار می‌کند). NULLIF: GUCِ خالی → NULL → صفر ردیف
--    (fail-closed). بدونِ policyِ FOR SELECT USING true — settings همیشه با GUCِ
--    ست‌شده خوانده می‌شود (برخلافِ platform.users که برای login bootstrap نیاز داشت).
-- ###########################################################################
ALTER TABLE platform.settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform.settings FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON platform.settings;

CREATE POLICY tenant_isolation ON platform.settings
    FOR ALL
    USING      (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::bigint)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::bigint);

-- ============================================================================
-- معیارِ «انجام‌شدهٔ» برشِ ۱۶ (برای تستِ نگهبان):
--   ۱) جدولِ platform.settings وجود دارد با ستون‌های tenant_id/key/value/
--      updated_at/updated_by و PRIMARY KEY (tenant_id, key).
--   ۲) tenant_id دارای FK → platform.tenants(id) و DEFAULT 1، NOT NULL.
--   ۳) platform_app دارای SELECT, INSERT, UPDATE روی platform.settings است.
--   ۴) idempotency: اجرای مجددِ این برش بدونِ خطا (CREATE TABLE IF NOT EXISTS +
--      GRANTهای امن + DROP POLICY IF EXISTS).
--   ۵) RLS: platform.settings دارای relrowsecurity=true + relforcerowsecurity=true
--      + policyِ tenant_isolation (FOR ALL، USING+WITH CHECK با الگوی NULLIF) است.
-- ============================================================================
