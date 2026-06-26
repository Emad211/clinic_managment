-- ============================================================================
-- schema_pg_slice12_patient_card_tokens.sql
-- برشِ ۱۲ — توکنِ کارتِ عمومیِ بیمار (خوشهٔ J — قدم ۴۴)
--
-- هدف:
--   ایجادِ سطحِ PHIِ رو-به-بیمار (patient-facing card) با توکنِ opaque و کوتاه‌عمر.
--   endpoint عمومیِ /card/{token} بدونِ JWT کار می‌کند، بنابراین GUCِ tenant
--   هنوز ست نیست — RLS روی جدولِ توکن این lookup را block می‌کند.
--   راهِ حل (مثلِ slice7): تابعِ SECURITY DEFINER که RLS را فقط برای resolve
--   عبور می‌دهد، سپس endpoint با GUC ست‌شده دادهٔ بالینی را (tenant-scoped) می‌خواند.
--
-- معماریِ امنیتی (قفل‌شده با security-privacy-advisor):
--   ۱) clinical.patient_card_tokens: جدول با RLS FORCE (staff issue/revoke از GUC می‌گذرد).
--   ۲) clinical.card_resolve_token(p_token text): SECURITY DEFINER — RLS bypass فقط
--      برای lookup معتبر؛ بدنه: token + NOT revoked + NOT expired → (patient_link_id, tenant_id).
--   ۳) endpoint عمومی: resolve → اگر None → 404؛ وگرنه set_tenant_guc(tenant_id) →
--      projection → zero-write.
--
-- گِیتِ LAN-vs-internet (ثبت‌شده، internet غیرفعال):
--   مواجهه با اینترنت نیازِ TLS + rate-limitِ توزیع‌شده + TTLِ کوتاه‌تر + آنتروپیِ
--   بیشتر دارد. مسیرِ SMS-link نساخته‌ایم (KYC بلاک). این slice فقط LAN (QR/tablet)
--   را پشتیبانی می‌کند. وقتی KYC تمام شد و VPS ایران آماده شد، internet را باز کن.
--
-- وابستگی: بعد از slice0 (رول‌ها) + slice2 (clinical schema + patient_links) +
--          slice5 (RLS).
-- ترتیب: numeric 12 → بعد از slice11 اعمال می‌شود.
-- idempotent: CREATE TABLE IF NOT EXISTS + CREATE OR REPLACE FUNCTION +
--             CREATE INDEX IF NOT EXISTS + DROP POLICY IF EXISTS + CREATE POLICY.
-- ============================================================================

-- ###########################################################################
-- ۱) جدولِ clinical.patient_card_tokens
--
--    یک توکنِ opaque (secrets.token_urlsafe(32)) به ازایِ هر بیمار.
--    ستون‌ها:
--      tenant_id     : مستأجر (RLS کلید اصلی)
--      patient_link_id: FK → clinical.patient_links(id)
--      token         : رشتهٔ opaque؛ UNIQUE — برای lookup در O(log n)
--      issued_at     : زمانِ صدور (TIMESTAMPTZ، now() پیش‌فرض)
--      expires_at    : انقضا (TTL کوتاه؛ LAN: ۸–۲۴h؛ آینده: SMS-link ≤ ۲۴h)
--      revoked_at    : زمانِ revoke؛ NULL = هنوز فعال
--      issued_by     : نامِ کاربرِ staff که توکن را صادر کرده
--
--    national_id اینجا ذخیره نمی‌شود. توکن صرفاً یک شناسهٔ opaque است.
-- ###########################################################################

CREATE TABLE IF NOT EXISTS clinical.patient_card_tokens (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       BIGINT NOT NULL,
    patient_link_id BIGINT NOT NULL,
    token           TEXT   NOT NULL,
    issued_at       TIMESTAMPTZ DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    revoked_at      TIMESTAMPTZ,
    issued_by       TEXT,
    CONSTRAINT uq_card_token UNIQUE (token),
    CONSTRAINT fk_card_token_patient_link
        FOREIGN KEY (patient_link_id)
        REFERENCES clinical.patient_links(id)
        ON DELETE CASCADE
);

-- ایندکسِ اصلی: lookup توکن در مسیرِ عمومی (O(log n))
CREATE INDEX IF NOT EXISTS idx_patient_card_tokens_token
    ON clinical.patient_card_tokens (token);

-- ایندکسِ کمکی: یافتنِ توکنِ فعالِ یک بیمار (برای staff UI / one-active-at-a-time)
CREATE INDEX IF NOT EXISTS idx_patient_card_tokens_patient_active
    ON clinical.patient_card_tokens (tenant_id, patient_link_id)
    WHERE revoked_at IS NULL;

-- ###########################################################################
-- ۲) RLS روی clinical.patient_card_tokens
--
--    RLS + FORCE: مسیرِ staffِ issue/revoke که GUC دارد، policy را رعایت می‌کند.
--    مسیرِ عمومیِ بدونِ GUC از card_resolve_token (SECURITY DEFINER) استفاده می‌کند.
--
--    FORCE: مالکِ جدول (superuser) نیز تابعِ policy باشد — مثلِ دیگر جداولِ clinical.
-- ###########################################################################

ALTER TABLE clinical.patient_card_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinical.patient_card_tokens FORCE ROW LEVEL SECURITY;

-- حذفِ policy قدیمی (idempotency)
DROP POLICY IF EXISTS tenant_isolation ON clinical.patient_card_tokens;

CREATE POLICY tenant_isolation ON clinical.patient_card_tokens
    FOR ALL
    USING      (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::bigint)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::bigint);

-- ###########################################################################
-- ۳) GRANTها — clinical.patient_card_tokens
--
--    platform_app و clinical_app: SELECT + INSERT + UPDATE (برای revoke).
--    DELETE عمداً نمی‌دهیم — revoke فقط revoked_at را ست می‌کند (audit trail).
-- ###########################################################################

GRANT SELECT, INSERT, UPDATE ON clinical.patient_card_tokens TO platform_app;
GRANT SELECT, INSERT, UPDATE ON clinical.patient_card_tokens TO clinical_app;
GRANT USAGE, SELECT ON SEQUENCE clinical.patient_card_tokens_id_seq TO platform_app;
GRANT USAGE, SELECT ON SEQUENCE clinical.patient_card_tokens_id_seq TO clinical_app;

-- ###########################################################################
-- ۴) clinical.card_resolve_token — SECURITY DEFINER
--
--    امضا:
--      clinical.card_resolve_token(p_token text)
--      RETURNS TABLE(patient_link_id bigint, tenant_id bigint)
--
--    هدف:
--      endpoint عمومیِ /card/{token} (بدونِ GUC) می‌تواند این تابع را صدا بزند تا
--      patient_link_id و tenant_id را برای توکنِ معتبر به‌دست آورد.
--      تابع RLS را bypass می‌کند (SECURITY DEFINER = با هویتِ مالک / BYPASSRLS اجرا می‌شود).
--      اما فقط ستون‌های کمینه و فقط برای توکنِ NOT revoked + NOT expired برمی‌گرداند.
--      اگر توکن وجود نداشته باشد، منقضی یا revoke‌شده باشد → صفر ردیف.
--
--    WHY SECURITY DEFINER:
--      مسیرِ عمومی همان chicken-and-egg مشکلِ slice7 را دارد: برای ست‌کردنِ GUC
--      نیاز به tenant_id داریم؛ برای خواندنِ tenant_id از جدولِ توکن (که RLS دارد)
--      نیاز به GUC داریم. SECURITY DEFINER این دورِ باطل را می‌شکند: تابع با
--      هویتِ مالک اجرا می‌شود که BYPASSRLS دارد — اما فقط کمینهٔ لازم برمی‌گرداند.
--
--    WHY STABLE:
--      این تابع فقط SELECT (بدونِ تغییرِ داده) → STABLE صحیح است.
--
--    WHY SET search_path = clinical, pg_temp:
--      جلوگیری از injection از طریقِ تابع‌های trojan در schema دیگر.
--
--    OWNER: superuser (sliceها با superuser اجرا می‌شوند → owner به‌صورتِ
--      خودکار superuser است = BYPASSRLS دارد).
-- ###########################################################################

CREATE OR REPLACE FUNCTION clinical.card_resolve_token(p_token TEXT)
RETURNS TABLE(patient_link_id BIGINT, tenant_id BIGINT)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = clinical, pg_temp
AS $$
    /*
        رزولوِ توکنِ کارتِ عمومیِ بیمار — بدونِ GUC.

        چرا SECURITY DEFINER:
            endpoint عمومیِ /card/{token} بدونِ JWT است → GUC ست نیست →
            RLS روی clinical.patient_card_tokens fail-closed → lookup صفر.
            این تابع با هویتِ مالک (BYPASSRLS) اجرا می‌شود و فقط
            (patient_link_id, tenant_id) را برمی‌گرداند.
            endpoint سپس set_tenant_guc(tenant_id) می‌زند و داده را
            تحتِ RLS (tenant-scoped) می‌خواند.

        چرا فقط این دو ستون:
            least-privilege — endpoint به هیچ اطلاعاتِ دیگری (مثلاً issued_by،
            expires_at، revoked_at) نیاز ندارد تا GUC را ست کند.

        چرا NOT revoked + NOT expired:
            هر دو شرط اینجا اعمال می‌شوند. اگر توکن منقضی یا revoke‌شده باشد
            → صفر ردیف → endpoint 404 برمی‌گرداند. مسیرِ عمومی هرگز نباید
            بداند آیا توکن وجود داشت یا منقضی شد (generic 404).
    */
    SELECT
        t.patient_link_id,
        t.tenant_id
    FROM clinical.patient_card_tokens t
    WHERE t.token = p_token
      AND t.revoked_at IS NULL
      AND t.expires_at > now();
$$;

-- ###########################################################################
-- ۵) مدیریتِ دسترسیِ تابع — فقط platform_app
--    PUBLIC نه — حداقلِ دسترسی
-- ###########################################################################

REVOKE ALL ON FUNCTION clinical.card_resolve_token(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION clinical.card_resolve_token(TEXT) TO platform_app;

-- ###########################################################################
-- ۶) گرنتِ clinical_app برای GRANTِ جدول (اگر clinical_app وجود دارد)
--    برخی استقرارها فقط platform_app دارند؛ DO $$ برای safety.
-- ###########################################################################

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'clinical_app') THEN
        EXECUTE 'GRANT EXECUTE ON FUNCTION clinical.card_resolve_token(TEXT) TO clinical_app';
    END IF;
END
$$;

-- ============================================================================
-- معیارِ «انجام‌شدهٔ» برشِ ۱۲ (برای تستِ نگهبان):
--   ۱) clinical.patient_card_tokens با ستون‌های مشخص وجود دارد.
--   ۲) UNIQUE constraint روی token وجود دارد.
--   ۳) FK به clinical.patient_links(id) با ON DELETE CASCADE وجود دارد.
--   ۴) RLS فعال + FORCE روی جدول.
--   ۵) policy tenant_isolation روی جدول وجود دارد.
--   ۶) ایندکس‌های idx_patient_card_tokens_token و idx_patient_card_tokens_patient_active موجودند.
--   ۷) clinical.card_resolve_token در pg_proc با SECURITY DEFINER + STABLE + owner=superuser.
--   ۸) PUBLIC حقِ EXECUTE روی تابع ندارد؛ platform_app دارد.
--   ۹) با GUC='' (بدونِ tenant)، تابع صفر ردیف برنمی‌گرداند اگر توکن معتبر است.
--      (تابع RLS را bypass می‌کند — این درست است: این هدفِ اصلیِ SECURITY DEFINER است)
--   ۱۰) idempotency: اجرای مجددِ این برش بدونِ خطا.
-- ============================================================================
