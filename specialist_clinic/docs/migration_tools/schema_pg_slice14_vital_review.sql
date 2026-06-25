-- ============================================================================
-- schema_pg_slice14_vital_review.sql
-- برشِ ۱۴ — بک‌اندِ تأیید/ردِ پزشک برای دادهٔ خوداظهار (خوشهٔ J — قدم ۴۷)
--
-- هدف:
--   پزشک می‌تواند vital_readingهای self-reported (verified=FALSE) را یا تأیید
--   (verify → verified=TRUE) یا رد (reject → rejected_at ست، verified=FALSE باقی)
--   کند. بعد از verify، ردیف وارد موتور/کارت می‌شود. بعد از reject، ردیف در DB
--   نگه‌داری می‌شود (soft-keep برای audit) ولی از موتور/کارت خارج می‌ماند.
--
-- اصلِ مقدس (قفل‌شده با gp-family-medicine-advisor):
--   ۶ فیلترِ verified=True در موتور (build_facts، کارت، ۳× engagement، followup)
--   دست‌نخورده باقی می‌مانند — این برش هیچ تغییری به آن فیلترها نمی‌دهد.
--   rejected هم verified=FALSE است → خودکار از موتور خارج می‌شود (Assert C).
--
-- تغییرات:
--   ۱) vital_readings: چهار ستونِ جدید (verified_by, verified_at, rejected_by,
--      rejected_at) — همه NULL-able، DEFAULT NULL.
--   ۲) ایندکس‌ها: idx_vital_readings_pending برای کوئریِ pending-list سریع.
--
-- وابستگی:
--   بعد از slice13 (vital_readings.verified موجود).
--
-- idempotent:
--   ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS.
-- ============================================================================

-- ###########################################################################
-- ۱) vital_readings — چهار ستونِ review metadata
--
--    verified_by   TEXT:       نامِ کاربرِ staff که verify کرده
--    verified_at   TIMESTAMPTZ: زمانِ verify (وقتِ تهران — کلاینت Iran ست می‌کند)
--    rejected_by   TEXT:       نامِ کاربرِ staff که reject کرده
--    rejected_at   TIMESTAMPTZ: زمانِ reject
--
--    همه DEFAULT NULL: ردیف‌های قدیمی (clinic-entered + slice13-self-report)
--    این ستون‌ها را NULL دارند — تا verify یا reject نشوند.
--
--    معنایِ state machine:
--      pending   : verified=FALSE, rejected_at IS NULL  (self-report آپلودشده، انتظار)
--      approved  : verified=TRUE                        (بعد از verify)
--      rejected  : verified=FALSE, rejected_at NOT NULL (بعد از reject — soft-keep)
--
--    NOTE: clinic-entered (slice2) با verified=TRUE (DEFAULT) شروع می‌کنند؛
--    verified_by/at برای آن‌ها NULL باقی می‌ماند (system-implicit, not physician-explicit).
-- ###########################################################################

ALTER TABLE clinical.vital_readings
    ADD COLUMN IF NOT EXISTS verified_by  TEXT,
    ADD COLUMN IF NOT EXISTS verified_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS rejected_by  TEXT,
    ADD COLUMN IF NOT EXISTS rejected_at  TIMESTAMPTZ;

-- ###########################################################################
-- ۲) ایندکس برای کوئریِ سریعِ pending (unverified + not-rejected)
--    staff می‌خواهد لیستِ ویتال‌های منتظرِ تأیید را ببیند:
--    WHERE verified=FALSE AND rejected_at IS NULL
-- ###########################################################################

CREATE INDEX IF NOT EXISTS idx_vital_readings_pending
    ON clinical.vital_readings (tenant_id, patient_link_id)
    WHERE verified = FALSE AND rejected_at IS NULL;

-- ============================================================================
-- معیارِ «انجام‌شدهٔ» برشِ ۱۴ (برای تستِ نگهبان):
--   ۱) vital_readings دارایِ ستونِ verified_by (TEXT, nullable).
--   ۲) vital_readings دارایِ ستونِ verified_at (TIMESTAMPTZ, nullable).
--   ۳) vital_readings دارایِ ستونِ rejected_by (TEXT, nullable).
--   ۴) vital_readings دارایِ ستونِ rejected_at (TIMESTAMPTZ, nullable).
--   ۵) ایندکسِ idx_vital_readings_pending وجود دارد.
--   ۶) idempotency: اجرایِ مجددِ این برش بدونِ خطا.
--   ۷) ۶ فیلترِ verified=True در موتور دست‌نخورده (ارزیابیِ کد، نه schema).
-- ============================================================================
