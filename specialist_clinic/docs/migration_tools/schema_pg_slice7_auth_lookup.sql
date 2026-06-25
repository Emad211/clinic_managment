-- ============================================================================
-- schema_pg_slice7_auth_lookup.sql
-- برشِ ۷ — رفعِ ریسک #۱۰: حذفِ خواندنِ cross-tenant در مسیرِ login
--
-- مشکل (قبل از این برش):
--   slice5 یک policy «tenant_isolation_read FOR SELECT USING(true)» روی platform.users
--   ساخته بود تا login endpoint بتواند username را بدون دانستنِ tenant پیدا کند.
--   اما Postgres برای FOR SELECT، تمامِ policyهای مرتبط را OR می‌کند:
--     tenant_isolation (FOR ALL)  → USING(tenant_id = GUC)
--     tenant_isolation_read       → USING(true)
--   پس نتیجهٔ OR: true → هر ردیفی برای SELECT در دسترس است، حتی با GUC اشتباه.
--   این به اپ‌رولِ کم‌امتیاز اجازه می‌دهد platform.users همهٔ tenantها را SELECT کند
--   (cross-tenant read) — ریسک افشای password_hash/role برای tenantهای دیگر.
--
-- راهِ حل (این برش):
--   ۱) حذفِ tenant_isolation_read (idempotent DROP POLICY IF EXISTS).
--   ۲) دو تابعِ SECURITY DEFINER که RLS را bypass می‌کنند اما فقط ستون‌های
--      کمینه را برمی‌گردانند (least-privilege):
--      a) auth_lookup_user: فقط ۸ ستونِ لازم برای authentication — بدونِ api_token_hash
--         (چون توکنِ API مربوط به مسیرِ login نیست و least-privilege حکم می‌کند).
--      b) auth_record_attempt: success/failure را در platform.users ثبت می‌کند
--         (UPDATE با SECURITY DEFINER — بدونِ نیاز به GUC).
--   ۳) REVOKE از PUBLIC + GRANT فقط به platform_app.
--
-- WHY SECURITY DEFINER:
--   مسیرِ login chicken-and-egg است: برای پیدا کردنِ tenant نیاز به user داریم،
--   برای یافتنِ user نیاز به tenant داریم. تابعِ SECURITY DEFINER با هویتِ مالک
--   (superuser → BYPASSRLS) اجرا می‌شود و RLS را برای این عملِ خاص دور می‌زند،
--   در حالی که همهٔ اعمالِ دیگر همچنان به RLS مقید هستند.
--
-- WHY SET search_path = platform, pg_temp:
--   بدونِ search_path صریح، یک مهاجم با دسترسیِ CREATE می‌تواند تابع‌هایِ تروجان
--   با نامِ مشابه بسازد. SET search_path در تعریفِ تابع ثابت می‌شود.
--
-- WHY بدونِ LIMIT در auth_lookup_user:
--   اگر username در چند tenant وجود داشت (آینده‌ٔ multi-tenant)، تابع چند ردیف
--   برمی‌گرداند. پایتون تعداد ردیف را بررسی می‌کند:
--     ۰ ردیف → DoesNotExist → InvalidCredentials
--     ۱ ردیف → authenticate
--   >۱ ردیف → MultipleObjectsReturned → InvalidCredentials (ambiguous — safe)
--   اگر LIMIT 1 بود، حالتِ ambiguous پنهان می‌ماند.
--
-- WHY api_token_hash برگشته نمی‌شود:
--   auth_lookup_user فقط برای مسیرِ password-based login است. api_token_hash
--   برای مسیرِ جداگانهٔ token-based auth استفاده می‌شود و در این تابع نیازی
--   به آن نیست. اگر برگردد، هر کدی که این تابع را صدا می‌زند به توکنِ هش‌شده
--   دسترسی خواهد داشت — این least-privilege را نقض می‌کند.
--
-- OWNER نکته:
--   owner تابع باید superuser باشد (تا با FORCE RLS bypass شود).
--   sliceها با superuser اجرا می‌شوند → owner به‌صورتِ خودکار superuser است.
--
-- وابستگی: بعد از slice0 (رول‌ها) + slice5 (RLS/policies).
-- idempotent: CREATE OR REPLACE + DROP POLICY IF EXISTS — هر بار ایمن است.
-- ============================================================================

-- ###########################################################################
-- ۱) حذفِ policyِ نشت‌دارِ tenant_isolation_read از platform.users
--    این policy برای SELECT روی platform.users USING(true) بود — یعنی هر
--    ردیفی برای SELECT در دسترس بود (cross-tenant read).
-- ###########################################################################
DROP POLICY IF EXISTS tenant_isolation_read ON platform.users;

-- ###########################################################################
-- ۲a) auth_lookup_user — جستجوی کاربر برای مسیرِ login (بدونِ tenant filter)
--
--    امضا:
--      platform.auth_lookup_user(p_username text)
--      RETURNS TABLE(id, tenant_id, username, password_hash, role, is_active,
--                    failed_attempts, locked_until)
--
--    برمی‌گرداند: کمینهٔ ستون‌های لازم برای authentication
--    برنمی‌گرداند: api_token_hash (least-privilege — مسیرِ login به آن نیاز ندارد)
--    بدونِ LIMIT: چندردیفی/ambiguous قابلِ تشخیص باشد (کالر تصمیم می‌گیرد)
-- ###########################################################################
CREATE OR REPLACE FUNCTION platform.auth_lookup_user(p_username TEXT)
RETURNS TABLE(
    id              BIGINT,
    tenant_id       BIGINT,
    username        TEXT,
    password_hash   BYTEA,
    role            TEXT,
    is_active       BOOLEAN,
    failed_attempts INTEGER,
    locked_until    TIMESTAMPTZ
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = platform, pg_temp
AS $$
    /*
        جستجوی کاربر برای مسیرِ login.

        چرا STABLE: این تابع داده را تغییر نمی‌دهد (فقط SELECT).
        چرا SECURITY DEFINER: RLS روی platform.users را bypass می‌کند تا
            login بتواند بدونِ دانستنِ tenant_id، username را پیدا کند.
        چرا فقط ۸ ستون: least-privilege — api_token_hash در مسیرِ login
            لازم نیست و نباید در دسترسِ هر کدِ login-path قرار گیرد.
        چرا بدون LIMIT: کالر (auth_service.py) تعداد ردیف را چک می‌کند:
            ۰→InvalidCredentials، ۱→authenticate، >۱→InvalidCredentials (ambiguous).
    */
    SELECT
        u.id,
        u.tenant_id,
        u.username,
        u.password_hash,
        u.role,
        u.is_active,
        u.failed_attempts,
        u.locked_until
    FROM platform.users u
    WHERE u.username = p_username;
$$;

-- ###########################################################################
-- ۲b) auth_record_attempt — ثبتِ موفقیت/شکستِ login در platform.users
--
--    امضا:
--      platform.auth_record_attempt(
--          p_user_id          bigint,
--          p_success          boolean,
--          p_lockout_threshold integer,
--          p_lockout_minutes   integer
--      ) RETURNS void
--
--    success=true: failed_attempts→0, locked_until→NULL, last_login→now()
--    success=false: failed_attempts++, اگر >= threshold → locked_until
--
--    آستانه‌ها پارامتری‌اند — منبعِ حقیقت در پایتون (_LOCKOUT_ATTEMPTS/_LOCKOUT_MINUTES)
--    می‌ماند. SQL از پایتون مقدار می‌گیرد، نه بالعکس.
-- ###########################################################################
CREATE OR REPLACE FUNCTION platform.auth_record_attempt(
    p_user_id           BIGINT,
    p_success           BOOLEAN,
    p_lockout_threshold INTEGER,
    p_lockout_minutes   INTEGER
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = platform, pg_temp
AS $$
/*
    ثبتِ نتیجهٔ یک تلاشِ login در platform.users.

    چرا SECURITY DEFINER:
        با RLS فعال روی platform.users (slice5)، UPDATE نیاز دارد GUC
        ست باشد (tenant_isolation WITH CHECK). در مسیرِ login، GUC هنوز ست
        نشده (chicken-and-egg). این تابع RLS را برای این عملِ خاص bypass می‌کند.

    چرا آستانه‌ها پارامتری:
        منبعِ حقیقتِ _LOCKOUT_ATTEMPTS و _LOCKOUT_MINUTES در پایتون است.
        SQL نباید این مقادیر را hardcode کند تا بتوان بدونِ migration تغییرشان داد.

    ایمنی:
        این تابع فقط بر اساسِ p_user_id کار می‌کند (که از auth_lookup_user آمده).
        هیچ اطلاعاتِ tenantِ دیگری را تغییر نمی‌دهد.
*/
BEGIN
    IF p_success THEN
        UPDATE platform.users
           SET failed_attempts = 0,
               locked_until    = NULL,
               last_login      = now()
         WHERE id = p_user_id;
    ELSE
        UPDATE platform.users
           SET failed_attempts = failed_attempts + 1,
               locked_until    = CASE
                                     WHEN failed_attempts + 1 >= p_lockout_threshold
                                     THEN now() + make_interval(mins => p_lockout_minutes)
                                     ELSE locked_until
                                 END
         WHERE id = p_user_id;
    END IF;
END;
$$;

-- ###########################################################################
-- ۳) مدیریتِ دسترسی — فقط platform_app می‌تواند این توابع را صدا بزند
-- ###########################################################################

-- auth_lookup_user
REVOKE ALL ON FUNCTION platform.auth_lookup_user(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION platform.auth_lookup_user(TEXT) TO platform_app;

-- auth_record_attempt
REVOKE ALL ON FUNCTION platform.auth_record_attempt(BIGINT, BOOLEAN, INTEGER, INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION platform.auth_record_attempt(BIGINT, BOOLEAN, INTEGER, INTEGER) TO platform_app;

-- ============================================================================
-- معیارِ «انجام‌شدهٔ» برشِ ۷ (برای تستِ نگهبان):
--   ۱) platform.users دیگر policyِ «tenant_isolation_read» ندارد.
--   ۲) platform.users همچنان policyِ «tenant_isolation» (FOR ALL) دارد.
--   ۳) platform.auth_lookup_user در pg_proc با proowner=superuser موجود است.
--   ۴) platform.auth_record_attempt در pg_proc با proowner=superuser موجود است.
--   ۵) رولِ platform_app حقِ EXECUTE روی هر دو تابع دارد؛ PUBLIC ندارد.
--   ۶) فراخوانیِ SELECT * FROM platform.auth_lookup_user('testuser') با رولِ
--      کم‌امتیاز (بدونِ GUC)، یک ردیف برمی‌گرداند (bypass RLS درست است).
--   ۷) SELECT password_hash FROM platform.users با رولِ کم‌امتیاز و GUC=''
--      → صفر ردیف (fail-closed باقی است).
--   ۸) idempotency: اجرای مجددِ این برش بدونِ خطا.
-- ============================================================================
