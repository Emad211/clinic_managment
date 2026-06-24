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
_MIG = os.path.join(_HERE, "..", "docs", "migration_tools")

# همهٔ برش‌ها به ترتیبِ نام: slice0 → slice2 → (slice3 در آینده)
SLICE_FILES = sorted(glob.glob(os.path.join(_MIG, "schema_pg_slice*.sql")))

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
    """اتصال با کاربرِ LOGINِ عضوِ clinical_app — مسیرِ ایزولاسیونِ واقعیِ production."""
    conn = psycopg.connect(_login_dsn())
    try:
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
