-- ============================================================================
-- schema_pg_slice17_data_consent.sql
-- برشِ ۱۷ — رضایتِ پردازشِ داده (data-processing consent) — قدم ۷۵ (خوشهٔ S)
--
-- هدف:
--   ستون‌های رضایتِ **پردازشِ داده** را به clinical.patient_links اضافه می‌کند.
--   این رضایت، مبنای قانونیِ **نگه‌داری/پردازشِ دادهٔ بالینیِ بیمار** در پلتفرم است
--   (محرمانگیِ پروندهٔ پزشکی) — و **کاملاً جدا** از `sms_consent`ِ موجود (slice0) است
--   که مبنای قانونیِ **فرستادنِ پیامک** است. این دو هرگز نباید یکی شوند.
--
-- چرا حالا (schema prep، نه ثبتِ رضایت):
--   PHIِ واقعی هنوز بارگذاری نشده (گِیتِ مالک). افزودنِ ستونِ افزایشیِ idempotent
--   اکنون امن است و آماده‌سازیِ schema برای سطحِ ثبت (capture UI) است که در onboarding/
--   intake (خوشهٔ U / قدم ۸۵) پس از نهایی‌شدنِ متنِ حقوقیِ R4 (وکیل) ساخته می‌شود.
--
-- ⚠️ قاعدهٔ مقدسِ این برش — «بدونِ منطقِ خواننده»:
--   تا وقتی سطحِ ثبت (U2/R4) ساخته شود، **هیچ کدی نباید وجود/مقدارِ این ستون را
--   به‌معنای رضایتِ گرفته‌شده تفسیر کند**. ستونِ خالی فقط زمانی بی‌ضرر است که هیچ
--   تصمیمی بر اساسش گرفته نشود. پیش‌فرضِ FALSE = «رضایت ثبت‌نشده» (وضعِ امنِ default-deny).
--   `version`/`source` از همین حالا هستند چون نسخهٔ متنِ رضایت و منشأ (intake/onboarding/
--   migration) برای اثباتِ بعدی لازم است و افزودنشان به ردیف‌های موجود دردسر دارد.
--
-- RLS:
--   clinical.patient_links از قبل RLS+FORCE+tenant_isolation دارد (slice5). ستون‌های
--   نو خودکار زیرِ همان policy می‌نشینند — هیچ RLS جدیدی لازم نیست (مثلِ slice11).
--   test_rls_coverage.py جدول‌محور است (نه ستون‌محور) → بدونِ تغییر سبز می‌ماند.
--
-- وابستگی: بعد از slice0 (clinical.patient_links + ستون‌های sms_consent) و slice5 (RLS).
-- ترتیب: numeric 17 → بعد از slice16. idempotent: ADD COLUMN IF NOT EXISTS (re-run امن).
-- ============================================================================

-- ###########################################################################
-- ۱) ستون‌های رضایتِ پردازشِ داده روی clinical.patient_links
--    ADD COLUMN IF NOT EXISTS → idempotent / safe to re-run (هرگز فرضِ DBِ تازه)
-- ###########################################################################

ALTER TABLE clinical.patient_links
    ADD COLUMN IF NOT EXISTS data_consent          BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE clinical.patient_links
    ADD COLUMN IF NOT EXISTS data_consent_at       TIMESTAMPTZ;

ALTER TABLE clinical.patient_links
    ADD COLUMN IF NOT EXISTS data_consent_version  TEXT;

ALTER TABLE clinical.patient_links
    ADD COLUMN IF NOT EXISTS data_consent_source   TEXT;

-- ###########################################################################
-- ۲) RLS — هیچ کاری لازم نیست. ستون‌های نو زیرِ سیاستِ tenant_isolationِ موجودِ
--    clinical.patient_links (slice5) قرار می‌گیرند (مثلِ ستون‌های holdoutِ slice11).
-- ###########################################################################

-- ############################################################################
-- ۳) GRANT — لازم نیست. platform_app از قبل SELECT/INSERT/UPDATE روی
--    clinical.patient_links دارد (slice0/slice2)؛ ستون‌های جدید از گرنتِ جدول ارث می‌برند.
-- ############################################################################

-- ============================================================================
-- معیارِ «انجام‌شدهٔ» برشِ ۱۷ (برای تستِ نگهبان):
--   ۱) clinical.patient_links دارایِ ستون‌های data_consent (BOOLEAN NOT NULL DEFAULT FALSE)،
--      data_consent_at (TIMESTAMPTZ nullable)، data_consent_version (TEXT nullable)،
--      data_consent_source (TEXT nullable) است.
--   ۲) data_consent جدا از sms_consent است (دو مفهومِ مستقل؛ هیچ یک دیگری را override نمی‌کند).
--   ۳) idempotency: اجرای مجدد بدونِ خطا (ADD COLUMN IF NOT EXISTS).
--   ۴) RLSِ موجودِ patient_links (slice5) خودکار شاملِ ستون‌های نو می‌شود (test_rls_coverage سبز).
-- ============================================================================
