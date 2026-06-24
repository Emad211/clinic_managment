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
