"""
tests/test_outcome_trend.py — تستِ سرویس + اندپوینت‌های آنالیتیکسِ مدیر (Step 50, cluster K).

دو endpointِ نو:
  GET /manager/lapsed-return   — نرخِ بازگشتِ کوهورتِ lapsed (closed-window).
  GET /manager/control-trend   — ۱۲ باکتِ ماهانهٔ ٪کنترل (per-condition + 'all').

assertهای گردهماییِ clinical-data-scientist (NULL-not-fabricated، غیرعلّی):
  1. seed (۱۰ بیمار/کوچک) → return_rate=null و pct_controlled=null (گِیت، نه صفر/خطا).
  2. کوهورتِ مصنوعیِ ≥۳۰ lapsed با برخی returned → نرخِ واقعی؛ control-trend ≥۳۰ assessable → pct واقعی.
  3. رویدادِ بازگشتِ درست: SMS/recall به‌عنوانِ بازگشت شمرده نشود؛ Appointmentِ done شمرده شود.
  4. verified-gate: قرائتِ verified=FALSE نه در lapsed-return نه در control-trend شمرده نشود.
  5. closed-window: بیماری که فقط در آیندهٔ T0+120d رویداد دارد (نه در پنجره) returned نشود.
  6. GUC/cross-tenant، API-shape (همه فیلدها + framing)، non-manager→403، بدونِ JWT→401.

داده‌ها با superuser ساخته می‌شوند؛ tenantهای ایزوله تا ترتیب-مستقل بمانند.
"""
import os
import uuid
from datetime import date, timedelta, datetime, timezone as _tz

import bcrypt
import psycopg
import pytest
from ninja.testing import TestClient

from config.api import api
from clinical.outcome_trend_service import (
    lapsed_return,
    control_trend,
    N_SUFFICIENT,
    LAPSE_WINDOW_DAYS,
    RETURN_WINDOW_DAYS,
    T0_OFFSET_DAYS,
)

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
# زمان‌بندیِ مرجع — هم‌سو با سرویس
# ---------------------------------------------------------------------------
def _now():
    return datetime.now(_tz.utc)


def _make_patient(conn, tenant_id, idx, condition_id):
    """یک بیمار + link + شرطِ فعال. برمی‌گرداند link_id."""
    pu = uuid.uuid4()
    uniq = pu.hex[:10]
    conn.execute("""
        INSERT INTO accounting.patients
            (tenant_id, uuid, name, family_name, national_id, phone_number, birthdate, gender)
        VALUES (%s, %s, %s, 'بازگشت', %s, %s, '1970-01-01', 'male')
        ON CONFLICT (uuid) DO NOTHING
    """, (tenant_id, pu, f"بیمار{idx}", uniq, "09" + pu.hex[:9]))
    pid = conn.execute(
        "SELECT id FROM accounting.patients WHERE uuid=%s", (pu,)
    ).fetchone()[0]
    conn.execute("""
        INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active, enrolled_at)
        VALUES (%s, %s, TRUE, now() - interval '900 days')
        ON CONFLICT (tenant_id, patient_id) DO NOTHING
    """, (tenant_id, pid))
    link_id = conn.execute(
        "SELECT id FROM clinical.patient_links WHERE tenant_id=%s AND patient_id=%s",
        (tenant_id, pid),
    ).fetchone()[0]
    if condition_id is not None:
        conn.execute("""
            INSERT INTO clinical.patient_conditions
                (tenant_id, patient_link_id, condition_id, is_active, diagnosed_at)
            VALUES (%s, %s, %s, TRUE, now() - interval '900 days')
            ON CONFLICT DO NOTHING
        """, (tenant_id, link_id, condition_id))
    return link_id


def _vital(conn, tid, lid, vtype, value, when, verified=True):
    conn.execute("""
        INSERT INTO clinical.vital_readings
            (tenant_id, patient_link_id, type, value, unit, measured_at, source, verified)
        VALUES (%s, %s, %s, %s, '', %s, 'clinic', %s)
    """, (tid, lid, vtype, value, when, verified))


def _appt(conn, tid, lid, when, status):
    conn.execute("""
        INSERT INTO clinical.appointments
            (tenant_id, patient_link_id, scheduled_at, status, created_at)
        VALUES (%s, %s, %s, %s, now() - interval '900 days')
    """, (tid, lid, when, status))


def _followup(conn, tid, lid, created_when, status):
    conn.execute("""
        INSERT INTO clinical.followup_tasks
            (tenant_id, patient_link_id, reason, status, created_at)
        VALUES (%s, %s, 'lapsed', %s, %s)
    """, (tid, lid, status, created_when))


def _sms(conn, tid, lid, when):
    conn.execute("""
        INSERT INTO clinical.sms_messages
            (tenant_id, patient_link_id, recipient, body, status, sent_at, created_at)
        VALUES (%s, %s, '09120000000', 'یادآوری', 'sent', %s, %s)
    """, (tid, lid, when, when))


# ===========================================================================
# Fixture: tenant 9020 — کوهورتِ lapsed-return مصنوعی
# ===========================================================================
@pytest.fixture(scope="session")
def seed_lapsed(seed_data):
    """
    tenant 9020، condition دیابت. سناریوها (همه با رویدادِ پیش از T0 در ≤ T0-120d → lapsed):
      A) ۳۵ بیمارِ lapsed با Appointment(done) در پنجرهٔ بازگشت → returned.
      B) ۱۰ بیمارِ lapsed بدونِ هیچ رویداد در پنجره → not returned.
      C) ۱ بیمارِ lapsed که در پنجرهٔ بازگشت فقط یک SMS دارد → NOT returned (tautology guard).
      D) ۱ بیمارِ lapsed که فقط در آیندهٔ T0+120d رویداد دارد → NOT returned (closed-window).
      E) ۱ بیمارِ lapsed که بازگشتش فقط vital(verified=FALSE) در پنجره است → NOT returned (verified-gate).
      F) ۱ بیمارِ غیر-lapsed (آخرین رویدادِ پیش از T0 جدیدتر از T0-120d) → از مخرج خارج.
    مخرج باید A+B+C+D+E = 48 باشد (همه lapsed)؛ صورت = A = 35.
    """
    TID = 9020
    now = _now()
    t0 = now - timedelta(days=T0_OFFSET_DAYS)
    # رویدادِ پیش از T0 که بیمار را lapsed می‌کند: T0 - 130d (≤ T0-120d)
    pre_lapse = t0 - timedelta(days=130)
    # رویدادِ بازگشت در پنجره (T0, T0+120d]: T0 + 30d
    in_return = t0 + timedelta(days=30)
    # رویدادِ آینده پس از پنجره: T0 + 200d
    after_window = t0 + timedelta(days=200)

    with _su_conn() as conn:
        conn.execute("""
            INSERT INTO platform.tenants (id, name, is_active)
            VALUES (%s, 'کوهورتِ بازگشت', TRUE) ON CONFLICT (id) DO NOTHING
        """, (TID,))
        conn.execute("""
            INSERT INTO clinical.conditions
                (id, tenant_id, name, code, is_chronic, display_order)
            VALUES (90201, %s, 'دیابت', 'diabetes', TRUE, 10)
            ON CONFLICT (tenant_id, name) DO NOTHING
        """, (TID,))
        dm_id = conn.execute(
            "SELECT id FROM clinical.conditions WHERE tenant_id=%s AND code='diabetes'",
            (TID,),
        ).fetchone()[0]

        # A) ۳۵ returned با Appointment(done) در پنجره
        for i in range(35):
            lid = _make_patient(conn, TID, 92000 + i, dm_id)
            _vital(conn, TID, lid, "hba1c", 8.0, pre_lapse)   # رویدادِ pre-lapse
            _appt(conn, TID, lid, in_return, "done")          # بازگشتِ معنادار
        # B) ۱۰ lapsed بدونِ بازگشت
        for i in range(10):
            lid = _make_patient(conn, TID, 92100 + i, dm_id)
            _vital(conn, TID, lid, "hba1c", 8.0, pre_lapse)
        # C) SMS-only در پنجره → tautology guard (NOT returned)
        lid_sms = _make_patient(conn, TID, 92200, dm_id)
        _vital(conn, TID, lid_sms, "hba1c", 8.0, pre_lapse)
        _sms(conn, TID, lid_sms, in_return)
        # D) closed-window: رویداد فقط در آیندهٔ پس از پنجره
        lid_future = _make_patient(conn, TID, 92201, dm_id)
        _vital(conn, TID, lid_future, "hba1c", 8.0, pre_lapse)
        _appt(conn, TID, lid_future, after_window, "done")
        # E) verified-gate: بازگشت فقط vital(verified=FALSE)
        lid_unv = _make_patient(conn, TID, 92202, dm_id)
        _vital(conn, TID, lid_unv, "hba1c", 8.0, pre_lapse)
        _vital(conn, TID, lid_unv, "hba1c", 7.0, in_return, verified=False)
        # F) غیر-lapsed: آخرین رویدادِ پیش از T0 جدیدتر از T0-120d → از مخرج خارج
        lid_active = _make_patient(conn, TID, 92203, dm_id)
        _vital(conn, TID, lid_active, "hba1c", 8.0, t0 - timedelta(days=10))

    return {
        "tenant_id": TID,
        "expected_denominator": 48,   # A35 + B10 + C1 + D1 + E1
        "expected_returned": 35,      # فقط A
        "lid_sms": lid_sms,
        "lid_future": lid_future,
        "lid_unv": lid_unv,
        "lid_active": lid_active,
    }


# ===========================================================================
# Fixture: tenant 9021 — control-trend با ≥۳۰ assessable در باکتِ ماهِ جاری
# ===========================================================================
@pytest.fixture(scope="session")
def seed_control_trend(seed_data):
    """
    tenant 9021، دیابت + indicatorِ hba1c. ۴۰ بیمارِ دیابتی با hba1c قدیمی (۳۰ روز پیش):
      - ۲۵ بیمار controlled (hba1c=6.5 < warn 7.0)
      - ۱۵ بیمار uncontrolled (hba1c=9.0 ≥ danger 8.0)
    + ۱ بیمار با قرائتِ verified=FALSE فقط → unknown (نباید assessable شود).
    در باکتِ ماهِ جاری: assessable=40، controlled=25 → pct=62.5٪.
    """
    TID = 9021
    when = _now() - timedelta(days=30)
    with _su_conn() as conn:
        conn.execute("""
            INSERT INTO platform.tenants (id, name, is_active)
            VALUES (%s, 'روندِ کنترل', TRUE) ON CONFLICT (id) DO NOTHING
        """, (TID,))
        conn.execute("""
            INSERT INTO clinical.conditions
                (id, tenant_id, name, code, is_chronic, display_order)
            VALUES (90211, %s, 'دیابت', 'diabetes', TRUE, 10)
            ON CONFLICT (tenant_id, name) DO NOTHING
        """, (TID,))
        # indicatorِ hba1c برای این tenant (warn 7.0 / danger 8.0، direction high)
        conn.execute("""
            INSERT INTO clinical.clinical_indicators
                (tenant_id, key, label, unit, category, direction, warn, danger, target,
                 conditions, risk_weight, is_vital, display_order)
            VALUES (%s, 'hba1c', 'HbA1c', '%%', 'glycemic', 'high', 7.0, 8.0, 7.0,
                    'diabetes', 3, TRUE, 10)
            ON CONFLICT (tenant_id, key) DO NOTHING
        """, (TID,))
        dm_id = conn.execute(
            "SELECT id FROM clinical.conditions WHERE tenant_id=%s AND code='diabetes'",
            (TID,),
        ).fetchone()[0]
        for i in range(40):
            lid = _make_patient(conn, TID, 92300 + i, dm_id)
            val = 6.5 if i < 25 else 9.0
            _vital(conn, TID, lid, "hba1c", val, when)
        # verified=FALSE only → unknown
        lid_unv = _make_patient(conn, TID, 92400, dm_id)
        _vital(conn, TID, lid_unv, "hba1c", 6.0, when, verified=False)
    return {"tenant_id": TID, "expected_assessable": 40, "expected_controlled": 25}


# ===========================================================================
# Fixture: manager + staff users روی tenant 9020/9021 (هر دو از seed_data)
# ===========================================================================
@pytest.fixture(scope="session")
def outcome_users(seed_lapsed, seed_control_trend):
    pw_m = "outcome_mgr_pw"
    with _su_conn() as conn:
        for tid in (9020, 9021):
            h = bcrypt.hashpw(pw_m.encode(), bcrypt.gensalt())
            conn.execute("""
                INSERT INTO platform.users
                    (tenant_id, username, password_hash, role, app, is_active, failed_attempts)
                VALUES (%s, %s, %s, 'manager', 'platform', TRUE, 0)
                ON CONFLICT (tenant_id, username) DO UPDATE
                    SET password_hash=EXCLUDED.password_hash, role='manager',
                        is_active=TRUE, failed_attempts=0, locked_until=NULL
            """, (tid, f"mgr_{tid}", h))
            hs = bcrypt.hashpw(pw_m.encode(), bcrypt.gensalt())
            conn.execute("""
                INSERT INTO platform.users
                    (tenant_id, username, password_hash, role, app, is_active, failed_attempts)
                VALUES (%s, %s, %s, 'staff', 'platform', TRUE, 0)
                ON CONFLICT (tenant_id, username) DO UPDATE
                    SET password_hash=EXCLUDED.password_hash, role='staff',
                        is_active=TRUE, failed_attempts=0, locked_until=NULL
            """, (tid, f"stf_{tid}", hs))
    return {"password": pw_m}


def _guc(tid):
    from platform_core.tenant_context import set_tenant_guc
    set_tenant_guc(tid)


def _guc_reset():
    from platform_core.tenant_context import set_tenant_guc
    set_tenant_guc(1)


# ===========================================================================
# Fixture: tenant 9022 — کوهورتِ کوچکِ ایزوله (شبیهِ seed ۱۰‌تایی).
# ترتیب-مستقل: tenantِ جدا تا fixtureهای session-scopeِ دیگر (که tenant 1 را با
# کوهورتِ بزرگ آلوده می‌کنند) این گِیت را نشکنند — درسِ ترتیب-مستقلِ test_cohort_outcomes.
# ===========================================================================
@pytest.fixture(scope="session")
def seed_small_isolated(seed_data):
    """
    tenant 9022، دیابت + indicatorِ hba1c. فقط ۸ بیمارِ lapsed + ۸ قرائتِ controlled
    (هر دو < min_n) → هر دو متریک باید NULL برگردانند (گِیت، نه صفر/خطا).
    """
    TID = 9022
    now = _now()
    t0 = now - timedelta(days=T0_OFFSET_DAYS)
    pre_lapse = t0 - timedelta(days=130)
    when_ctrl = now - timedelta(days=20)
    with _su_conn() as conn:
        conn.execute("""
            INSERT INTO platform.tenants (id, name, is_active)
            VALUES (%s, 'کوهورتِ کوچکِ ایزوله', TRUE) ON CONFLICT (id) DO NOTHING
        """, (TID,))
        conn.execute("""
            INSERT INTO clinical.conditions
                (id, tenant_id, name, code, is_chronic, display_order)
            VALUES (90221, %s, 'دیابت', 'diabetes', TRUE, 10)
            ON CONFLICT (tenant_id, name) DO NOTHING
        """, (TID,))
        conn.execute("""
            INSERT INTO clinical.clinical_indicators
                (tenant_id, key, label, unit, category, direction, warn, danger, target,
                 conditions, risk_weight, is_vital, display_order)
            VALUES (%s, 'hba1c', 'HbA1c', '%%', 'glycemic', 'high', 7.0, 8.0, 7.0,
                    'diabetes', 3, TRUE, 10)
            ON CONFLICT (tenant_id, key) DO NOTHING
        """, (TID,))
        dm_id = conn.execute(
            "SELECT id FROM clinical.conditions WHERE tenant_id=%s AND code='diabetes'",
            (TID,),
        ).fetchone()[0]
        for i in range(8):
            lid = _make_patient(conn, TID, 92500 + i, dm_id)
            _vital(conn, TID, lid, "hba1c", 8.0, pre_lapse)        # lapsed
            _appt(conn, TID, lid, t0 + timedelta(days=30), "done")  # returned (ولی n<30 → null)
            _vital(conn, TID, lid, "hba1c", 6.5, when_ctrl)        # controlled قرائتِ تازه
    return {"tenant_id": TID}


# ===========================================================================
# ۱. tenantِ کوچکِ ایزوله (۸ بیمار < min_n) → هر دو متریک NULL graceful
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_seed_returns_null_for_both(seed_small_isolated):
    """tenant 9022 با ۸ بیمار < min_n → return_rate=null و pct_controlled=null (نه صفر/خطا)."""
    tid = seed_small_isolated["tenant_id"]
    _guc(tid)
    try:
        lr = lapsed_return(tenant_id=tid)
        ct = control_trend(tenant_id=tid)
    finally:
        _guc_reset()

    assert lr["denominator"] < N_SUFFICIENT, f"باید < ۳۰ باشد؛ {lr['denominator']}"
    assert lr["denominator"] > 0, "باید کوهورتِ غیرصفر داشته باشد (گِیت روی n، نه نبودِ داده)"
    assert lr["return_rate"] is None, "return_rate باید NULL باشد نه صفر"
    assert lr["min_n"] == N_SUFFICIENT
    assert lr["lapse_window_days"] == LAPSE_WINDOW_DAYS
    assert lr["return_window_days"] == RETURN_WINDOW_DAYS

    assert ct["min_n"] == N_SUFFICIENT
    # هر باکت باید pct=null باشد (assessable < ۳۰)
    for b in ct["buckets"]:
        assert b["pct_controlled"] is None, (
            f"باکت {b['ym']}/{b['condition']} باید NULL باشد؛ {b}"
        )


# ===========================================================================
# ۲. lapsed-return: کوهورتِ ≥۳۰ → نرخِ واقعی + رویدادِ بازگشتِ درست + verified + closed-window
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_lapsed_return_real_rate_and_event_gates(seed_lapsed):
    """
    مخرج = همهٔ lapsedها (A35+B10+C1+D1+E1=48)؛ صورت = فقط A (Appointment done) = 35.
    این هم‌زمان اثبات می‌کند:
      - رویدادِ بازگشتِ درست (Appointment done شمرده).
      - SMS-only (C) NOT returned (tautology guard).
      - closed-window (D، رویدادِ آینده) NOT returned.
      - verified-gate (E، vital verified=FALSE) NOT returned.
      - غیر-lapsed (F) از مخرج خارج.
    """
    tid = seed_lapsed["tenant_id"]
    _guc(tid)
    try:
        lr = lapsed_return(tenant_id=tid)
    finally:
        _guc_reset()

    assert lr["denominator"] == seed_lapsed["expected_denominator"], (
        f"مخرج باید {seed_lapsed['expected_denominator']} باشد؛ {lr['denominator']} "
        f"(غیر-lapsed باید خارج باشد؛ همهٔ lapsedها داخل)"
    )
    assert lr["returned"] == seed_lapsed["expected_returned"], (
        f"صورت باید {seed_lapsed['expected_returned']} باشد؛ {lr['returned']} "
        f"(فقط Appointment done؛ نه SMS/closed-window/unverified)"
    )
    assert lr["return_rate"] is not None, "denominator ≥ ۳۰ → نرخ باید عددی باشد"
    expected_pct = round(
        seed_lapsed["expected_returned"] * 100.0 / seed_lapsed["expected_denominator"], 1
    )
    assert lr["return_rate"] == expected_pct, (
        f"return_rate باید {expected_pct} باشد؛ {lr['return_rate']}"
    )


# ===========================================================================
# ۳. control-trend: ≥۳۰ assessable در یک باکت → pct واقعی + verified-gate
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_control_trend_real_pct_and_verified_gate(seed_control_trend):
    """
    باکتِ ماهِ جاریِ سریِ diabetes (و all): assessable=40، controlled=25 → pct=62.5.
    قرائتِ verified=FALSE نباید assessable شود (وگرنه assessable=41).
    """
    tid = seed_control_trend["tenant_id"]
    _guc(tid)
    try:
        ct = control_trend(tenant_id=tid)
    finally:
        _guc_reset()

    # آخرین باکت = ماهِ جاری (buckets قدیمی→جدید)
    last_ym = ct["buckets"][-1]["ym"]
    dm_current = next(
        b for b in ct["buckets"]
        if b["ym"] == last_ym and b["condition"] == "diabetes"
    )
    assert dm_current["assessable_n"] == seed_control_trend["expected_assessable"], (
        f"assessable باید {seed_control_trend['expected_assessable']} باشد "
        f"(verified=FALSE خارج)؛ {dm_current['assessable_n']}"
    )
    assert dm_current["controlled_n"] == seed_control_trend["expected_controlled"]
    assert dm_current["pct_controlled"] == 62.5, (
        f"pct باید 62.5 باشد؛ {dm_current['pct_controlled']}"
    )

    # سریِ 'all' باید همان عدد را بدهد (همه دیابتی‌اند و hba1c برای all کنترلی است)
    all_current = next(
        b for b in ct["buckets"]
        if b["ym"] == last_ym and b["condition"] == "all"
    )
    assert all_current["assessable_n"] == seed_control_trend["expected_assessable"]
    assert all_current["pct_controlled"] == 62.5


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_control_trend_has_12_buckets_per_series(seed_control_trend):
    """۱۲ باکت × (۵ condition + all) = ۷۲ ردیف؛ همه فیلدها حاضر."""
    tid = seed_control_trend["tenant_id"]
    _guc(tid)
    try:
        ct = control_trend(tenant_id=tid)
    finally:
        _guc_reset()
    # ۶ سری × ۱۲ ماه
    assert len(ct["buckets"]) == 12 * 6, f"باید ۷۲ باکت باشد؛ {len(ct['buckets'])}"
    yms = sorted({b["ym"] for b in ct["buckets"]})
    assert len(yms) == 12
    conds = {b["condition"] for b in ct["buckets"]}
    assert conds == {"diabetes", "hypertension", "hyperlipidemia", "ckd", "thyroid", "all"}


# ===========================================================================
# ۴. GUC/cross-tenant: متریک‌ها دادهٔ tenantِ دیگر را نگیرند
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_cross_tenant_isolation(seed_lapsed, seed_control_trend):
    """
    GUC/RLS scoping:
      - tenant 9099 (هرگز seed نشده، خالی) → denominator=0، return_rate=null؛
        همهٔ باکت‌های control-trend pct=null. اثباتِ مخرجِ خالی → NULL نه خطا.
      - tenant 9021 (کوهورتِ control با رویدادهای جدید) نباید کوهورتِ lapsedِ
        ۹۰۲۰ را به‌عنوان denominator ببیند → denominator < min_n.
    """
    EMPTY = 9099
    _guc(EMPTY)
    try:
        lr_empty = lapsed_return(tenant_id=EMPTY)
        ct_empty = control_trend(tenant_id=EMPTY)
    finally:
        _guc_reset()
    assert lr_empty["denominator"] == 0, (
        f"tenant خالی نباید کوهورتِ tenantِ دیگر را ببیند؛ {lr_empty['denominator']}"
    )
    assert lr_empty["return_rate"] is None
    assert all(b["pct_controlled"] is None for b in ct_empty["buckets"])
    assert all(b["assessable_n"] == 0 for b in ct_empty["buckets"])

    # tenant 9021 کوهورتِ lapsed ندارد (رویدادهایش جدیدند) → denominator کوچک
    _guc(9021)
    try:
        lr_ct = lapsed_return(tenant_id=9021)
    finally:
        _guc_reset()
    assert lr_ct["denominator"] < N_SUFFICIENT, (
        f"tenant 9021 نباید lapsedِ ۹۰۲۰ را ببیند؛ {lr_ct['denominator']}"
    )


# ===========================================================================
# ۵. API-shape + auth: همه فیلدها سریال، non-manager→403، بدونِ JWT→401
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_api_shape_lapsed_return(seed_lapsed, outcome_users):
    token = _get_token("mgr_9020", outcome_users["password"])
    resp = _client().get(
        "/manager/lapsed-return",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    for f in ("denominator", "returned", "return_rate", "lapse_window_days",
              "return_window_days", "min_n", "framing"):
        assert f in data, f"فیلد گم شده: {f}"
    assert data["denominator"] == seed_lapsed["expected_denominator"]
    assert data["returned"] == seed_lapsed["expected_returned"]
    assert data["return_rate"] is not None
    # framing غیرعلّی
    assert data["framing"] and "علّی" in data["framing"]
    assert "immortal-time" in data["framing"] or "survivorship" in data["framing"]


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_api_shape_control_trend(seed_control_trend, outcome_users):
    token = _get_token("mgr_9021", outcome_users["password"])
    resp = _client().get(
        "/manager/control-trend",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    for f in ("buckets", "min_n", "framing"):
        assert f in data, f"فیلد سطحِ بالا گم شده: {f}"
    assert data["framing"] and "secular trend" in data["framing"]
    assert len(data["buckets"]) == 12 * 6
    b0 = data["buckets"][0]
    for f in ("ym", "condition", "assessable_n", "controlled_n", "pct_controlled"):
        assert f in b0, f"فیلدِ باکت گم شده: {f}"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_api_non_manager_403(seed_lapsed, seed_control_trend, outcome_users):
    """staff → 403 برای هر دو."""
    token = _get_token("stf_9020", outcome_users["password"])
    for ep in ("/manager/lapsed-return",):
        resp = _client().get(ep, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403, f"{ep}: {resp.text}"
        assert resp.json()["code"] == "forbidden"
    token2 = _get_token("stf_9021", outcome_users["password"])
    resp = _client().get(
        "/manager/control-trend", headers={"Authorization": f"Bearer {token2}"}
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "forbidden"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_api_requires_jwt(seed_data):
    """بدونِ JWT → 401 برای هر دو."""
    assert _client().get("/manager/lapsed-return").status_code == 401
    assert _client().get("/manager/control-trend").status_code == 401
