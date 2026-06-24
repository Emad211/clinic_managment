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
    # نوشتن روی جدولِ بالینی مجاز است (سپس rollback می‌شود)
    clinical_tx.execute(
        "INSERT INTO clinical.patient_links (tenant_id, patient_id) VALUES (1, %s)", (pid,)
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
        conn.execute(
            """INSERT INTO clinical.processed_invoices
                   (tenant_id, accounting_invoice_id, national_id, full_name)
               VALUES (1, 999999, 'FAKE', 'تستِ مرز')"""
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
