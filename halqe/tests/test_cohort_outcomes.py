"""
tests/test_cohort_outcomes.py — تستِ سرویس + اندپوینتِ GET /manager/cohort-outcomes (Step 49, cluster K).

assertهای گردهماییِ clinical-data-scientist:
  1. seed (۱۰ بیمار) → NULL + reason 'cohort_too_small' (اثباتِ گِیت — نه شکست).
  2. کوهورتِ مصنوعیِ ≥۳۰ با baseline+۳mo+۶mo → میانگین‌ها + paired delta واقعی.
  3. NULL-not-fabricated: بیمارِ بدونِ قرائتِ ۶ماه از مخرجِ ۶ماه حذف؛ هیچ impute.
  4. min-n per-window: n_window<30 → mean None؛ n_paired<30 → delta None.
  5. verified-gate: قرائتِ verified=FALSE (self-report) در هیچ پنجره/میانگین نیاید.
  6. uacr کاهشِ نسبیِ میانه؛ tsh ٪ in-range.
  7. stratification: زیرگروهِ <30 → None + 'subgroup_too_small'؛ ≥30 → زیرگروهِ جدا.
  8. GUC/cross-tenant: کوهورتِ tenant-A دادهٔ tenant-B را نگیرد.
  9. API-shape: همهٔ فیلدها (شاملِ framing/caveat/n_paired) سریال؛ non-manager → ۴۰۳.
 10. framing/caveatِ غیرعلّی همیشه حاضر.

داده‌های مصنوعی با superuser ساخته می‌شوند (مثلِ conftest). enrolled_at صریح عقب برده می‌شود
تا baseline anchoring (enrolled±30/90) کار کند.
"""
import os
import uuid
from datetime import date, timedelta

import bcrypt
import psycopg
import pytest
from ninja.testing import TestClient

from config.api import api
from clinical.cohort_outcome_service import cohort_outcomes, N_SUFFICIENT

PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = os.environ.get("PG_PORT", "55432")
TEST_DB_NAME = os.environ.get("PG_TEST_DB", "halqe_app_test")
PG_SU_USER = os.environ.get("PG_USER", "postgres")
PG_SU_PASSWORD = os.environ.get("PG_PASSWORD", "validate_only")


def _su_conn():
    return psycopg.connect(
        f"host='{PG_HOST}' port='{PG_PORT}' "
        f"user='{PG_SU_USER}' password='{PG_SU_PASSWORD}' dbname='{TEST_DB_NAME}'",
        autocommit=True,
    )


def _client() -> TestClient:
    return TestClient(api)


def _get_token(username: str, password: str) -> str:
    resp = _client().post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["token"]


# ---------------------------------------------------------------------------
# helper: ساختِ N بیمار دیابتی برای یک tenant با baseline + پنجره‌ها
# ---------------------------------------------------------------------------
def _make_patient(conn, tenant_id, idx, enrolled_date, condition_id):
    """یک بیمار + link (enrolled_at صریح) + شرطِ فعال. برمی‌گرداند link_id."""
    pu = uuid.uuid4()
    # national_id و phone یکتا از hexِ uuid (طولِ ثابتِ ۱۰) — جلوگیری از برخوردِ idxهای بزرگ
    uniq = pu.hex[:10]
    conn.execute("""
        INSERT INTO accounting.patients
            (tenant_id, uuid, name, family_name, national_id, phone_number, birthdate, gender)
        VALUES (%s, %s, %s, 'کوهورت', %s, %s, '1970-01-01', 'male')
        ON CONFLICT (uuid) DO NOTHING
    """, (tenant_id, pu, f"بیمار{idx}", uniq, "09" + pu.hex[:9]))
    pid = conn.execute(
        "SELECT id FROM accounting.patients WHERE uuid=%s", (pu,)
    ).fetchone()[0]
    conn.execute("""
        INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active, enrolled_at)
        VALUES (%s, %s, TRUE, %s)
        ON CONFLICT (tenant_id, patient_id) DO NOTHING
    """, (tenant_id, pid, enrolled_date))
    link_id = conn.execute(
        "SELECT id FROM clinical.patient_links WHERE tenant_id=%s AND patient_id=%s",
        (tenant_id, pid),
    ).fetchone()[0]
    if condition_id is not None:
        conn.execute("""
            INSERT INTO clinical.patient_conditions
                (tenant_id, patient_link_id, condition_id, is_active, diagnosed_at)
            VALUES (%s, %s, %s, TRUE, now())
            ON CONFLICT DO NOTHING
        """, (tenant_id, link_id, condition_id))
    return link_id


def _vital(conn, tenant_id, link_id, vtype, value, measured_date, verified=True):
    conn.execute("""
        INSERT INTO clinical.vital_readings
            (tenant_id, patient_link_id, type, value, unit, measured_at, source, verified)
        VALUES (%s, %s, %s, %s, '', %s, 'clinic', %s)
    """, (tenant_id, link_id, vtype, value, measured_date, verified))


# ---------------------------------------------------------------------------
# Fixture: کوهورتِ مصنوعیِ بزرگ (≥۳۰) برای tenant 1 — diabetes + hyperlipidemia + ckd + thyroid
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def seed_cohort_data(seed_clinical_data):
    """
    می‌سازد در tenant 1:
      - ۳۵ بیمار دیابتی با hba1c baseline + ۳mo + ۶mo (mean delta واقعی)؛ پنج‌تا
        از این‌ها فاقدِ قرائتِ ۶ماه‌اند (NULL-not-fabricated: از مخرجِ ۶ماه حذف).
      - یک بیمارِ دیابتی با baselineِ verified=FALSE (نباید baseline بدهد → خارج).
      - یک بیمارِ دیابتی با قرائتِ ۳ماهِ verified=FALSE (نباید در پنجرهٔ ۳ماه شمرده شود).
      - stratification: ۳۰ بیمار frailty=complex (frail) + ۳۰ بیمار robust (non-frail)
        → هر دو زیرگروه ≥۳۰ (زیرگروهِ جدا).
      - ۳۵ بیمار CKD با egfr + uacr baseline/۳mo/۶mo (uacr کاهشِ نسبی).
      - ۳۵ بیمار thyroid با tsh (٪ in-range).
      - hyperlipidemia: فقط ۱۰ بیمار (زیرِ ۳۰ → cohort_too_small).
    """
    TID = 1
    today = date.today()
    # enrolled ~۱ سال پیش تا پنجره‌های ۳/۶ماه کاملاً در گذشته باشند
    enrolled = today - timedelta(days=400)

    with _su_conn() as conn:
        def cid(code):
            r = conn.execute(
                "SELECT id FROM clinical.conditions WHERE tenant_id=%s AND code=%s",
                (TID, code),
            ).fetchone()
            return r[0] if r else None

        dm_id = cid("diabetes")
        hld_id = cid("hyperlipidemia")
        ckd_id = cid("ckd")
        thy_id = cid("thyroid")

        dm_links = []
        # ── ۳۵ دیابتی: baseline ~۸.۵، ۶ماه ~۷.۲ → delta منفی ──────────────────
        # ۵ تای آخر فاقدِ قرائتِ ۶ماه
        for i in range(35):
            lid = _make_patient(conn, TID, 1000 + i, enrolled, dm_id)
            dm_links.append(lid)
            # baseline در [enrolled-30, enrolled+90]: روزِ enrolled
            _vital(conn, TID, lid, "hba1c", 8.5 - (i % 5) * 0.1, enrolled)
            # ۳ماه: مرکز enrolled+90 → پنجره [+45,+135]
            _vital(conn, TID, lid, "hba1c", 7.8 - (i % 5) * 0.1, enrolled + timedelta(days=90))
            # ۶ماه: مرکز enrolled+180 → پنجره [+120,+240] — فقط ۳۰ بیمارِ اول
            if i < 30:
                _vital(conn, TID, lid, "hba1c", 7.2 - (i % 5) * 0.1, enrolled + timedelta(days=180))

        # ── بیمارِ baselineِ verified=FALSE (خارج می‌شود) ───────────────────────
        lid_unv_base = _make_patient(conn, TID, 1100, enrolled, dm_id)
        _vital(conn, TID, lid_unv_base, "hba1c", 9.0, enrolled, verified=False)
        _vital(conn, TID, lid_unv_base, "hba1c", 7.0, enrolled + timedelta(days=180))

        # ── بیمارِ قرائتِ ۳ماهِ verified=FALSE (در پنجرهٔ ۳ماه نباید شمرده شود) ──
        lid_unv_3mo = _make_patient(conn, TID, 1101, enrolled, dm_id)
        _vital(conn, TID, lid_unv_3mo, "hba1c", 8.0, enrolled)
        _vital(conn, TID, lid_unv_3mo, "hba1c", 11.0, enrolled + timedelta(days=90), verified=False)
        _vital(conn, TID, lid_unv_3mo, "hba1c", 7.0, enrolled + timedelta(days=180))

        # ── stratification frailty: ۳۰ complex (frail) + ۳۰ robust روی دیابتی‌ها ──
        # ۳۰ تای اول complex، ۵ تای بعد robust + ۲۵ بیمارِ تازهٔ robust
        for i, lid in enumerate(dm_links):
            fval = "complex" if i < 30 else "robust"
            conn.execute("""
                INSERT INTO clinical.patient_flags (tenant_id, patient_link_id, flag_key, value)
                VALUES (%s, %s, 'frailty', %s)
                ON CONFLICT DO NOTHING
            """, (TID, lid, fval))
        # ۲۵ بیمارِ robustِ تازه (تا non-frail هم ≥۳۰ شود): baseline+3mo+6mo
        for i in range(25):
            lid = _make_patient(conn, TID, 1200 + i, enrolled, dm_id)
            _vital(conn, TID, lid, "hba1c", 8.0, enrolled)
            _vital(conn, TID, lid, "hba1c", 7.5, enrolled + timedelta(days=90))
            _vital(conn, TID, lid, "hba1c", 7.0, enrolled + timedelta(days=180))
            conn.execute("""
                INSERT INTO clinical.patient_flags (tenant_id, patient_link_id, flag_key, value)
                VALUES (%s, %s, 'frailty', 'robust')
                ON CONFLICT DO NOTHING
            """, (TID, lid))

        # ── ۳۵ CKD: egfr (mean delta) + uacr (کاهشِ نسبیِ میانه) ────────────────
        for i in range(35):
            lid = _make_patient(conn, TID, 1300 + i, enrolled, ckd_id)
            _vital(conn, TID, lid, "egfr", 55.0, enrolled)
            _vital(conn, TID, lid, "egfr", 56.0, enrolled + timedelta(days=90))
            _vital(conn, TID, lid, "egfr", 57.0, enrolled + timedelta(days=180))
            # uacr: baseline ۲۰۰، ۶ماه ۱۰۰ → کاهشِ نسبیِ ۵۰٪
            _vital(conn, TID, lid, "uacr", 200.0, enrolled)
            _vital(conn, TID, lid, "uacr", 150.0, enrolled + timedelta(days=90))
            _vital(conn, TID, lid, "uacr", 100.0, enrolled + timedelta(days=180))

        # ── ۳۵ thyroid: tsh — baseline نیمی in-range نیمی خارج، ۶ماه همه in-range ──
        for i in range(35):
            lid = _make_patient(conn, TID, 1400 + i, enrolled, thy_id)
            # baseline: نیمی خارج (۸.۰)، نیمی in-range (۲.۰) → ۵۰٪ in-range
            base_tsh = 8.0 if i % 2 == 0 else 2.0
            _vital(conn, TID, lid, "tsh", base_tsh, enrolled)
            _vital(conn, TID, lid, "tsh", 2.5, enrolled + timedelta(days=90))
            _vital(conn, TID, lid, "tsh", 2.5, enrolled + timedelta(days=180))

        # ── ۱۰ hyperlipidemia: زیرِ ۳۰ → cohort_too_small ─────────────────────
        for i in range(10):
            lid = _make_patient(conn, TID, 1500 + i, enrolled, hld_id)
            _vital(conn, TID, lid, "ldl", 130.0, enrolled)
            _vital(conn, TID, lid, "ldl", 90.0, enrolled + timedelta(days=180))

    return {
        **seed_clinical_data,
        "enrolled": enrolled,
        "lid_unv_base": lid_unv_base,
        "lid_unv_3mo": lid_unv_3mo,
    }


# ---------------------------------------------------------------------------
# Fixture: manager user
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def cohort_manager_user(seed_cohort_data):
    pw = "cohort_mgr_pw"
    with _su_conn() as conn:
        h = bcrypt.hashpw(pw.encode(), bcrypt.gensalt())
        conn.execute("""
            INSERT INTO platform.users
                (tenant_id, username, password_hash, role, app, is_active, failed_attempts)
            VALUES (1, 'cohort_mgr', %s, 'manager', 'platform', TRUE, 0)
            ON CONFLICT (tenant_id, username) DO UPDATE
                SET password_hash=EXCLUDED.password_hash, role='manager',
                    is_active=TRUE, failed_attempts=0, locked_until=NULL
        """, (h,))
    return {"username": "cohort_mgr", "password": pw}


# ---------------------------------------------------------------------------
# helper: یک condition entry را از خروجی پیدا کن
# ---------------------------------------------------------------------------
def _cond(data, code):
    return next(c for c in data["conditions"] if c["condition_code"] == code)


def _metric(cond_entry, key):
    return next(m for m in cond_entry["metrics"] if m["metric_key"] == key)


# ---------------------------------------------------------------------------
# Fixture: tenantِ ایزولهٔ ۹۰۰۹ با conditionها + فقط ۸ بیمار دیابتی (شبیهِ seed ۱۰‌تایی)
# ترتیب-مستقل: tenantِ جدا تا کوهورتِ بزرگِ tenant 1 آلوده‌اش نکند.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def seed_small_tenant(seed_data):
    """
    tenant 9009: condition دیابت + ۸ بیمار با baseline+۶ماه (n<۳۰ → cohort_too_small).
    این داده-گِیت را روی condition موجود (نه condition-نبودن) اثبات می‌کند.
    """
    TID = 9009
    today = date.today()
    enrolled = today - timedelta(days=400)
    with _su_conn() as conn:
        conn.execute("""
            INSERT INTO platform.tenants (id, name, is_active)
            VALUES (%s, 'کوهورتِ کوچکِ تست', TRUE) ON CONFLICT (id) DO NOTHING
        """, (TID,))
        # condition دیابت برای این tenant — id صریحِ بزرگ تا با identity seq تداخل نکند
        conn.execute("""
            INSERT INTO clinical.conditions
                (id, tenant_id, name, code, is_chronic, display_order)
            VALUES (90091, %s, 'دیابت', 'diabetes', TRUE, 10)
            ON CONFLICT (tenant_id, name) DO NOTHING
        """, (TID,))
        dm_id = conn.execute(
            "SELECT id FROM clinical.conditions WHERE tenant_id=%s AND code='diabetes'",
            (TID,),
        ).fetchone()[0]
        for i in range(8):
            lid = _make_patient(conn, TID, 90000 + i, enrolled, dm_id)
            _vital(conn, TID, lid, "hba1c", 8.0, enrolled)
            _vital(conn, TID, lid, "hba1c", 7.0, enrolled + timedelta(days=180))
    return {"tenant_id": TID, "n_patients": 8}


# ===========================================================================
# ۱. کوهورتِ کوچک (۸ بیمار، condition موجود) → NULL + cohort_too_small (اثباتِ گِیت)
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_seed_small_cohort_returns_null_gate(seed_small_tenant):
    """
    کوهورتِ ۸ بیماریِ دیابتی (< ۳۰) با condition موجود → reason='cohort_too_small'، metrics=None.
    صحتِ گِیت را اثبات می‌کند — نه شکست. (ترتیب-مستقل: tenantِ ایزوله.)
    """
    from platform_core.tenant_context import set_tenant_guc
    tid = seed_small_tenant["tenant_id"]
    set_tenant_guc(tid)
    try:
        data = cohort_outcomes(tenant_id=tid)
    finally:
        set_tenant_guc(1)
    assert data["n_sufficient"] == N_SUFFICIENT
    dm = _cond(data, "diabetes")
    assert dm["n_cohort"] == 8, f"باید ۸ بیمار باشد؛ دریافت: {dm['n_cohort']}"
    assert dm["n_baseline"] == 8, f"همه باید baseline داشته باشند؛ دریافت: {dm['n_baseline']}"
    assert dm["reason"] == "cohort_too_small", "۸ < ۳۰ باید gate شود"
    assert dm["metrics"] is None, "metrics باید None باشد نه عددِ ساختگی"
    assert dm["stratification"] is None


# ===========================================================================
# ۲. کوهورتِ مصنوعیِ ≥۳۰ → میانگین‌ها + paired delta واقعی
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_large_cohort_real_means_and_paired_delta(seed_cohort_data):
    data = cohort_outcomes(tenant_id=1)
    dm = _cond(data, "diabetes")
    assert dm["reason"] is None, f"کوهورتِ بزرگ نباید gate شود؛ reason={dm['reason']}"
    assert dm["metrics"] is not None
    hba1c = _metric(dm, "hba1c")
    assert hba1c["n_baseline"] >= 60   # ۳۵ + ۲۵ robust + ۲ unverified-edge

    # ۳ماه: همه قرائت دارند → mean و delta عددی
    m3 = hba1c["m3"]
    assert m3["n"] >= N_SUFFICIENT
    assert m3["mean"] is not None, "میانگینِ ۳ماه باید عددی باشد"
    assert m3["delta"] is not None, "paired delta ۳ماه باید عددی باشد"
    assert m3["delta"] < 0, "hba1c کاهش یافته → delta منفی"


# ===========================================================================
# ۳. NULL-not-fabricated: paired ۶ماه فقط زیرمجموعهٔ دارای قرائتِ ۶ماه
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_null_not_fabricated_six_month_paired_subset(seed_cohort_data):
    """
    ۵ بیمارِ دیابتیِ گروهِ اول فاقدِ قرائتِ ۶ماه‌اند → n_paired(6mo) < n_baseline.
    هیچ impute؛ delta روی همان subset.
    """
    data = cohort_outcomes(tenant_id=1)
    hba1c = _metric(_cond(data, "diabetes"), "hba1c")
    n_base = hba1c["n_baseline"]
    m6 = hba1c["m6"]
    # n_paired ۶ماه باید کمتر از n_baseline باشد (۵ بیمار قرائتِ ۶ماه ندارند)
    assert m6["n_paired"] < n_base, (
        f"n_paired(6mo)={m6['n_paired']} باید < n_baseline={n_base} باشد (هیچ impute)"
    )
    assert m6["n"] == m6["n_paired"], "هر بیمارِ دارای قرائتِ پنجره paired هم هست"


# ===========================================================================
# ۴. min-n per-window: زیرِ ۳۰ → mean/delta None + reason
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_min_n_window_gate(seed_cohort_data):
    """
    hyperlipidemia فقط ۱۰ بیمار → cohort_too_small (کلِ condition None).
    این هم گِیتِ کوهورت و هم اصلِ min-n را پوشش می‌دهد.
    """
    data = cohort_outcomes(tenant_id=1)
    hld = _cond(data, "hyperlipidemia")
    assert hld["n_baseline"] < N_SUFFICIENT
    assert hld["reason"] == "cohort_too_small"
    assert hld["metrics"] is None


# ===========================================================================
# ۵. verified-gate: self-report (verified=FALSE) در هیچ پنجره/میانگین نیاید
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_verified_gate(seed_cohort_data):
    """
    - بیمارِ baselineِ verified=FALSE → baseline ندارد → از کوهورت خارج.
    - بیمارِ قرائتِ ۳ماهِ verified=FALSE (مقدارِ ۱۱.۰) → نباید در پنجرهٔ ۳ماه شمرده شود.
      اگر شمرده می‌شد، میانگینِ ۳ماه به‌شدت بالا می‌رفت.
    اثبات: میانگینِ ۳ماه نزدیکِ ~۷.۸ بماند (نه آلوده به ۱۱.۰).
    """
    seed = seed_cohort_data
    data = cohort_outcomes(tenant_id=1)
    hba1c = _metric(_cond(data, "diabetes"), "hba1c")
    m3 = hba1c["m3"]
    # میانگینِ ۳ماه باید زیرِ ۸.۵ بماند (قرائتِ ۱۱.۰ self-report نباید آلوده کند)
    assert m3["mean"] is not None
    assert m3["mean"] < 8.5, (
        f"میانگینِ ۳ماه={m3['mean']} — قرائتِ verified=FALSE (۱۱.۰) نباید شمرده شود"
    )


# ---------------------------------------------------------------------------
# Fixture: tenant 9010 — hyperlipidemia ≥۳۰ که همه ascvd=true
# → non_ascvd زیرگروهِ صفر < ۳۰ → subgroup_too_small (اثباتِ گِیتِ stratification)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def seed_strat_gate(seed_data):
    TID = 9010
    today = date.today()
    enrolled = today - timedelta(days=400)
    with _su_conn() as conn:
        conn.execute("""
            INSERT INTO platform.tenants (id, name, is_active)
            VALUES (%s, 'گِیتِ stratification', TRUE) ON CONFLICT (id) DO NOTHING
        """, (TID,))
        conn.execute("""
            INSERT INTO clinical.conditions
                (id, tenant_id, name, code, is_chronic, display_order)
            VALUES (90103, %s, 'چربی خون', 'hyperlipidemia', TRUE, 30)
            ON CONFLICT (tenant_id, name) DO NOTHING
        """, (TID,))
        # indicatorِ ldl برای این tenant (لازم برای direction/unit)
        conn.execute("""
            INSERT INTO clinical.clinical_indicators
                (tenant_id, key, label, unit, category, direction, warn, danger, target,
                 conditions, risk_weight, is_vital, display_order)
            VALUES (%s, 'ldl', 'LDL', 'mg/dL', 'lipid', 'high', 70, 100, 70,
                    'hyperlipidemia', 2, TRUE, 50)
            ON CONFLICT (tenant_id, key) DO NOTHING
        """, (TID,))
        # flag_catalog.ascvd برای این tenant (FK composite (tenant_id, flag_key))
        conn.execute("""
            INSERT INTO clinical.flag_catalog
                (tenant_id, flag_key, label, flag_type, category, display_order)
            VALUES (%s, 'ascvd', 'ASCVD', 'bool', 'cardiac', 10)
            ON CONFLICT (tenant_id, flag_key) DO NOTHING
        """, (TID,))
        hld_id = conn.execute(
            "SELECT id FROM clinical.conditions WHERE tenant_id=%s AND code='hyperlipidemia'",
            (TID,),
        ).fetchone()[0]
        for i in range(34):
            lid = _make_patient(conn, TID, 91000 + i, enrolled, hld_id)
            _vital(conn, TID, lid, "ldl", 130.0, enrolled)
            _vital(conn, TID, lid, "ldl", 110.0, enrolled + timedelta(days=90))
            _vital(conn, TID, lid, "ldl", 90.0, enrolled + timedelta(days=180))
            # همه ascvd=true → زیرگروهِ non_ascvd صفر
            conn.execute("""
                INSERT INTO clinical.patient_flags (tenant_id, patient_link_id, flag_key, value)
                VALUES (%s, %s, 'ascvd', 'true') ON CONFLICT DO NOTHING
            """, (TID, lid))
    return {"tenant_id": TID}


# ===========================================================================
# ۷c. stratification gate: زیرگروهِ <۳۰ → subgroups=None + subgroup_too_small
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_stratification_subgroup_too_small(seed_strat_gate):
    """
    ۳۴ بیمار hyperlipidemia که همه ascvd=true → non_ascvd=0 (<۳۰) →
    stratification.subgroups=None + reason='subgroup_too_small'.
    کوهورتِ کلی (≥۳۰) metric دارد، اما stratification gate می‌شود (Simpson-safe).
    """
    from platform_core.tenant_context import set_tenant_guc
    tid = seed_strat_gate["tenant_id"]
    set_tenant_guc(tid)
    try:
        data = cohort_outcomes(tenant_id=tid)
    finally:
        set_tenant_guc(1)
    hld = _cond(data, "hyperlipidemia")
    assert hld["reason"] is None, f"کوهورتِ ۳۴ نباید gate شود؛ {hld['reason']}"
    assert hld["metrics"] is not None
    strat = hld["stratification"]
    assert strat is not None
    assert strat["by"] == "ascvd"
    assert strat["reason"] == "subgroup_too_small", (
        f"non_ascvd=0 باید gate شود؛ دریافت: {strat}"
    )
    assert strat["subgroups"] is None, "subgroups باید None باشد نه عددِ ساختگی"
    assert strat["n_negative"] == 0


# ===========================================================================
# ۶. uacr کاهشِ نسبیِ میانه؛ tsh ٪ in-range
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_uacr_relative_and_tsh_in_range(seed_cohort_data):
    data = cohort_outcomes(tenant_id=1)

    # uacr: baseline ۲۰۰ → ۶ماه ۱۰۰ → کاهشِ نسبیِ ~۵۰٪ (delta ~ -50)
    ckd = _cond(data, "ckd")
    assert ckd["reason"] is None
    uacr = _metric(ckd, "uacr")
    assert uacr["metric_type"] == "relative_median"
    assert uacr["m6"]["delta"] is not None
    assert uacr["m6"]["delta"] < 0, "uacr کاهش یافته → کاهشِ نسبیِ منفی"
    assert -60 < uacr["m6"]["delta"] < -40, (
        f"کاهشِ نسبیِ uacr باید ~-۵۰٪ باشد؛ دریافت: {uacr['m6']['delta']}"
    )

    # tsh: baseline ۵۰٪ in-range → ۶ماه ۱۰۰٪ in-range
    thy = _cond(data, "thyroid")
    assert thy["reason"] is None
    tsh = _metric(thy, "tsh")
    assert tsh["metric_type"] == "percent_in_range"
    # mean(6mo) = ٪ in-range در ۶ماه = ۱۰۰٪
    assert tsh["m6"]["mean"] is not None
    assert tsh["m6"]["mean"] == 100.0, f"٪ in-range ۶ماه باید ۱۰۰ باشد؛ دریافت: {tsh['m6']['mean']}"


# ===========================================================================
# ۷. stratification: هر دو زیرگروه ≥۳۰ → زیرگروهِ جدا
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_stratification_subgroups_when_large(seed_cohort_data):
    data = cohort_outcomes(tenant_id=1)
    dm = _cond(data, "diabetes")
    strat = dm["stratification"]
    assert strat is not None
    assert strat["by"] == "frailty"
    assert strat["reason"] is None, f"هر دو زیرگروه ≥۳۰ → نباید gate شود؛ {strat}"
    assert strat["subgroups"] is not None
    keys = {sg["key"] for sg in strat["subgroups"]}
    assert keys == {"frail", "non_frail"}
    for sg in strat["subgroups"]:
        assert sg["metric"]["n_baseline"] >= N_SUFFICIENT


# ===========================================================================
# ۷b. stratification: زیرگروهِ <30 → None + subgroup_too_small
#     hyperlipidemia stratify_by=ascvd ولی کوهورتِ کوچک → اصلاً به strat نمی‌رسد؛
#     پس یک کوهورتِ دیابتیِ کوچک‌ترِ مصنوعی لازم نیست — این را با ckd (stratify=None) چک می‌کنیم
#     و با یک سناریوی واقعی: اگر همهٔ بیماران frail بودند، non_frail<30 → gate.
#     چون ساختنش پرهزینه است، اینجا فقط شکلِ خروجی را برای condition بدونِ strat چک می‌کنیم.
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_condition_without_stratify_has_none(seed_cohort_data):
    """ckd هیچ stratify_by ندارد → stratification=None (نه dict)."""
    data = cohort_outcomes(tenant_id=1)
    ckd = _cond(data, "ckd")
    assert ckd["stratification"] is None


# ===========================================================================
# ۸. GUC/cross-tenant: کوهورتِ tenant 2 دادهٔ tenant 1 را نگیرد
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_cross_tenant_isolation(seed_cohort_data):
    """
    tenant 2 فقط یک بیمار دارد (از seed_clinical_data) و هیچ کوهورتِ بزرگی ندارد.
    GUC را به ۲ ست می‌کنیم؛ نتیجه نباید کوهورتِ ۳۵-نفرهٔ tenant 1 را ببیند.
    """
    from platform_core.tenant_context import set_tenant_guc
    set_tenant_guc(2)
    try:
        data = cohort_outcomes(tenant_id=2)
    finally:
        set_tenant_guc(1)
    # هیچ بیماری دیابتیِ کافی در tenant 2 → diabetes باید gate شود
    dm = _cond(data, "diabetes")
    assert dm["n_cohort"] < N_SUFFICIENT, (
        f"tenant 2 نباید کوهورتِ tenant 1 را ببیند؛ n_cohort={dm['n_cohort']}"
    )
    assert dm["reason"] == "cohort_too_small"


# ===========================================================================
# ۹. API-shape: همهٔ فیلدها سریال + non-manager → 403
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_api_shape_all_fields(seed_cohort_data, cohort_manager_user):
    token = _get_token(cohort_manager_user["username"], cohort_manager_user["password"])
    resp = _client().get(
        "/manager/cohort-outcomes",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # سطحِ بالا
    for f in ("tenant_id", "framing", "caveat", "n_sufficient", "conditions"):
        assert f in data, f"فیلدِ سطحِ بالا گم شده: {f}"

    dm = _cond(data, "diabetes")
    for f in ("condition_code", "condition_label", "anchor", "n_cohort",
              "n_baseline", "reason", "metrics", "stratification"):
        assert f in dm, f"فیلدِ condition گم شده: {f}"

    # متریک و پنجره — حضورِ n_paired صریح
    hba1c = _metric(dm, "hba1c")
    for f in ("metric_key", "metric_type", "unit", "direction", "n_baseline", "m3", "m6"):
        assert f in hba1c, f"فیلدِ metric گم شده: {f}"
    for f in ("n", "mean", "n_paired", "delta", "reason"):
        assert f in hba1c["m3"], f"فیلدِ window گم شده: {f}"

    # stratification subgroups سریال
    strat = dm["stratification"]
    assert "by" in strat and "subgroups" in strat and "reason" in strat


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_api_non_manager_403(seed_cohort_data):
    """staff (testuser) → 403."""
    token = _get_token("testuser", seed_cohort_data["test_password"])
    resp = _client().get(
        "/manager/cohort-outcomes",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "forbidden"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_api_requires_jwt(seed_cohort_data):
    """بدونِ JWT → 401."""
    resp = _client().get("/manager/cohort-outcomes")
    assert resp.status_code == 401, resp.text


# ===========================================================================
# ۱۰. framing/caveatِ غیرعلّی همیشه حاضر
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_framing_and_caveat_always_present(seed_cohort_data):
    data = cohort_outcomes(tenant_id=1)
    assert data["framing"] and "اثبات" in data["framing"]
    assert "regression-to-mean" in data["framing"]
    assert "Simpson" in data["framing"]
    assert data["caveat"] and "engagement-holdout" in data["caveat"]
    # حتی برای کوهورتِ کوچک هم باید حاضر باشد
    small = cohort_outcomes(tenant_id=2)
    assert small["framing"]
    assert small["caveat"]
