-- ============================================================================
-- schema_pg_slice18_allergies_note.sql
-- برشِ ۱۸ — تکمیلِ clinical.allergies برای کاکپیتِ پروندهٔ بیمار (فاز ۱)
--
-- ⚠️ تصمیمِ معماریِ کلیدی (ضدِ توهم، Evolve-not-Rewrite):
--   جدولِ مفهومیِ «حساسیت‌ها» از قبل به‌صورتِ clinical.allergies در slice2
--   (schema_pg_slice2_clinical.sql، خطِ ۳۴۵) وجود دارد — با ستون‌های
--   id, tenant_id, patient_link_id, substance, reaction, severity, created_at
--   + FKِ مرکبِ tenant-safe به clinical.patient_links(tenant_id,id)
--   + severity CHECK در slice4a (mild|moderate|severe|anaphylaxis).
--   این جدول از قبل ستونِ tenant_id دارد → slice5 خودکار RLS+FORCE+policyِ
--   tenant_isolation رویش گذاشته و test_rls_coverage.py از هم‌اکنون آن را
--   می‌پوشاند (allowlistِ EXEMPT خالی است).
--
--   بنابراین یک جدولِ موازیِ «clinical.patient_allergies» ساخته نمی‌شود:
--     * ضدِ «یک جدول per aggregate» و ایجادِ دادهٔ تکراری بود،
--     * DBِ موجود (که allergies را از قبل دارد) را دو-پاره می‌کرد،
--     * و چون شمارهٔ ۱۸ > ۵ است، جدولِ جدید بدونِ RLالسِ inline در همین برش
--       تا اجرای بعدیِ slice5 محافظت‌نشده می‌ماند و RLS coverage را می‌شکست.
--   درعوض همان جدولِ کانونی تکمیل می‌شود (افزایشی) تا مصرفِ endpoint را بدهد.
--
-- هدفِ این برش (افزایشی):
--   ۱) ستونِ `note TEXT` (nullable) — یادداشتِ آزادِ حساسیت که کاکپیتِ فاز ۱
--      در JSON بازمی‌گرداند ({id, substance, severity, note}). جدول از قبل
--      `reaction` دارد (شرحِ ساختاریافته‌ترِ واکنش)؛ `note` مکمّلِ آزادِ آن است
--      و هیچ‌کدام جای دیگری را نمی‌گیرد.
--   ۲) یک index روی (patient_link_id) — الگوی بقیهٔ جداولِ per-patientِ slice2
--      (idx_pc_patient و …)؛ allergies در slice2 index نداشت.
--
-- RLS:
--   هیچ کاری لازم نیست. clinical.allergies از قبل ENABLE+FORCE+tenant_isolation
--   دارد (slice5)؛ ستونِ نو خودکار زیرِ همان policy می‌نشیند (مثلِ slice11/slice17).
--   test_rls_coverage.py جدول‌محور است (نه ستون‌محور) → بدونِ تغییر سبز می‌ماند.
--
-- GRANT:
--   clinical_app و platform_app از قبل SELECT/INSERT/UPDATE/DELETE روی جداولِ
--   clinical دارند (footerِ slice2). ستونِ جدید از گرنتِ جدول ارث می‌برد.
--   با این حال، مطابقِ قاعدهٔ پایدارِ «هر برش جداولِ خودش را re-grant کند»
--   (memory: migration-schema-validation)، گرنتِ صریحِ همین جدول تکرار می‌شود
--   تا این برش به‌تنهایی هم خودبسنده باشد.
--
-- وابستگی: بعد از slice2 (clinical.allergies) و slice5 (RLS). ترتیبِ numeric 18
--   (conftest._slice_order + test_pg_schema numeric sort) → پس از slice17.
-- idempotent: ADD COLUMN IF NOT EXISTS + CREATE INDEX IF NOT EXISTS + GRANT
--   (همه safe-for-re-run؛ هرگز فرضِ DBِ تازه).
-- ============================================================================

-- ###########################################################################
-- ۱) ستونِ یادداشتِ آزاد روی clinical.allergies
--    ADD COLUMN IF NOT EXISTS → idempotent / safe to re-run
-- ###########################################################################

ALTER TABLE clinical.allergies
    ADD COLUMN IF NOT EXISTS note TEXT;

-- ###########################################################################
-- ۲) index روی patient_link_id — کوئریِ «حساسیت‌های این بیمار» (پرتکرارترین مسیر)
--    allergies در slice2 index نداشت؛ این هم‌راستا با idx_pc_patient و
--    idx_medevents_patient است.
-- ###########################################################################

CREATE INDEX IF NOT EXISTS idx_allergies_patient
    ON clinical.allergies (patient_link_id);

-- ###########################################################################
-- ۳) GRANT (re-grant صریح — خودبسندگیِ برش)
--    idempotent: GRANT روی جدولِ موجود بارها امن است.
-- ###########################################################################

GRANT SELECT, INSERT, UPDATE, DELETE ON clinical.allergies TO clinical_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON clinical.allergies TO platform_app;

-- ============================================================================
-- معیارِ «انجام‌شدهٔ» برشِ ۱۸ (برای تستِ نگهبان):
--   ۱) clinical.allergies دارایِ ستونِ note (TEXT nullable) است.
--   ۲) index idx_allergies_patient روی (patient_link_id) وجود دارد.
--   ۳) RLالسِ موجودِ allergies (slice5) خودکار شاملِ ستونِ نو می‌شود
--      (test_rls_coverage.py سبز؛ allergies هم‌چنان ENABLE+FORCE+tenant_isolation).
--   ۴) severity CHECK (slice4a) دست‌نخورده: مقادیرِ نامعتبر رد می‌شوند.
--   ۵) idempotency: اجرای مجدد بدونِ خطا (ADD COLUMN / CREATE INDEX / GRANT
--      همه IF NOT EXISTS یا re-run-safe).
-- ============================================================================
