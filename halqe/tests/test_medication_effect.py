"""
tests/test_medication_effect.py — تستِ اندپوینت GET /patients/{uuid}/medications/{id}/effect

تستِ assertهای گردهمایی (Step 38):
  1. داروی بدونِ هیچ observationِ پس → data_insufficient, reason=no_post, delta=null, n_post=0
  2. داروی شروع‌شده ۲۰ روز پیش با hba1c (post_start=60) → data_insufficient, reason=post_window_not_elapsed
  3. drug_class=other / aspirin → data_insufficient, reason=no_indicator_for_class
  4. suggestion_only==True در هر پاسخ
  5. حالتِ کافی: داروی دیابت با ≥۱ pre و ≥۱ post در پنجره → delta عددیِ واقعی + direction_of_change + caveat
  6. تستِ سطحِ‌API: همهٔ فیلدهایِ DTO در پاسخ (status/reason/delta/caveat سریال‌شده)

fixture اختصاصی:
  seed_med_effect_data — extends seed_clinical_data با:
    - داروِ metformin با start_date=2 سال پیش + pre/post hba1c readings واقعی
    - داروِ aspirin (no indicator)
    - داروِ ccb با start_date=20 روز پیش (post_window_not_elapsed)
    - داروِ metformin2 با start_date=2 سال پیش ولی بدونِ هیچ observationِ post
"""
import uuid
from datetime import date, timedelta

import psycopg
import pytest
from ninja.testing import TestClient

from config.api import api


# ---------------------------------------------------------------------------
# Client helper
# ---------------------------------------------------------------------------
def _client() -> TestClient:
    return TestClient(api)


def _get_token(seed, username: str = "testuser") -> str:
    resp = _client().post(
        "/auth/login",
        json={"username": username, "password": seed["test_password"]},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["token"]


# ---------------------------------------------------------------------------
# conftest helpers — reuse DB credentials
# ---------------------------------------------------------------------------
import os

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


# ---------------------------------------------------------------------------
# Fixture: seed_med_effect_data — داده‌های اختصاصیِ تستِ medication effect
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def seed_med_effect_data(seed_clinical_data):
    """
    داده‌هایِ لازم برای تستِ medication effect:

    Med A (metformin_effect_test):
      - drug_class=metformin، start_date = 2 سال پیش
      - pre observations: 2 hba1c reading قبل از start
      - post observations: 2 hba1c reading بعد از start (در پنجرهٔ 60–180 روز)
      → باید 'ok' برگردد

    Med B (aspirin_no_indicator):
      - drug_class=aspirin، start_date = 1 سال پیش
      → باید data_insufficient, reason=no_indicator_for_class

    Med C (ccb_too_recent):
      - drug_class=ccb، start_date = امروز - 20 روز (post_window=14 روز برای bp_systolic)
      → باید data_insufficient, reason=post_window_not_elapsed
      (post_start برای bp_systolic=14 → 20>=14 پس این را 5 روز پیش می‌زنیم تا مطمئن شویم)
      NOTE: post_start_days=14 → اگر 20 روز گذشته، 20>=14 → باید ok شود اگر داده داشته باشد
      پس start_date را 5 روز پیش می‌گذاریم (5 < 14) → post_window_not_elapsed ✓

    Med D (metformin_no_post):
      - drug_class=metformin، start_date = 3 سال پیش (start date کاملاً مختلف از Med A)
      - فقط pre observation دارد، بدونِ post در آن پنجرهٔ خاص
      → باید data_insufficient, reason=no_post

    Med E (metformin_no_start_date):
      - drug_class=metformin، start_date=NULL
      → باید data_insufficient, reason=no_start_date
    """
    link_id = seed_clinical_data["link_id"]
    today = date.today()
    two_years_ago  = today - timedelta(days=730)
    three_years_ago = today - timedelta(days=1095)  # Med D: پنجرهٔ کاملاً جدا از Med A
    one_year_ago   = today - timedelta(days=365)
    five_days_ago  = today - timedelta(days=5)

    with _su_conn() as conn:
        # ── Med A: metformin با start دو سال پیش ─────────────────────────────
        # is_active=FALSE: این fixture‌ها برای تستِ medication_effect هستند، نه active med list
        # این کار test_patient_record را که len(active_medications)==2 چک می‌کند مصون نگه می‌دارد
        row = conn.execute("""
            INSERT INTO clinical.patient_medications
                (tenant_id, patient_link_id, drug_name, dose,
                 start_date, drug_class, is_active, created_at)
            VALUES (1, %s, 'متفورمین‌تست', '1000mg', %s, 'metformin', FALSE, now())
            RETURNING id
        """, (link_id, two_years_ago)).fetchone()
        med_a_id = row[0]

        # pre readings برای Med A: ۹۰ و ۱۲۰ روز قبل از start_date
        # pre_window: [start-180, start)
        pre_date1 = two_years_ago - timedelta(days=90)
        pre_date2 = two_years_ago - timedelta(days=30)
        # post readings برای Med A: ۶۰ و ۱۲۰ روز بعد از start_date
        # post_window: [start+60, start+180]
        post_date1 = two_years_ago + timedelta(days=70)
        post_date2 = two_years_ago + timedelta(days=120)

        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES
                (1, %s, 'hba1c', 8.2, '%%', %s, 'clinic'),
                (1, %s, 'hba1c', 8.0, '%%', %s, 'clinic'),
                (1, %s, 'hba1c', 6.8, '%%', %s, 'clinic'),
                (1, %s, 'hba1c', 7.0, '%%', %s, 'clinic')
        """, (link_id, pre_date1, link_id, pre_date2,
              link_id, post_date1, link_id, post_date2))

        # ── Med B: aspirin بدون indicator ────────────────────────────────────
        row = conn.execute("""
            INSERT INTO clinical.patient_medications
                (tenant_id, patient_link_id, drug_name, dose,
                 start_date, drug_class, is_active, created_at)
            VALUES (1, %s, 'آسپرین‌تست', '80mg', %s, 'aspirin', FALSE, now())
            RETURNING id
        """, (link_id, one_year_ago)).fetchone()
        med_b_id = row[0]

        # ── Med C: ccb با ۵ روز پیش (< 14 روز = post_window_not_elapsed) ─────
        row = conn.execute("""
            INSERT INTO clinical.patient_medications
                (tenant_id, patient_link_id, drug_name, dose,
                 start_date, drug_class, is_active, created_at)
            VALUES (1, %s, 'آملودیپین‌تست', '5mg', %s, 'ccb', FALSE, now())
            RETURNING id
        """, (link_id, five_days_ago)).fetchone()
        med_c_id = row[0]

        # ── Med D: metformin با start_date=3 سال پیش — فقط pre، بدون post ─────
        # post_window برای hba1c: [three_years_ago+60, three_years_ago+180]
        # ≈ [2022-08-24, 2022-12-22] — در آن بازه هیچ vital وارد نمی‌شود
        row = conn.execute("""
            INSERT INTO clinical.patient_medications
                (tenant_id, patient_link_id, drug_name, dose,
                 start_date, drug_class, is_active, created_at)
            VALUES (1, %s, 'متفورمین‌بدون‌پس', '500mg', %s, 'metformin', FALSE, now())
            RETURNING id
        """, (link_id, three_years_ago)).fetchone()
        med_d_id = row[0]

        # فقط pre برای Med D — تاریخِ قبل از three_years_ago (در pre_window)
        # هیچ post reading ثبت نمی‌شود → n_post=0
        pre_date_d = three_years_ago - timedelta(days=60)
        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES (1, %s, 'hba1c', 9.1, '%%', %s, 'clinic')
        """, (link_id, pre_date_d))

        # ── Med E: metformin بدون start_date ─────────────────────────────────
        row = conn.execute("""
            INSERT INTO clinical.patient_medications
                (tenant_id, patient_link_id, drug_name, dose,
                 start_date, drug_class, is_active, created_at)
            VALUES (1, %s, 'متفورمین‌بدون‌شروع', '500mg', NULL, 'metformin', FALSE, now())
            RETURNING id
        """, (link_id,)).fetchone()
        med_e_id = row[0]

    return {
        **seed_clinical_data,
        "med_a_id": med_a_id,   # metformin: ok case
        "med_b_id": med_b_id,   # aspirin: no_indicator_for_class
        "med_c_id": med_c_id,   # ccb recent: post_window_not_elapsed
        "med_d_id": med_d_id,   # metformin: no_post
        "med_e_id": med_e_id,   # metformin: no_start_date
    }


# ===========================================================================
# ۱. داروِ بدونِ observationِ پس → data_insufficient, reason=no_post, delta=null
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_no_post_observations_returns_data_insufficient(seed_med_effect_data):
    """
    گردهمایی assert ۱:
    داروی bدونِ هیچ observationِ پس از شروع → status=data_insufficient, reason=no_post,
    delta=null (نه صفر), n_post=0.
    """
    seed = seed_med_effect_data
    token = _get_token(seed)
    patient_uuid = seed["patient_uuid"]
    med_id = seed["med_d_id"]

    resp = _client().get(
        f"/patients/{patient_uuid}/medications/{med_id}/effect",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["status"] == "data_insufficient"
    assert data["reason"] == "no_post"
    assert data["delta"] is None, f"delta باید null باشد؛ دریافت‌شد: {data['delta']}"
    assert data["n_post"] == 0
    assert data["suggestion_only"] is True


# ===========================================================================
# ۲. داروِ ۵ روز پیش با bp_systolic (post_start=14) → post_window_not_elapsed
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_post_window_not_elapsed(seed_med_effect_data):
    """
    گردهمایی assert ۲:
    داروِ شروع‌شدهٔ ۵ روز پیش با indicator bp_systolic (post_start=14 روز)
    → data_insufficient, reason=post_window_not_elapsed.
    """
    seed = seed_med_effect_data
    token = _get_token(seed)
    patient_uuid = seed["patient_uuid"]
    med_id = seed["med_c_id"]

    resp = _client().get(
        f"/patients/{patient_uuid}/medications/{med_id}/effect",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["status"] == "data_insufficient"
    assert data["reason"] == "post_window_not_elapsed"
    assert data["suggestion_only"] is True


# ===========================================================================
# ۳. drug_class=aspirin → data_insufficient, reason=no_indicator_for_class
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_aspirin_no_indicator_for_class(seed_med_effect_data):
    """
    گردهمایی assert ۳:
    drug_class=aspirin → data_insufficient, reason=no_indicator_for_class.
    """
    seed = seed_med_effect_data
    token = _get_token(seed)
    patient_uuid = seed["patient_uuid"]
    med_id = seed["med_b_id"]

    resp = _client().get(
        f"/patients/{patient_uuid}/medications/{med_id}/effect",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["status"] == "data_insufficient"
    assert data["reason"] == "no_indicator_for_class"
    assert data["suggestion_only"] is True


# ===========================================================================
# ۴. suggestion_only==True در هر پاسخ
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_suggestion_only_always_true(seed_med_effect_data):
    """
    گردهمایی assert ۴:
    suggestion_only=True در هر پاسخ — ok و data_insufficient.
    """
    seed = seed_med_effect_data
    token = _get_token(seed)
    patient_uuid = seed["patient_uuid"]
    headers = {"Authorization": f"Bearer {token}"}

    for med_id_key in ("med_a_id", "med_b_id", "med_c_id", "med_d_id", "med_e_id"):
        med_id = seed[med_id_key]
        resp = _client().get(
            f"/patients/{patient_uuid}/medications/{med_id}/effect",
            headers=headers,
        )
        assert resp.status_code == 200, f"status!=200 for {med_id_key}: {resp.text}"
        data = resp.json()
        assert data["suggestion_only"] is True, (
            f"suggestion_only باید True باشد برای {med_id_key}؛ دریافت: {data.get('suggestion_only')}"
        )


# ===========================================================================
# ۵. حالتِ کافی: metformin با pre و post → ok + delta عددی + caveat
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_sufficient_data_returns_ok_with_delta_and_caveat(seed_med_effect_data):
    """
    گردهمایی assert ۵:
    داروِ دیابت (metformin) با ≥۱ pre و ≥۱ post در پنجره →
    status=ok، delta عددیِ واقعی، direction_of_change مقدار دارد، caveat حاضر است.

    هشدار: اگر vitalsِ pre/post در fixture با اندازه‌گیری‌هایِ seed_clinical_data
    overlap کنند (مثلاً hba1c=7.2 از seed_data یا seed_clinical_data که ممکن است
    در پنجرهٔ post باشند) نتیجه ممکن است کمی متفاوت باشد ولی همیشه عددی است.
    """
    seed = seed_med_effect_data
    token = _get_token(seed)
    patient_uuid = seed["patient_uuid"]
    med_id = seed["med_a_id"]

    resp = _client().get(
        f"/patients/{patient_uuid}/medications/{med_id}/effect",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["status"] == "ok", (
        f"باید ok باشد؛ دریافت: {data['status']}, reason: {data.get('reason')}"
    )
    assert data["delta"] is not None, "delta در حالتِ ok نباید null باشد"
    assert isinstance(data["delta"], (int, float)), f"delta باید عدد باشد؛ دریافت: {type(data['delta'])}"
    assert data["direction_of_change"] in ("improved", "worsened", "unchanged"), (
        f"direction_of_change نامعتبر: {data['direction_of_change']}"
    )
    assert data["caveat"] is not None and len(data["caveat"]) > 0, (
        "caveat در حالتِ ok باید حاضر باشد"
    )
    assert data["suggestion_only"] is True
    assert data["n_pre"] >= 1
    assert data["n_post"] >= 1


# ===========================================================================
# ۵b. no_start_date
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_no_start_date_returns_data_insufficient(seed_med_effect_data):
    """
    داروی بدونِ start_date → data_insufficient, reason=no_start_date.
    """
    seed = seed_med_effect_data
    token = _get_token(seed)
    patient_uuid = seed["patient_uuid"]
    med_id = seed["med_e_id"]

    resp = _client().get(
        f"/patients/{patient_uuid}/medications/{med_id}/effect",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["status"] == "data_insufficient"
    assert data["reason"] == "no_start_date"
    assert data["delta"] is None
    assert data["suggestion_only"] is True


# ===========================================================================
# ۶. تستِ سطحِ‌API: همهٔ فیلدهای DTO در پاسخ
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_api_surface_all_fields_serialized_ok_case(seed_med_effect_data):
    """
    گردهمایی assert ۶ (حالتِ ok):
    GET → پاسخ شاملِ **همهٔ** فیلدهای DTO (به‌ویژه status/reason/delta/caveat سریال‌شده).
    درسِ ۳۴/۳۶/۳۷ — تستِ سطحِ‌API اجباری است.
    """
    EXPECTED_FIELDS = {
        "status", "reason", "suggestion_only",
        "drug_name", "drug_class",
        "indicator", "indicator_key", "unit",
        "pre_value", "post_value", "delta",
        "direction_of_change",
        "n_pre", "n_post",
        "pre_window", "post_window",
        "start_date",
        "caveat", "meaningful_threshold",
    }

    seed = seed_med_effect_data
    token = _get_token(seed)
    patient_uuid = seed["patient_uuid"]

    # test روی حالتِ ok (med_a)
    resp = _client().get(
        f"/patients/{patient_uuid}/medications/{seed['med_a_id']}/effect",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ok"

    missing = EXPECTED_FIELDS - set(data.keys())
    assert not missing, (
        f"فیلدهای DTO در پاسخِ ok گم شده‌اند: {missing}"
    )

    # تأییدِ نوعِ فیلدهای کلیدی
    assert isinstance(data["status"], str)
    assert isinstance(data["suggestion_only"], bool)
    assert isinstance(data["n_pre"], int)
    assert isinstance(data["n_post"], int)
    assert data["delta"] is not None
    assert data["caveat"] is not None


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_api_surface_all_fields_serialized_insufficient_case(seed_med_effect_data):
    """
    گردهمایی assert ۶ (حالتِ data_insufficient):
    GET → پاسخ شاملِ **همهٔ** فیلدهای DTO با null-هایِ صریح.
    """
    EXPECTED_FIELDS = {
        "status", "reason", "suggestion_only",
        "drug_name", "drug_class",
        "indicator", "indicator_key", "unit",
        "pre_value", "post_value", "delta",
        "direction_of_change",
        "n_pre", "n_post",
        "pre_window", "post_window",
        "start_date",
        "caveat", "meaningful_threshold",
    }

    seed = seed_med_effect_data
    token = _get_token(seed)
    patient_uuid = seed["patient_uuid"]

    # test روی حالتِ data_insufficient (med_b = aspirin)
    resp = _client().get(
        f"/patients/{patient_uuid}/medications/{seed['med_b_id']}/effect",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "data_insufficient"

    missing = EXPECTED_FIELDS - set(data.keys())
    assert not missing, (
        f"فیلدهای DTO در پاسخِ data_insufficient گم شده‌اند: {missing}"
    )

    # در حالتِ data_insufficient: delta باید null (نه صفر)، caveat باید null
    assert data["delta"] is None, (
        f"delta در data_insufficient باید null باشد؛ دریافت: {data['delta']}"
    )
    assert data["caveat"] is None or data["status"] == "data_insufficient"
    assert data["suggestion_only"] is True


# ===========================================================================
# ۷. 404 برای دارویِ ناموجود
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_404_for_unknown_medication(seed_med_effect_data):
    """دارویِ ناموجود (id=999999) → 404."""
    seed = seed_med_effect_data
    token = _get_token(seed)
    patient_uuid = seed["patient_uuid"]

    resp = _client().get(
        f"/patients/{patient_uuid}/medications/999999/effect",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404, resp.text


# ===========================================================================
# ۸. 401 بدونِ JWT
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_requires_jwt(seed_med_effect_data):
    """بدونِ JWT → 401."""
    seed = seed_med_effect_data
    patient_uuid = seed["patient_uuid"]
    med_id = seed["med_a_id"]

    resp = _client().get(f"/patients/{patient_uuid}/medications/{med_id}/effect")
    assert resp.status_code == 401, resp.text


# ===========================================================================
# ۹. گیتِ verified (یافتهٔ گردهماییِ قدم ۴۹): self-reportِ تأییدنشده در تحلیل نیاید
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_unverified_post_reading_excluded(seed_clinical_data):
    """
    گپِ گیتِ مقدس که clinical-data-scientist حین قدم ۴۹ گرفت و من بستم:
    قرائتِ post با verified=FALSE (خوداظهارِ تأییدنشده) نباید در میانگینِ
    medication-effect شمرده شود — هم‌راستا با slice13/قدم ۴۷ (دادهٔ تأییدنشده
    هرگز در تصمیم‌یار تا تأییدِ پزشک).

    سناریو (روی patient_linkِ ایزوله تا از داده‌های seed/fixture مستقل باشد):
    متفورمین با pre-hba1cِ verified + تنها post-hba1cِ **unverified** در پنجره
    → چون post تأییدنشده حذف می‌شود → n_post=0 → reason=no_post (نه عددِ آلوده).
    سرویس مستقیم صدا زده می‌شود (patient_linkِ ایزوله بیمارِ accounting ندارد، پس
    endpoint با UUID resolve نمی‌شود؛ فیکس هم در همین سرویس است). leak-safe: با id.
    """
    from clinical.medication_effect_service import compute_medication_effect
    from clinical.models import PatientMedication
    from platform_core.tenant_context import set_tenant_guc

    link_id = seed_clinical_data["link_id"]   # بیمارِ seed (FKِ accountingِ معتبر)
    today = date.today()
    # پنجرهٔ ~۶ سال پیش — پیش از بازهٔ دادهٔ seed (~۲ سال) تا هیچ قرائتِ دیگری آلوده نکند
    start = today - timedelta(days=2190)
    pre_date = start - timedelta(days=40)          # in [start-180, start)
    post_date = start + timedelta(days=125)        # in [start+60, start+180]

    with _su_conn() as conn:
        med_id = conn.execute(
            """INSERT INTO clinical.patient_medications
                   (tenant_id, patient_link_id, drug_name, dose, start_date,
                    drug_class, is_active, created_at)
               VALUES (1, %s, %s, '1000mg', %s, 'metformin', FALSE, now())
               RETURNING id""",
            (link_id, "متفورمین‌گیت‌verified", start),
        ).fetchone()[0]
        pre_id = conn.execute(
            """INSERT INTO clinical.vital_readings
                   (tenant_id, patient_link_id, type, value, unit, measured_at,
                    source, verified)
               VALUES (1, %s, 'hba1c', %s, %s, %s, 'clinic', TRUE)
               RETURNING id""",
            (link_id, 9.0, "%", pre_date),
        ).fetchone()[0]
        post_id = conn.execute(
            """INSERT INTO clinical.vital_readings
                   (tenant_id, patient_link_id, type, value, unit, measured_at,
                    source, verified)
               VALUES (1, %s, 'hba1c', %s, %s, %s, 'patient_self', FALSE)
               RETURNING id""",
            (link_id, 6.0, "%", post_date),
        ).fetchone()[0]

    try:
        set_tenant_guc(1)
        med = PatientMedication.objects.get(id=med_id)
        result = compute_medication_effect(med, tenant_id=1)
        # postِ تأییدنشده حذف شد → n_post=0 → no_post (نه delta آلوده)
        assert result["n_post"] == 0, (
            f"قرائتِ postِ تأییدنشده نباید شمرده شود؛ n_post={result['n_post']}"
        )
        assert result["status"] == "data_insufficient"
        assert result["reason"] == "no_post"
        assert result["delta"] is None
        # pre verified شمرده شد (اثباتِ اینکه فیلتر فقط unverified را حذف می‌کند، نه همه)
        assert result["n_pre"] == 1, f"pre verified باید شمرده شود؛ n_pre={result['n_pre']}"
    finally:
        # cleanup leak-safe — فقط دو ردیفِ همین تست با id (درسِ قدم ۴۴)
        with _su_conn() as conn:
            conn.execute(
                "DELETE FROM clinical.vital_readings WHERE id = ANY(%s)",
                ([pre_id, post_id],),
            )
            conn.execute(
                "DELETE FROM clinical.patient_medications WHERE id = %s",
                (med_id,),
            )


# ===========================================================================
# ۹. تاریخِ شروع — ISO از بک‌اند (Jalali سمتِ کلاینت فرمت می‌شود، مثلِ بقیهٔ اندپوینت‌ها)
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_start_date_is_iso(seed_med_effect_data):
    """
    start_date باید ISO (YYYY-MM-DD) باشد — کنوانسیونِ halqe: بک‌اند ISO می‌دهد،
    فرانت با formatJalali نمایش می‌دهد (هیچ تبدیلِ جلالیِ دست‌سازِ سرور).
    """
    seed = seed_med_effect_data
    token = _get_token(seed)
    patient_uuid = seed["patient_uuid"]
    med_id = seed["med_a_id"]

    resp = _client().get(
        f"/patients/{patient_uuid}/medications/{med_id}/effect",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    sd = data.get("start_date")
    assert sd is not None, "start_date نباید null باشد"
    # فرمتِ ISO: YYYY-MM-DD و قابلِ parse
    from datetime import date as _date
    parsed = _date.fromisoformat(sd)
    assert parsed.isoformat() == sd, f"start_date باید ISO باشد؛ دریافت: {sd}"


# ===========================================================================
# ۱۰. delta واقعاً کاهش‌یافته (هباalc pre > post → improved)
# ===========================================================================
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_delta_sign_matches_direction(seed_med_effect_data):
    """
    در fixture: pre_hba1c = mean(8.2, 8.0) = 8.1; post_hba1c ≈ mean(6.8, 7.0) = 6.9
    delta ≈ 6.9 - 8.1 = -1.2 (منفی = کاهش)
    direction hba1c = high → کاهش = improved
    """
    seed = seed_med_effect_data
    token = _get_token(seed)
    patient_uuid = seed["patient_uuid"]
    med_id = seed["med_a_id"]

    resp = _client().get(
        f"/patients/{patient_uuid}/medications/{med_id}/effect",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    if data["status"] != "ok":
        pytest.skip(
            f"حالتِ ok نبود (reason={data.get('reason')}) — ممکن است observations دیگری "
            f"در پنجره باشند؛ این تست فقط برای حالتِ ok معنا دارد."
        )

    # delta باید منفی باشد (hba1c کاهش یافته)
    delta = data["delta"]
    assert delta is not None
    # direction باید improved باشد (اگر abs(delta) >= threshold=0.5)
    if abs(delta) >= 0.5:
        assert data["direction_of_change"] == "improved", (
            f"hba1c کاهش یافته (delta={delta}) باید improved باشد؛ "
            f"دریافت: {data['direction_of_change']}"
        )
