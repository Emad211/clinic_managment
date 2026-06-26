-- ============================================================================
-- schema_pg_slice5_rls.sql
-- برشِ ۵ — فعال‌سازیِ Row Level Security (RLS) روی جداولِ clinical.* و platform.*
--
-- هدف:
--   هر ردیف را به همان tenant محدود کند که GUCِ app.current_tenant در آن لحظه نشان می‌دهد.
--   درخواست‌های احراز‌هویت‌نشده یا بدونِ GUC → GUC خالی → NULL → صفر ردیف (fail-closed).
--
-- GUC نامِ قطعی: `app.current_tenant`
--   set_tenant_guc(tid) در platform_core/tenant_context.py با
--   SELECT set_config('app.current_tenant', %s, false) مقداردهی می‌کند.
--   TenantGucMiddleware در ابتدای هر request آن را به '' پاک می‌کند.
--
-- NULLIF برای fail-closed:
--   NULLIF(current_setting('app.current_tenant', true), '')::bigint
--   اگر GUC ست نشده یا خالی باشد → NULL → tenant_id=NULL → هیچ ردیفی match نمی‌کند.
--   این رفتار عمدی است: درخواستِ بدون‌احراز‌هویت هیچ داده‌ای نباید ببیند.
--
-- چرا FORCE:
--   مالکِ جداول سوپریوزر است (sliceها با سوپریوزر اجرا می‌شوند). PostgreSQL سوپریوزر
--   به‌صورتِ پیش‌فرض RLS را bypass می‌کند مگر اینکه FORCE ROW LEVEL SECURITY تنظیم شود.
--   FORCE تضمین می‌کند که حتی superuser (و رول مالک) تابعِ policy باشد — برای کوئری‌هایی
--   که با هویتِ سوپریوزر اجرا می‌شوند (مثلِ مهاجرت/seed که به خواندنِ همهٔ tenant نیاز دارند)
--   همچنان bypass می‌شود چون FORCE فقط رول‌هایی را که BYPASSRLS ندارند مقید می‌کند؛
--   سوپریوزرِ واقعی همیشه BYPASSRLS دارد.
--   آداپتورِ اپ (platform_app) BYPASSRLS ندارد → تابعِ policy است → درست.
--
-- چرا security_invoker روی VIEW:
--   VIEW‌ای که security_invoker نیست با حقوقِ مالکِ view (سوپریوزر) اجرا می‌شود.
--   چون سوپریوزر BYPASSRLS دارد، RLS روی vital_readings و lab_results در زمانِ کوئری
--   از طریقِ VIEW اعمال نمی‌شود → داده‌های همهٔ tenantها از VIEW دیده می‌شوند.
--   با security_invoker=true، VIEW با حقوقِ کوئری‌کنندهٔ واقعی اجرا می‌شود → RLS اعمال می‌شود.
--   (در PG17+ این پیش‌فرض است؛ در PG16 باید صریحاً تنظیم شود.)
--
-- accounting.* عمداً اینجا RLS نمی‌گیرد:
--   accounting از طریقِ پلِ read-only (mode=ro / GRANT SELECT) قابلِ دسترسی است.
--   سیاستِ چندمستأجریِ accounting در مرحلهٔ T1 تعریف می‌شود (RLS-TODO در slice0).
--   اضافه‌کردنِ RLS به accounting در این برش خارج از scope است و می‌تواند مهاجرت‌های
--   موجود را بشکند — به همین دلیل حلقهٔ پایین تنها schemaهای clinical و platform را می‌پوشاند.
--
-- وابستگی: بعد از همهٔ برش‌های ۰–۴c (که جداول و رول‌ها را می‌سازند).
-- idempotent: DO $$ ... DROP POLICY IF EXISTS + CREATE POLICY هر بار ایمن است.
-- ============================================================================

-- ###########################################################################
-- ۱) فعال‌سازیِ RLS روی همهٔ جداولِ tenant_id‌دارِ clinical و platform
--    حلقه روی pg_catalog.pg_class می‌زند؛ platform.tenants که tenant_id ندارد
--    خودکار رد می‌شود.
-- ###########################################################################

DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT n.nspname AS schema_name, c.relname AS table_name
        FROM   pg_catalog.pg_class c
        JOIN   pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE  c.relkind = 'r'
          AND  n.nspname IN ('clinical', 'platform')
          AND  EXISTS (
                   SELECT 1
                   FROM   pg_catalog.pg_attribute a
                   WHERE  a.attrelid = c.oid
                     AND  a.attname  = 'tenant_id'
                     AND  NOT a.attisdropped
               )
        ORDER BY n.nspname, c.relname
    LOOP
        -- فعال‌سازیِ RLS
        EXECUTE format(
            'ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',
            r.schema_name, r.table_name
        );

        -- FORCE: مالکِ جدول (superuser) هم تابعِ policy باشد
        EXECUTE format(
            'ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY',
            r.schema_name, r.table_name
        );

        -- حذفِ policy قدیمی (idempotency)
        EXECUTE format(
            'DROP POLICY IF EXISTS tenant_isolation ON %I.%I',
            r.schema_name, r.table_name
        );

        -- ساختنِ policy جدید: هم READ هم WRITE را به tenant محدود می‌کند.
        -- NULLIF: GUCِ خالی → NULL → هیچ ردیفی match نمی‌کند (fail-closed).
        EXECUTE format(
            $pol$
            CREATE POLICY tenant_isolation ON %I.%I
                FOR ALL
                USING      (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::bigint)
                WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::bigint)
            $pol$,
            r.schema_name, r.table_name
        );

        RAISE NOTICE 'RLS enabled on %.%', r.schema_name, r.table_name;
    END LOOP;
END
$$;

-- ###########################################################################
-- ۱b) استثناءِ auth bootstrap: platform.users — SELECT آزاد، WRITE قفل
--
-- مشکلِ معماری: login endpoint باید username را بدونِ دانستنِ tenant پیدا کند
-- (chicken-and-egg: برای پیدا کردنِ tenant نیاز به user داریم، برای user نیاز به tenant).
-- راهِ حل: policy جداگانه برای FOR SELECT روی platform.users (بدون USING) که
-- به هر auth query اجازه می‌دهد همهٔ کاربرها را ببیند.
-- ایمنی: auth امنیت را از طریقِ JWT (tenant_id در claim) تضمین می‌کند، نه RLS.
-- WRITE همچنان با tenant_isolation قفل است — نوشتنِ cross-tenant ممکن نیست.
--
-- پس از این block، platform.users دو policy دارد:
--   tenant_isolation          (FOR ALL)    → USING+WITH CHECK tenant-scoped (از حلقه)
--   tenant_isolation_read     (FOR SELECT) → USING true (همه می‌توانند بخوانند)
-- در Postgres وقتی FOR SELECT چند policy دارد، هر کدام که TRUE شود کافی است (OR).
-- پس SELECT همیشه مجاز است (چون tenant_isolation_read همیشه true است).
-- INSERT/UPDATE/DELETE فقط با tenant_isolation (USING+WITH CHECK) check می‌شوند.
-- ###########################################################################

DROP POLICY IF EXISTS tenant_isolation_read ON platform.users;
CREATE POLICY tenant_isolation_read ON platform.users
    FOR SELECT
    USING (true);

-- ###########################################################################
-- ۲) security_invoker روی clinical.observations
--    بدونِ این، VIEW با حقوقِ مالک (superuser/BYPASSRLS) اجرا می‌شود و RLSِ
--    vital_readings و lab_results دور زده می‌شود → داده‌های همهٔ tenant‌ها لیک می‌شود.
--    با security_invoker=true، VIEW با حقوقِ کوئری‌کنندهٔ واقعی اجرا می‌شود.
--    RLS-TODO اصلی که در کامنتِ slice2_clinical.sql نزدیکِ تعریفِ VIEW ثبت شده بود
--    با این دستور بسته می‌شود.
--    نکته: نامِ GUC در کامنتِ قدیمیِ slice2 به اشتباه `app.current_tenant_id` آمده بود؛
--    نامِ واقعی در کد `app.current_tenant` است — این برش با نامِ صحیح کار می‌کند.
-- ###########################################################################

ALTER VIEW clinical.observations SET (security_invoker = true);

-- ============================================================================
-- معیارِ «انجام‌شدهٔ» برشِ ۵ (برای تستِ نگهبان):
--   ۱) همهٔ جداولِ tenant_id‌دارِ clinical و platform: relrowsecurity=true + relforcerowsecurity=true.
--   ۲) policy tenant_isolation روی هر یک از این جداول وجود دارد.
--   ۳) رول‌هایِ platform_app و platform_login_test فاقدِ rolbypassrls و rolsuper هستند.
--   ۴) GUC=N → فقط ردیف‌های tenant N دیده می‌شوند؛ GUC='' → صفر ردیف (fail-closed).
--   ۵) INSERT با tenant_id مغایر با GUC → WITH CHECK رد می‌کند (نشتِ نوشتن بسته).
--   ۶) SELECT از clinical.observations با GUC=1 فقط tenant 1 → security_invoker کار می‌کند.
--   ۷) idempotency: اجرای مجددِ این برش بدونِ خطا (DROP POLICY IF EXISTS).
-- ============================================================================
