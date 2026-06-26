-- ============================================================================
-- schema_pg_slice6_onboarding.sql
-- برشِ ۶ — onboarding/provisioning: تابعِ SECURITY DEFINER برای ساختِ tenant
--
-- WHY SECURITY DEFINER:
--   با RLS فعال روی platform.users (slice5)، INSERT روی این جدول از طریقِ
--   رولِ کم‌امتیازِ platform_app نیاز دارد GUC=tenant_id_جدید باشد — یعنی
--   یک provisioning request که هنوز tenant وجود ندارد باید با GUCِ tenant-id
--   ناشناخته درج کند. این دوره-باطل (chicken-and-egg) است.
--   راهِ امن: یک تابع که با مالکیتِ superuser اجرا می‌شود (SECURITY DEFINER)
--   می‌تواند RLS را برای این عملِ خاص (provisioning) دور بزند، در حالی‌که
--   همهٔ اعمالِ دیگر همچنان به RLS مقید هستند.
--
-- WHY SET search_path = platform, pg_temp:
--   بدونِ search_path صریح، یک مهاجمِ با دسترسیِ CREATE به schema عمومی
--   می‌تواند تابع-هایِ تروجان با نامِ مشابه بسازد. SET search_path در خودِ
--   تعریفِ تابع ثابت می‌شود و تغییرِ search_path خارجی تأثیری ندارد.
--
-- IDEMPOTENCY:
--   - tenant: INSERT ... ON CONFLICT (name) DO NOTHING — name به‌عنوانِ کلیدِ
--     طبیعیِ idempotency انتخاب شده. اگر tenant با همین name موجود باشد، id
--     همانِ موجود برگردانده می‌شود. (id IDENTITY است و UNIQUE CONSTRAINT روی
--     name در این برش اضافه می‌شود.)
--   - user: INSERT ... ON CONFLICT (tenant_id, username) DO NOTHING — اگر کاربر
--     موجود باشد، بدونِ تغییر رد می‌شود.
--   اجرای دوباره با همان آرگومان‌ها: همان tenant_id بازگردانده می‌شود، بدونِ
--   duplicate و بدونِ خطا.
--
-- WHO CALLS THIS:
--   فقط لایهٔ اپ (onboarding_service.py) تصمیم می‌گیرد چه کسی می‌تواند این
--   تابع را صدا بزند. EXECUTE به platform_app گرنت شده — رولِ‌های دیگر (از
--   جمله clinical_app, accounting_app) به آن دسترسی ندارند.
--
-- وابستگی: بعد از slice0 (platform schema + رول‌ها) و slice5 (RLS).
-- idempotent: CREATE OR REPLACE + UNIQUE IF NOT EXISTS + REVOKE/GRANT ایمن‌اند.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- ۱) اضافه‌کردنِ UNIQUE constraint روی platform.tenants.name (برای idempotency)
--    additive و idempotent: اگر constraint وجود داشته باشد خطا نمی‌دهد.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM   pg_constraint c
        JOIN   pg_namespace n ON n.oid = c.connamespace
        WHERE  n.nspname = 'platform'
          AND  c.conrelid = 'platform.tenants'::regclass
          AND  c.conname  = 'uq_tenants_name'
    ) THEN
        ALTER TABLE platform.tenants ADD CONSTRAINT uq_tenants_name UNIQUE (name);
        RAISE NOTICE 'UNIQUE constraint uq_tenants_name added to platform.tenants';
    ELSE
        RAISE NOTICE 'UNIQUE constraint uq_tenants_name already exists — skipped';
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- ۱b) بازنشانیِ sequenceِ platform.tenants برای idempotency
--
-- slice0 از INSERT ... (id, name) VALUES (1, ...) استفاده می‌کند — id صریح.
-- وقتی id صریح داده می‌شود، IDENTITY sequenceِ BY DEFAULT جابجا نمی‌شود.
-- اولین INSERT بدونِ id صریح (provisioning) باقیمانده sequence را از 1 شروع
-- می‌کند و با tenant id=1 موجود conflict می‌کند.
-- راه‌حل: sequence را به max(id)+1 بازنشانی کن — idempotent و ایمن.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    v_max_id BIGINT;
BEGIN
    SELECT COALESCE(MAX(id), 1) INTO v_max_id FROM platform.tenants;
    -- SETVAL(seq, val, is_called=true) → بعدی از val+1 شروع می‌شود
    PERFORM setval(
        pg_get_serial_sequence('platform.tenants', 'id'),
        v_max_id,
        true   -- is_called=true: nextval از v_max_id+1 شروع می‌شود
    );
    RAISE NOTICE 'platform.tenants sequence reset to % (next will be %)', v_max_id, v_max_id + 1;
END
$$;

-- ---------------------------------------------------------------------------
-- ۲) تابعِ provisioning — SECURITY DEFINER
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION platform.provision_tenant(
    p_name            TEXT,
    p_admin_username  TEXT,
    p_password_hash   BYTEA,
    p_admin_full_name TEXT DEFAULT NULL
)
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = platform, pg_temp
AS $$
/*
    ایجادِ idempotentِ یک tenant و کاربرِ مدیرِ آن.

    آرگومان‌ها:
        p_name            — نامِ tenant (کلیدِ طبیعیِ idempotency؛ UNIQUE)
        p_admin_username  — نامِ کاربری مدیرِ اولیه
        p_password_hash   — bcrypt hash آماده (BYTEA) — رمزِ متنی وارد نمی‌شود
        p_admin_full_name — نامِ کاملِ مدیر (اختیاری)

    خروجی: tenant_id (همیشه یک عددِ مثبت ≥ 2، چون tenant 1 از پیش موجود است)

    جریانِ کار:
        ۱) tenant را idempotent اضافه کن (ON CONFLICT name → DO NOTHING)
        ۲) tenant_id موجود یا تازه‌ساخته را بگیر
        ۳) کاربرِ مدیر را idempotent اضافه کن (ON CONFLICT (tenant_id, username) → DO NOTHING)
        ۴) tenant_id را برگردان

    ایمنی:
        - RLS توسطِ SECURITY DEFINER دور زده می‌شود (فقط در این تابع)
        - هیچ SQL injection: از %L / placeholderهای parameterized استفاده نمی‌شود
          (مستقیماً با VALUES + متغیر PL/pgSQL که type-safe است)
        - رولِ platform_app نمی‌تواند این تابع را بدونِ EXECUTE GRANT فراخوانی کند
*/
DECLARE
    v_tenant_id BIGINT;
BEGIN
    -- ── گامِ ۱: tenant را idempotent بساز ──────────────────────────────────
    -- قبل از INSERT، sequence را به max(id) بازنشانی کن.
    -- این لازم است چون seed‌هایی که id صریح می‌دهند (مثل: INSERT ... (id, name) VALUES (1, ...))
    -- sequenceِ IDENTITY را جلو نمی‌برند. بدونِ این بازنشانی، nextval ممکن است با
    -- یک id موجود conflict کند.
    PERFORM setval(
        pg_get_serial_sequence('platform.tenants', 'id'),
        (SELECT COALESCE(MAX(id), 0) FROM platform.tenants),
        true   -- is_called: nextval از max+1 شروع می‌شود
    );

    INSERT INTO platform.tenants (name, is_active)
    VALUES (p_name, TRUE)
    ON CONFLICT (name) DO NOTHING;

    -- tenant_id را بگیر (چه تازه درج‌شده، چه موجود)
    SELECT id INTO v_tenant_id
    FROM   platform.tenants
    WHERE  name = p_name;

    IF v_tenant_id IS NULL THEN
        RAISE EXCEPTION 'provision_tenant: نتوانست tenant_id برای name=% پیدا کند', p_name;
    END IF;

    -- ── گامِ ۲: کاربرِ مدیر را idempotent بساز ────────────────────────────
    -- role='manager': نقشِ واقعیِ مدیرِ tenant در platform.users
    --   (از CHECK(role IN ('admin','manager','reception','doctor','staff')) در slice0)
    -- app='platform': این کاربر از مسیرِ halqe وارد می‌شود
    INSERT INTO platform.users (
        tenant_id,
        username,
        password_hash,
        role,
        app,
        full_name,
        is_active,
        failed_attempts
    )
    VALUES (
        v_tenant_id,
        p_admin_username,
        p_password_hash,
        'manager',
        'platform',
        p_admin_full_name,
        TRUE,
        0
    )
    ON CONFLICT (tenant_id, username) DO NOTHING;
    -- تفسیرِ idempotency: اگر کاربر موجود است، رمز را تغییر نمی‌دهیم.
    -- این عمداً انتخاب شده: re-provisioning نباید رمزِ موجود را overwrite کند.
    -- برای reset رمز، یک تابعِ جداگانه (reset_password) بنویسید.

    RETURN v_tenant_id;
END;
$$;

-- ---------------------------------------------------------------------------
-- ۳) مدیریتِ دسترسی — فقط platform_app می‌تواند این تابع را صدا بزند
-- ---------------------------------------------------------------------------

-- از PUBLIC حذف کن (پیش‌فرضِ Postgres برای CREATEد تابع است)
REVOKE ALL ON FUNCTION platform.provision_tenant(TEXT, TEXT, BYTEA, TEXT) FROM PUBLIC;

-- فقط به platform_app گرنت بده (که platform_login_test و رول‌های appِ دیگر از آن ارث می‌برند)
GRANT EXECUTE ON FUNCTION platform.provision_tenant(TEXT, TEXT, BYTEA, TEXT) TO platform_app;

-- ============================================================================
-- معیارِ «انجام‌شدهٔ» برشِ ۶:
--   ۱) platform.tenants.uq_tenants_name وجود دارد (UNIQUE روی name).
--   ۲) platform.provision_tenant در pg_proc با proowner=superuser موجود است.
--   ۳) رولِ platform_app حقِ EXECUTE دارد؛ PUBLIC ندارد.
--   ۴) فراخوانیِ تابع از رولِ platform_app → tenant + user ساخته می‌شود.
--   ۵) فراخوانیِ دوباره با همان name → همان tenant_id، بدونِ خطا.
--   ۶) کاربرِ ساخته‌شده با auth_service.login قابلِ ورود است (bcrypt معتبر).
--   ۷) tenant_id برگشتی ≠ 1 (نشتِ به tenant پیش‌فرض نشده است).
-- ============================================================================
