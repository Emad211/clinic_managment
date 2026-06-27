-- ============================================================================
-- schema_pg_slice15_tenant_indexes.sql
-- برشِ ۱۵ — ایندکس‌های tenant-time برای مقیاسِ چندمستأجری (قدم ۶۴)
--
-- هدف:
--   دو ایندکسِ مرکبِ tenant-LED برای دو مسیرِ داغِ واقعاً tenant-محور.
--   زیرِ FORCE RLS هر کوئری ضمناً `tenant_id = GUC` دارد؛ پس یک ایندکسِ
--   tenant-پیشرو می‌تواند فیلترِ tenant + فیلتر/مرتب‌سازیِ ثانویه را در یک
--   اسکن سرویس دهد (بدونِ sort/heap-fetchِ اضافه).
--
-- استدلالِ data-architect (چرا فقط همین دو، نه بیشتر):
--   این‌ها تنها دو مسیرِ داغی هستند که واقعاً «tenant-پیشرو» کوئری می‌شوند.
--   بقیهٔ مسیرهای per-patient (vital_readings، lab_results، patient_medications،
--   suggestion_log، …) از قبل با ایندکس‌های patient_link_id-پیشرو پوشش داده
--   شده‌اند؛ افزودنِ ایندکسِ tenant-time روی آن‌ها فقط write-amplificationِ
--   بی‌فایده است (مثلاً عمداً ایندکسِ vital_readings (tenant_id, measured_at)
--   *اضافه نمی‌شود*). minimal-by-design.
--
--   R1) list_patients: filter(tenant_id).order_by(-enrolled_at) با صفحه‌بندی +
--       count. امروز هیچ ایندکسِ پوشاننده ندارد → seq-scan + sort.
--   R2) worklist + واجد-شرایطیِ conversion + dispatcher._open_followup_exists
--       (per-patient-per-run → ریسکِ مقیاسِ واقعی). idx_followup_status موجود
--       (status, due_date) است و tenant-پیشرو نیست؛ یک ایندکسِ tenant-پیشروِ
--       مرکب، filter(tenant_id, status) + order_by(due_date) را در یک اسکن
--       پوشش می‌دهد.
--
-- وابستگی / ترتیب:
--   patient_links در slice0 ساخته می‌شود؛ followup_tasks در slice2.
--   نام‌گذاریِ numeric ادامه دارد (slice14 آخرین موجود بود) → conftest و
--   apply_schema برش‌ها را numeric-aware مرتب می‌کنند، پس slice15 پس از
--   slice14 اعمال می‌شود. این برش فقط روی ستون‌هایِ از-پیش-موجود ایندکس
--   می‌سازد؛ هیچ ستون/جدولِ جدیدی اضافه نمی‌کند.
--
-- idempotent:
--   فقط CREATE INDEX IF NOT EXISTS — امنِ re-run، هرگز فرضِ DBِ تازه.
--
-- OPERATIONS NOTE (مهم برای production):
--   این برش از `CREATE INDEX IF NOT EXISTS` ساده استفاده می‌کند چون هدفش
--   DBهای bootstrapِ تازه/کوچک است (داربستِ تست + provisionِ مستأجرِ جدید)؛
--   در آن‌ها قفلِ کوتاهِ ساختِ ایندکس بی‌اهمیت است.
--   اما اعمال روی یک جدولِ تولیدیِ *بزرگ* (که از قبل داده دارد) باید به‌صورتِ
--   یک گامِ جداگانهٔ غیرِ تراکنشی با `CREATE INDEX CONCURRENTLY` انجام شود تا
--   جدول قفلِ نوشتن نخورد. توجه: `CONCURRENTLY` نمی‌تواند درونِ یک transaction
--   block اجرا شود (و idempotency-اش متفاوت است: شکستِ نیمه‌کاره ایندکسِ
--   INVALID جا می‌گذارد که باید DROP و دوباره ساخته شود). به همین دلیل اینجا
--   نسخهٔ ساده می‌آید؛ runbookِ production نسخهٔ CONCURRENTLY را جدا اجرا کند.
--
-- بدونِ GRANT (ایندکس‌ها امتیازِ جدولِ مادر را به ارث می‌برند).
-- بدونِ تغییرِ RLS. فقط دو CREATE INDEX.
-- ============================================================================

-- ###########################################################################
-- R1) clinical.patient_links — list_patients: filter(tenant_id) + order_by(-enrolled_at)
--     filter(tenant_id).order_by(-enrolled_at) با صفحه‌بندی paged + count.
--     ستونِ enrolled_at به‌صورتِ DESC تا با ترتیبِ نزولیِ کوئری هم‌راستا شود
--     (index-orderِ مستقیم، بدونِ sort step).
-- ###########################################################################

CREATE INDEX IF NOT EXISTS idx_patient_links_tenant_enrolled
    ON clinical.patient_links (tenant_id, enrolled_at DESC);

-- ###########################################################################
-- R2) clinical.followup_tasks — worklist + conversion eligibility +
--     dispatcher._open_followup_exists (per-patient-per-run = ریسکِ مقیاسِ واقعی).
--     idx_followup_status موجود (status, due_date) tenant-پیشرو *نیست*؛ زیرِ
--     FORCE RLS هر کوئری tenant_id = GUC حمل می‌کند، پس یک ایندکسِ مرکبِ
--     tenant-پیشرو filter(tenant_id, status) + order_by(due_date) را در یک
--     اسکن سرویس می‌دهد.
-- ###########################################################################

CREATE INDEX IF NOT EXISTS idx_followup_tenant_status_due
    ON clinical.followup_tasks (tenant_id, status, due_date);

-- ============================================================================
-- معیارِ «انجام‌شدهٔ» برشِ ۱۵ (برای تستِ نگهبان):
--   ۱) ایندکسِ idx_patient_links_tenant_enrolled روی clinical.patient_links وجود دارد.
--   ۲) ایندکسِ idx_followup_tenant_status_due روی clinical.followup_tasks وجود دارد.
--   ۳) idempotency: اجرای مجددِ این برش بدونِ خطا (CREATE INDEX IF NOT EXISTS).
-- ============================================================================
