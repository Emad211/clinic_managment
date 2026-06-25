-- ============================================================================
-- schema_pg_slice11_engagement_holdout.sql
-- برشِ ۱۱ — فلگِ holdoutِ تعامل (گروهِ کنترل برای سنجشِ اثرِ علّی)
--
-- هدف:
--   اضافه‌کردنِ سه ستونِ holdout به clinical.patient_links تا موتورِ تعامل
--   بتواند یک گروهِ کنترلِ deterministic بسازد و اثرِ causal موتور را بسنجد.
--   فقط dispatch_patient (ناجِ تعاملِ خودکار) gate می‌شود؛ مراقبتِ بالینی،
--   followup_engine، rule_engine، ویزیت و نسخه هرگز دریغ نمی‌شوند.
--
-- طراحی (قفل‌شده با clinical-data-scientist):
--   engagement_holdout BOOLEAN NOT NULL DEFAULT FALSE
--     TRUE = ناجِ تعاملِ خودکار suppressed (sms + worklist از موتورِ engagement)
--   engagement_holdout_since DATE
--     تاریخِ شروعِ holdout؛ NULL اگر هرگز تخصیص نگرفته
--   engagement_holdout_until DATE
--     تاریخِ انقضایِ stepped-wedge؛ NULL = open-ended (تا manager ببندد)
--
-- مرزِ مراقبت (اصلِ مقدس):
--   فقط dispatch_patient گیت می‌شود. followup_engine.generate_for_patient،
--   rule_engine.evaluate، و تمامِ ویزیت/نسخه/ردفلگ دست‌نخورده می‌مانند.
--   «مراقبتِ بالینی هرگز دریغ نمی‌شود» — فقط ناجِ تعاملِ خودکار suppressed
--   می‌شود و با status='holdout' در engagement_dispatch ثبت می‌شود.
--
-- ⚠️ گِیتِ consent (در ROADMAP علامت خورده):
--   سیاستِ consent/آگاه‌سازیِ بیمار برای نگه‌داشتنِ یادآور نیازِ تأییدِ
--   legal/پزشکِ مسئول دارد پیش از استفادهٔ زنده در production.
--   مکانیزم فعال است ولی باید با manager/پزشکِ مسئول توافق شود.
--
-- وابستگی: بعد از slice0 (رول‌ها + tenants) + slice2 (clinical schema + patient_links).
-- ترتیب: numeric 11 → بعد از slice10 اعمال می‌شود (conftest + test_pg_schema numeric sort).
-- idempotent: ALTER TABLE ... ADD COLUMN IF NOT EXISTS (safe for re-run).
-- ============================================================================

-- ###########################################################################
-- ۱) ستون‌های holdout روی clinical.patient_links
--    ADD COLUMN IF NOT EXISTS → idempotent / safe to re-run
-- ###########################################################################

ALTER TABLE clinical.patient_links
    ADD COLUMN IF NOT EXISTS engagement_holdout       BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE clinical.patient_links
    ADD COLUMN IF NOT EXISTS engagement_holdout_since DATE;

ALTER TABLE clinical.patient_links
    ADD COLUMN IF NOT EXISTS engagement_holdout_until DATE;

-- ###########################################################################
-- ۲) ایندکس برای کوئریِ سریعِ «بیمارانِ در holdout» (مدیریت + آمار)
--    سودمندِ assign_engagement_holdout و گزارشِ holdout dashboard
-- ###########################################################################

CREATE INDEX IF NOT EXISTS idx_patient_links_holdout
    ON clinical.patient_links (tenant_id, engagement_holdout, engagement_holdout_until)
    WHERE engagement_holdout = TRUE;

-- ###########################################################################
-- ۳) هیچ RLS جداگانه‌ای لازم نیست — ستون‌های نو به‌صورتِ خودکار تحتِ
--    سیاستِ tenant_isolation موجودِ patient_links (slice5) قرار می‌گیرند.
-- ###########################################################################

-- ###########################################################################
-- ۴) GRANT — platform_app نیاز به UPDATE روی patient_links دارد تا
--    assign_engagement_holdout بتواند ستون‌های holdout را بنویسد.
--    clinical_app و platform_app این گرنت را از slice0/slice2 ارث می‌برند.
--    تأیید: این slice هیچ REVOKE جدیدی اضافه نمی‌کند.
-- ###########################################################################
-- (گرنت‌های موجود از slice0/slice2 روی clinical.patient_links کافی‌اند؛
--  ستون‌های جدید خودکار از گرنتِ جدول ارث می‌برند در Postgres.)

-- ============================================================================
-- معیارِ «انجام‌شدهٔ» برشِ ۱۱ (برای تستِ نگهبان):
--   ۱) clinical.patient_links دارایِ ستون‌های engagement_holdout (BOOLEAN NOT NULL DEFAULT FALSE),
--      engagement_holdout_since (DATE nullable), engagement_holdout_until (DATE nullable) است.
--   ۲) ایندکسِ idx_patient_links_holdout وجود دارد.
--   ۳) idempotency: اجرای مجدد بدونِ خطا.
--   ۴) RLS موجودِ patient_links (slice5) به‌طورِ خودکار شاملِ ستون‌های نو می‌شود.
-- ============================================================================
