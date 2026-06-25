"""
DDI (Drug-Drug Interaction) layer tests.

Tests the ddi_alerts() surface function in clinical/rule_engine.py
and the DdiPair model (clinical.ddi_pairs / slice8).

Coverage:
  1. seed_count: 12 pairs in ddi_pairs for tenant_id=1.
  2. match_both_classes: patient with acei+arb → contraindicated DDI fires.
  3. order_independent: arb+acei (reversed) → same match (canonical lookup).
  4. no_false_positive_single_class: only acei alone → no DDI.
  5. is_active_false_excluded: deactivating a pair → not in output.
  6. severity_sort: contraindicated before major before moderate.
  7. no_classes_no_alert: empty med_classes → empty list.
  8. payload_contract: every alert has suggestion_only=True + required keys.
  9. grouped_includes_ddi_field: grouped() output carries "ddi" key.
 10. grouped_ddi_contraindicated_patient: grouped() for acei+arb patient
     returns ddi with severity=contraindicated.
 11. grouped_ddi_empty_for_no_interaction: patient with no DDI pair → ddi=[].
 12. ddi_model_meta: DdiPair.Meta.managed=False, db_table correct.

NOTE: these tests are django_db tests using the halqe_app_test Postgres DB
(same Docker container as other halqe tests). They require the session fixture
django_db_setup (from conftest.py) which applies all slices including slice8.
Real SMS is never sent (no engagement dispatch). No accounting writes.
"""
import psycopg
import pytest

from clinical.rule_engine import ddi_alerts, grouped, build_facts
from clinical.models import DdiPair


# ---------------------------------------------------------------------------
# Conninfo (same as conftest)
# ---------------------------------------------------------------------------
import os

_PG_HOST = os.environ.get("PG_HOST", "localhost")
_PG_PORT = os.environ.get("PG_PORT", "55432")
_PG_SU_USER = os.environ.get("PG_USER", "postgres")
_PG_SU_PASSWORD = os.environ.get("PG_PASSWORD", "validate_only")
_TEST_DB = os.environ.get("PG_TEST_DB", "halqe_app_test")

_SU_CONNINFO = (
    f"host='{_PG_HOST}' port='{_PG_PORT}' "
    f"user='{_PG_SU_USER}' password='{_PG_SU_PASSWORD}' "
    f"dbname='{_TEST_DB}'"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ddi_patient(django_db_setup):
    """
    Seed one patient (tenant_id=1) with medications:
      acei (active), arb (active), fibrate (active), sglt2i (active)
    → expected DDI pairs: acei+arb (contraindicated), fibrate+statin would need
      statin. arb+acei match via canonical order.
    Returns dict with patient_link_id.
    """
    import uuid as uuid_mod
    pat_uuid = uuid_mod.UUID("dd100000-0000-0000-0000-000000000001")
    with psycopg.connect(_SU_CONNINFO, autocommit=True) as conn:
        conn.execute("""
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id, phone_number,
                 birthdate, gender)
            VALUES (1, %s, 'DDI', 'تست', 'DDI0000001', '09119990001',
                    '1970-01-01', 'male')
            ON CONFLICT (uuid) DO NOTHING
        """, (pat_uuid,))
        row = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s", (pat_uuid,)
        ).fetchone()
        patient_id = row[0]

        conn.execute("""
            INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active)
            VALUES (1, %s, TRUE)
            ON CONFLICT (tenant_id, patient_id) DO NOTHING
        """, (patient_id,))
        link_row = conn.execute(
            "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s",
            (patient_id,)
        ).fetchone()
        link_id = link_row[0]

        # Active medications: acei + arb (DDI: contraindicated pair)
        # Also add sglt2i (DDI: loop_diuretic+sglt2i if loop_diuretic present)
        for drug_name, drug_class in [
            ("لیزینوپریل", "acei"),
            ("لوزارتان", "arb"),
            ("داپاگلیفلوزین", "sglt2i"),
        ]:
            conn.execute("""
                INSERT INTO clinical.patient_medications
                    (tenant_id, patient_link_id, drug_name, drug_class,
                     is_active, created_at)
                VALUES (1, %s, %s, %s, TRUE, now())
                ON CONFLICT DO NOTHING
            """, (link_id, drug_name, drug_class))

    return {"link_id": link_id, "patient_id": patient_id}


@pytest.fixture(scope="module")
def ddi_no_interaction_patient(django_db_setup):
    """
    Patient with only metformin (no DDI pairs in catalog).
    """
    import uuid as uuid_mod
    pat_uuid = uuid_mod.UUID("dd100000-0000-0000-0000-000000000002")
    with psycopg.connect(_SU_CONNINFO, autocommit=True) as conn:
        conn.execute("""
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id, phone_number,
                 birthdate, gender)
            VALUES (1, %s, 'DDI', 'بدون‌تداخل', 'DDI0000002', '09119990002',
                    '1970-01-01', 'male')
            ON CONFLICT (uuid) DO NOTHING
        """, (pat_uuid,))
        row = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s", (pat_uuid,)
        ).fetchone()
        patient_id = row[0]

        conn.execute("""
            INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active)
            VALUES (1, %s, TRUE)
            ON CONFLICT (tenant_id, patient_id) DO NOTHING
        """, (patient_id,))
        link_row = conn.execute(
            "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s",
            (patient_id,)
        ).fetchone()
        link_id = link_row[0]

        conn.execute("""
            INSERT INTO clinical.patient_medications
                (tenant_id, patient_link_id, drug_name, drug_class,
                 is_active, created_at)
            VALUES (1, %s, 'متفورمین', 'metformin', TRUE, now())
            ON CONFLICT DO NOTHING
        """, (link_id,))

    return {"link_id": link_id}


# ---------------------------------------------------------------------------
# 1. Seed count
# ---------------------------------------------------------------------------
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_ddi_seed_count(django_db_setup):
    """ddi_pairs باید ۱۲ جفت seed‌شده برای tenant_id=1 داشته باشد."""
    count = DdiPair.objects.filter(tenant_id=1).count()
    assert count == 12, f"انتظار ۱۲ جفتِ DDI، ولی {count} یافت شد"


# ---------------------------------------------------------------------------
# 2. Match both classes present
# ---------------------------------------------------------------------------
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_ddi_match_both_classes(ddi_patient):
    """بیمارِ دارای acei+arb → جفتِ contraindicated باید در خروجی باشد."""
    med_classes = {"acei", "arb", "sglt2i"}
    alerts = ddi_alerts(med_classes, tenant_id=1)
    assert alerts, "انتظار حداقل یک DDI alert برای acei+arb"
    codes = {(a["class_a"], a["class_b"]) for a in alerts}
    assert ("acei", "arb") in codes, (
        f"جفتِ acei+arb باید در alerts باشد. یافته: {codes}"
    )
    # Severity should be contraindicated
    acei_arb = next(a for a in alerts if a["class_a"] == "acei" and a["class_b"] == "arb")
    assert acei_arb["severity"] == "contraindicated"


# ---------------------------------------------------------------------------
# 3. Order-independent (reversed input)
# ---------------------------------------------------------------------------
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_ddi_order_independent(ddi_patient):
    """arb+acei (ترتیبِ معکوس) همان نتیجه را می‌دهد چون lookup canonical است."""
    alerts_fwd = ddi_alerts({"acei", "arb"}, tenant_id=1)
    alerts_rev = ddi_alerts({"arb", "acei"}, tenant_id=1)
    # مجموعهٔ جفت‌ها باید یکسان باشد (set comparison)
    codes_fwd = {(a["class_a"], a["class_b"]) for a in alerts_fwd}
    codes_rev = {(a["class_a"], a["class_b"]) for a in alerts_rev}
    assert codes_fwd == codes_rev, (
        f"ترتیبِ ورودی نباید مهم باشد. fwd={codes_fwd}, rev={codes_rev}"
    )
    assert ("acei", "arb") in codes_fwd


# ---------------------------------------------------------------------------
# 4. No false-positive: single class
# ---------------------------------------------------------------------------
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_ddi_no_false_positive_single_class():
    """فقط یک کلاس از یک جفت → بدونِ DDI (false-positive نیست)."""
    alerts = ddi_alerts({"acei"}, tenant_id=1)
    assert alerts == [], (
        f"فقط با acei نباید DDI فعال شود. یافته: {alerts}"
    )

    alerts2 = ddi_alerts({"arb"}, tenant_id=1)
    assert alerts2 == [], f"فقط با arb نباید DDI فعال شود. یافته: {alerts2}"


# ---------------------------------------------------------------------------
# 5. is_active=False excluded
# ---------------------------------------------------------------------------
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_ddi_inactive_excluded(django_db_setup):
    """
    جفتِ غیرفعال (is_active=False) از خروجی حذف می‌شود.
    جفتِ فیبرات+استاتین را غیرفعال کنیم، سپس برگردانیم.
    """
    # ابتدا مطمئن می‌شویم جفت fibrate+statin وجود دارد
    pair = DdiPair.objects.filter(
        tenant_id=1, class_a="fibrate", class_b="statin"
    ).first()
    assert pair is not None, "جفتِ fibrate+statin باید seed شده باشد"

    original_active = pair.is_active

    try:
        # غیرفعال کردن
        with psycopg.connect(_SU_CONNINFO, autocommit=True) as conn:
            conn.execute(
                "UPDATE clinical.ddi_pairs SET is_active=FALSE "
                "WHERE tenant_id=1 AND class_a='fibrate' AND class_b='statin'"
            )

        # هر دو کلاس موجود، ولی is_active=False
        alerts = ddi_alerts({"fibrate", "statin"}, tenant_id=1)
        codes = {(a["class_a"], a["class_b"]) for a in alerts}
        assert ("fibrate", "statin") not in codes, (
            f"جفتِ غیرفعال نباید در خروجی باشد. یافته: {codes}"
        )
    finally:
        # بازگرداندن به وضعِ اولیه
        with psycopg.connect(_SU_CONNINFO, autocommit=True) as conn:
            conn.execute(
                "UPDATE clinical.ddi_pairs SET is_active=%s "
                "WHERE tenant_id=1 AND class_a='fibrate' AND class_b='statin'",
                (original_active,)
            )


# ---------------------------------------------------------------------------
# 6. Severity sort: contraindicated first
# ---------------------------------------------------------------------------
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_ddi_severity_sort():
    """
    خروجی بر اساس severity مرتب است: contraindicated < major < moderate < minor.
    بیمارِ دارای acei+arb (contraindicated) + loop_diuretic+sglt2i (moderate).
    """
    alerts = ddi_alerts({"acei", "arb", "loop_diuretic", "sglt2i"}, tenant_id=1)
    assert len(alerts) >= 2, f"انتظار حداقل ۲ DDI alert. یافته: {alerts}"

    # اولین باید شدیدترین باشد
    _rank = DdiPair.SEVERITY_RANK
    for i in range(len(alerts) - 1):
        a = _rank.get(alerts[i]["severity"], 99)
        b = _rank.get(alerts[i + 1]["severity"], 99)
        assert a <= b, (
            f"مرتب‌سازیِ severity اشتباه: {alerts[i]['severity']} بعد از "
            f"{alerts[i+1]['severity']} آمده"
        )

    # اولین جفت باید contraindicated باشد
    assert alerts[0]["severity"] == "contraindicated", (
        f"اولین DDI باید contraindicated باشد. یافته: {alerts[0]['severity']}"
    )


# ---------------------------------------------------------------------------
# 7. Empty med_classes → empty list
# ---------------------------------------------------------------------------
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_ddi_empty_med_classes():
    """بدونِ هیچ داروی فعال → لیستِ خالی."""
    alerts = ddi_alerts(set(), tenant_id=1)
    assert alerts == [], f"با med_classes خالی نباید DDI فعال شود. یافته: {alerts}"


# ---------------------------------------------------------------------------
# 8. Payload contract: every alert carries required fields + suggestion_only=True
# ---------------------------------------------------------------------------
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_ddi_payload_contract():
    """هر alert باید suggestion_only=True و تمامِ فیلدهای قراردادی داشته باشد."""
    alerts = ddi_alerts({"acei", "arb", "su", "thiazide"}, tenant_id=1)
    assert alerts, "انتظار حداقل یک DDI"
    required_keys = {"class_a", "class_b", "severity", "message_fa", "evidence", "suggestion_only"}
    for alert in alerts:
        missing = required_keys - set(alert.keys())
        assert not missing, f"فیلدهای زیر در alert کم است: {missing}. alert={alert}"
        assert alert["suggestion_only"] is True, (
            f"suggestion_only باید True باشد. alert={alert}"
        )
        assert alert["severity"] in ("contraindicated", "major", "moderate", "minor"), (
            f"مقدارِ نامعتبر برای severity: {alert['severity']}"
        )


# ---------------------------------------------------------------------------
# 9. grouped() includes "ddi" key
# ---------------------------------------------------------------------------
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_grouped_includes_ddi_field(ddi_no_interaction_patient):
    """grouped() باید فیلدِ 'ddi' را برگرداند (حتی اگر خالی باشد)."""
    result = grouped(
        ddi_no_interaction_patient["link_id"],
        demographics=None,
        tenant_id=1,
    )
    assert "ddi" in result, (
        f"grouped() باید فیلدِ 'ddi' داشته باشد. کلیدهای موجود: {list(result.keys())}"
    )
    assert isinstance(result["ddi"], list)


# ---------------------------------------------------------------------------
# 10. grouped() DDI for acei+arb patient → contraindicated in ddi list
# ---------------------------------------------------------------------------
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_grouped_ddi_contraindicated_patient(ddi_patient):
    """grouped() برای بیمارِ acei+arb باید ddi شاملِ contraindicated باشد."""
    result = grouped(
        ddi_patient["link_id"],
        demographics=None,
        tenant_id=1,
    )
    assert "ddi" in result
    ddi = result["ddi"]
    assert ddi, (
        f"بیمارِ acei+arb باید حداقل یک DDI داشته باشد. result[ddi]={ddi}"
    )
    severities = [a["severity"] for a in ddi]
    assert "contraindicated" in severities, (
        f"acei+arb باید contraindicated باشد. severities={severities}"
    )
    # اولین باید شدیدترین باشد (sorted)
    assert ddi[0]["severity"] == "contraindicated", (
        f"اولین DDI باید contraindicated باشد. یافته: {ddi[0]['severity']}"
    )
    # همهٔ alertها suggestion_only=True
    for a in ddi:
        assert a["suggestion_only"] is True


# ---------------------------------------------------------------------------
# 11. grouped() DDI empty for patient with no interacting classes
# ---------------------------------------------------------------------------
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_grouped_ddi_empty_for_no_interaction(ddi_no_interaction_patient):
    """بیمارِ دارای فقط metformin → ddi=[] (هیچ تداخلی نیست)."""
    result = grouped(
        ddi_no_interaction_patient["link_id"],
        demographics=None,
        tenant_id=1,
    )
    assert result["ddi"] == [], (
        f"بیمارِ دارای فقط metformin نباید DDI داشته باشد. دریافتی: {result['ddi']}"
    )


# ---------------------------------------------------------------------------
# 12. DdiPair model meta
# ---------------------------------------------------------------------------
def test_ddi_model_meta():
    """DdiPair.Meta باید managed=False و db_table صحیح داشته باشد."""
    meta = DdiPair._meta
    assert meta.managed is False, "DdiPair باید managed=False باشد"
    assert '"clinical"."ddi_pairs"' in meta.db_table, (
        f"db_table اشتباه است: {meta.db_table}"
    )


# ---------------------------------------------------------------------------
# 13. API serialisation guard: GET /suggestions must actually RETURN `ddi`.
#     The engine computes ddi inside grouped(), but django-ninja drops any
#     field not declared in SuggestionsResponseDTO — so without the DTO field
#     the interaction never reaches the client. This exercises the real
#     endpoint end-to-end (login → GET) to guard that serialisation.
# ---------------------------------------------------------------------------
@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_suggestions_api_serialises_ddi(seed_data, ddi_patient):
    """بیمارِ acei+arb باید جفتِ contraindicated را از طریقِ پاسخِ API (نه فقط grouped) بدهد."""
    from ninja.testing import TestClient
    from config.api import api

    client = TestClient(api)
    login = client.post(
        "/auth/login",
        json={"username": "testuser", "password": seed_data["test_password"]},
    )
    assert login.status_code == 200, f"Login failed: {login.text}"
    token = login.json()["token"]

    # ddi_patient fixture seeds acei + arb (contraindicated) under this uuid
    ddi_uuid = "dd100000-0000-0000-0000-000000000001"
    resp = client.get(
        f"/patients/{ddi_uuid}/suggestions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()

    # Critical regression assertion: `ddi` must be serialised in the response.
    assert "ddi" in data, (
        f"`ddi` must be present in the /suggestions response (DTO serialisation). "
        f"Got keys: {list(data.keys())}"
    )
    assert isinstance(data["ddi"], list) and data["ddi"], (
        f"acei+arb patient must surface a DDI through the API. Got: {data['ddi']}"
    )
    pair = data["ddi"][0]  # contraindicated sorts first
    assert {"class_a", "class_b", "severity", "message_fa"} <= set(pair.keys()), (
        f"ddi entry missing required keys: {pair}"
    )
    assert pair["severity"] == "contraindicated", (
        f"acei+arb must serialise as contraindicated. Got: {pair}"
    )
    assert (pair["class_a"], pair["class_b"]) == ("acei", "arb"), (
        f"expected canonical (acei, arb). Got: {(pair['class_a'], pair['class_b'])}"
    )
