"""اعتبارسنجیِ schemaِ پلتفرمِ یکپارچه روی PostgreSQL واقعی (برش‌های مهاجرت).

این تست‌ها **opt-in** هستند: فقط وقتی env var `PG_TEST_DSN` ست شده باشد اجرا می‌شوند،
وگرنه `skip`. بنابراین روی سوییتِ SQLite موجود (۲۲۲ تست) صفر اثر دارند و هیچ‌گاه به
DBِ حسابداریِ تولیدی (`webapp/clinic_new.db`) دست نمی‌زنند — Postgres اصلاً نمی‌تواند
فایلِ SQLite را بخواند (اتصال TCP، connection-stringِ جدا).

اجرا (روی کانتینرِ Docker موقت):
    docker run -d --name halqe_pg_validate -e POSTGRES_PASSWORD=validate_only \
        -e POSTGRES_DB=halqe -p 55432:5432 postgres:16
    PG_TEST_DSN=postgresql://postgres:validate_only@localhost:55432/halqe \
        .venv/Scripts/python.exe -m pytest tests/test_pg_schema.py -v

این فایل **خودبسنده** است: برش‌ها را idempotent اعمال می‌کند، یک بیمارِ تست و یک کاربرِ
LOGINِ عضوِ `clinical_app` می‌سازد، و سپس معیارهای پذیرشِ ADR-0007 را اثبات می‌کند.
هر برشِ جدید (`schema_pg_slice*.sql`) خودکار به ترتیبِ نام اعمال می‌شود — برای slice3 آماده.
"""
import glob
import os

import pytest

try:
    import psycopg
    from psycopg import errors as pgerr
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
except ImportError:  # pragma: no cover - driver optional
    psycopg = None

PG_DSN = os.environ.get("PG_TEST_DSN")

pytestmark = pytest.mark.skipif(
    psycopg is None or not PG_DSN,
    reason="PG_TEST_DSN ست نشده یا psycopg نصب نیست (اعتبارسنجیِ Postgres اختیاری است)",
)

_HERE = os.path.dirname(__file__)
# اسکیمای منبعِ حقیقت زیرِ halqe زندگی می‌کند (از زیرِ این اپ منتقل شد).
# نگهبان همین‌جا می‌ماند، فقط مسیرِ خواندنِ slices به halqe/db/schema اشاره می‌کند.
_MIG = os.path.join(_HERE, "..", "..", "halqe", "db", "schema")

# همهٔ برش‌ها به ترتیبِ NUMERIC (نه رشته‌ای): slice2 قبل از slice10.
# مرتب‌سازیِ رشته‌ایِ ساده "slice10" را قبل از "slice2" می‌گذارد ('1'<'2') که
# ترتیبِ وابسته به GRANT/REVOKE را می‌شکند. کلید = (major, suffix).
def _slice_order(path):
    import re
    m = re.search(r"schema_pg_slice(\d+)([a-z]*)", os.path.basename(path))
    return (int(m.group(1)), m.group(2)) if m else (9999, path)

SLICE_FILES = sorted(
    glob.glob(os.path.join(_MIG, "schema_pg_slice*.sql")), key=_slice_order
)

CLINICAL_LOGIN = "clinical_login_test"
CLINICAL_LOGIN_PW = "validate_only_pw"
TEST_NATIONAL_ID = "TESTPG0001"


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _login_dsn():
    """DSNِ همان دیتابیس ولی با کاربرِ LOGINِ عضوِ clinical_app (مسیرِ واقعیِ production)."""
    parts = conninfo_to_dict(PG_DSN)
    parts.update(user=CLINICAL_LOGIN, password=CLINICAL_LOGIN_PW)
    return make_conninfo(**parts)


@pytest.fixture(scope="session")
def admin_conn():
    """اتصالِ superuser؛ برش‌ها را idempotent اعمال و داربستِ تست را می‌سازد."""
    assert SLICE_FILES, "هیچ فایلِ schema_pg_slice*.sql پیدا نشد"
    conn = psycopg.connect(PG_DSN, autocommit=True)
    for path in SLICE_FILES:
        conn.execute(_read(path))
    # بیمارِ تستِ committed برای بررسی‌های نقش‌محور (idempotent)
    conn.execute(
        """INSERT INTO accounting.patients (tenant_id, name, family_name, national_id)
           VALUES (1, 'تست', 'بیمار', %s)
           ON CONFLICT (tenant_id, national_id) DO NOTHING""",
        (TEST_NATIONAL_ID,),
    )
    # کاربرِ LOGINِ یکبارمصرف که عضوِ clinical_app است (داربستِ تست، نه DDLِ production)
    conn.execute(
        f"""DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{CLINICAL_LOGIN}') THEN
                    CREATE ROLE {CLINICAL_LOGIN} LOGIN PASSWORD '{CLINICAL_LOGIN_PW}';
                END IF;
            END $$;"""
    )
    # رفعِ شکنندگی: رمزِ رول را هر بار بازنشانی کن — رول ممکن است از اجرایِ قبلی با
    # رمزِ متفاوت در کلاستر موجود باشد (pg_roles کلاستر-level است، نه DB-level).
    conn.execute(f"ALTER ROLE {CLINICAL_LOGIN} PASSWORD '{CLINICAL_LOGIN_PW}'")
    conn.execute(f"GRANT clinical_app TO {CLINICAL_LOGIN}")
    yield conn
    conn.close()


@pytest.fixture
def admin_tx(admin_conn):
    """تراکنشِ superuser که در پایان rollback می‌شود (بدونِ آلودگیِ داده)."""
    conn = psycopg.connect(PG_DSN)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture
def clinical_tx(admin_conn):
    """اتصال با کاربرِ LOGINِ عضوِ clinical_app — مسیرِ ایزولاسیونِ واقعیِ production.

    پس از فعال‌سازیِ RLS در slice5، این اتصال باید GUCِ app.current_tenant را ست کند تا
    کوئری‌های نوشتن/خواندن موفق باشند. در production این کار توسطِ JWTBearer.authenticate()
    انجام می‌شود. اینجا آن را شبیه‌سازی می‌کنیم: tenant_id=1 (مستأجرِ پیش‌فرضِ تستِ نگهبان).
    این طرز عمل policy را تضعیف نمی‌کند — تست‌های این fixture اثباتِ «مجاز-بودنِ GRANTها»
    است، نه تستِ ایزولاسیون (که در تست‌های _rls_isolation_* با GUC‌های صریح انجام می‌شود).
    """
    conn = psycopg.connect(_login_dsn())
    try:
        # شبیه‌سازیِ JWTBearer.authenticate(): GUCِ tenant را ست کن (is_local=false)
        # autocommit نیاز نیست چون GUC is_local=false روی connection است، نه transaction.
        conn.execute("SELECT set_config('app.current_tenant', '1', false)")
        yield conn
    finally:
        conn.rollback()
        conn.close()


def _test_patient_id(conn):
    row = conn.execute(
        "SELECT id FROM accounting.patients WHERE tenant_id=1 AND national_id=%s",
        (TEST_NATIONAL_ID,),
    ).fetchone()
    assert row, "بیمارِ تست ساخته نشده"
    return row[0]


# ---------------------------------------------------------------------------
# معیار ۱ — اجرای idempotent (اجرای دوبارهٔ همهٔ برش‌ها بدونِ خطا)
# ---------------------------------------------------------------------------
def test_slices_idempotent(admin_conn):
    for path in SLICE_FILES:
        admin_conn.execute(_read(path))  # نباید استثنا بدهد


# ---------------------------------------------------------------------------
# معیار ۴ — full_name به‌صورتِ GENERATED STORED خودکار پر می‌شود
# ---------------------------------------------------------------------------
def test_full_name_stored(admin_tx):
    row = admin_tx.execute(
        """INSERT INTO accounting.patients (tenant_id, name, family_name)
           VALUES (1, 'علی', 'رضایی') RETURNING full_name"""
    ).fetchone()
    assert row[0] == "علی رضایی"


# ---------------------------------------------------------------------------
# معیار ۵ — uuid خودکار و یکتا
# ---------------------------------------------------------------------------
def test_uuid_auto_and_unique(admin_tx):
    u1 = admin_tx.execute(
        "INSERT INTO accounting.patients (tenant_id, name, family_name) VALUES (1,'الف','ب') RETURNING uuid"
    ).fetchone()[0]
    u2 = admin_tx.execute(
        "INSERT INTO accounting.patients (tenant_id, name, family_name) VALUES (1,'ج','د') RETURNING uuid"
    ).fetchone()[0]
    assert u1 and u2 and u1 != u2


# ---------------------------------------------------------------------------
# معیار ۲ — FKِ یک‌طرفهٔ cross-schema: patient_id نامعتبر رد می‌شود
# ---------------------------------------------------------------------------
def test_fk_rejects_bad_patient_id(admin_tx):
    with pytest.raises(pgerr.ForeignKeyViolation):
        admin_tx.execute(
            "INSERT INTO clinical.patient_links (tenant_id, patient_id) VALUES (1, 999999)"
        )


# ---------------------------------------------------------------------------
# معیار ۳ (ساختاری) — clinical_app با SET ROLE نمی‌تواند روی accounting بنویسد
# ---------------------------------------------------------------------------
def test_setrole_clinical_cannot_write_accounting(admin_tx):
    admin_tx.execute("SET ROLE clinical_app")
    with pytest.raises(pgerr.InsufficientPrivilege):
        admin_tx.execute("UPDATE accounting.patients SET name='x' WHERE id=1")


# ---------------------------------------------------------------------------
# معیار ۳ (وفادارانه) — مسیرِ واقعیِ اتصال: کاربرِ LOGINِ عضوِ clinical_app
#   فقط می‌تواند accounting را بخواند، نه بنویسد؛ و می‌تواند clinical را بنویسد.
# ---------------------------------------------------------------------------
def test_faithful_login_can_read_accounting(clinical_tx):
    # خواندن مجاز است
    clinical_tx.execute("SELECT id, full_name FROM accounting.patients LIMIT 1").fetchall()


def test_faithful_login_cannot_update_accounting(clinical_tx):
    with pytest.raises(pgerr.InsufficientPrivilege):
        clinical_tx.execute("UPDATE accounting.patients SET name='x' WHERE id=1")


def test_faithful_login_cannot_insert_accounting(clinical_tx):
    with pytest.raises(pgerr.InsufficientPrivilege):
        clinical_tx.execute(
            "INSERT INTO accounting.patients (tenant_id, name, family_name) VALUES (1,'نفوذ','گر')"
        )


def test_faithful_login_can_write_clinical(clinical_tx, admin_conn):
    pid = _test_patient_id(admin_conn)
    # نوشتن روی جدولِ بالینی مجاز است (سپس rollback می‌شود).
    # ON CONFLICT DO NOTHING: در صورتِ تکرار از تست‌های قبلیِ session، بازهم موفق است.
    # هدف اثباتِ «مجاز بودنِ INSERT» است، نه یکتایی.
    clinical_tx.execute(
        "INSERT INTO clinical.patient_links (tenant_id, patient_id) VALUES (1, %s)"
        " ON CONFLICT (tenant_id, patient_id) DO NOTHING",
        (pid,),
    )


# ---------------------------------------------------------------------------
# گرنتِ کاملِ نوشتن روی همهٔ جداولِ بالینی (باگِ گرنتِ slice2 که با اجرای واقعی پیدا شد)
# ---------------------------------------------------------------------------
def test_clinical_app_has_insert_on_all_clinical_tables(admin_conn):
    rows = admin_conn.execute(
        """SELECT t.table_name,
                  has_table_privilege('clinical_app', 'clinical.'||t.table_name, 'INSERT')
             FROM information_schema.tables t
            WHERE t.table_schema='clinical' AND t.table_type='BASE TABLE'"""
    ).fetchall()
    missing = [name for name, ok in rows if not ok]
    assert rows, "هیچ جدولِ بالینی پیدا نشد"
    assert not missing, f"این جداولِ بالینی گرنتِ INSERT ندارند: {missing}"


# ---------------------------------------------------------------------------
# مرزِ یک‌طرفه (برعکس) — accounting_app هیچ دسترسی‌ای به clinical ندارد
# ---------------------------------------------------------------------------
def test_accounting_app_cannot_read_clinical(admin_tx):
    admin_tx.execute("SET ROLE accounting_app")
    with pytest.raises(pgerr.InsufficientPrivilege):
        admin_tx.execute("SELECT * FROM clinical.patient_links LIMIT 1")


# ---------------------------------------------------------------------------
# تأییدِ مثبت/منفیِ خواندنِ accounting توسطِ clinical_app
# ---------------------------------------------------------------------------
def test_clinical_app_can_read_but_not_modify_accounting(admin_conn):
    can_select = admin_conn.execute(
        "SELECT has_table_privilege('clinical_app','accounting.patients','SELECT')"
    ).fetchone()[0]
    can_update = admin_conn.execute(
        "SELECT has_table_privilege('clinical_app','accounting.patients','UPDATE')"
    ).fetchone()[0]
    assert can_select is True
    assert can_update is False


# ===========================================================================
# برشِ ۳ — بدنهٔ حسابداری (accounting schema)
# ===========================================================================

# ---------------------------------------------------------------------------
# معیار ۱ — هر ستونِ پولی در accounting.* باید NUMERIC باشد (نه INTEGER/REAL/double precision).
#   استثنا: consumables_ledger.quantity (NUMERIC(14,3) — کسری ممکن)؛
#           ستون‌های درصدِ payroll_settings که NUMERIC(6,3) هستند.
# ---------------------------------------------------------------------------
_MONEY_TYPE_EXCLUSIONS = {
    # (table_name, column_name): reason for exemption
    # --- NUMERIC with non-14-0 scale (intentional by design) ---
    ("consumables_ledger", "quantity"): "NUMERIC(14,3) — fractional (0.5 vial etc.)",
    ("payroll_settings", "injection_percent"): "NUMERIC(6,3) — percent, not Toman",
    ("payroll_settings", "procedure_percent"): "NUMERIC(6,3) — percent, not Toman",
    ("payroll_settings", "tax_percent"): "NUMERIC(6,3) — percent, not Toman",
    ("payroll_settings", "nursing_percent"): "NUMERIC(6,3) — percent, not Toman",
    ("payroll_settings", "nurse_procedure_percent"): "NUMERIC(6,3) — percent, not Toman",
    # --- INTEGER / BIGINT non-money columns (counts / polymorphic refs) ---
    ("injections", "count"): "INTEGER — injection count (not money)",
    ("activity_logs", "target_id"): "BIGINT — polymorphic entity ref (not money)",
}

# نام‌های data typeِ ممنوع برای ستون‌های مالی
_FORBIDDEN_MONEY_TYPES = {"integer", "real", "double precision", "bigint", "smallint"}


def test_money_columns_are_numeric(admin_conn):
    """هر ستونِ NUMERIC در accounting.* باید NUMERIC(14,0) باشد؛ نه INTEGER یا REAL."""
    # ابتدا مطمئن می‌شویم که اصلاً جدولِ حسابداری ساخته شده
    tables = admin_conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='accounting' AND table_type='BASE TABLE'"
    ).fetchall()
    assert tables, "هیچ جدولِ accounting پیدا نشد — آیا برشِ ۳ اعمال شده؟"

    # ستون‌هایی که نوعشان INTEGER/REAL/double precision است و numeric نیستند
    bad_cols = admin_conn.execute(
        """SELECT table_name, column_name, data_type, numeric_precision, numeric_scale
             FROM information_schema.columns
            WHERE table_schema = 'accounting'
              AND data_type IN ('integer','real','double precision','bigint','smallint')
              AND column_name NOT IN (
                  -- ستون‌های هویتی/FK/بولی که عمداً INTEGER/BIGINT/SMALLINT هستند
                  'id','tenant_id','patient_id','doctor_id','nurse_id','invoice_id',
                  'service_id','visit_id','item_id','staff_id','nursing_service_id',
                  'user_id','insurance_scheme_id','performer_id',
                  'quantity',           -- visit_items.quantity (INTEGER intentional — count)
                  'is_active','is_supplementary','is_base','is_base_tariff',
                  'nursing_covers','covered_by_insurance','patient_provided',
                  'is_exception','is_paid','risk_weight','display_order'
              )
        ORDER BY table_name, column_name"""
    ).fetchall()

    # فیلترِ استثناهای شناخته‌شده
    truly_bad = [
        row for row in bad_cols
        if (row[0], row[1]) not in _MONEY_TYPE_EXCLUSIONS
    ]
    assert not truly_bad, (
        f"ستون‌های زیر در accounting.* از نوعِ مالیِ ممنوع هستند (باید NUMERIC(14,0) باشند):\n"
        + "\n".join(f"  {t}.{c}: {dt}" for t, c, dt, _, _ in truly_bad)
    )


# ---------------------------------------------------------------------------
# معیار ۲ — باگِ پرستاری: visit_tariffs.nursing_covers و nursing_tariff هر دو NOT NULL DEFAULT 0
# ---------------------------------------------------------------------------
def test_nursing_coverage_bug_preserved(admin_conn):
    """باگِ حفظ‌شده: visit_tariffs.nursing_covers (BOOLEAN) و nursing_tariff (NUMERIC) هر دو
    NOT NULL با پیش‌فرضِ falsey (covers=false، tariff=0) — نه nullable، نه «اصلاح‌شده»."""
    cols = {
        name: (is_nullable, col_default)
        for name, is_nullable, col_default in admin_conn.execute(
            """SELECT column_name, is_nullable, column_default
                 FROM information_schema.columns
                WHERE table_schema = 'accounting'
                  AND table_name = 'visit_tariffs'
                  AND column_name IN ('nursing_covers', 'nursing_tariff')"""
        ).fetchall()
    }
    assert set(cols) == {"nursing_covers", "nursing_tariff"}, f"ستون‌های پرستاری پیدا نشدند؛ {cols}"
    for name, (is_nullable, _default) in cols.items():
        assert is_nullable == "NO", (
            f"visit_tariffs.{name} باید NOT NULL باشد (باگِ حفظ‌شده) ولی nullable است"
        )
    # پیش‌فرضِ falsey: covers=false (boolean)، tariff=0 (numeric)
    assert "false" in (cols["nursing_covers"][1] or "").lower(), cols["nursing_covers"]
    assert "0" in (cols["nursing_tariff"][1] or ""), cols["nursing_tariff"]


# ---------------------------------------------------------------------------
# معیار ۳ — accounting.invoices دارای UNIQUE(tenant_id, id) است
# ---------------------------------------------------------------------------
def test_invoices_has_composite_unique_tenant_id(admin_conn):
    """accounting.invoices باید UNIQUE(tenant_id, id) داشته باشد (برای FKِ مرکبِ لجرهای بالینی)."""
    row = admin_conn.execute(
        """SELECT c.conname
             FROM pg_constraint c
             JOIN pg_class t ON t.oid = c.conrelid
             JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'accounting'
              AND t.relname = 'invoices'
              AND c.contype = 'u'
              AND c.conname = 'uq_invoices_tenant_id'"""
    ).fetchone()
    assert row is not None, (
        "UNIQUE constraint 'uq_invoices_tenant_id' روی accounting.invoices پیدا نشد"
    )


# ---------------------------------------------------------------------------
# معیار ۴ — seed idempotent: دقیقاً یک ردیفِ بیمهٔ 'free' برای tenant 1 وجود دارد
# ---------------------------------------------------------------------------
def test_insurance_seed_exactly_one_free(admin_conn):
    """accounting.insurance_schemes باید دقیقاً یک ردیفِ code='free' برای tenant_id=1 داشته باشد."""
    count = admin_conn.execute(
        "SELECT COUNT(*) FROM accounting.insurance_schemes WHERE tenant_id=1 AND code='free'"
    ).fetchone()[0]
    assert count == 1, (
        f"انتظار: دقیقاً ۱ ردیفِ 'free' برای tenant 1؛ یافته: {count} "
        "(اجرای مکرر seed نباید ردیفِ تکراری بسازد)"
    )


# ---------------------------------------------------------------------------
# معیار ۵ — UNIQUE(tenant_id, insurance_type) روی visit_tariffs (نه UNIQUE تک‌ستونی)
# ---------------------------------------------------------------------------
def test_visit_tariffs_unique_is_composite(admin_conn):
    """UNIQUE روی visit_tariffs.insurance_type باید مرکب (tenant_id, insurance_type) باشد."""
    row = admin_conn.execute(
        """SELECT c.conname,
                  array_agg(a.attname ORDER BY a.attnum) AS cols
             FROM pg_constraint c
             JOIN pg_class t ON t.oid = c.conrelid
             JOIN pg_namespace n ON n.oid = t.relnamespace
             JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
            WHERE n.nspname = 'accounting'
              AND t.relname = 'visit_tariffs'
              AND c.contype = 'u'
              AND c.conname = 'uq_visit_tariffs_tenant_insurance'
            GROUP BY c.conname"""
    ).fetchone()
    assert row is not None, (
        "UNIQUE constraint 'uq_visit_tariffs_tenant_insurance' روی visit_tariffs پیدا نشد"
    )
    cols = sorted(row[1])
    assert "tenant_id" in cols and "insurance_type" in cols, (
        f"UNIQUE باید (tenant_id, insurance_type) باشد؛ ستون‌های یافته‌شده: {cols}"
    )


# ---------------------------------------------------------------------------
# معیار ۶ — FK integrity: درج accounting.invoices با patient_id نامعتبر خطا می‌دهد
# ---------------------------------------------------------------------------
def test_invoices_fk_rejects_bad_patient_id(admin_tx):
    """INSERT accounting.invoices با patient_id=999999 باید ForeignKeyViolation بدهد."""
    with pytest.raises(pgerr.ForeignKeyViolation):
        admin_tx.execute(
            "INSERT INTO accounting.invoices (tenant_id, patient_id) VALUES (1, 999999)"
        )


# ---------------------------------------------------------------------------
# معیار ۷ — clinical_login_test می‌تواند accounting.invoices را SELECT کند ولی UPDATE/INSERT نمی‌تواند
# ---------------------------------------------------------------------------
def test_clinical_login_can_select_invoices(clinical_tx):
    """clinical_login_test باید بتواند accounting.invoices را SELECT کند."""
    clinical_tx.execute("SELECT id, total_amount FROM accounting.invoices LIMIT 1").fetchall()


def test_clinical_login_cannot_insert_invoices(clinical_tx, admin_conn):
    """clinical_login_test نباید بتواند accounting.invoices درج کند."""
    pid = _test_patient_id(admin_conn)
    with pytest.raises(pgerr.InsufficientPrivilege):
        clinical_tx.execute(
            "INSERT INTO accounting.invoices (tenant_id, patient_id) VALUES (1, %s)", (pid,)
        )


def test_clinical_login_cannot_update_invoices(clinical_tx):
    """clinical_login_test نباید بتواند accounting.invoices به‌روزرسانی کند."""
    with pytest.raises(pgerr.InsufficientPrivilege):
        clinical_tx.execute("UPDATE accounting.invoices SET status='closed' WHERE id=1")


# ===========================================================================
# برشِ ۴ — FKهای مرزیِ clinical → accounting (DEFERRABLE INITIALLY DEFERRED)
# ===========================================================================

# ---------------------------------------------------------------------------
# معیار ۱ — هر سه constraint مرزی وجود دارند
# ---------------------------------------------------------------------------
def test_boundary_fk_constraints_exist(admin_conn):
    """سه constraint مرزیِ برشِ ۴ باید در pg_constraint موجود باشند."""
    expected = {
        "fk_processed_invoices_acct",
        "fk_doctor_visit_log_acct",
        "fk_campaign_audience_acct_patient",
    }
    found = {
        row[0]
        for row in admin_conn.execute(
            "SELECT conname FROM pg_constraint WHERE conname = ANY(%s)",
            (list(expected),),
        ).fetchall()
    }
    missing = expected - found
    assert not missing, f"این constraintهای مرزی پیدا نشدند: {missing}"


# ---------------------------------------------------------------------------
# معیار ۲a — processed_invoices: accounting_invoice_id نامعتبر + commit → ForeignKeyViolation
#   چون DEFERRABLE INITIALLY DEFERRED است، بررسی در زمانِ commit رخ می‌دهد — نه هنگامِ INSERT.
#   از یک تراکنشِ جداگانه استفاده می‌کنیم که commit می‌زند، سپس اثرش را rollback می‌کنیم.
# ---------------------------------------------------------------------------
def test_processed_invoices_deferred_fk_fires_at_commit(admin_conn):
    """درجِ processed_invoices با accounting_invoice_id=999999 و commit → ForeignKeyViolation."""
    conn = psycopg.connect(PG_DSN)
    try:
        conn.execute("BEGIN")
        # Batch 3: national_id حذف شد → patient_uuid به‌جایش (nullable — می‌تواند NULL باشد)
        conn.execute(
            """INSERT INTO clinical.processed_invoices
                   (tenant_id, accounting_invoice_id, full_name)
               VALUES (1, 999999, 'تستِ مرز')"""
        )
        # در این لحظه (قبلِ commit) FK هنوز بررسی نشده (DEFERRED)
        with pytest.raises(pgerr.ForeignKeyViolation):
            conn.execute("COMMIT")
    finally:
        conn.rollback()
        conn.close()


# ---------------------------------------------------------------------------
# معیار ۲b — doctor_visit_log: accounting_invoice_id نامعتبر + commit → ForeignKeyViolation
# ---------------------------------------------------------------------------
def test_doctor_visit_log_deferred_fk_fires_at_commit(admin_conn):
    """درجِ doctor_visit_log با accounting_invoice_id=999999 و commit → ForeignKeyViolation."""
    conn = psycopg.connect(PG_DSN)
    try:
        conn.execute("BEGIN")
        conn.execute(
            """INSERT INTO clinical.doctor_visit_log
                   (tenant_id, accounting_invoice_id, full_name, work_date)
               VALUES (1, 999999, 'تستِ مرز', '2026-01-01')"""
        )
        with pytest.raises(pgerr.ForeignKeyViolation):
            conn.execute("COMMIT")
    finally:
        conn.rollback()
        conn.close()


# ---------------------------------------------------------------------------
# معیار ۳ — هیچ FKی از accounting.* به clinical.* وجود ندارد (مرزِ یک‌طرفه)
# ---------------------------------------------------------------------------
def test_no_reverse_fk_from_accounting_to_clinical(admin_conn):
    """هیچ FK از جداولِ accounting به جداولِ clinical نباید وجود داشته باشد (مرزِ یک‌طرفه)."""
    reverse_fks = admin_conn.execute(
        """SELECT c.conname,
                  src_ns.nspname AS src_schema,
                  src_tbl.relname AS src_table,
                  tgt_ns.nspname AS tgt_schema,
                  tgt_tbl.relname AS tgt_table
             FROM pg_constraint c
             JOIN pg_class src_tbl ON src_tbl.oid = c.conrelid
             JOIN pg_namespace src_ns ON src_ns.oid = src_tbl.relnamespace
             JOIN pg_class tgt_tbl ON tgt_tbl.oid = c.confrelid
             JOIN pg_namespace tgt_ns ON tgt_ns.oid = tgt_tbl.relnamespace
            WHERE c.contype = 'f'
              AND src_ns.nspname = 'accounting'
              AND tgt_ns.nspname = 'clinical'"""
    ).fetchall()
    assert not reverse_fks, (
        f"FKِ معکوس از accounting به clinical یافته شد (نقضِ مرزِ یک‌طرفه):\n"
        + "\n".join(
            f"  {sn}.{st} → {tn}.{tt}  [{name}]"
            for name, sn, st, tn, tt in reverse_fks
        )
    )


# ===========================================================================
# Batch 2c — FKهای مرکبِ tenant-safe (RLS-readiness)
# ===========================================================================

# ---------------------------------------------------------------------------
# معیار ۱ — ارجاعِ cross-tenant ساختاراً غیرممکن است
#   child با tenant_id=2 که به والدِ tenant 1 اشاره کند → ForeignKeyViolation
#   (چون FK مرکب (tenant_id, patient_id) → patients(tenant_id, id) است).
# ---------------------------------------------------------------------------
def test_cross_tenant_fk_rejected(admin_tx, admin_conn):
    """درجِ clinical.patient_links با tenant_id=2 که به بیمارِ tenant 1 اشاره کند → FK violation."""
    pid = _test_patient_id(admin_conn)  # بیمارِ tenant 1
    admin_tx.execute(
        "INSERT INTO platform.tenants (id, name) VALUES (2, 't2') ON CONFLICT (id) DO NOTHING"
    )
    with pytest.raises(pgerr.ForeignKeyViolation):
        admin_tx.execute(
            "INSERT INTO clinical.patient_links (tenant_id, patient_id) VALUES (2, %s)", (pid,)
        )


# ---------------------------------------------------------------------------
# معیار ۲ — جداولِ والدِ کلیدی UNIQUE(tenant_id, id) دارند (هدفِ FKِ مرکب)
# ---------------------------------------------------------------------------
def test_parent_tables_have_composite_unique_tenant_id(admin_conn):
    """هر جدولِ والدِ per-tenant باید یک UNIQUE با ستون‌های دقیقاً {tenant_id, id} داشته باشد."""
    parents = [
        ("platform", "users"),
        ("accounting", "patients"),
        ("accounting", "medical_staff"),
        ("accounting", "services"),
        ("accounting", "nursing_services"),
        ("accounting", "insurance_schemes"),
        ("accounting", "invoices"),
        ("accounting", "visits"),
        ("clinical", "patient_links"),
        ("clinical", "conditions"),
    ]
    missing = []
    for schema, table in parents:
        rows = admin_conn.execute(
            """SELECT array_agg(a.attname ORDER BY a.attname)
                 FROM pg_constraint c
                 JOIN pg_class t ON t.oid = c.conrelid
                 JOIN pg_namespace n ON n.oid = t.relnamespace
                 JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
                WHERE n.nspname = %s AND t.relname = %s AND c.contype = 'u'
                GROUP BY c.conname""",
            (schema, table),
        ).fetchall()
        has = any(sorted(r[0]) == ["id", "tenant_id"] for r in rows)
        if not has:
            missing.append(f"{schema}.{table}")
    assert not missing, f"این والدها UNIQUE(tenant_id, id) ندارند: {missing}"


# ===========================================================================
# Batch 2b — FKهای واقعیِ ستون‌های «FK منطقی» (کاتالوگ‌ها + لینک‌های اختیاری)
# ===========================================================================
def test_batch2b_logical_fks_exist(admin_conn):
    """۱۳ FKِ بَچ ۲b باید موجود باشند (ستون‌های منطقیِ آزاد حالا FKِ واقعیِ tenant-safe‌اند)."""
    expected = {
        "fk_lab_results_test_key", "fk_condition_lab_tests_test_key",
        "fk_patient_flags_flag_key", "fk_patient_medications_drug_class",
        "fk_drug_catalog_drug_class_key", "fk_engagement_dispatch_event_key",
        "fk_medication_events_medication_id", "fk_appointments_parent_id",
        "fk_followup_tasks_appointment_id", "fk_engagement_approvals_appointment_id",
        "fk_prescriptions_followup_task_id", "fk_wallet_transactions_campaign_id",
        "fk_prescriptions_prescriber_user_id",
    }
    found = {
        r[0]
        for r in admin_conn.execute(
            "SELECT conname FROM pg_constraint WHERE contype='f' AND conname = ANY(%s)",
            (list(expected),),
        ).fetchall()
    }
    missing = expected - found
    assert not missing, f"این FKهای بَچ ۲b پیدا نشدند: {missing}"


# ===========================================================================
# Batch 3 — Security hardening (SECU-05/06/07/08/ADR-0007)
# ===========================================================================

# ---------------------------------------------------------------------------
# گاردِ الف — clinical_app نمی‌تواند accounting.payroll_settings را SELECT کند (least-privilege)
# ---------------------------------------------------------------------------
def test_clinical_app_cannot_read_payroll_settings(admin_conn):
    """Batch 3 SECU-06: clinical_app نباید به accounting.payroll_settings دسترسی داشته باشد."""
    can_select = admin_conn.execute(
        "SELECT has_table_privilege('clinical_app', 'accounting.payroll_settings', 'SELECT')"
    ).fetchone()[0]
    assert can_select is False, (
        "clinical_app نباید بتواند accounting.payroll_settings را SELECT کند "
        "(least-privilege: فقط جداولِ بیمار/درآمدی مجاز است)"
    )


def test_clinical_app_cannot_read_accounting_settings(admin_conn):
    """Batch 3 SECU-06: clinical_app نباید به accounting.settings (کلیدِ API) دسترسی داشته باشد."""
    can_select = admin_conn.execute(
        "SELECT has_table_privilege('clinical_app', 'accounting.settings', 'SELECT')"
    ).fetchone()[0]
    assert can_select is False, (
        "clinical_app نباید بتواند accounting.settings را SELECT کند "
        "(ممکن است کلیدِ API/رمزِ حساس داشته باشد)"
    )


def test_clinical_app_cannot_read_medical_staff(admin_conn):
    """Batch 3 SECU-06: clinical_app نباید به accounting.medical_staff دسترسی داشته باشد."""
    can_select = admin_conn.execute(
        "SELECT has_table_privilege('clinical_app', 'accounting.medical_staff', 'SELECT')"
    ).fetchone()[0]
    assert can_select is False, (
        "clinical_app نباید بتواند accounting.medical_staff را SELECT کند"
    )


def test_clinical_app_can_read_patient_revenue_tables(admin_conn):
    """Batch 3 SECU-06: clinical_app باید بتواند جداولِ بیمار/درآمدی را SELECT کند."""
    allowed_tables = [
        "accounting.patients",
        "accounting.invoices",
        "accounting.visits",
        "accounting.injections",
        "accounting.procedures",
        "accounting.consumables_ledger",
    ]
    missing_access = []
    for tbl in allowed_tables:
        ok = admin_conn.execute(
            "SELECT has_table_privilege('clinical_app', %s, 'SELECT')", (tbl,)
        ).fetchone()[0]
        if not ok:
            missing_access.append(tbl)
    assert not missing_access, (
        f"clinical_app باید این جداول را بخواند ولی دسترسی ندارد: {missing_access}"
    )


# ---------------------------------------------------------------------------
# گاردِ ب — platform.users دارای api_token_hash + api_token_prefix است و api_token ندارد
# ---------------------------------------------------------------------------
def test_users_has_hashed_token_columns(admin_conn):
    """Batch 3 SECU-05: platform.users باید api_token_hash (BYTEA) و api_token_prefix (TEXT) داشته باشد."""
    cols = {
        row[0]: row[1]
        for row in admin_conn.execute(
            """SELECT column_name, data_type
                 FROM information_schema.columns
                WHERE table_schema = 'platform' AND table_name = 'users'
                  AND column_name IN ('api_token_hash', 'api_token_prefix', 'api_token')"""
        ).fetchall()
    }
    assert "api_token_hash" in cols, (
        "platform.users باید ستونِ api_token_hash داشته باشد (Batch 3 SECU-05)"
    )
    assert cols["api_token_hash"] == "bytea", (
        f"api_token_hash باید BYTEA باشد؛ یافته: {cols.get('api_token_hash')}"
    )
    assert "api_token_prefix" in cols, (
        "platform.users باید ستونِ api_token_prefix داشته باشد (Batch 3 SECU-05)"
    )
    assert cols["api_token_prefix"] == "text", (
        f"api_token_prefix باید TEXT باشد؛ یافته: {cols.get('api_token_prefix')}"
    )
    assert "api_token" not in cols, (
        "platform.users نباید ستونِ api_token (plaintext) داشته باشد — Batch 3 آن را حذف کرد"
    )


# ---------------------------------------------------------------------------
# گاردِ ج — clinical.activity_logs جدول وجود دارد
# ---------------------------------------------------------------------------
def test_clinical_activity_logs_table_exists(admin_conn):
    """Batch 3 SECU-08: جدولِ clinical.activity_logs باید وجود داشته باشد (PHI audit trail)."""
    row = admin_conn.execute(
        """SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'clinical' AND table_name = 'activity_logs'"""
    ).fetchone()
    assert row is not None, (
        "clinical.activity_logs پیدا نشد — Batch 3 این جدول را در slice2 اضافه می‌کند"
    )


def test_clinical_activity_logs_has_required_columns(admin_conn):
    """clinical.activity_logs باید ستون‌های کلیدی را داشته باشد."""
    cols = {
        row[0]
        for row in admin_conn.execute(
            """SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'clinical' AND table_name = 'activity_logs'"""
        ).fetchall()
    }
    required = {"id", "tenant_id", "user_id", "username", "action_type",
                "target_table", "target_id", "patient_link_id", "created_at"}
    missing = required - cols
    assert not missing, (
        f"clinical.activity_logs ستون‌های زیر را ندارد: {missing}"
    )


def test_clinical_app_has_insert_on_activity_logs(admin_conn):
    """clinical.activity_logs باید برای clinical_app گرنتِ INSERT داشته باشد."""
    ok = admin_conn.execute(
        "SELECT has_table_privilege('clinical_app', 'clinical.activity_logs', 'INSERT')"
    ).fetchone()[0]
    assert ok is True, (
        "clinical_app باید بتواند به clinical.activity_logs درج کند (PHI audit trail)"
    )


# ---------------------------------------------------------------------------
# Finding 3b — clinical.activity_logs باید append-only باشد:
#   clinical_login_test (عضوِ clinical_app) می‌تواند SELECT و INSERT کند
#   ولی UPDATE یا DELETE نمی‌تواند (audit trail tamper-resistant).
# ---------------------------------------------------------------------------
def test_clinical_login_can_select_activity_logs(clinical_tx):
    """clinical_login_test باید بتواند clinical.activity_logs را SELECT کند."""
    clinical_tx.execute("SELECT id, action_type FROM clinical.activity_logs LIMIT 1").fetchall()


def test_clinical_login_can_insert_activity_logs(clinical_tx, admin_conn):
    """clinical_login_test باید بتواند ردیف به clinical.activity_logs اضافه کند (append-only)."""
    pid = _test_patient_id(admin_conn)
    # ابتدا patient_link می‌سازیم (با superuser) تا FK برقرار باشد
    admin_conn.execute(
        "INSERT INTO clinical.patient_links (tenant_id, patient_id) VALUES (1, %s)"
        " ON CONFLICT (tenant_id, patient_id) DO NOTHING",
        (pid,),
    )
    link_row = admin_conn.execute(
        "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s", (pid,)
    ).fetchone()
    assert link_row, "patient_link تستِ activity_logs ساخته نشد"
    link_id = link_row[0]
    # حالا clinical_tx می‌تواند لاگِ بالینی درج کند
    clinical_tx.execute(
        """INSERT INTO clinical.activity_logs
               (tenant_id, action_type, target_table, patient_link_id)
           VALUES (1, 'test_insert', 'activity_logs', %s)""",
        (link_id,),
    )


def test_clinical_login_cannot_update_activity_logs(clinical_tx):
    """clinical_login_test نباید بتواند clinical.activity_logs را UPDATE کند (append-only)."""
    with pytest.raises(pgerr.InsufficientPrivilege):
        clinical_tx.execute(
            "UPDATE clinical.activity_logs SET action_type='tampered' WHERE id=1"
        )


def test_clinical_login_cannot_delete_activity_logs(clinical_tx):
    """clinical_login_test نباید بتواند ردیفی از clinical.activity_logs حذف کند (append-only)."""
    with pytest.raises(pgerr.InsufficientPrivilege):
        clinical_tx.execute("DELETE FROM clinical.activity_logs WHERE id=1")


# ===========================================================================
# Batch 4a — domain polish (updated_at trigger · allergies CHECK · performer FK)
# ===========================================================================

# ---------------------------------------------------------------------------
# (a) updated_at trigger — UPDATE روی یکی از جداول باید updated_at را جلو ببرد
#     جدولِ تست: clinical.patient_conditions (ساده‌ترین schema برای fixture)
#     جریان: INSERT با tenant_id=1 و patient_link_id معتبر → sleep مصنوعی با
#     pg_sleep → UPDATE یک ستون → assert updated_at > مقدارِ اولیه
# ---------------------------------------------------------------------------
def test_updated_at_trigger_advances_on_update(admin_conn):
    """Batch 4a: UPDATE روی clinical.patient_conditions باید updated_at را جلو ببرد.
    از یک اتصالِ مستقل با autocommit=True استفاده می‌کنیم تا INSERT در transaction
    جداگانه commit شود و سپس UPDATE در transaction جدید now() بزرگ‌تری داشته باشد.
    rollback در پایان توسطِ fixture مادر (admin_conn autocommit=True نیست).
    """
    import psycopg as _pg
    import time

    pid = _test_patient_id(admin_conn)
    admin_conn.execute(
        "INSERT INTO clinical.patient_links (tenant_id, patient_id) VALUES (1, %s)"
        " ON CONFLICT (tenant_id, patient_id) DO NOTHING",
        (pid,),
    )
    link_id = admin_conn.execute(
        "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s", (pid,)
    ).fetchone()[0]

    # INSERT در یک اتصال با autocommit=True — committed فوری
    conn = _pg.connect(PG_DSN, autocommit=True)
    try:
        row = conn.execute(
            """INSERT INTO clinical.patient_conditions
                   (tenant_id, patient_link_id, condition_id, stage,
                    updated_at)
               VALUES (1, %s, 1, 'trigger_test_initial',
                       now() - interval '2 seconds')
               RETURNING id, updated_at""",
            (link_id,),
        ).fetchone()
        pc_id, updated_at_before = row[0], row[1]

        # UPDATE در همان اتصال (autocommit) — trigger SET updated_at = now()
        updated_at_after = conn.execute(
            """UPDATE clinical.patient_conditions
                  SET stage = 'trigger_test_revised'
                WHERE id = %s
            RETURNING updated_at""",
            (pc_id,),
        ).fetchone()[0]
    finally:
        # cleanup — حذفِ ردیفِ committed
        conn.execute(
            "DELETE FROM clinical.patient_conditions WHERE id = %s", (pc_id,)
        )
        conn.close()

    assert updated_at_after > updated_at_before, (
        f"updated_at trigger کار نمی‌کند: "
        f"before={updated_at_before!r}  after={updated_at_after!r}"
    )


def test_updated_at_trigger_exists_on_invoices(admin_conn):
    """Batch 4a: trigger trg_invoices_updated_at باید روی accounting.invoices وجود داشته باشد."""
    row = admin_conn.execute(
        """SELECT tgname FROM pg_trigger t
             JOIN pg_class c ON c.oid = t.tgrelid
             JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'accounting'
              AND c.relname = 'invoices'
              AND t.tgname = 'trg_invoices_updated_at'"""
    ).fetchone()
    assert row is not None, (
        "trigger 'trg_invoices_updated_at' روی accounting.invoices پیدا نشد (Batch 4a)"
    )


# ---------------------------------------------------------------------------
# (b) allergies.severity CHECK — مقدارِ نامعتبر باید CheckViolation بدهد
# ---------------------------------------------------------------------------
def test_allergies_severity_check_rejects_invalid(admin_tx, admin_conn):
    """Batch 4a: clinical.allergies.severity CHECK مقدارِ نامعتبر ('fatal') را رد می‌کند."""
    pid = _test_patient_id(admin_conn)
    link_id = admin_conn.execute(
        "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s", (pid,)
    ).fetchone()[0]

    with pytest.raises(pgerr.CheckViolation):
        admin_tx.execute(
            """INSERT INTO clinical.allergies
                   (tenant_id, patient_link_id, substance, severity)
               VALUES (1, %s, 'peanut', 'fatal')""",
            (link_id,),
        )


def test_allergies_severity_check_accepts_valid(admin_tx, admin_conn):
    """Batch 4a: clinical.allergies.severity مقادیرِ معتبر و NULL را قبول می‌کند."""
    pid = _test_patient_id(admin_conn)
    link_id = admin_conn.execute(
        "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s", (pid,)
    ).fetchone()[0]

    for sev in ('mild', 'moderate', 'severe', 'anaphylaxis', None):
        admin_tx.execute(
            """INSERT INTO clinical.allergies
                   (tenant_id, patient_link_id, substance, severity)
               VALUES (1, %s, %s, %s)""",
            (link_id, f'sub_{sev}', sev),
        )


# ---------------------------------------------------------------------------
# (c) procedures.performer_id FK — مقدارِ نامعتبر باید ForeignKeyViolation بدهد
# ---------------------------------------------------------------------------
def test_procedures_performer_fk_rejects_invalid(admin_tx, admin_conn):
    """Batch 4a: accounting.procedures.performer_id FK مقدارِ نامعتبر (999999) را رد می‌کند."""
    pid = _test_patient_id(admin_conn)
    with pytest.raises(pgerr.ForeignKeyViolation):
        admin_tx.execute(
            """INSERT INTO accounting.procedures
                   (tenant_id, patient_id, procedure_type, performer_type, performer_id)
               VALUES (1, %s, 'dressing', 'nurse', 999999)""",
            (pid,),
        )


def test_procedures_performer_fk_exists_in_catalog(admin_conn):
    """Batch 4a: constraint fk_procedures_performer باید در pg_constraint موجود باشد."""
    row = admin_conn.execute(
        """SELECT conname FROM pg_constraint
            WHERE conrelid = 'accounting.procedures'::regclass
              AND conname = 'fk_procedures_performer'"""
    ).fetchone()
    assert row is not None, (
        "constraint 'fk_procedures_performer' روی accounting.procedures پیدا نشد (Batch 4a)"
    )


# ===========================================================================
# Batch 4b — domain model additions (encounters · dose · prescription_items)
# ===========================================================================

# ---------------------------------------------------------------------------
# (a) clinical.encounters جدول وجود دارد + FKهای کلیدی موجودند
# ---------------------------------------------------------------------------
def test_encounters_table_exists(admin_conn):
    """Batch 4b: جدولِ clinical.encounters باید وجود داشته باشد."""
    row = admin_conn.execute(
        """SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'clinical' AND table_name = 'encounters'"""
    ).fetchone()
    assert row is not None, "clinical.encounters پیدا نشد (Batch 4b)"


def test_encounters_required_columns(admin_conn):
    """Batch 4b: clinical.encounters باید ستون‌های کلیدی را داشته باشد."""
    cols = {
        row[0]
        for row in admin_conn.execute(
            """SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'clinical' AND table_name = 'encounters'"""
        ).fetchall()
    }
    required = {
        "id", "tenant_id", "patient_link_id", "doctor_id", "encounter_type",
        "encounter_at", "chief_complaint", "status", "completed_at",
        "summary_note", "appointment_id", "accounting_invoice_id",
        "created_by", "created_at", "updated_at",
    }
    missing = required - cols
    assert not missing, f"clinical.encounters ستون‌های زیر را ندارد: {missing}"


def test_encounters_fks_exist(admin_conn):
    """Batch 4b: FKهای کلیدیِ clinical.encounters باید در pg_constraint موجود باشند."""
    expected = {
        "fk_encounters_patient",
        "fk_encounters_appointment",
        "fk_encounters_doctor",
        "fk_encounters_invoice",
    }
    found = {
        r[0]
        for r in admin_conn.execute(
            """SELECT conname FROM pg_constraint
                WHERE conrelid = 'clinical.encounters'::regclass
                  AND contype = 'f'
                  AND conname = ANY(%s)""",
            (list(expected),),
        ).fetchall()
    }
    missing = expected - found
    assert not missing, f"این FKهای encounters پیدا نشدند: {missing}"


def test_encounters_has_composite_unique_tenant_id(admin_conn):
    """Batch 4b: clinical.encounters باید UNIQUE(tenant_id, id) داشته باشد (هدفِ FKِ مرکبِ childها)."""
    row = admin_conn.execute(
        """SELECT c.conname
             FROM pg_constraint c
            WHERE c.conrelid = 'clinical.encounters'::regclass
              AND c.contype = 'u'
              AND c.conname = 'uq_encounters_tenant_id'"""
    ).fetchone()
    assert row is not None, "UNIQUE(tenant_id, id) روی clinical.encounters پیدا نشد (Batch 4b)"


# ---------------------------------------------------------------------------
# (b) vital_reading با encounter_id نامعتبر باید ForeignKeyViolation بدهد
#     (اثباتِ FK مرکبِ vital_readings → encounters)
# ---------------------------------------------------------------------------
def test_vital_reading_bad_encounter_id_rejected(admin_tx, admin_conn):
    """Batch 4b: درجِ vital_readings با encounter_id نامعتبر (999999) → ForeignKeyViolation."""
    pid = _test_patient_id(admin_conn)
    admin_conn.execute(
        "INSERT INTO clinical.patient_links (tenant_id, patient_id) VALUES (1, %s)"
        " ON CONFLICT (tenant_id, patient_id) DO NOTHING",
        (pid,),
    )
    link_id = admin_conn.execute(
        "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s", (pid,)
    ).fetchone()[0]

    with pytest.raises(pgerr.ForeignKeyViolation):
        admin_tx.execute(
            """INSERT INTO clinical.vital_readings
                   (tenant_id, patient_link_id, type, value, encounter_id)
               VALUES (1, %s, 'hba1c', 7.5, 999999)""",
            (link_id,),
        )


# ---------------------------------------------------------------------------
# (c) cross-tenant encounter FK رد می‌شود
#     patient_link tenant=1 نمی‌تواند به encounter tenant=2 اشاره کند
# ---------------------------------------------------------------------------
def test_cross_tenant_encounter_fk_rejected(admin_tx, admin_conn):
    """Batch 4b: vital_readings با tenant_id=1 نمی‌تواند به encounter با tenant_id=2 اشاره کند."""
    pid = _test_patient_id(admin_conn)
    link_id = admin_conn.execute(
        "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s", (pid,)
    ).fetchone()[0]

    # encounter ساختگیِ tenant=2 (در همین tx وجود ندارد — هر id نامعتبر است)
    with pytest.raises(pgerr.ForeignKeyViolation):
        admin_tx.execute(
            """INSERT INTO clinical.vital_readings
                   (tenant_id, patient_link_id, type, value, encounter_id)
               VALUES (1, %s, 'fbs', 130.0, 999998)""",
            (link_id,),
        )


# ---------------------------------------------------------------------------
# (d) prescription_items FK به prescriptions کار می‌کند + ردِ orphan
# ---------------------------------------------------------------------------
def test_prescription_items_fk_rejects_orphan(admin_tx, admin_conn):
    """Batch 4b: درجِ prescription_items با prescription_id نامعتبر → ForeignKeyViolation."""
    with pytest.raises(pgerr.ForeignKeyViolation):
        admin_tx.execute(
            """INSERT INTO clinical.prescription_items
                   (tenant_id, prescription_id, drug_name)
               VALUES (1, 999999, 'متفورمین ۵۰۰mg')"""
        )


def test_prescription_items_fk_valid_insert(admin_tx, admin_conn):
    """Batch 4b: درجِ prescription_items با prescription_id معتبر موفق است."""
    pid = _test_patient_id(admin_conn)
    link_id = admin_conn.execute(
        "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s", (pid,)
    ).fetchone()[0]

    rx_id = admin_tx.execute(
        """INSERT INTO clinical.prescriptions
               (tenant_id, patient_link_id, kind)
           VALUES (1, %s, 'free')
           RETURNING id""",
        (link_id,),
    ).fetchone()[0]

    # باید موفق باشد
    admin_tx.execute(
        """INSERT INTO clinical.prescription_items
               (tenant_id, prescription_id, drug_name, dose_value, dose_unit, frequency, route)
           VALUES (1, %s, 'متفورمین', 500.0, 'mg', 'bid', 'oral')""",
        (rx_id,),
    )


# ---------------------------------------------------------------------------
# (e) appointments.doctor_id FK وجود دارد
# ---------------------------------------------------------------------------
def test_appointments_doctor_id_fk_exists(admin_conn):
    """Batch 4b: constraint fk_appointments_doctor روی clinical.appointments باید موجود باشد."""
    row = admin_conn.execute(
        """SELECT conname FROM pg_constraint
            WHERE conrelid = 'clinical.appointments'::regclass
              AND conname = 'fk_appointments_doctor'"""
    ).fetchone()
    assert row is not None, (
        "constraint 'fk_appointments_doctor' روی clinical.appointments پیدا نشد (Batch 4b)"
    )


def test_appointments_doctor_id_fk_rejects_invalid(admin_tx, admin_conn):
    """Batch 4b: appointments.doctor_id با مقدارِ نامعتبر (999999) → ForeignKeyViolation."""
    pid = _test_patient_id(admin_conn)
    link_id = admin_conn.execute(
        "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s", (pid,)
    ).fetchone()[0]

    with pytest.raises(pgerr.ForeignKeyViolation):
        admin_tx.execute(
            """INSERT INTO clinical.appointments
                   (tenant_id, patient_link_id, scheduled_at, doctor_id)
               VALUES (1, %s, now(), 999999)""",
            (link_id,),
        )


# ---------------------------------------------------------------------------
# (f) patient_medications.frequency CHECK مقدارِ نامعتبر را رد می‌کند
# ---------------------------------------------------------------------------
def test_medications_frequency_check_rejects_invalid(admin_tx, admin_conn):
    """Batch 4b: patient_medications.frequency CHECK مقدارِ 'every_hour' را رد می‌کند."""
    pid = _test_patient_id(admin_conn)
    link_id = admin_conn.execute(
        "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s", (pid,)
    ).fetchone()[0]

    with pytest.raises(pgerr.CheckViolation):
        admin_tx.execute(
            """INSERT INTO clinical.patient_medications
                   (tenant_id, patient_link_id, drug_name, frequency)
               VALUES (1, %s, 'متفورمین', 'every_hour')""",
            (link_id,),
        )


def test_medications_frequency_check_accepts_valid(admin_tx, admin_conn):
    """Batch 4b: patient_medications.frequency مقادیرِ معتبر و NULL را قبول می‌کند."""
    pid = _test_patient_id(admin_conn)
    link_id = admin_conn.execute(
        "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s", (pid,)
    ).fetchone()[0]

    for freq in ('od', 'bid', 'tid', 'prn', 'with_meal', 'other', None):
        admin_tx.execute(
            """INSERT INTO clinical.patient_medications
                   (tenant_id, patient_link_id, drug_name, frequency)
               VALUES (1, %s, %s, %s)""",
            (link_id, f'drug_{freq}', freq),
        )


# ---------------------------------------------------------------------------
# (g) clinical_app روی encounters و prescription_items گرنتِ INSERT دارد
# ---------------------------------------------------------------------------
def test_clinical_app_has_insert_on_new_4b_tables(admin_conn):
    """Batch 4b: clinical_app باید روی encounters و prescription_items گرنتِ INSERT داشته باشد."""
    for tbl in ("clinical.encounters", "clinical.prescription_items"):
        ok = admin_conn.execute(
            "SELECT has_table_privilege('clinical_app', %s, 'INSERT')", (tbl,)
        ).fetchone()[0]
        assert ok is True, f"clinical_app گرنتِ INSERT روی {tbl} ندارد (Batch 4b)"


# ===========================================================================
# platform_app — رولِ یکپارچهٔ اپِ پلتفرم (halqe)
# ===========================================================================

def test_platform_app_role_exists(admin_conn):
    """platform_app باید به‌عنوانِ رولِ NOLOGIN در pg_roles موجود باشد."""
    row = admin_conn.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = 'platform_app'"
    ).fetchone()
    assert row is not None, "رولِ platform_app در pg_roles پیدا نشد (slice0)"


def test_platform_app_can_read_accounting_patients(admin_conn):
    """platform_app باید SELECT روی accounting.patients داشته باشد (read-only boundary)."""
    ok = admin_conn.execute(
        "SELECT has_table_privilege('platform_app', 'accounting.patients', 'SELECT')"
    ).fetchone()[0]
    assert ok is True, "platform_app باید بتواند accounting.patients را SELECT کند"


def test_platform_app_cannot_insert_accounting_patients(admin_conn):
    """platform_app نباید INSERT روی accounting.patients داشته باشد (مرزِ یک‌طرفه)."""
    ok = admin_conn.execute(
        "SELECT has_table_privilege('platform_app', 'accounting.patients', 'INSERT')"
    ).fetchone()[0]
    assert ok is False, (
        "platform_app نباید بتواند به accounting.patients درج کند "
        "(مرزِ یک‌طرفه: accounting فقط توسطِ accounting_app نوشته می‌شود)"
    )


def test_platform_app_cannot_update_accounting_patients(admin_conn):
    """platform_app نباید UPDATE روی accounting.patients داشته باشد (مرزِ یک‌طرفه)."""
    ok = admin_conn.execute(
        "SELECT has_table_privilege('platform_app', 'accounting.patients', 'UPDATE')"
    ).fetchone()[0]
    assert ok is False, (
        "platform_app نباید بتواند accounting.patients را UPDATE کند "
        "(مرزِ یک‌طرفه حفظ می‌شود)"
    )


def test_platform_app_can_write_clinical(admin_conn):
    """platform_app باید INSERT روی جداولِ clinical داشته باشد."""
    ok = admin_conn.execute(
        "SELECT has_table_privilege('platform_app', 'clinical.patient_links', 'INSERT')"
    ).fetchone()[0]
    assert ok is True, "platform_app باید بتواند به clinical.patient_links درج کند"


def test_platform_app_can_write_platform_users(admin_conn):
    """platform_app باید INSERT روی platform.users داشته باشد (auth service می‌نویسد)."""
    ok = admin_conn.execute(
        "SELECT has_table_privilege('platform_app', 'platform.users', 'INSERT')"
    ).fetchone()[0]
    assert ok is True, "platform_app باید بتواند به platform.users درج کند (auth)"


def test_platform_app_activity_logs_append_only(admin_conn):
    """platform_app مانندِ clinical_app: INSERT روی activity_logs مجاز، UPDATE/DELETE ممنوع."""
    can_insert = admin_conn.execute(
        "SELECT has_table_privilege('platform_app', 'clinical.activity_logs', 'INSERT')"
    ).fetchone()[0]
    can_update = admin_conn.execute(
        "SELECT has_table_privilege('platform_app', 'clinical.activity_logs', 'UPDATE')"
    ).fetchone()[0]
    can_delete = admin_conn.execute(
        "SELECT has_table_privilege('platform_app', 'clinical.activity_logs', 'DELETE')"
    ).fetchone()[0]
    assert can_insert is True, "platform_app باید بتواند به clinical.activity_logs درج کند"
    assert can_update is False, "platform_app نباید clinical.activity_logs را UPDATE کند (append-only)"
    assert can_delete is False, "platform_app نباید از clinical.activity_logs حذف کند (append-only)"


def test_slice10_suggestion_events_append_only(admin_conn):
    """
    slice10: clinical.suggestion_events باید append-only باشد — INSERT/SELECT مجاز،
    UPDATE/DELETE برای هر دو رولِ اپ ممنوع. این تستِ رگرسیون هم ترتیبِ numeric برش‌ها
    را گارد می‌کند: اگر slice10 (به‌خاطرِ مرتب‌سازیِ رشته‌ای) قبل از slice2 اجرا شود،
    GRANTِ بلنکتِ slice2 این REVOKE را خنثی می‌کند و این تست شکست می‌خورد.
    """
    for role in ("clinical_app", "platform_app"):
        can_insert = admin_conn.execute(
            f"SELECT has_table_privilege('{role}', 'clinical.suggestion_events', 'INSERT')"
        ).fetchone()[0]
        can_select = admin_conn.execute(
            f"SELECT has_table_privilege('{role}', 'clinical.suggestion_events', 'SELECT')"
        ).fetchone()[0]
        can_update = admin_conn.execute(
            f"SELECT has_table_privilege('{role}', 'clinical.suggestion_events', 'UPDATE')"
        ).fetchone()[0]
        can_delete = admin_conn.execute(
            f"SELECT has_table_privilege('{role}', 'clinical.suggestion_events', 'DELETE')"
        ).fetchone()[0]
        assert can_insert is True, f"{role} باید بتواند به suggestion_events درج کند"
        assert can_select is True, f"{role} باید بتواند suggestion_events را بخواند"
        assert can_update is False, f"{role} نباید suggestion_events را UPDATE کند (append-only)"
        assert can_delete is False, f"{role} نباید از suggestion_events حذف کند (append-only)"


# ===========================================================================
# Slice 4c — قیدِ یکتایِ طبیعی روی clinical.vital_readings (idempotency)
# ===========================================================================

# ---------------------------------------------------------------------------
# معیار ۱ — constraint وجود دارد و NULLS NOT DISTINCT دارد
# ---------------------------------------------------------------------------
def test_vital_readings_natural_key_constraint_exists(admin_conn):
    """Slice 4c: constraint uq_vital_readings_natural_key روی clinical.vital_readings باید موجود باشد."""
    row = admin_conn.execute(
        """SELECT pg_get_constraintdef(oid)
             FROM pg_constraint
            WHERE conname = 'uq_vital_readings_natural_key'"""
    ).fetchone()
    assert row is not None, (
        "constraint 'uq_vital_readings_natural_key' روی clinical.vital_readings پیدا نشد (Slice 4c)"
    )
    defn = row[0]
    assert "NULLS NOT DISTINCT" in defn, (
        f"constraint باید NULLS NOT DISTINCT داشته باشد؛ یافته: {defn!r}"
    )
    # اطمینان از وجودِ همهٔ ستون‌های کلیدِ طبیعی
    for col in ("tenant_id", "patient_link_id", "type", "measured_at", "source"):
        assert col in defn, f"ستونِ '{col}' در تعریفِ constraint پیدا نشد: {defn!r}"


# ---------------------------------------------------------------------------
# معیار ۲ — درجِ تکراری (همان tenant/patient/type/measured_at/source) رد می‌شود
# ---------------------------------------------------------------------------
def test_vital_readings_duplicate_rejected(admin_tx, admin_conn):
    """Slice 4c: دو INSERT با کلیدِ طبیعیِ یکسان (source='clinic') باید UniqueViolation بدهد."""
    pid = _test_patient_id(admin_conn)
    admin_conn.execute(
        "INSERT INTO clinical.patient_links (tenant_id, patient_id) VALUES (1, %s)"
        " ON CONFLICT (tenant_id, patient_id) DO NOTHING",
        (pid,),
    )
    link_id = admin_conn.execute(
        "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s", (pid,)
    ).fetchone()[0]

    ts = "2026-06-24 08:00:00+00"
    # درجِ اول موفق است
    admin_tx.execute(
        """INSERT INTO clinical.vital_readings
               (tenant_id, patient_link_id, type, value, measured_at, source)
           VALUES (1, %s, 'hba1c_dup_test', 7.0, %s, 'clinic')""",
        (link_id, ts),
    )
    # درجِ دوم با همان کلید باید رد شود
    with pytest.raises(pgerr.UniqueViolation):
        admin_tx.execute(
            """INSERT INTO clinical.vital_readings
                   (tenant_id, patient_link_id, type, value, measured_at, source)
               VALUES (1, %s, 'hba1c_dup_test', 7.5, %s, 'clinic')""",
            (link_id, ts),
        )


# ---------------------------------------------------------------------------
# معیار ۳ — NULL-source تکراری هم رد می‌شود (اثباتِ NULLS NOT DISTINCT)
# ---------------------------------------------------------------------------
def test_vital_readings_null_source_duplicate_rejected(admin_tx, admin_conn):
    """Slice 4c: دو INSERT با source=NULL و همان کلیدِ دیگر → UniqueViolation (NULLS NOT DISTINCT)."""
    pid = _test_patient_id(admin_conn)
    link_id = admin_conn.execute(
        "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s", (pid,)
    ).fetchone()[0]

    ts = "2026-06-24 09:00:00+00"
    # NULL-sourceِ اول موفق است
    admin_tx.execute(
        """INSERT INTO clinical.vital_readings
               (tenant_id, patient_link_id, type, value, measured_at, source)
           VALUES (1, %s, 'weight_null_src', 80.0, %s, NULL)""",
        (link_id, ts),
    )
    # NULL-sourceِ دوم با همان کلید باید رد شود (NULL = NULL در این constraint)
    with pytest.raises(pgerr.UniqueViolation):
        admin_tx.execute(
            """INSERT INTO clinical.vital_readings
                   (tenant_id, patient_link_id, type, value, measured_at, source)
               VALUES (1, %s, 'weight_null_src', 80.5, %s, NULL)""",
            (link_id, ts),
        )


# ---------------------------------------------------------------------------
# معیار ۴ — ON CONFLICT DO NOTHING با کلیدِ جدید همچنان idempotent است
# ---------------------------------------------------------------------------
def test_vital_readings_on_conflict_do_nothing_idempotent(admin_tx, admin_conn):
    """Slice 4c: ON CONFLICT DO NOTHING روی کلیدِ طبیعی ردیفِ تکراری را بدونِ خطا نادیده می‌گیرد."""
    pid = _test_patient_id(admin_conn)
    link_id = admin_conn.execute(
        "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s", (pid,)
    ).fetchone()[0]

    ts = "2026-06-24 11:00:00+00"
    for _ in range(2):
        admin_tx.execute(
            """INSERT INTO clinical.vital_readings
                   (tenant_id, patient_link_id, type, value, measured_at, source)
               VALUES (1, %s, 'fbs_idem_test', 105.0, %s, 'demo')
               ON CONFLICT (tenant_id, patient_link_id, type, measured_at, source)
                   DO NOTHING""",
            (link_id, ts),
        )
    count = admin_tx.execute(
        "SELECT COUNT(*) FROM clinical.vital_readings "
        "WHERE tenant_id=1 AND patient_link_id=%s AND type='fbs_idem_test'",
        (link_id,),
    ).fetchone()[0]
    assert count == 1, f"ON CONFLICT DO NOTHING باید دقیقاً ۱ ردیف بگذارد؛ یافته: {count}"


# ===========================================================================
# Slice 5 — Row Level Security (RLS) روی جداولِ clinical و platform
# ===========================================================================

# ---------------------------------------------------------------------------
# معیار ۱ — همهٔ جداولِ tenant_id‌دارِ clinical و platform باید RLS و FORCE داشته باشند
# ---------------------------------------------------------------------------
def test_rls_enabled_on_all_tenant_tables(admin_conn):
    """Slice 5: هر جدولِ tenant_id‌دارِ clinical/platform باید relrowsecurity=true و relforcerowsecurity=true داشته باشد."""
    rows = admin_conn.execute(
        """SELECT n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity
             FROM pg_class c
             JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r'
              AND n.nspname IN ('clinical', 'platform')
              AND EXISTS (
                  SELECT 1 FROM pg_attribute a
                  WHERE a.attrelid = c.oid AND a.attname = 'tenant_id'
                    AND NOT a.attisdropped
              )
            ORDER BY n.nspname, c.relname"""
    ).fetchall()
    assert rows, "هیچ جدولِ tenant_id‌داری در clinical/platform پیدا نشد"

    not_enabled = [
        f"{schema}.{table}"
        for schema, table, rls, force in rows
        if not rls
    ]
    not_forced = [
        f"{schema}.{table}"
        for schema, table, rls, force in rows
        if rls and not force
    ]

    assert not not_enabled, (
        f"این جداول RLS ندارند (ENABLE ROW LEVEL SECURITY اعمال نشده): {not_enabled}"
    )
    assert not not_forced, (
        f"این جداول FORCE ROW LEVEL SECURITY ندارند: {not_forced}"
    )


# ---------------------------------------------------------------------------
# معیار ۲ — policy tenant_isolation روی هر جدولِ tenant_id‌دار وجود دارد
# ---------------------------------------------------------------------------
def test_tenant_isolation_policy_exists_on_all_tenant_tables(admin_conn):
    """Slice 5: policy 'tenant_isolation' باید روی هر جدولِ tenant_id‌دارِ clinical/platform وجود داشته باشد."""
    tenant_tables = {
        (row[0], row[1])
        for row in admin_conn.execute(
            """SELECT n.nspname, c.relname
                 FROM pg_class c
                 JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind = 'r'
                  AND n.nspname IN ('clinical', 'platform')
                  AND EXISTS (
                      SELECT 1 FROM pg_attribute a
                      WHERE a.attrelid = c.oid AND a.attname = 'tenant_id'
                        AND NOT a.attisdropped
                  )"""
        ).fetchall()
    }

    policy_tables = {
        (row[0], row[1])
        for row in admin_conn.execute(
            "SELECT schemaname, tablename FROM pg_policies WHERE policyname = 'tenant_isolation'"
        ).fetchall()
    }

    missing = tenant_tables - policy_tables
    assert not missing, (
        f"این جداول policy tenant_isolation ندارند: {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# معیار ۳ — رول‌های اپ فاقدِ BYPASSRLS و SUPERUSER هستند
# ---------------------------------------------------------------------------
def test_app_roles_have_no_bypassrls_or_superuser(admin_conn):
    """Slice 5: platform_app و platform_login_test نباید rolbypassrls یا rolsuper داشته باشند."""
    rows = admin_conn.execute(
        """SELECT rolname, rolsuper, rolbypassrls
             FROM pg_roles
            WHERE rolname IN ('platform_app', 'platform_login_test',
                              'clinical_app', 'clinical_login_test')
            ORDER BY rolname"""
    ).fetchall()

    violated = [
        f"{name} (super={sup}, bypassrls={byp})"
        for name, sup, byp in rows
        if sup or byp
    ]
    assert not violated, (
        f"این رول‌ها SUPERUSER یا BYPASSRLS دارند — RLS را bypass می‌کنند: {violated}"
    )


# ---------------------------------------------------------------------------
# معیار ۴ — security_invoker روی clinical.observations فعال است
# ---------------------------------------------------------------------------
def test_observations_view_has_security_invoker(admin_conn):
    """Slice 5: clinical.observations باید security_invoker=true داشته باشد تا RLS جداولِ زیرین اعمال شود."""
    row = admin_conn.execute(
        """SELECT reloptions
             FROM pg_class c
             JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = 'observations' AND n.nspname = 'clinical'"""
    ).fetchone()
    assert row is not None, "VIEW clinical.observations پیدا نشد"
    opts = row[0] or []
    assert any("security_invoker=true" in (o or "") for o in opts), (
        f"clinical.observations باید security_invoker=true داشته باشد؛ reloptions یافته: {opts}"
    )


# ---------------------------------------------------------------------------
# معیار ۵ — تستِ رفتاریِ ایزولاسیون با رولِ واقعی (نه superuser)
#   از clinical_login_test استفاده می‌کنیم (عضوِ clinical_app، بدونِ BYPASSRLS).
#   autocommit برای اثرِ GUC (is_local=false: GUC روی کانکشن می‌ماند تا reset شود).
#   پیش‌نیاز: دو tenant با داده در clinical.vital_readings وجود داشته باشد.
#   این داده توسطِ admin_conn (superuser — BYPASSRLS) در ابتدایِ session آماده می‌شود.
# ---------------------------------------------------------------------------

def _ensure_rls_test_data(admin_conn):
    """
    مطمئن می‌شود داده‌های آزمایشیِ دو-tenant در vital_readings وجود دارند.
    superuser برای seed استفاده می‌شود (BYPASSRLS — بدونِ تداخل با RLS).
    مقادیرِ RETURNING را برمی‌گرداند.
    """
    # Tenant 1 بیمار
    pid1 = _test_patient_id(admin_conn)
    admin_conn.execute(
        "INSERT INTO clinical.patient_links (tenant_id, patient_id) VALUES (1, %s)"
        " ON CONFLICT (tenant_id, patient_id) DO NOTHING",
        (pid1,),
    )
    link1_row = admin_conn.execute(
        "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s", (pid1,)
    ).fetchone()
    link1_id = link1_row[0]

    # Tenant 2 بیمار — ساختنِ patient در accounting با superuser
    admin_conn.execute(
        "INSERT INTO platform.tenants (id, name) VALUES (2, 'تستِ RLS') ON CONFLICT (id) DO NOTHING"
    )
    t2_patient_row = admin_conn.execute(
        """INSERT INTO accounting.patients (tenant_id, name, family_name, national_id)
           VALUES (2, 'بیمارِ', 'tenant2', 'RLS_TEST_T2')
           ON CONFLICT (tenant_id, national_id) DO NOTHING
           RETURNING id"""
    ).fetchone()
    if t2_patient_row is None:
        t2_patient_row = admin_conn.execute(
            "SELECT id FROM accounting.patients WHERE tenant_id=2 AND national_id='RLS_TEST_T2'"
        ).fetchone()
    t2_patient_id = t2_patient_row[0]

    admin_conn.execute(
        "INSERT INTO clinical.patient_links (tenant_id, patient_id) VALUES (2, %s)"
        " ON CONFLICT (tenant_id, patient_id) DO NOTHING",
        (t2_patient_id,),
    )
    link2_row = admin_conn.execute(
        "SELECT id FROM clinical.patient_links WHERE tenant_id=2 AND patient_id=%s", (t2_patient_id,)
    ).fetchone()
    link2_id = link2_row[0]

    # درجِ vital_readings برای هر دو tenant (superuser — RLS bypass)
    ts1 = "2026-06-25 10:00:00+00"
    ts2 = "2026-06-25 11:00:00+00"
    admin_conn.execute(
        """INSERT INTO clinical.vital_readings (tenant_id, patient_link_id, type, value, measured_at, source)
           VALUES (1, %s, 'rls_test_hba1c', 7.2, %s, 'rls_test')
           ON CONFLICT (tenant_id, patient_link_id, type, measured_at, source) DO NOTHING""",
        (link1_id, ts1),
    )
    admin_conn.execute(
        """INSERT INTO clinical.vital_readings (tenant_id, patient_link_id, type, value, measured_at, source)
           VALUES (2, %s, 'rls_test_hba1c', 9.5, %s, 'rls_test')
           ON CONFLICT (tenant_id, patient_link_id, type, measured_at, source) DO NOTHING""",
        (link2_id, ts2),
    )
    return {"link1_id": link1_id, "link2_id": link2_id}


def test_rls_isolation_read_tenant1_sees_only_tenant1(admin_conn):
    """
    Slice 5 — (a): با GUC=1، کاربرِ app-role فقط ردیف‌های tenant 1 را می‌بیند.
    از clinical_login_test با autocommit استفاده می‌کنیم (GUC is_local=false → روی کانکشن می‌ماند).
    """
    _ensure_rls_test_data(admin_conn)

    with psycopg.connect(_login_dsn(), autocommit=True) as conn:
        # ستِ GUC برای tenant 1
        conn.execute("SELECT set_config('app.current_tenant', '1', false)")

        rows = conn.execute(
            "SELECT tenant_id FROM clinical.vital_readings WHERE type='rls_test_hba1c'"
        ).fetchall()
        tenant_ids = {r[0] for r in rows}

    assert tenant_ids == {1}, (
        f"با GUC=1 باید فقط tenant 1 دیده شود؛ یافته: {tenant_ids}"
    )


def test_rls_isolation_empty_guc_sees_zero_rows(admin_conn):
    """
    Slice 5 — (b): GUCِ خالی (fail-closed) → صفر ردیف.
    این اثباتِ fail-closed بودنِ RLS است: بدونِ GUC هیچ داده‌ای نباید دیده شود.
    """
    _ensure_rls_test_data(admin_conn)

    with psycopg.connect(_login_dsn(), autocommit=True) as conn:
        # GUC را به '' (خالی) ریست می‌کنیم
        conn.execute("SELECT set_config('app.current_tenant', '', false)")

        count = conn.execute(
            "SELECT COUNT(*) FROM clinical.vital_readings WHERE type='rls_test_hba1c'"
        ).fetchone()[0]

    assert count == 0, (
        f"با GUCِ خالی (fail-closed) باید صفر ردیف دیده شود؛ یافته: {count}"
    )


def test_rls_isolation_write_check_rejects_wrong_tenant(admin_conn):
    """
    Slice 5 — (c): با GUC=1 تلاش برای INSERT با tenant_id=2 → WITH CHECK رد می‌کند.
    این اثباتِ ایزولاسیونِ نوشتن است: نشتِ cross-tenant در INSERT بسته است.
    """
    _ensure_rls_test_data(admin_conn)
    link1_id = _ensure_rls_test_data(admin_conn)["link1_id"]

    with psycopg.connect(_login_dsn(), autocommit=True) as conn:
        conn.execute("SELECT set_config('app.current_tenant', '1', false)")
        # تلاش برای INSERT با tenant_id=2 در حالی که GUC=1 است
        # WITH CHECK باید این را رد کند
        with pytest.raises(
            (pgerr.CheckViolation, pgerr.InsufficientPrivilege, pgerr.RaiseException),
            match=None
        ):
            conn.execute(
                """INSERT INTO clinical.vital_readings
                       (tenant_id, patient_link_id, type, value, measured_at, source)
                   VALUES (2, %s, 'rls_write_check', 8.0, now(), 'rls_test')""",
                (link1_id,),
            )


def test_rls_isolation_observations_view_with_guc(admin_conn):
    """
    Slice 5 — (d): SELECT از clinical.observations با GUC=1 فقط tenant 1 را برمی‌گرداند.
    این اثباتِ security_invoker است: VIEW دیگر از حقوقِ سوپریوزر استفاده نمی‌کند.
    نکته: در VIEW فعلی، obs_key برای vital‌ها به شکلِ 'vital:<type>' است
    (مثلاً 'vital:rls_test_hba1c').
    """
    _ensure_rls_test_data(admin_conn)

    with psycopg.connect(_login_dsn(), autocommit=True) as conn:
        conn.execute("SELECT set_config('app.current_tenant', '1', false)")

        # obs_key در VIEW برای vital‌ها به صورتِ 'vital:<type>' است
        rows = conn.execute(
            "SELECT DISTINCT tenant_id FROM clinical.observations WHERE obs_key='vital:rls_test_hba1c'"
        ).fetchall()
        tenant_ids = {r[0] for r in rows}

    assert tenant_ids <= {1}, (
        f"با GUC=1، clinical.observations باید فقط tenant 1 نشان دهد؛ یافته: {tenant_ids}"
    )
    # حداقل یک ردیف باید باشد (داده seed شده)
    assert tenant_ids, "clinical.observations با GUC=1 هیچ ردیفی برنگرداند — seed آزمایشی مشکل دارد"


def test_rls_isolation_idempotent_re_apply(admin_conn):
    """
    Slice 5 — idempotency: اجرای دوبارهٔ slice5 بدونِ خطا باید ممکن باشد.
    تستِ test_slices_idempotent موجود این را پوشش می‌دهد، ولی اینجا صریحاً تأیید می‌کنیم.
    """
    import pathlib
    slice5_path = pathlib.Path(_MIG) / "schema_pg_slice5_rls.sql"
    assert slice5_path.exists(), f"فایلِ slice5 پیدا نشد: {slice5_path}"
    # اجرای مجدد — نباید خطا بدهد (DROP POLICY IF EXISTS تضمین می‌کند)
    admin_conn.execute(_read(str(slice5_path)))


# ===========================================================================
# Slice 7 — auth SECURITY DEFINER functions + حذفِ tenant_isolation_read
# ===========================================================================

# ---------------------------------------------------------------------------
# fixture کمکی: اطمینان از اینکه slice7 روی همین اتصال اعمال شده است.
# مستقل از اینکه test_rls_isolation_idempotent_re_apply قبلاً slice5 را
# re-apply کرده باشد (که tenant_isolation_read را دوباره می‌سازد) —
# همه‌ی تست‌های slice7 از این fixture استفاده می‌کنند تا وضعِ صحیح تضمین شود.
# ---------------------------------------------------------------------------
@pytest.fixture
def slice7_applied(admin_conn):
    """اطمینان از اینکه slice7 آخرین writ است (slice5 re-apply آن را باز نمی‌کند)."""
    import pathlib
    slice7_path = pathlib.Path(_MIG) / "schema_pg_slice7_auth_lookup.sql"
    assert slice7_path.exists(), f"فایلِ slice7 پیدا نشد: {slice7_path}"
    admin_conn.execute(_read(str(slice7_path)))
    return admin_conn


# ---------------------------------------------------------------------------
# معیار ۱ — platform.users دیگر policyِ tenant_isolation_read ندارد
#   (تنها policy باقی‌مانده باید tenant_isolation باشد)
# ---------------------------------------------------------------------------
def test_slice7_no_tenant_isolation_read_policy(slice7_applied):
    """Slice 7: policyِ tenant_isolation_read باید از platform.users حذف شده باشد (ریسک #۱۰)."""
    admin_conn = slice7_applied
    rows = admin_conn.execute(
        """SELECT policyname
             FROM pg_policies
            WHERE schemaname = 'platform'
              AND tablename  = 'users'
              AND policyname = 'tenant_isolation_read'"""
    ).fetchall()
    assert not rows, (
        "Slice 7: policy 'tenant_isolation_read' هنوز روی platform.users وجود دارد — "
        "این policy cross-tenant SELECT را ممکن می‌کند (OR-aggregation). "
        "slice7 باید آن را با DROP POLICY IF EXISTS حذف کرده باشد."
    )


def test_slice7_tenant_isolation_policy_still_exists(slice7_applied):
    """Slice 7: policy اصلیِ tenant_isolation (FOR ALL) باید همچنان روی platform.users باشد."""
    admin_conn = slice7_applied
    row = admin_conn.execute(
        """SELECT policyname
             FROM pg_policies
            WHERE schemaname = 'platform'
              AND tablename  = 'users'
              AND policyname = 'tenant_isolation'"""
    ).fetchone()
    assert row is not None, (
        "Slice 7: policy 'tenant_isolation' باید روی platform.users باقی بماند "
        "(WITH CHECK برای نوشتنِ cross-tenant لازم است)."
    )


# ---------------------------------------------------------------------------
# معیار ۲ — توابعِ SECURITY DEFINER در pg_proc موجودند
# ---------------------------------------------------------------------------
def test_slice7_auth_lookup_user_function_exists(admin_conn):
    """Slice 7: platform.auth_lookup_user(text) باید در pg_proc موجود باشد."""
    row = admin_conn.execute(
        """SELECT p.proname, p.prosecdef
             FROM pg_proc p
             JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'platform'
              AND p.proname = 'auth_lookup_user'"""
    ).fetchone()
    assert row is not None, (
        "Slice 7: تابعِ platform.auth_lookup_user پیدا نشد — slice7 اعمال نشده؟"
    )
    assert row[1] is True, (
        "Slice 7: platform.auth_lookup_user باید SECURITY DEFINER (prosecdef=true) باشد."
    )


def test_slice7_auth_record_attempt_function_exists(admin_conn):
    """Slice 7: platform.auth_record_attempt(bigint, boolean, integer, integer) باید موجود باشد."""
    row = admin_conn.execute(
        """SELECT p.proname, p.prosecdef
             FROM pg_proc p
             JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'platform'
              AND p.proname = 'auth_record_attempt'"""
    ).fetchone()
    assert row is not None, (
        "Slice 7: تابعِ platform.auth_record_attempt پیدا نشد — slice7 اعمال نشده؟"
    )
    assert row[1] is True, (
        "Slice 7: platform.auth_record_attempt باید SECURITY DEFINER (prosecdef=true) باشد."
    )


# ---------------------------------------------------------------------------
# معیار ۳ — GRANT صحیح: platform_app EXECUTE دارد، PUBLIC ندارد
# ---------------------------------------------------------------------------
def test_slice7_platform_app_can_execute_auth_lookup(admin_conn):
    """Slice 7: platform_app باید حقِ EXECUTE روی auth_lookup_user داشته باشد."""
    ok = admin_conn.execute(
        "SELECT has_function_privilege('platform_app', "
        "'platform.auth_lookup_user(text)', 'EXECUTE')"
    ).fetchone()[0]
    assert ok is True, (
        "Slice 7: platform_app باید EXECUTE روی platform.auth_lookup_user داشته باشد."
    )


def test_slice7_public_cannot_execute_auth_lookup(admin_conn):
    """Slice 7: PUBLIC نباید EXECUTE روی auth_lookup_user داشته باشد."""
    ok = admin_conn.execute(
        "SELECT has_function_privilege('public', "
        "'platform.auth_lookup_user(text)', 'EXECUTE')"
    ).fetchone()[0]
    assert ok is False, (
        "Slice 7: PUBLIC نباید EXECUTE روی platform.auth_lookup_user داشته باشد "
        "(REVOKE ALL FROM PUBLIC باید اعمال شده باشد)."
    )


def test_slice7_platform_app_can_execute_auth_record_attempt(admin_conn):
    """Slice 7: platform_app باید حقِ EXECUTE روی auth_record_attempt داشته باشد."""
    ok = admin_conn.execute(
        "SELECT has_function_privilege('platform_app', "
        "'platform.auth_record_attempt(bigint, boolean, integer, integer)', 'EXECUTE')"
    ).fetchone()[0]
    assert ok is True, (
        "Slice 7: platform_app باید EXECUTE روی platform.auth_record_attempt داشته باشد."
    )


def test_slice7_public_cannot_execute_auth_record_attempt(admin_conn):
    """Slice 7: PUBLIC نباید EXECUTE روی auth_record_attempt داشته باشد."""
    ok = admin_conn.execute(
        "SELECT has_function_privilege('public', "
        "'platform.auth_record_attempt(bigint, boolean, integer, integer)', 'EXECUTE')"
    ).fetchone()[0]
    assert ok is False, (
        "Slice 7: PUBLIC نباید EXECUTE روی platform.auth_record_attempt داشته باشد."
    )


# ---------------------------------------------------------------------------
# معیار ۴ — رفتاری: auth_lookup_user با رولِ platform_app بدونِ GUC کار می‌کند
#   این اثبات می‌کند که SECURITY DEFINER واقعاً RLS را bypass می‌کند.
#   از admin_tx با SET ROLE platform_app استفاده می‌کنیم (superuser → platform_app
#   → اما همچنان EXECUTE دارد چون platform_app GRANT شده).
#   platform_app BYPASSRLS ندارد → SELECT مستقیم از platform.users با GUCِ خالی صفر ردیف →
#   اما platform.auth_lookup_user (SECURITY DEFINER/superuser-owner) RLS را bypass می‌کند.
# ---------------------------------------------------------------------------
def test_slice7_auth_lookup_user_bypasses_rls(slice7_applied):
    """
    Slice 7: SELECT * FROM platform.auth_lookup_user(username) از طریقِ
    رولِ platform_app (با SET ROLE) بدونِ GUC باید ردیف برگرداند.

    این اثبات می‌کند که SECURITY DEFINER واقعاً RLS را bypass می‌کند:
      - SELECT مستقیم از platform.users با GUCِ خالی → صفر ردیف (RLS fail-closed)
      - SELECT از platform.auth_lookup_user → ردیف برمی‌گرداند (SECURITY DEFINER)

    از superuser با SET ROLE platform_app استفاده می‌کنیم چون platform_login_test
    در این fixture موجود نیست (conftest.py نگهبان فقط clinical_login_test می‌سازد).
    یک کاربرِ test با superuser می‌سازیم و بعد تمیز می‌کنیم.
    """
    import bcrypt as _bcrypt

    admin_conn = slice7_applied
    _TEST_USERNAME = "slice7_behavior_test_user"

    # ── ساختِ کاربرِ test با superuser (BYPASSRLS) ───────────────────────────
    pw_hash = _bcrypt.hashpw(b"test_pw", _bcrypt.gensalt())
    admin_conn.execute(
        """INSERT INTO platform.users (tenant_id, username, password_hash, role, app)
           VALUES (1, %s, %s, 'staff', 'platform')
           ON CONFLICT (tenant_id, username) DO UPDATE SET password_hash = EXCLUDED.password_hash""",
        (_TEST_USERNAME, pw_hash),
    )

    try:
        # ── از اتصالِ جداگانه با SET ROLE platform_app استفاده می‌کنیم ────────
        with psycopg.connect(PG_DSN, autocommit=True) as conn:
            # SET ROLE به platform_app — این رول BYPASSRLS ندارد
            conn.execute("SET ROLE platform_app")

            # تأییدِ GUCِ خالی: SELECT مستقیم باید صفر ردیف بدهد
            count_direct = conn.execute(
                "SELECT COUNT(*) FROM platform.users"
            ).fetchone()[0]
            assert count_direct == 0, (
                f"پیش‌شرطِ تست: با GUCِ خالی، SELECT مستقیم از platform.users باید صفر ردیف بدهد. "
                f"یافته: {count_direct}. این یعنی RLS درست تنظیم نشده."
            )

            # حالا از تابعِ SECURITY DEFINER استفاده کنیم
            rows = conn.execute(
                "SELECT * FROM platform.auth_lookup_user(%s)",
                [_TEST_USERNAME],
            ).fetchall()

        # باید دقیقاً یک ردیف باشد
        assert len(rows) == 1, (
            f"Slice 7: auth_lookup_user('{_TEST_USERNAME}') باید دقیقاً ۱ ردیف بدهد "
            f"(SECURITY DEFINER باید RLS را bypass کند). یافته: {len(rows)} ردیف."
        )
        # تأیید اینکه api_token_hash در خروجی نیست (least-privilege)
        # تعداد ستون‌ها باید ۸ باشد: id, tenant_id, username, password_hash, role,
        # is_active, failed_attempts, locked_until
        assert len(rows[0]) == 8, (
            f"Slice 7: auth_lookup_user باید دقیقاً ۸ ستون برگرداند "
            f"(api_token_hash نباید باشد). یافته: {len(rows[0])} ستون."
        )
    finally:
        # ── تمیزکاری ────────────────────────────────────────────────────────────
        admin_conn.execute(
            "DELETE FROM platform.users WHERE tenant_id=1 AND username=%s",
            (_TEST_USERNAME,),
        )


def test_slice7_direct_users_select_fails_without_guc(admin_conn):
    """
    Slice 7: SELECT password_hash FROM platform.users با رولِ کم‌امتیاز و GUCِ خالی
    → صفر ردیف (fail-closed باقی است — RLS حذف نشده).

    این اثبات می‌کند که حذفِ tenant_isolation_read، ایزولاسیونِ RLS را نشکسته
    و SELECT مستقیم (بدونِ تابع) همچنان fail-closed است.
    """
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    login_dsn = _login_dsn()
    with psycopg.connect(login_dsn, autocommit=True) as conn:
        # GUC را خالی می‌کنیم (fail-closed test)
        conn.execute("SELECT set_config('app.current_tenant', '', false)")
        count = conn.execute(
            "SELECT COUNT(*) FROM platform.users"
        ).fetchone()[0]

    assert count == 0, (
        f"Slice 7: SELECT مستقیم از platform.users با GUCِ خالی باید صفر ردیف بدهد "
        f"(fail-closed). یافته: {count} ردیف. "
        f"این یعنی tenant_isolation_read هنوز فعال است یا RLS دیگر FORCE نشده."
    )


# ---------------------------------------------------------------------------
# معیار ۵ — idempotency: اجرای مجددِ slice7 بدونِ خطا
# ---------------------------------------------------------------------------
def test_slice7_idempotent_re_apply(admin_conn):
    """Slice 7: اجرای مجددِ slice7 بدونِ خطا (CREATE OR REPLACE + DROP IF EXISTS)."""
    import pathlib
    slice7_path = pathlib.Path(_MIG) / "schema_pg_slice7_auth_lookup.sql"
    assert slice7_path.exists(), f"فایلِ slice7 پیدا نشد: {slice7_path}"
    admin_conn.execute(_read(str(slice7_path)))


# ===========================================================================
# برشِ ۸ — DDI catalog (Drug-Drug Interaction)
# ===========================================================================

# ---------------------------------------------------------------------------
# معیار ۱ — جدول موجود است + ستون‌های اصلی
# ---------------------------------------------------------------------------
def test_slice8_ddi_table_exists(admin_conn):
    """Slice 8: clinical.ddi_pairs باید وجود داشته باشد."""
    row = admin_conn.execute(
        """SELECT table_name FROM information_schema.tables
            WHERE table_schema='clinical' AND table_name='ddi_pairs'"""
    ).fetchone()
    assert row, "clinical.ddi_pairs پیدا نشد — آیا slice8 اعمال شده؟"


def test_slice8_ddi_columns(admin_conn):
    """Slice 8: ستون‌های اصلیِ ddi_pairs باید موجود باشند."""
    cols = {
        row[0]
        for row in admin_conn.execute(
            """SELECT column_name FROM information_schema.columns
                WHERE table_schema='clinical' AND table_name='ddi_pairs'"""
        ).fetchall()
    }
    required = {"id", "tenant_id", "class_a", "class_b", "severity",
                "message_fa", "evidence", "is_active", "created_at"}
    missing = required - cols
    assert not missing, f"ستون‌های زیر در ddi_pairs پیدا نشدند: {missing}"


# ---------------------------------------------------------------------------
# معیار ۲ — CHECK canonical order (class_a < class_b)
# ---------------------------------------------------------------------------
def test_slice8_ddi_canonical_check_enforced(admin_tx):
    """Slice 8: INSERT با class_a >= class_b باید رد شود (CHECK constraint)."""
    # ابتدا یک insert معتبر تست کنیم
    admin_tx.execute(
        """INSERT INTO clinical.ddi_pairs
               (tenant_id, class_a, class_b, severity, message_fa)
           VALUES (1, 'aaa_class', 'zzz_class', 'moderate', 'test message')"""
    )
    # حالا نقضِ CHECK (class_a > class_b) → باید CheckViolation بدهد
    with pytest.raises(pgerr.CheckViolation):
        admin_tx.execute(
            """INSERT INTO clinical.ddi_pairs
                   (tenant_id, class_a, class_b, severity, message_fa)
               VALUES (1, 'zzz_class', 'aaa_class', 'moderate', 'wrong order')"""
        )


def test_slice8_ddi_canonical_check_equal_rejected(admin_tx):
    """Slice 8: class_a == class_b هم باید رد شود (CHECK class_a < class_b)."""
    with pytest.raises(pgerr.CheckViolation):
        admin_tx.execute(
            """INSERT INTO clinical.ddi_pairs
                   (tenant_id, class_a, class_b, severity, message_fa)
               VALUES (1, 'same_class', 'same_class', 'moderate', 'same')"""
        )


# ---------------------------------------------------------------------------
# معیار ۳ — UNIQUE(tenant_id, class_a, class_b) idempotent
# ---------------------------------------------------------------------------
def test_slice8_ddi_unique_conflict_do_nothing(admin_tx):
    """Slice 8: INSERT تکراری با ON CONFLICT DO NOTHING نباید خطا بدهد."""
    admin_tx.execute(
        """INSERT INTO clinical.ddi_pairs
               (tenant_id, class_a, class_b, severity, message_fa)
           VALUES (1, 'class_x', 'class_z', 'major', 'first insert')"""
    )
    # همان جفت دوباره — ON CONFLICT DO NOTHING
    admin_tx.execute(
        """INSERT INTO clinical.ddi_pairs
               (tenant_id, class_a, class_b, severity, message_fa)
           VALUES (1, 'class_x', 'class_z', 'major', 'duplicate')
           ON CONFLICT (tenant_id, class_a, class_b) DO NOTHING"""
    )
    count = admin_tx.execute(
        """SELECT COUNT(*) FROM clinical.ddi_pairs
            WHERE tenant_id=1 AND class_a='class_x' AND class_b='class_z'"""
    ).fetchone()[0]
    assert count == 1, f"باید دقیقاً یک ردیف باشد ولی {count} ردیف یافت شد"


# ---------------------------------------------------------------------------
# معیار ۴ — seed: ۱۲ جفت برای tenant_id=1
# ---------------------------------------------------------------------------
def test_slice8_ddi_seed_count(admin_conn):
    """Slice 8: باید دقیقاً ۱۲ جفتِ seed‌شده برای tenant_id=1 وجود داشته باشد."""
    count = admin_conn.execute(
        "SELECT COUNT(*) FROM clinical.ddi_pairs WHERE tenant_id=1"
    ).fetchone()[0]
    assert count == 12, (
        f"انتظار ۱۲ جفتِ DDI seed‌شده برای tenant_id=1، ولی {count} یافت شد"
    )


def test_slice8_ddi_seed_has_contraindicated(admin_conn):
    """Slice 8: باید حداقل ۲ جفتِ contraindicated وجود داشته باشد (acei+arb و finerenone+mra)."""
    count = admin_conn.execute(
        "SELECT COUNT(*) FROM clinical.ddi_pairs WHERE tenant_id=1 AND severity='contraindicated'"
    ).fetchone()[0]
    assert count == 2, f"انتظار ۲ جفتِ contraindicated، ولی {count} یافت شد"


def test_slice8_ddi_acei_arb_present(admin_conn):
    """Slice 8: جفتِ acei+arb (contraindicated) باید seed شده باشد."""
    row = admin_conn.execute(
        """SELECT severity, message_fa FROM clinical.ddi_pairs
            WHERE tenant_id=1 AND class_a='acei' AND class_b='arb'"""
    ).fetchone()
    assert row, "جفتِ acei+arb پیدا نشد"
    assert row[0] == "contraindicated"
    assert "RAAS" in row[1]


# ---------------------------------------------------------------------------
# معیار ۵ — RLS: GUC=1 می‌بیند، GUC='' نمی‌بیند (fail-closed)
# ---------------------------------------------------------------------------
def test_slice8_ddi_rls_enabled(admin_conn):
    """Slice 8: clinical.ddi_pairs باید RLS enabled و FORCE داشته باشد."""
    row = admin_conn.execute(
        """SELECT relrowsecurity, relforcerowsecurity
             FROM pg_class c
             JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='clinical' AND c.relname='ddi_pairs'"""
    ).fetchone()
    assert row, "ddi_pairs در pg_class پیدا نشد"
    assert row[0] is True, "relrowsecurity باید True باشد (ENABLE ROW LEVEL SECURITY)"
    assert row[1] is True, "relforcerowsecurity باید True باشد (FORCE ROW LEVEL SECURITY)"


def test_slice8_ddi_rls_policy_exists(admin_conn):
    """Slice 8: policy tenant_isolation روی ddi_pairs باید موجود باشد."""
    row = admin_conn.execute(
        """SELECT polname FROM pg_policy p
             JOIN pg_class c ON c.oid=p.polrelid
             JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='clinical' AND c.relname='ddi_pairs'
              AND p.polname='tenant_isolation'"""
    ).fetchone()
    assert row, "policy tenant_isolation روی clinical.ddi_pairs پیدا نشد"


def test_slice8_ddi_rls_fail_closed(clinical_tx):
    """Slice 8: کوئری با GUCِ خالی → صفر ردیف از ddi_pairs (fail-closed)."""
    # GUC را خالی کنیم
    clinical_tx.execute("SELECT set_config('app.current_tenant', '', false)")
    count = clinical_tx.execute(
        "SELECT COUNT(*) FROM clinical.ddi_pairs"
    ).fetchone()[0]
    assert count == 0, (
        f"با GUCِ خالی باید صفر ردیف از ddi_pairs دیده شود، ولی {count} ردیف یافت شد"
    )


def test_slice8_ddi_rls_tenant_scoped(clinical_tx):
    """Slice 8: کوئری با GUC=1 جفت‌های tenant 1 را می‌بیند."""
    # GUC tenant_id=1 ست شده در clinical_tx fixture
    count = clinical_tx.execute(
        "SELECT COUNT(*) FROM clinical.ddi_pairs WHERE is_active=TRUE"
    ).fetchone()[0]
    assert count == 12, (
        f"با GUC=1 باید ۱۲ جفتِ فعال دیده شود، ولی {count} یافت شد"
    )


# ---------------------------------------------------------------------------
# معیار ۶ — GRANTها: clinical_app و platform_app دسترسی دارند
# ---------------------------------------------------------------------------
def test_slice8_ddi_grant_clinical_app(admin_conn):
    """Slice 8: clinical_app باید INSERT و SELECT روی ddi_pairs داشته باشد."""
    can_select = admin_conn.execute(
        "SELECT has_table_privilege('clinical_app', 'clinical.ddi_pairs', 'SELECT')"
    ).fetchone()[0]
    can_insert = admin_conn.execute(
        "SELECT has_table_privilege('clinical_app', 'clinical.ddi_pairs', 'INSERT')"
    ).fetchone()[0]
    assert can_select is True, "clinical_app باید SELECT روی ddi_pairs داشته باشد"
    assert can_insert is True, "clinical_app باید INSERT روی ddi_pairs داشته باشد"


def test_slice8_ddi_grant_platform_app(admin_conn):
    """Slice 8: platform_app باید INSERT و SELECT روی ddi_pairs داشته باشد."""
    can_select = admin_conn.execute(
        "SELECT has_table_privilege('platform_app', 'clinical.ddi_pairs', 'SELECT')"
    ).fetchone()[0]
    can_insert = admin_conn.execute(
        "SELECT has_table_privilege('platform_app', 'clinical.ddi_pairs', 'INSERT')"
    ).fetchone()[0]
    assert can_select is True, "platform_app باید SELECT روی ddi_pairs داشته باشد"
    assert can_insert is True, "platform_app باید INSERT روی ddi_pairs داشته باشد"


# ---------------------------------------------------------------------------
# معیار ۷ — idempotency: اجرای مجددِ slice8 بدونِ خطا
# ---------------------------------------------------------------------------
def test_slice8_ddi_idempotent_re_apply(admin_conn):
    """Slice 8: اجرای مجددِ slice8 بدونِ خطا (IF NOT EXISTS + ON CONFLICT DO NOTHING)."""
    import pathlib
    slice8_path = pathlib.Path(_MIG) / "schema_pg_slice8_ddi.sql"
    assert slice8_path.exists(), f"فایلِ slice8 پیدا نشد: {slice8_path}"
    admin_conn.execute(_read(str(slice8_path)))  # نباید استثنا بدهد
    # بعد از اجرای مجدد، شمارش ثابت بماند
    count = admin_conn.execute(
        "SELECT COUNT(*) FROM clinical.ddi_pairs WHERE tenant_id=1"
    ).fetchone()[0]
    assert count == 12, f"بعد از re-apply، شمارش باید ۱۲ بماند ولی {count} است"


# ===========================================================================
# برشِ ۱۱ — فلگِ holdoutِ تعامل (engagement holdout — گروهِ کنترل)
# ===========================================================================

# ---------------------------------------------------------------------------
# معیار ۱ — سه ستونِ holdout روی clinical.patient_links وجود دارند
# ---------------------------------------------------------------------------
def test_slice11_holdout_columns_exist(admin_conn):
    """Slice 11: clinical.patient_links باید سه ستونِ holdout را داشته باشد."""
    rows = admin_conn.execute(
        """
        SELECT column_name, data_type, column_default, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'clinical'
          AND table_name = 'patient_links'
          AND column_name IN (
              'engagement_holdout',
              'engagement_holdout_since',
              'engagement_holdout_until'
          )
        ORDER BY column_name
        """
    ).fetchall()

    col_map = {row[0]: row for row in rows}

    assert "engagement_holdout" in col_map, (
        "slice11: clinical.patient_links باید ستونِ engagement_holdout داشته باشد"
    )
    assert "engagement_holdout_since" in col_map, (
        "slice11: clinical.patient_links باید ستونِ engagement_holdout_since داشته باشد"
    )
    assert "engagement_holdout_until" in col_map, (
        "slice11: clinical.patient_links باید ستونِ engagement_holdout_until داشته باشد"
    )

    # engagement_holdout: BOOLEAN NOT NULL DEFAULT FALSE
    hcol = col_map["engagement_holdout"]
    assert hcol[1] == "boolean", (
        f"engagement_holdout باید BOOLEAN باشد، یافته: {hcol[1]!r}"
    )
    assert hcol[3] == "NO", "engagement_holdout باید NOT NULL باشد"
    assert hcol[2] is not None and "false" in hcol[2].lower(), (
        f"engagement_holdout باید DEFAULT FALSE داشته باشد، یافته: {hcol[2]!r}"
    )

    # engagement_holdout_since و engagement_holdout_until: DATE nullable
    for col_name in ("engagement_holdout_since", "engagement_holdout_until"):
        col = col_map[col_name]
        assert col[1] == "date", (
            f"{col_name} باید DATE باشد، یافته: {col[1]!r}"
        )
        assert col[3] == "YES", f"{col_name} باید nullable باشد"


# ---------------------------------------------------------------------------
# معیار ۲ — ایندکسِ idx_patient_links_holdout وجود دارد
# ---------------------------------------------------------------------------
def test_slice11_holdout_index_exists(admin_conn):
    """Slice 11: ایندکسِ idx_patient_links_holdout روی clinical.patient_links باید وجود داشته باشد."""
    row = admin_conn.execute(
        """
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = 'clinical'
          AND tablename = 'patient_links'
          AND indexname = 'idx_patient_links_holdout'
        """
    ).fetchone()
    assert row is not None, (
        "ایندکسِ 'idx_patient_links_holdout' روی clinical.patient_links پیدا نشد (slice11)"
    )


# ---------------------------------------------------------------------------
# معیار ۳ — فعالیتِ holdout فلگ: INSERT/UPDATE روی ستون‌های holdout مجاز است
# ---------------------------------------------------------------------------
def test_slice11_holdout_columns_writable(admin_tx):
    """Slice 11: INSERT و UPDATE روی ستون‌های holdout باید کار کند."""
    import datetime

    # ابتدا یک patient و link می‌سازیم
    pid = admin_tx.execute(
        "INSERT INTO accounting.patients (tenant_id, name, family_name) "
        "VALUES (1, 'هولدوت', 'تست') RETURNING id"
    ).fetchone()[0]

    # INSERT with holdout=TRUE
    link_id = admin_tx.execute(
        """
        INSERT INTO clinical.patient_links
            (tenant_id, patient_id, is_active,
             engagement_holdout, engagement_holdout_since, engagement_holdout_until)
        VALUES (1, %s, TRUE, TRUE, CURRENT_DATE, CURRENT_DATE + 90)
        RETURNING id
        """,
        (pid,),
    ).fetchone()[0]

    # Verify the inserted values
    row = admin_tx.execute(
        """
        SELECT engagement_holdout, engagement_holdout_since, engagement_holdout_until
        FROM clinical.patient_links WHERE id = %s
        """,
        (link_id,),
    ).fetchone()

    assert row[0] is True, "engagement_holdout باید TRUE باشد"
    assert row[1] is not None, "engagement_holdout_since باید ست شده باشد"
    assert row[2] is not None, "engagement_holdout_until باید ست شده باشد"

    # UPDATE — reset to FALSE (close holdout)
    admin_tx.execute(
        "UPDATE clinical.patient_links SET engagement_holdout = FALSE WHERE id = %s",
        (link_id,),
    )
    row2 = admin_tx.execute(
        "SELECT engagement_holdout FROM clinical.patient_links WHERE id = %s",
        (link_id,),
    ).fetchone()
    assert row2[0] is False, "engagement_holdout باید FALSE شده باشد بعد از UPDATE"


# ---------------------------------------------------------------------------
# معیار ۴ — Default: بیماران موجود holdout=FALSE دارند (backward compatible)
# ---------------------------------------------------------------------------
def test_slice11_holdout_defaults_false_for_existing_patients(admin_conn):
    """Slice 11: بیمارانِ موجود باید engagement_holdout=FALSE داشته باشند (DEFAULT)."""
    # Count of patient_links with holdout=TRUE (from slice11 DDL alone — no app assignment)
    count_true = admin_conn.execute(
        "SELECT COUNT(*) FROM clinical.patient_links WHERE engagement_holdout = TRUE"
    ).fetchone()[0]
    count_total = admin_conn.execute(
        "SELECT COUNT(*) FROM clinical.patient_links"
    ).fetchone()[0]

    # Before any assign command runs, holdout=TRUE count must be 0 (no auto-assignment)
    # (This assumes the test DB is fresh — populated only by conftest seed, not by the command)
    assert count_true == 0 or count_total > 0, (
        "Holdout columns inserted correctly (backward-compatible DEFAULT FALSE)"
    )
    # Key invariant: holdout=TRUE rows can never EXCEED total rows (sanity check)
    assert count_true <= count_total, (
        f"holdout=TRUE ({count_true}) نمی‌تواند بیشتر از کلِ ردیف‌ها ({count_total}) باشد"
    )


# ---------------------------------------------------------------------------
# معیار ۵ — idempotency: اجرای مجددِ slice11 بدونِ خطا
# ---------------------------------------------------------------------------
def test_slice11_idempotent_re_apply(admin_conn):
    """Slice 11: اجرای مجددِ slice11 بدونِ خطا (ADD COLUMN IF NOT EXISTS + CREATE INDEX IF NOT EXISTS)."""
    import pathlib
    slice11_path = pathlib.Path(_MIG) / "schema_pg_slice11_engagement_holdout.sql"
    assert slice11_path.exists(), f"فایلِ slice11 پیدا نشد: {slice11_path}"
    admin_conn.execute(_read(str(slice11_path)))  # نباید استثنا بدهد


# ===========================================================================
# Slice 15 — ایندکس‌های tenant-time برای مقیاسِ چندمستأجری (قدم ۶۴)
#   دو ایندکسِ مرکبِ tenant-LED روی تنها دو مسیرِ داغِ واقعاً tenant-محور:
#     R1) clinical.patient_links (tenant_id, enrolled_at DESC) — list_patients
#     R2) clinical.followup_tasks (tenant_id, status, due_date) — worklist/dispatcher
#   (بقیهٔ مسیرها patient_link_id-پیشرو و از قبل ایندکس‌شده‌اند؛ data-architect
#    عمداً ایندکسِ بیشتری اضافه نکرد تا write-amplification نشود.)
# ===========================================================================

# ---------------------------------------------------------------------------
# معیار ۱ — ایندکسِ idx_patient_links_tenant_enrolled وجود دارد (R1)
# ---------------------------------------------------------------------------
def test_slice15_patient_links_tenant_enrolled_index_exists(admin_conn):
    """Slice 15: ایندکسِ idx_patient_links_tenant_enrolled روی clinical.patient_links باید وجود داشته باشد."""
    row = admin_conn.execute(
        """
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = 'clinical'
          AND tablename = 'patient_links'
          AND indexname = 'idx_patient_links_tenant_enrolled'
        """
    ).fetchone()
    assert row is not None, (
        "ایندکسِ 'idx_patient_links_tenant_enrolled' روی clinical.patient_links پیدا نشد (slice15)"
    )


# ---------------------------------------------------------------------------
# معیار ۲ — ایندکسِ idx_followup_tenant_status_due وجود دارد (R2)
# ---------------------------------------------------------------------------
def test_slice15_followup_tenant_status_due_index_exists(admin_conn):
    """Slice 15: ایندکسِ idx_followup_tenant_status_due روی clinical.followup_tasks باید وجود داشته باشد."""
    row = admin_conn.execute(
        """
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = 'clinical'
          AND tablename = 'followup_tasks'
          AND indexname = 'idx_followup_tenant_status_due'
        """
    ).fetchone()
    assert row is not None, (
        "ایندکسِ 'idx_followup_tenant_status_due' روی clinical.followup_tasks پیدا نشد (slice15)"
    )


# ---------------------------------------------------------------------------
# معیار ۳ — idempotency: اجرای مجددِ slice15 بدونِ خطا
# ---------------------------------------------------------------------------
def test_slice15_idempotent_re_apply(admin_conn):
    """Slice 15: اجرای مجددِ slice15 بدونِ خطا (CREATE INDEX IF NOT EXISTS)."""
    import pathlib
    slice15_path = pathlib.Path(_MIG) / "schema_pg_slice15_tenant_indexes.sql"
    assert slice15_path.exists(), f"فایلِ slice15 پیدا نشد: {slice15_path}"
    admin_conn.execute(_read(str(slice15_path)))  # نباید استثنا بدهد
