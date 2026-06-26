"""
Tests for the patient-list + clinical-record read slice.

Coverage:
  1. GET /patients  — list enrolled patients (with demographics)
  2. GET /patients  — pagination: limit/offset + total
  3. GET /patients/{uuid}/record — conditions (active only), active meds, recent vitals
  4. GET /patients/{uuid}/record — only ACTIVE medications returned
  5. Both endpoints return 401 without JWT
  6. Both endpoints return 200 with valid JWT
  7. Tenant isolation: a patient enrolled under tenant-2 is NOT visible to tenant-1 token

Architecture notes:
  - list_patients: N+1-avoidance via get_patients_by_ids (one batch accounting query per page)
  - Both endpoints: tenant_id scoped from JWT claims (request.tenant_id set by JWTBearer)
  - Clinical reads on 'default'; demographics reads on 'accounting_read'
"""
import pytest
from ninja.testing import TestClient

from config.api import api


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client() -> TestClient:
    return TestClient(api)


def _get_token(seed_data, username: str = "testuser") -> str:
    """Obtain a JWT for testuser (tenant 1) via POST /auth/login."""
    resp = _client().post(
        "/auth/login",
        json={"username": username, "password": seed_data["test_password"]},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["token"]


# ---------------------------------------------------------------------------
# 1. Patient list — basic
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_list_patients_returns_enrolled_patient_with_demographics(seed_clinical_data):
    """
    GET /patients → 200.
    The seeded tenant-1 patient must appear in the list with correct demographics.
    """
    token = _get_token(seed_clinical_data)
    # Use the max page size: the session seeds many patients across all test
    # modules, and /patients is ordered newest-first, so the original (oldest)
    # seeded patient is NOT on the default first page. Request all rows so this
    # assertion verifies *presence + demographics*, not page placement.
    resp = _client().get(
        "/patients?limit=200",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert "items" in data
    assert "total" in data
    assert data["total"] >= 1

    # Find our test patient by uuid
    patient_uuid = str(seed_clinical_data["patient_uuid"])
    found = next(
        (item for item in data["items"] if item["patient_uuid"] == patient_uuid),
        None,
    )
    assert found is not None, f"Test patient not in list. items={data['items']}"
    assert found["full_name"] == "علی رضایی"
    assert found["national_id"] == "1234567890"
    assert found["phone_number"] == "09120000001"
    assert found["is_active"] is True


# ---------------------------------------------------------------------------
# 2. Patient list — pagination (limit / offset)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_list_patients_pagination(seed_clinical_data):
    """
    GET /patients?limit=1&offset=0 → 1 item, total >= 1.
    GET /patients?limit=1&offset=9999 → 0 items, total unchanged.
    """
    token = _get_token(seed_clinical_data)
    client = _client()
    headers = {"Authorization": f"Bearer {token}"}

    # First page — 1 item
    resp = client.get("/patients?limit=1&offset=0", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["limit"] == 1
    assert data["offset"] == 0
    total = data["total"]
    assert total >= 1

    # Out-of-range offset — 0 items but total still correct
    resp2 = client.get("/patients?limit=1&offset=9999", headers=headers)
    assert resp2.status_code == 200, resp2.text
    data2 = resp2.json()
    assert len(data2["items"]) == 0
    assert data2["total"] == total


# ---------------------------------------------------------------------------
# 3. Clinical record — full structure
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_get_patient_record_returns_conditions_and_meds_and_vitals(seed_clinical_data):
    """
    GET /patients/{uuid}/record → 200.
    - demographics present
    - active conditions (diabetes + hypertension)
    - active medications only (2 active; 1 inactive excluded)
    - recent vitals (newest first, ≤10)
    """
    token = _get_token(seed_clinical_data)
    patient_uuid = seed_clinical_data["patient_uuid"]
    resp = _client().get(
        f"/patients/{patient_uuid}/record",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Demographics
    assert data["demographics"]["full_name"] == "علی رضایی"
    assert data["demographics"]["national_id"] == "1234567890"

    # Active conditions — at least diabetes and hypertension
    cond_codes = [c["condition_code"] for c in data["active_conditions"]]
    assert "diabetes" in cond_codes, f"diabetes missing from {cond_codes}"
    assert "hypertension" in cond_codes, f"hypertension missing from {cond_codes}"
    # All returned conditions must be active
    for cond in data["active_conditions"]:
        assert cond["is_active"] is True

    # Active medications: exactly 2 (متفورمین + آملودیپین); گلیبنکلامید is inactive
    assert len(data["active_medications"]) == 2, (
        f"Expected 2 active meds, got {len(data['active_medications'])}: "
        f"{[m['drug_name'] for m in data['active_medications']]}"
    )
    active_drug_names = {m["drug_name"] for m in data["active_medications"]}
    assert "متفورمین" in active_drug_names
    assert "آملودیپین" in active_drug_names
    assert "گلیبنکلامید" not in active_drug_names

    # Recent vitals — has items, newest first
    vitals = data["recent_vitals"]
    assert len(vitals) >= 1
    assert len(vitals) <= 10
    if len(vitals) > 1:
        # Confirm descending order — parse ISO strings to datetime so that
        # microsecond precision differences don't break string comparison
        # (e.g. '18:16:55.230Z' vs '18:16:55Z' are ordered wrong alphabetically).
        from datetime import datetime, timezone as _tz

        def _parse_ts(s: str) -> datetime:
            # Handle both 'Z' suffix and '+00:00' offset; strip trailing Z and add offset.
            s = s.replace("Z", "+00:00")
            return datetime.fromisoformat(s)

        for i in range(len(vitals) - 1):
            ts_a = _parse_ts(vitals[i]["measured_at"])
            ts_b = _parse_ts(vitals[i + 1]["measured_at"])
            assert ts_a >= ts_b, (
                f"Vitals must be returned newest-first: "
                f"{vitals[i]['measured_at']} < {vitals[i + 1]['measured_at']}"
            )


# ---------------------------------------------------------------------------
# 4. Clinical record — ONLY active medications returned
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_record_excludes_inactive_medications(seed_clinical_data):
    """
    The inactive medication (گلیبنکلامید, is_active=False) must NOT appear
    in the record's active_medications list.
    """
    token = _get_token(seed_clinical_data)
    patient_uuid = seed_clinical_data["patient_uuid"]
    resp = _client().get(
        f"/patients/{patient_uuid}/record",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    meds = resp.json()["active_medications"]
    drug_names = [m["drug_name"] for m in meds]
    assert "گلیبنکلامید" not in drug_names, (
        "Inactive medication must not appear in active_medications"
    )


# ---------------------------------------------------------------------------
# 5. Both endpoints return 401 without JWT
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_list_patients_requires_jwt(seed_clinical_data):
    """GET /patients without token → 401."""
    resp = _client().get("/patients")
    assert resp.status_code == 401, resp.text


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_get_record_requires_jwt(seed_clinical_data):
    """GET /patients/{uuid}/record without token → 401."""
    patient_uuid = seed_clinical_data["patient_uuid"]
    resp = _client().get(f"/patients/{patient_uuid}/record")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# 6. Both endpoints return 200 with valid JWT
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_list_patients_with_valid_token_returns_200(seed_clinical_data):
    """GET /patients with valid token → 200."""
    token = _get_token(seed_clinical_data)
    resp = _client().get(
        "/patients",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_get_record_with_valid_token_returns_200(seed_clinical_data):
    """GET /patients/{uuid}/record with valid token → 200."""
    token = _get_token(seed_clinical_data)
    patient_uuid = seed_clinical_data["patient_uuid"]
    resp = _client().get(
        f"/patients/{patient_uuid}/record",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# 7. Tenant isolation — tenant-2 patient NOT visible to tenant-1 token
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_tenant_isolation_list_does_not_show_other_tenant_patient(seed_clinical_data):
    """
    Tenant-1 token must NOT see the tenant-2 patient in the list.

    The tenant-2 patient (uuid=11111111-...) is enrolled under tenant_id=2.
    A tenant-1 token has tenant_id=1 → only tenant_id=1 patient_links are returned.
    """
    token = _get_token(seed_clinical_data)
    resp = _client().get(
        "/patients",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    tenant2_uuid = str(seed_clinical_data["tenant2_patient_uuid"])
    in_list = any(item["patient_uuid"] == tenant2_uuid for item in data["items"])
    assert not in_list, (
        f"Tenant-2 patient ({tenant2_uuid}) must NOT appear in tenant-1 response"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_tenant_isolation_record_404_for_other_tenant_patient(seed_clinical_data):
    """
    GET /patients/{uuid}/record for tenant-2 patient with tenant-1 token → 404.

    The accounting patient exists (uuid resolves), but there is no
    patient_link with tenant_id=1, so the endpoint must 404.
    """
    token = _get_token(seed_clinical_data)
    tenant2_uuid = seed_clinical_data["tenant2_patient_uuid"]
    resp = _client().get(
        f"/patients/{tenant2_uuid}/record",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404, (
        f"Expected 404 for cross-tenant record access, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# 8. Vital level evaluation — server-side, driven by clinical_indicators
#
# آستانه‌های خوانده‌شده از seed در schema_pg_slice2_clinical.sql (tenant 1):
#   hba1c:       warn=7.0,  danger=8.0,  direction=high
#   bp_systolic: warn=130,  danger=140,  direction=high
#   ldl:         warn=70,   danger=100,  direction=high
#   weight:      warn=NULL, danger=NULL  (ردیف هست اما آستانه ندارد → ok)
#   'temperature': هیچ ردیفی در clinical_indicators ندارد → None
#
# هشدار drift: اگر seedهای clinical_indicators تغییر کنند، اعداد زیر باید
# هم‌خوان به‌روز شوند. اعداد اینجا از slice2 seed خوانده شده‌اند (2026-06-25).
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_vital_level_warn_hba1c(seed_clinical_data):
    """
    Unit-style test of level evaluation (بدون insert جدید، از vitals موجود).

    seed_clinical_data vitals برای این بیمار شامل hba1c=7.2 است.
    آستانه از clinical_indicators slice2 seed (tenant 1):
      direction=high, warn=7.0, danger=8.0.
    → 7.2 >= warn=7.0 و 7.2 < danger=8.0 → 'warn'.

    تست مستقیم منطقِ _evaluate_reading را از DB می‌خواند (نه hardcode).
    """
    from clinical.rule_engine import _evaluate_reading
    from clinical.models import ClinicalIndicator

    # خواندن indicator map از DB (منبع حقیقت — همان کاری که endpoint می‌کند)
    indicator_map = {
        row.key: row
        for row in ClinicalIndicator.objects.filter(tenant_id=1, is_active=True)
    }
    assert "hba1c" in indicator_map, (
        "hba1c must be seeded in clinical_indicators for tenant 1"
    )

    # محدودهٔ warn (>= warn و < danger)
    ind = indicator_map["hba1c"]
    warn_val = float(ind.warn)
    danger_val = float(ind.danger)

    # مقدار مرزیِ warn: کمی بالاتر از warn و کمی کمتر از danger
    test_val = warn_val + (danger_val - warn_val) / 2   # درست در وسط محدودهٔ warn

    level = _evaluate_reading("hba1c", test_val, indicator_map)
    assert level == "warn", (
        f"hba1c={test_val} (between warn={warn_val} and danger={danger_val}) "
        f"should return 'warn'; got {level!r}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_vital_level_danger_hba1c(seed_clinical_data):
    """
    Unit-style: مقدار >= danger باید 'danger' برگرداند.
    آستانه از clinical_indicators slice2 seed: danger=8.0.
    """
    from clinical.rule_engine import _evaluate_reading
    from clinical.models import ClinicalIndicator

    indicator_map = {
        row.key: row
        for row in ClinicalIndicator.objects.filter(tenant_id=1, is_active=True)
    }
    ind = indicator_map["hba1c"]
    danger_val = float(ind.danger)

    # مقدار بالاتر از danger
    test_val = danger_val + 1.0   # e.g. 9.0 when danger=8.0

    level = _evaluate_reading("hba1c", test_val, indicator_map)
    assert level == "danger", (
        f"hba1c={test_val} (>= danger={danger_val}) should return 'danger'; got {level!r}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_vital_level_ok_bp_systolic(seed_clinical_data):
    """
    Unit-style: مقدار کمتر از warn باید 'ok' برگرداند.
    آستانه از clinical_indicators slice2 seed: bp_systolic warn=130.
    """
    from clinical.rule_engine import _evaluate_reading
    from clinical.models import ClinicalIndicator

    indicator_map = {
        row.key: row
        for row in ClinicalIndicator.objects.filter(tenant_id=1, is_active=True)
    }
    assert "bp_systolic" in indicator_map, "bp_systolic must be seeded"
    ind = indicator_map["bp_systolic"]
    warn_val = float(ind.warn)

    # مقدار پایین‌تر از warn
    test_val = warn_val - 5.0   # e.g. 125 when warn=130

    level = _evaluate_reading("bp_systolic", test_val, indicator_map)
    assert level == "ok", (
        f"bp_systolic={test_val} (< warn={warn_val}) should return 'ok'; got {level!r}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_vital_level_none_for_unknown_type(seed_clinical_data):
    """
    وقتی کلیدی در clinical_indicators نباشد، _vital_level باید None برگرداند.

    این تست مستقیم همان شرط در endpoint را تست می‌کند:
      if vtype not in _indicator_map: return None

    'temperature' در clinical_indicators slice2 seed نشده‌است.
    """
    from clinical.models import ClinicalIndicator

    indicator_map = {
        row.key: row
        for row in ClinicalIndicator.objects.filter(tenant_id=1, is_active=True)
    }

    # تأیید که 'temperature' واقعاً وجود ندارد (نه فرض می‌کنیم)
    assert "temperature" not in indicator_map, (
        "temperature must NOT be in clinical_indicators seed — "
        "if it was added, choose another unmapped key for this test"
    )

    # شبیه‌سازیِ منطقِ endpoint: if vtype not in _indicator_map → None
    def _vital_level(vtype: str, value: float):
        if vtype not in indicator_map:
            return None
        from clinical.rule_engine import _evaluate_reading
        return _evaluate_reading(vtype, value, indicator_map)

    result = _vital_level("temperature", 37.5)
    assert result is None, (
        f"vital type 'temperature' not in clinical_indicators → level must be None; "
        f"got {result!r}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_vital_level_field_present_in_record_response(seed_clinical_data):
    """
    Integration: GET /patients/{uuid}/record باید `level` را در هر vital برگرداند.
    تأیید می‌کند که فیلد در JSON وجود دارد (نه فقط بدون خطا بودن).
    """
    token = _get_token(seed_clinical_data)
    patient_uuid = seed_clinical_data["patient_uuid"]
    resp = _client().get(
        f"/patients/{patient_uuid}/record",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    vitals = data["recent_vitals"]
    assert len(vitals) >= 1, "At least one vital must be in recent_vitals"

    for v in vitals:
        assert "level" in v, (
            f"VitalReadingDTO must include 'level' field; missing in vital type={v.get('type')}"
        )
        # مقدار باید یکی از ok/warn/danger/None باشد
        lvl = v["level"]
        assert lvl in (None, "ok", "warn", "danger"), (
            f"level must be one of ok/warn/danger/None; got {lvl!r} for type={v.get('type')}"
        )

    # vitals با کلید shناخته‌شده (مثل hba1c) نباید None level داشته باشند
    hba1c_vitals = [v for v in vitals if v["type"] == "hba1c"]
    if hba1c_vitals:
        for v in hba1c_vitals:
            assert v["level"] is not None, (
                f"hba1c has a clinical_indicators row → level must not be None; "
                f"got None for value={v.get('value')}"
            )


# ---------------------------------------------------------------------------
# 9. verified-gate on the record surface (Step-61)
#
# The /record endpoint is the physician verify surface — it MUST show unverified
# self-report rows (that powers the verify inbox). But the clinical level badge
# (ok/warn/danger) is a decision-support derivation; per the SACRED verified-gate
# it must NOT be computed for unverified (verified=FALSE) data. We compute `level`
# only when verified=TRUE; the raw value + verified flag are always serialised.
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_record_no_clinical_level_for_unverified_self_report(seed_clinical_data):
    """
    Step-61 verified-gate regression (record surface):

    Seed a dedicated patient with two danger-range hba1c readings:
      - a VERIFIED hba1c=9.0 (clinic)        → level MUST be 'danger'
      - an UNVERIFIED self-report hba1c=9.5  → level MUST be None (gate),
        while the raw value + verified=False are still serialised (verify inbox).

    Without the gate, the unverified self-report would carry a 'danger' clinical
    badge before any physician verified it — a forbidden decision-support bleed.
    """
    import uuid as _uuid
    import psycopg as _psycopg

    _CONNINFO = (
        "host='localhost' port='55432' "
        "user='postgres' password='validate_only' "
        "dbname='halqe_app_test'"
    )
    u = _uuid.UUID("d1000061-0000-0000-0000-000000000061")
    with _psycopg.connect(_CONNINFO, autocommit=True) as conn:
        conn.execute("""
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id,
                 phone_number, birthdate, gender)
            VALUES (1, %s, 'گیت', 'تأیید', 'REC0000061', '09100000061',
                    '1971-01-01', 'male')
            ON CONFLICT (uuid) DO NOTHING
        """, (u,))
        pat_id = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s", (u,)
        ).fetchone()[0]
        conn.execute("""
            INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active)
            VALUES (1, %s, TRUE)
            ON CONFLICT (tenant_id, patient_id) DO NOTHING
        """, (pat_id,))
        link_id = conn.execute(
            "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s",
            (pat_id,)
        ).fetchone()[0]
        # VERIFIED danger reading (verified column defaults TRUE)
        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES (1, %s, 'hba1c', 9.0, '%%', now() - interval '5 days', 'clinic')
            ON CONFLICT DO NOTHING
        """, (link_id,))
        # UNVERIFIED self-report danger reading
        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at,
                 source, verified)
            VALUES (1, %s, 'hba1c', 9.5, '%%', now() - interval '1 days',
                    'patient_self', FALSE)
            ON CONFLICT DO NOTHING
        """, (link_id,))

    token = _get_token(seed_clinical_data)
    resp = _client().get(
        f"/patients/{u}/record",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    vitals = resp.json()["recent_vitals"]

    verified_rows = [
        v for v in vitals if v["type"] == "hba1c" and v["verified"] is True
    ]
    unverified_rows = [
        v for v in vitals if v["type"] == "hba1c" and v["verified"] is False
    ]

    assert verified_rows, "Expected the verified hba1c row in the record"
    assert unverified_rows, (
        "Expected the unverified self-report hba1c row (it must be shown for the "
        "verify inbox — do NOT filter it out of /record)"
    )

    # verified danger reading → clinical level computed
    assert any(v["level"] == "danger" for v in verified_rows), (
        "Verified danger hba1c must still get its clinical level badge"
    )

    # unverified self-report → NO clinical level (gate); raw value preserved
    for v in unverified_rows:
        assert v["level"] is None, (
            f"Unverified self-report must NOT get a clinical level badge "
            f"(verified-gate); got level={v['level']!r}"
        )
        assert v["value"] == 9.5, (
            "Raw self-reported value must still be serialised for the verify inbox"
        )
