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
-- مدلِ tenant-scoping:
--   در سطحِ اپلیکیشن (WHERE tenant_id=%s) — همان الگوی platform.users و
--   platform.tenants. RLS فقط روی schema clinical فعال است؛ schema platform
--   بدونِ RLS است (app-level tenant scoping). این برش RLS اضافه نمی‌کند.
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
--    schema platform بدونِ RLS است؛ scoping در سطحِ اپلیکیشن (WHERE tenant_id).
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

-- ============================================================================
-- معیارِ «انجام‌شدهٔ» برشِ ۱۶ (برای تستِ نگهبان):
--   ۱) جدولِ platform.settings وجود دارد با ستون‌های tenant_id/key/value/
--      updated_at/updated_by و PRIMARY KEY (tenant_id, key).
--   ۲) tenant_id دارای FK → platform.tenants(id) و DEFAULT 1، NOT NULL.
--   ۳) platform_app دارای SELECT, INSERT, UPDATE روی platform.settings است.
--   ۴) idempotency: اجرای مجددِ این برش بدونِ خطا (CREATE TABLE IF NOT EXISTS +
--      GRANTهای امن).
-- ============================================================================
