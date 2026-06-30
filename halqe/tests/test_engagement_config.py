"""
tests/test_engagement_config.py — Step 52 (cluster L): engagement config + guardrails.

WHAT THIS TESTS
───────────────
Approval enrichment (GET /engagement/approvals):
  E1. Every new EngagementApproval field is serialised:
        event_label  (from engagement_events.label; fallback = event_key)
        patient_name (FIRST name only, from accounting Port — minimum-necessary)
        sms_opt_out / sms_consent (from patient_links)
        last_contact_at = max(latest done-appt scheduled_at, latest verified vital)
      and `total` is correct.
  E2. last_contact_at is null when the patient has no done-appt and no verified vital.
  E3. event_label falls back to event_key when no engagement_events row exists.

Event config (manager-only):
  V1. GET /engagement/events → list for the tenant.
  V2. PUT /engagement/events/{key} → channel + cooldown roundtrip.
  V3. staff → 403 on GET and PUT.
  V4. invalid channel → 422; negative cooldown → 422.

Settings (manager-only):
  T1. GET /engagement/settings → defaults when unset.
  T2. PUT then GET → roundtrip.
  T3. staff → 403 on GET and PUT.
  T4. invalid quiet hour → 422; negative cap → 422.

Daily-cap enforcement (dispatcher):
  C1. With a small cap, once the budget is reached, SMS enqueue is skipped
      (+daily_cap_skipped counter) and stays under the cap below it.
  C2. cap=0 (unlimited) → gate inert (no daily_cap_skipped).
  C3. Other guardrails still hold (opt-out still skips with its own counter).

NO REAL SMS: NullProvider only; these endpoints never send. The dispatcher only
ENQUEUES approvals (physician gate) — no provider is touched.

STRATEGY
────────
- Uses session 'seed_data' (patient 'علی', one verified hba1c vital).
- A manager + staff user are seeded inline (reusing the approval_seed fixture
  from test_engagement_approvals for the manager id/username + tenant-2 user).
- DB MODE — transaction=True + the 'accounting_read' alias (step 52a):
  GET /engagement/approvals enrichment reads patient demographics through the
  accounting Port (the 'accounting_read' alias), so each test must declare that
  alias OR pytest-django blocks it (DatabaseOperationForbidden). The marker is
  ``@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)``
  — IDENTICAL to test_control_room.py, the established precedent for Port-backed
  endpoints.

  WHY transaction=True IS LOAD-BEARING (the hang fix): under the default
  (transaction=False) django_db marker, each test's ORM writes (enqueue_approval
  → INSERT into clinical.engagement_approvals) stay in an UNCOMMITTED transaction
  that holds row locks until the test ends. The end-of-test ``_cleanup_events()``
  opens a SEPARATE psycopg autocommit connection and runs
  ``DELETE FROM clinical.engagement_approvals WHERE event_key LIKE ...`` — which
  blocks FOREVER on the lock held by the still-open test transaction, which can
  never commit because the test is stuck inside _cleanup_events(). That
  self-deadlock is the suite hang that shelved step 52. transaction=True commits
  the ORM writes, so the autocommit DELETE no longer contends → no deadlock.
  (managed=False models are not flushed by TransactionTestCase, so the
  module-scoped seed survives — same as test_control_room.py.)

- psycopg-autocommit seeds (engagement_events) are cleaned up explicitly with a
  namespaced prefix; approval rows the tests commit are cleaned the same way.
"""
from __future__ import annotations

import datetime
import os

import psycopg
import pytest

from django.utils import timezone
from ninja.testing import TestClient
from config.api import api
import jwt
from django.conf import settings as dj_settings

# Reuse the manager-seeding fixture from the approvals test module.
from tests.test_engagement_approvals import approval_seed  # noqa: F401


# ---------------------------------------------------------------------------
# Connection string (superuser — for seed/cleanup only)
# ---------------------------------------------------------------------------
_PG_HOST = os.environ.get("PG_HOST", "localhost")
_PG_PORT = os.environ.get("PG_PORT", "55432")
_PG_SU_USER = os.environ.get("PG_USER", "postgres")
_PG_SU_PW = os.environ.get("PG_PASSWORD", "validate_only")
_DB_NAME = os.environ.get("PG_TEST_DB", "halqe_app_test")

_CONNINFO = (
    f"host='{_PG_HOST}' port='{_PG_PORT}' "
    f"user='{_PG_SU_USER}' password='{_PG_SU_PW}' dbname='{_DB_NAME}'"
)

_EK = "TEST-config-step52"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mint_token(user_id: int, tenant_id: int, role: str, username: str) -> str:
    exp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
    return jwt.encode(
        {"user_id": user_id, "tenant_id": tenant_id, "role": role,
         "username": username, "exp": exp},
        dj_settings.SECRET_KEY,
        algorithm="HS256",
    )


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _client():
    return TestClient(api)


def _seed_event(event_key: str, channel: str, label: str | None = None,
                cooldown_days: int = 30,
                sms_template: str = "سلام {name} عزیز، تست.",
                tenant_id: int = 1):
    """Insert/update an engagement_event row (psycopg autocommit — persists)."""
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO clinical.engagement_events
                (tenant_id, event_key, label, category, channel,
                 sms_template, lead_days, cooldown_days, is_active)
            VALUES (%s, %s, %s, 'clinical', %s, %s, 0, %s, TRUE)
            ON CONFLICT (tenant_id, event_key) DO UPDATE
                SET label = EXCLUDED.label,
                    channel = EXCLUDED.channel,
                    sms_template = EXCLUDED.sms_template,
                    cooldown_days = EXCLUDED.cooldown_days,
                    is_active = TRUE
            """,
            (tenant_id, event_key, label or f"برچسبِ {event_key}", channel,
             sms_template, cooldown_days),
        )


def _cleanup_events(prefix: str = _EK):
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        conn.execute(
            "DELETE FROM clinical.engagement_events WHERE event_key LIKE %s",
            (f"{prefix}%",),
        )
        conn.execute(
            "DELETE FROM clinical.engagement_dispatch WHERE event_key LIKE %s",
            (f"{prefix}%",),
        )
        conn.execute(
            "DELETE FROM clinical.engagement_approvals WHERE event_key LIKE %s",
            (f"{prefix}%",),
        )
        conn.execute(
            "DELETE FROM clinical.followup_tasks WHERE source_event LIKE %s",
            (f"{prefix}%",),
        )


def _clear_settings():
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        conn.execute(
            "DELETE FROM platform.settings WHERE tenant_id=1 AND key LIKE 'engagement_%'"
        )


# ===========================================================================
# E1-E3: Approval enrichment
# ===========================================================================

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_approval_enrichment_all_fields(django_db_setup, approval_seed):
    """E1: GET /engagement/approvals serialises every enrichment field."""
    from clinical.engagement_approval_service import enqueue_approval

    _cleanup_events()
    link_id = approval_seed["link_id"]
    ek = f"{_EK}-enrich"
    _seed_event(ek, "sms", label="آزمایشِ دوره‌ای")

    enqueue_approval(
        1, link_id,
        event_key=ek,
        period_key=f"{ek}:p1",
        channel="sms",
        message="سلام، آزمایشِ دوره‌ای شما رسیده است.",
        due_date=datetime.date(2026, 7, 1),
    )

    staff_token = _mint_token(approval_seed["user_id"], 1, "staff", "testuser")
    resp = _client().get("/engagement/approvals", headers=_auth_headers(staff_token))
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["total"] >= 1
    item = next((i for i in data["items"] if i["event_key"] == ek), None)
    assert item is not None, f"approval for {ek} not in queue"

    # event_label resolved from engagement_events.label
    assert item["event_label"] == "آزمایشِ دوره‌ای"
    # patient_name = FIRST name only (seed patient name is 'علی')
    assert item["patient_name"] == "علی", item["patient_name"]
    # opt_out/consent from patient_links. Base seed: opt_out False, consent True —
    # step 75 grants sms_consent to the normal seeded patient (the no-consent send
    # path is covered by test_send_blocked_without_consent). Still proves the
    # enrichment DTO serialises sms_consent correctly (here: True).
    assert item["sms_opt_out"] is False
    assert item["sms_consent"] is True
    # last_contact_at present: seed_data has a verified hba1c vital ~1 day ago
    assert item["last_contact_at"] is not None
    # contract fields present
    assert item["channel"] == "sms"
    assert item["due_date"] == "2026-07-01"
    assert item["status"] == "pending"

    _cleanup_events()


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_approval_last_contact_null_when_no_history(django_db_setup, approval_seed):
    """
    E2: last_contact_at is null for a patient with no done-appt and no verified vital.

    Uses the tenant-2 patient_link from approval_seed (no vitals/appointments seeded).

    NOTE (step 52a): the enqueue is a tenant-2 ORM write, so the RLS GUC must be
    set to 2 for that INSERT (the autouse conftest fixture defaults it to 1, which
    would make the WITH CHECK policy reject a tenant_id=2 row). We set the GUC to 2
    around the write, then restore it to 1 so the autocommit cleanup behaves. The
    engagement_events seed row is also created for tenant 2 so the tenant-2
    enrichment can resolve its label.
    """
    from clinical.engagement_approval_service import enqueue_approval
    from platform_core.tenant_context import set_tenant_guc

    _cleanup_events()
    t2_link_id = approval_seed["t2_link_id"]
    ek = f"{_EK}-nohist"
    _seed_event(ek, "sms", label="بدون سابقه", tenant_id=2)

    # Tenant-2 ORM write needs the GUC at 2 (RLS WITH CHECK). Restore to 1 after.
    set_tenant_guc(2)
    try:
        enqueue_approval(
            2, t2_link_id,
            event_key=ek,
            period_key=f"{ek}:p1",
            channel="sms",
            message="سلام",
        )
    finally:
        set_tenant_guc(1)

    t2_mgr_token = _mint_token(
        approval_seed["t2_mgr_id"], 2, "manager", approval_seed["t2_mgr_username"]
    )
    resp = _client().get("/engagement/approvals", headers=_auth_headers(t2_mgr_token))
    assert resp.status_code == 200, resp.text
    data = resp.json()

    item = next((i for i in data["items"] if i["event_key"] == ek), None)
    assert item is not None
    assert item["last_contact_at"] is None, item["last_contact_at"]
    # event_label still resolved
    assert item["event_label"] == "بدون سابقه"

    _cleanup_events()


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_approval_event_label_fallback_to_key(django_db_setup, approval_seed):
    """E3: event_label falls back to event_key when no engagement_events row exists."""
    from clinical.engagement_approval_service import enqueue_approval

    _cleanup_events()
    link_id = approval_seed["link_id"]
    ek = f"{_EK}-noevent"
    # NOTE: deliberately do NOT seed an engagement_events row for ek.

    enqueue_approval(
        1, link_id,
        event_key=ek,
        period_key=f"{ek}:p1",
        channel="sms",
        message="سلام",
    )

    staff_token = _mint_token(approval_seed["user_id"], 1, "staff", "testuser")
    resp = _client().get("/engagement/approvals", headers=_auth_headers(staff_token))
    assert resp.status_code == 200, resp.text
    data = resp.json()

    item = next((i for i in data["items"] if i["event_key"] == ek), None)
    assert item is not None
    assert item["event_label"] == ek, item["event_label"]

    _cleanup_events()


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_approval_last_contact_prefers_max_source(django_db_setup, approval_seed):
    """
    E1b: last_contact_at = the LATER of (done-appt scheduled_at, verified vital).

    Uses a DEDICATED isolated patient (not the shared approval_seed patient) so
    that other transaction=True tests committing appointments/vitals for the shared
    patient do not race the MAX() and produce a later timestamp than expected.
    We seed:
      - a verified vital ~2 days ago (the "older" contact)
      - a done-appointment ~1 day ago (the "newer" contact → must win)
    Asserting the appt wins proves max-source logic; patient isolation removes
    the cross-test interference that caused the full-suite failure.
    """
    import uuid as _uuid
    from clinical.engagement_approval_service import enqueue_approval
    from clinical.models import Appointment, PatientLink

    _cleanup_events()
    ek = f"{_EK}-maxsrc"
    _seed_event(ek, "sms", label="بیشینه منبع")

    # ── Seed a dedicated accounting patient + clinical link (autocommit — persists) ──
    isolated_uuid = _uuid.uuid4()
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        conn.execute("""
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id, phone_number,
                 birthdate, gender)
            VALUES (1, %s, 'ایزوله', 'مکس‌منبع', %s, '09190000099',
                    '1980-01-01', 'male')
            ON CONFLICT (uuid) DO NOTHING
        """, (isolated_uuid, f"iso-{isolated_uuid.hex[:8]}"))

        row = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s", (isolated_uuid,)
        ).fetchone()
        isolated_patient_id = row[0]

        conn.execute("""
            INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active)
            VALUES (1, %s, TRUE)
            ON CONFLICT (tenant_id, patient_id) DO NOTHING
        """, (isolated_patient_id,))
        link_row = conn.execute(
            "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s",
            (isolated_patient_id,)
        ).fetchone()
        isolated_link_id = link_row[0]

        # Older contact: a verified vital ~2 days ago
        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at,
                 source, verified)
            VALUES (1, %s, 'hba1c', 7.0, '%%', now() - interval '2 days',
                    'clinic', TRUE)
        """, (isolated_link_id,))

    # Newer contact: a done-appointment ~1 day ago (ORM write — needs GUC; it's
    # tenant-1 so the autouse fixture already set GUC=1 before this test starts)
    appt_at = timezone.now() - datetime.timedelta(days=1)
    Appointment.objects.create(
        tenant_id=1,
        patient_link_id=isolated_link_id,
        scheduled_at=appt_at,
        status=Appointment.STATUS_DONE,
        created_at=timezone.now(),
    )

    enqueue_approval(
        1, isolated_link_id, event_key=ek, period_key=f"{ek}:p1",
        channel="sms", message="سلام",
    )

    staff_token = _mint_token(approval_seed["user_id"], 1, "staff", "testuser")
    resp = _client().get("/engagement/approvals", headers=_auth_headers(staff_token))
    assert resp.status_code == 200, resp.text
    item = next((i for i in resp.json()["items"] if i["event_key"] == ek), None)
    assert item is not None, f"approval for {ek} not in queue"

    assert item["last_contact_at"] is not None
    parsed = datetime.datetime.fromisoformat(item["last_contact_at"])
    # The done-appointment (~1d ago) is newer than the verified vital (~2d ago)
    assert abs((parsed - appt_at).total_seconds()) < 5, (
        f"last_contact_at {parsed} should equal the done-appt {appt_at} "
        f"(delta={(parsed - appt_at).total_seconds():.1f}s)"
    )

    # Clean up: remove all rows for the isolated patient.
    # Order matters because of FK constraints:
    #   engagements → patient_links; appointments → patient_links;
    #   vital_readings → patient_links; patient_links → accounting.patients.
    # The approval row was committed (transaction=True), and _cleanup_events()
    # deletes it via event_key. The appointment was also committed by the ORM;
    # delete it explicitly before removing the patient_link.
    _cleanup_events()
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        conn.execute(
            "DELETE FROM clinical.appointments WHERE patient_link_id=%s",
            (isolated_link_id,)
        )
        conn.execute(
            "DELETE FROM clinical.vital_readings WHERE patient_link_id=%s",
            (isolated_link_id,)
        )
        conn.execute(
            "DELETE FROM clinical.patient_links WHERE id=%s", (isolated_link_id,)
        )
        conn.execute(
            "DELETE FROM accounting.patients WHERE uuid=%s", (isolated_uuid,)
        )


# ===========================================================================
# V1-V4: Event config
# ===========================================================================

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_events_list_manager(django_db_setup, approval_seed):
    """V1: GET /engagement/events returns tenant events for a manager."""
    _cleanup_events()
    ek = f"{_EK}-list"
    _seed_event(ek, "worklist", label="رویدادِ لیست", cooldown_days=14)

    mgr_token = _mint_token(
        approval_seed["mgr_id"], 1, "manager", approval_seed["mgr_username"]
    )
    resp = _client().get("/engagement/events", headers=_auth_headers(mgr_token))
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    row = next((r for r in rows if r["event_key"] == ek), None)
    assert row is not None
    assert row["label"] == "رویدادِ لیست"
    assert row["channel"] == "worklist"
    assert row["cooldown_days"] == 14
    assert "category" in row

    _cleanup_events()


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_event_update_roundtrip(django_db_setup, approval_seed):
    """V2: PUT /engagement/events/{key} updates channel + cooldown, then GET reflects it."""
    _cleanup_events()
    ek = f"{_EK}-update"
    _seed_event(ek, "worklist", cooldown_days=30)

    mgr_token = _mint_token(
        approval_seed["mgr_id"], 1, "manager", approval_seed["mgr_username"]
    )
    resp = _client().put(
        f"/engagement/events/{ek}",
        headers=_auth_headers(mgr_token),
        json={"channel": "both", "cooldown_days": 7},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["channel"] == "both"
    assert data["cooldown_days"] == 7

    # GET reflects the change
    resp2 = _client().get("/engagement/events", headers=_auth_headers(mgr_token))
    row = next(r for r in resp2.json() if r["event_key"] == ek)
    assert row["channel"] == "both"
    assert row["cooldown_days"] == 7

    _cleanup_events()


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_events_staff_forbidden(django_db_setup, approval_seed):
    """V3: staff → 403 on GET and PUT events."""
    _cleanup_events()
    ek = f"{_EK}-staff"
    _seed_event(ek, "worklist")

    staff_token = _mint_token(approval_seed["user_id"], 1, "staff", "testuser")

    g = _client().get("/engagement/events", headers=_auth_headers(staff_token))
    assert g.status_code == 403
    assert g.json()["code"] == "forbidden"

    p = _client().put(
        f"/engagement/events/{ek}",
        headers=_auth_headers(staff_token),
        json={"channel": "sms", "cooldown_days": 5},
    )
    assert p.status_code == 403
    assert p.json()["code"] == "forbidden"

    _cleanup_events()


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_event_update_invalid_channel_and_cooldown(django_db_setup, approval_seed):
    """V4: invalid channel → 422; negative cooldown → 422."""
    _cleanup_events()
    ek = f"{_EK}-invalid"
    _seed_event(ek, "worklist")

    mgr_token = _mint_token(
        approval_seed["mgr_id"], 1, "manager", approval_seed["mgr_username"]
    )

    bad_ch = _client().put(
        f"/engagement/events/{ek}",
        headers=_auth_headers(mgr_token),
        json={"channel": "telegram", "cooldown_days": 5},
    )
    assert bad_ch.status_code == 422, bad_ch.text
    assert bad_ch.json()["code"] == "validation_error"

    bad_cd = _client().put(
        f"/engagement/events/{ek}",
        headers=_auth_headers(mgr_token),
        json={"channel": "sms", "cooldown_days": -1},
    )
    assert bad_cd.status_code == 422, bad_cd.text
    assert bad_cd.json()["code"] == "validation_error"

    # 404 for unknown event_key
    missing = _client().put(
        f"/engagement/events/{_EK}-does-not-exist",
        headers=_auth_headers(mgr_token),
        json={"channel": "sms", "cooldown_days": 5},
    )
    assert missing.status_code == 404, missing.text
    assert missing.json()["code"] == "not_found"

    _cleanup_events()


# ===========================================================================
# T1-T4: Settings
# ===========================================================================

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_settings_defaults(django_db_setup, approval_seed):
    """T1: GET /engagement/settings returns module defaults when unset."""
    _clear_settings()
    mgr_token = _mint_token(
        approval_seed["mgr_id"], 1, "manager", approval_seed["mgr_username"]
    )
    resp = _client().get("/engagement/settings", headers=_auth_headers(mgr_token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["quiet_start"] == "08:00"
    assert data["quiet_end"] == "21:00"
    assert data["daily_cap"] == 50
    _clear_settings()


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_settings_put_get_roundtrip(django_db_setup, approval_seed):
    """T2: PUT then GET → roundtrip."""
    _clear_settings()
    mgr_token = _mint_token(
        approval_seed["mgr_id"], 1, "manager", approval_seed["mgr_username"]
    )
    put = _client().put(
        "/engagement/settings",
        headers=_auth_headers(mgr_token),
        json={"quiet_start": "09:30", "quiet_end": "20:15", "daily_cap": 25},
    )
    assert put.status_code == 200, put.text
    assert put.json() == {"quiet_start": "09:30", "quiet_end": "20:15", "daily_cap": 25}

    get = _client().get("/engagement/settings", headers=_auth_headers(mgr_token))
    assert get.json() == {"quiet_start": "09:30", "quiet_end": "20:15", "daily_cap": 25}
    _clear_settings()


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_settings_staff_forbidden(django_db_setup, approval_seed):
    """T3: staff → 403 on GET and PUT settings."""
    staff_token = _mint_token(approval_seed["user_id"], 1, "staff", "testuser")

    g = _client().get("/engagement/settings", headers=_auth_headers(staff_token))
    assert g.status_code == 403
    assert g.json()["code"] == "forbidden"

    p = _client().put(
        "/engagement/settings",
        headers=_auth_headers(staff_token),
        json={"quiet_start": "08:00", "quiet_end": "21:00", "daily_cap": 10},
    )
    assert p.status_code == 403
    assert p.json()["code"] == "forbidden"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_settings_invalid_values(django_db_setup, approval_seed):
    """T4: invalid quiet hour → 422; negative cap → 422."""
    _clear_settings()
    mgr_token = _mint_token(
        approval_seed["mgr_id"], 1, "manager", approval_seed["mgr_username"]
    )

    bad_hour = _client().put(
        "/engagement/settings",
        headers=_auth_headers(mgr_token),
        json={"quiet_start": "25:99", "quiet_end": "21:00", "daily_cap": 10},
    )
    assert bad_hour.status_code == 422, bad_hour.text
    assert bad_hour.json()["code"] == "validation_error"

    bad_cap = _client().put(
        "/engagement/settings",
        headers=_auth_headers(mgr_token),
        json={"quiet_start": "08:00", "quiet_end": "21:00", "daily_cap": -5},
    )
    assert bad_cap.status_code == 422, bad_cap.text
    assert bad_cap.json()["code"] == "validation_error"
    _clear_settings()


# ===========================================================================
# C1-C3: Daily-cap enforcement (dispatcher)
# ===========================================================================

def _patch_collect(svc, ek, period_suffix):
    """Build a _collect_due_events mock that yields one sms event for `ek`."""
    def _mock(tenant_id, pid):
        from clinical.models import EngagementEvent
        ev_obj = EngagementEvent.objects.filter(tenant_id=1, event_key=ek).first()
        cfg = {ek: ev_obj} if ev_obj else {}
        events = [{"event_key": ek, "period_key": f"{ek}:{period_suffix}",
                   "detail": "تست"}]
        return events, cfg
    return _mock


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_daily_cap_blocks_sms_when_reached(django_db_setup, approval_seed):
    """
    C1: Once the daily SMS budget is reached, the next enqueue is suppressed
    with daily_cap_skipped, and the gate counter is correct.

    CAP STRATEGY — baseline-relative (full-suite robust):
    _sms_used_today_count(1) is tenant-1-wide: it counts ALL sms dispatch ledger
    rows + pending/approved sms approvals created today, regardless of event_key.
    Other suite tests (test_engagement_dispatch, test_engagement_approvals,
    test_engagement_run) commit sms rows for tenant-1 today, so a fixed cap=1
    would be >= already-used and the FIRST dispatch here would be suppressed too.
    Fix: read the current baseline BEFORE setting the cap, then set
    cap = baseline + 1. The first dispatch (used=baseline < cap) enqueues;
    the second (used=baseline+1 == cap) is suppressed. Intent preserved.
    """
    import clinical.engagement_service as svc
    from clinical.engagement_settings import save_engagement_settings
    from clinical.models import EngagementApproval

    _cleanup_events()
    _clear_settings()
    link_id = approval_seed["link_id"]
    ek = f"{_EK}-cap"
    _seed_event(ek, "sms")

    # Read the current tenant-wide baseline BEFORE setting the cap so we are
    # immune to however many sms rows other tests already committed today.
    baseline = svc._sms_used_today_count(1)
    cap = baseline + 1  # exactly one more slot available
    save_engagement_settings(1, quiet_start="08:00", quiet_end="21:00", daily_cap=cap)

    original_collect = svc._collect_due_events
    original_phone = svc._get_patient_phone
    svc._get_patient_phone = lambda *a, **kw: "09120000001"
    try:
        # First dispatch — used=baseline < cap → queued
        svc._collect_due_events = _patch_collect(svc, ek, "p1")
        r1 = svc.dispatch_patient(1, link_id)
        assert r1["queued"] == 1, r1
        assert r1["daily_cap_skipped"] == 0, r1

        # Second dispatch (different period) — used=baseline+1 == cap → suppressed
        svc._collect_due_events = _patch_collect(svc, ek, "p2")
        r2 = svc.dispatch_patient(1, link_id)
        assert r2["queued"] == 0, r2
        assert r2["daily_cap_skipped"] == 1, r2
        assert r2["skipped"] >= 1, r2

        # Only ONE approval for OUR event_key (the second was never enqueued)
        cnt = EngagementApproval.objects.filter(
            tenant_id=1, patient_link_id=link_id, event_key=ek
        ).count()
        assert cnt == 1, f"Expected exactly 1 approval, got {cnt}"
    finally:
        svc._collect_due_events = original_collect
        svc._get_patient_phone = original_phone

    _cleanup_events()
    _clear_settings()


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_daily_cap_zero_is_unlimited(django_db_setup, approval_seed):
    """C2: cap=0 → gate inert; repeated dispatch enqueues without daily_cap_skipped."""
    import clinical.engagement_service as svc
    from clinical.engagement_settings import save_engagement_settings

    _cleanup_events()
    _clear_settings()
    link_id = approval_seed["link_id"]
    ek = f"{_EK}-cap0"
    _seed_event(ek, "sms")

    save_engagement_settings(1, quiet_start="08:00", quiet_end="21:00", daily_cap=0)

    original_collect = svc._collect_due_events
    original_phone = svc._get_patient_phone
    svc._get_patient_phone = lambda *a, **kw: "09120000001"
    try:
        svc._collect_due_events = _patch_collect(svc, ek, "p1")
        r1 = svc.dispatch_patient(1, link_id)
        svc._collect_due_events = _patch_collect(svc, ek, "p2")
        r2 = svc.dispatch_patient(1, link_id)
        assert r1["queued"] == 1, r1
        assert r2["queued"] == 1, r2
        assert r1["daily_cap_skipped"] == 0 and r2["daily_cap_skipped"] == 0
    finally:
        svc._collect_due_events = original_collect
        svc._get_patient_phone = original_phone

    _cleanup_events()
    _clear_settings()


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_daily_cap_does_not_break_optout_guardrail(django_db_setup, approval_seed):
    """
    C3: Other guardrails still hold with the cap present — an opted-out patient is
    skipped via opt_out_skipped (NOT daily_cap_skipped), and no approval is made.
    """
    import clinical.engagement_service as svc
    from clinical.engagement_settings import save_engagement_settings
    from clinical.models import PatientLink, EngagementApproval

    _cleanup_events()
    _clear_settings()
    link_id = approval_seed["link_id"]
    ek = f"{_EK}-optout"
    _seed_event(ek, "sms")

    save_engagement_settings(1, quiet_start="08:00", quiet_end="21:00", daily_cap=5)
    PatientLink.objects.filter(id=link_id).update(sms_opt_out=True)

    original_collect = svc._collect_due_events
    try:
        svc._collect_due_events = _patch_collect(svc, ek, "p1")
        r = svc.dispatch_patient(1, link_id)
    finally:
        svc._collect_due_events = original_collect
        # opt_out rolled back by django_db transaction; explicit reset is belt+braces
        PatientLink.objects.filter(id=link_id).update(sms_opt_out=False)

    assert r["opt_out_skipped"] == 1, r
    assert r["daily_cap_skipped"] == 0, r
    assert r["queued"] == 0, r

    cnt = EngagementApproval.objects.filter(
        tenant_id=1, patient_link_id=link_id, event_key=ek
    ).count()
    assert cnt == 0

    _cleanup_events()
    _clear_settings()
