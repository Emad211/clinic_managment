"""
test_audit_coverage.py — قدم ۷۷ (S5): گاردِ پوششِ ردِ ممیزی (audit trail).

مسیرِ نوشتنِ audit کامل است: هر اقدامِ حالت‌تغییردهنده `clinical.audit.log_activity`
را صدا می‌زند (راستی‌آزمایی‌شده با security-privacy-advisor). `test_audit_log.py` از قبل
login / followup_done / suggestion accept-dismiss / append-only را assert می‌کند. این گارد
اقدامِ پر-ارزشِ PHI-محورِ **لاگ‌شده ولی assert-نشده** را قفل می‌کند —
encounter_created / prescription_created / card_token_issued — هرکدام باید یک ردیفِ
clinical.activity_logs با tenant_id + شناسهٔ کاربر + patient_link_id بسازد (ردِ شواهدِ حقوقی).

نکتهٔ مهم: `log_activity` best-effort است (استثنا را می‌بلعد، audit.py:66)، پس این تست
**وجودِ ردیف** را assert می‌کند، نه صرفاً نبودِ استثنا — یک شکستِ بلعیده‌شده وگرنه بی‌صدا pass می‌شد.

(engagement_sms_sent / doctor-queue / followup_generated با patient_link_id لاگ می‌شوند و در
تست‌های e2eِ خودشان اجرا می‌شوند؛ card_token_revoked طبقِ طراحی tenant+user+token_id لاگ می‌کند —
بیمار از طریقِ token قابلِ بازیابی است، patient_card.py:342.)

PG-only (از clinical.activity_logs می‌خواند با psycopg superuser، مثلِ test_audit_log).
"""
import psycopg
import pytest
from ninja.testing import TestClient

from config.api import api

_CONNINFO = (
    "host='localhost' port='55432' "
    "user='postgres' password='validate_only' "
    "dbname='halqe_app_test'"
)


def _client() -> TestClient:
    return TestClient(api)


def _count(conn, action_type: str, tenant_id: int = 1) -> int:
    return conn.execute(
        "SELECT count(*) FROM clinical.activity_logs "
        "WHERE action_type=%s AND tenant_id=%s",
        (action_type, tenant_id),
    ).fetchone()[0]


def _latest(conn, action_type: str, tenant_id: int = 1):
    """(tenant_id, user_id, username, patient_link_id, target_table) of the most
    recent row for this action_type+tenant, or None."""
    return conn.execute(
        "SELECT tenant_id, user_id, username, patient_link_id, target_table "
        "FROM clinical.activity_logs "
        "WHERE action_type=%s AND tenant_id=%s "
        "ORDER BY created_at DESC LIMIT 1",
        (action_type, tenant_id),
    ).fetchone()


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_encounter_created_is_audited(seed_clinical_data):
    """create_encounter → encounter_created row with tenant + user + patient_link_id."""
    from clinical.encounter_service import create_encounter

    link_id = seed_clinical_data["link_id"]
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        before = _count(conn, "encounter_created")

    create_encounter(
        patient_link_id=link_id, tenant_id=1,
        encounter_type="visit", created_by="testuser",
    )

    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        assert _count(conn, "encounter_created") > before, (
            "no audit row written for encounter_created"
        )
        row = _latest(conn, "encounter_created")

    t_id, user_id, username, plid, _ = row
    assert t_id == 1
    assert (username or user_id), "audit row must carry a user identifier"
    assert plid == link_id, (
        f"encounter_created audit must carry patient_link_id={link_id}, got {plid}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_prescription_created_is_audited(seed_clinical_data):
    """add_prescription_to_encounter → prescription_created row with patient_link_id."""
    from clinical.encounter_service import (
        create_encounter,
        add_prescription_to_encounter,
    )

    link_id = seed_clinical_data["link_id"]
    user_id = seed_clinical_data["user_id"]
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        before = _count(conn, "prescription_created")

    enc = create_encounter(
        patient_link_id=link_id, tenant_id=1,
        encounter_type="visit", created_by="testuser",
    )
    add_prescription_to_encounter(
        enc.id, 1,
        kind="chronic",
        items=[{
            "drug_name": "متفورمین", "drug_class": "metformin",
            "frequency": "bid", "route": "oral",
            "quantity": 60, "duration_days": 30,
        }],
        prescriber_user_id=user_id, created_by="testuser",
    )

    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        assert _count(conn, "prescription_created") > before, (
            "no audit row written for prescription_created"
        )
        row = _latest(conn, "prescription_created")

    t_id, u_id, username, plid, _ = row
    assert t_id == 1
    assert (username or u_id), "audit row must carry a user identifier"
    assert plid == link_id, (
        f"prescription_created audit must carry patient_link_id={link_id}, got {plid}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_card_token_issued_is_audited(seed_clinical_data):
    """POST /patients/{uuid}/card-token → card_token_issued row with tenant+user+patient."""
    resp = _client().post(
        "/auth/login",
        json={"username": "testuser", "password": seed_clinical_data["test_password"]},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]
    patient_uuid = seed_clinical_data["patient_uuid"]
    link_id = seed_clinical_data["link_id"]

    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        before = _count(conn, "card_token_issued")

    r = _client().post(
        f"/patients/{patient_uuid}/card-token",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, f"issue failed: {r.status_code} {r.text}"

    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        assert _count(conn, "card_token_issued") > before, (
            "no audit row written for card_token_issued"
        )
        row = _latest(conn, "card_token_issued")

    t_id, user_id, username, plid, _ = row
    assert t_id == 1
    assert user_id is not None and username == "testuser", (
        "card_token_issued (endpoint audit) must carry user_id + username from JWT"
    )
    assert plid == link_id, (
        f"card_token_issued audit must carry patient_link_id={link_id}, got {plid}"
    )
