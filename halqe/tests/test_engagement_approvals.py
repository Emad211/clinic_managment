"""
tests/test_engagement_approvals.py — Step 17: Physician Approval Queue.

WHAT THIS TESTS
───────────────
1.  enqueue_approval creates a pending row.
2.  enqueue_approval twice (same period_key) → idempotent: returns same row, no duplicate.
3.  list_pending shows the pending row.
4.  approve → status=approved, decided_by set, decided_at set (aware datetime).
5.  reject → status=rejected, decided_by set, decided_at set.
6.  double-approve → 409 InvalidApprovalTransition (already decided).
7.  reject then approve → 409 (already decided).
8.  STAFF cannot approve (403) — manager gate is enforced at the endpoint.
9.  STAFF cannot reject (403).
10. MANAGER can approve (200).
11. Tenant isolation: approve in wrong tenant → 404 ApprovalNotFound.
12. GET /engagement/approvals — returns pending queue, not approved/rejected.
13. Audit: approve writes an activity_log row; reject writes an activity_log row.
14. NO SMS/provider is invoked anywhere — assert the SMS import is absent from the
    service module.

STRATEGY
────────
Service-layer tests (1-7, 11, 13-14) use the ORM + psycopg superuser for setup.
API-layer tests (8-12) use ninja.testing.TestClient with JWT tokens minted directly.

All tests use the session-scoped 'seed_data' fixture for patient_link_id.
A manager user is seeded inline in this module (testmanager / manager_pw).
No SMS is sent — EngagementApproval is a pure queue with no provider reference.
"""
import datetime
import os
import uuid
import bcrypt
import psycopg
import pytest

from django.utils import timezone
from ninja.testing import TestClient
from config.api import api
import jwt
from django.conf import settings

# ---------------------------------------------------------------------------
# Connection string (superuser — for seed/direct-DB assertions only)
# ---------------------------------------------------------------------------
_PG_HOST = os.environ.get("PG_HOST", "localhost")
_PG_PORT = os.environ.get("PG_PORT", "55432")
_PG_SU_USER = os.environ.get("PG_USER", "postgres")
_PG_SU_PW = os.environ.get("PG_PASSWORD", "validate_only")
_DB_NAME = os.environ.get("PG_TEST_DB", "halqe_app_test")

_CONNINFO = (
    f"host='{_PG_HOST}' port='{_PG_PORT}' "
    f"user='{_PG_SU_USER}' password='{_PG_SU_PW}' "
    f"dbname='{_DB_NAME}'"
)


# ---------------------------------------------------------------------------
# Module-level event_key namespace — avoids collisions with other test files
# ---------------------------------------------------------------------------
_EK = "TEST-approval-step17"


# ---------------------------------------------------------------------------
# Helpers — JWT token minting
# ---------------------------------------------------------------------------

def _mint_token(user_id: int, tenant_id: int, role: str, username: str) -> str:
    """Mint a valid JWT for TestClient headers (same algorithm as auth_service)."""
    exp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
    return jwt.encode(
        {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "role": role,
            "username": username,
            "exp": exp,
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _client():
    return TestClient(api)


# ---------------------------------------------------------------------------
# Seed a manager user + a second-tenant patient_link for isolation tests.
# Session-scoped so it runs once and is reused across tests.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def approval_seed(seed_data):
    """
    Extend the session seed with:
      - A manager user 'testmanager' in tenant 1.
      - A manager user 'testmanager2' in tenant 2 (for real tenant isolation tests).
      - A second-tenant patient_link for isolation tests.
    Returns a dict with ids the tests need.
    """
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        # Tenant-1 manager user
        mgr_pw = "manager_pw"
        pw_hash = bcrypt.hashpw(mgr_pw.encode(), bcrypt.gensalt())
        conn.execute("""
            INSERT INTO platform.users
                (tenant_id, username, password_hash, role, app, is_active, failed_attempts)
            VALUES (1, 'testmanager', %s, 'manager', 'platform', TRUE, 0)
            ON CONFLICT (tenant_id, username) DO UPDATE
                SET password_hash = EXCLUDED.password_hash,
                    is_active = TRUE, failed_attempts = 0, locked_until = NULL
        """, (pw_hash,))
        mgr_row = conn.execute(
            "SELECT id FROM platform.users WHERE tenant_id=1 AND username='testmanager'"
        ).fetchone()
        mgr_id = mgr_row[0]

        # Tenant-2 setup
        conn.execute("""
            INSERT INTO platform.tenants (id, name, is_active)
            VALUES (2, 'درمانگاه تست ۲', TRUE)
            ON CONFLICT (id) DO NOTHING
        """)

        # Tenant-2 manager user (for real isolation API test)
        t2_pw_hash = bcrypt.hashpw(mgr_pw.encode(), bcrypt.gensalt())
        conn.execute("""
            INSERT INTO platform.users
                (tenant_id, username, password_hash, role, app, is_active, failed_attempts)
            VALUES (2, 'testmanager2', %s, 'manager', 'platform', TRUE, 0)
            ON CONFLICT (tenant_id, username) DO UPDATE
                SET password_hash = EXCLUDED.password_hash,
                    is_active = TRUE, failed_attempts = 0, locked_until = NULL
        """, (t2_pw_hash,))
        t2_mgr_row = conn.execute(
            "SELECT id FROM platform.users WHERE tenant_id=2 AND username='testmanager2'"
        ).fetchone()
        t2_mgr_id = t2_mgr_row[0]

        # Tenant-2 patient_link
        t2_uuid = uuid.UUID("22222222-aaaa-bbbb-cccc-dddddddddddd")
        conn.execute("""
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id, phone_number,
                 birthdate, gender)
            VALUES (2, %s, 'تست', 'جداسازی', '0000000099', '09100000099',
                    '1990-01-01', 'male')
            ON CONFLICT (uuid) DO NOTHING
        """, (t2_uuid,))
        t2_pat_row = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s", (t2_uuid,)
        ).fetchone()
        t2_pat_id = t2_pat_row[0]
        conn.execute("""
            INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active)
            VALUES (2, %s, TRUE)
            ON CONFLICT (tenant_id, patient_id) DO NOTHING
        """, (t2_pat_id,))
        t2_link_row = conn.execute(
            "SELECT id FROM clinical.patient_links WHERE tenant_id=2 AND patient_id=%s",
            (t2_pat_id,)
        ).fetchone()
        t2_link_id = t2_link_row[0]

    return {
        **seed_data,
        "mgr_id": mgr_id,
        "mgr_username": "testmanager",
        "mgr_pw": "manager_pw",
        "t2_mgr_id": t2_mgr_id,
        "t2_mgr_username": "testmanager2",
        "t2_link_id": t2_link_id,
    }


# ---------------------------------------------------------------------------
# Helper: clean up approval rows with our test event_key between tests so
# idempotency / duplicate tests see a fresh state.
# ---------------------------------------------------------------------------

def _cleanup_approvals(event_key_prefix: str = _EK):
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        conn.execute(
            "DELETE FROM clinical.engagement_approvals WHERE event_key LIKE %s",
            (f"{event_key_prefix}%",),
        )


# ===========================================================================
# 1. enqueue_approval creates a pending row
# ===========================================================================

@pytest.mark.django_db
def test_enqueue_creates_pending(django_db_setup, approval_seed):
    """enqueue_approval creates a row with status='pending'."""
    from clinical.engagement_approval_service import enqueue_approval
    from clinical.models import EngagementApproval

    _cleanup_approvals()
    link_id = approval_seed["link_id"]
    ek = f"{_EK}-create"
    pk = "2026-Q3-T1"

    approval = enqueue_approval(
        1, link_id,
        event_key=ek,
        period_key=pk,
        channel="sms",
        message="سلام بیمار",
        due_date=datetime.date(2026, 7, 1),
    )

    assert approval.id is not None
    assert approval.status == EngagementApproval.STATUS_PENDING
    assert approval.event_key == ek
    assert approval.period_key == pk
    assert approval.channel == "sms"
    assert approval.decided_by is None
    assert approval.decided_at is None
    assert approval.sent_at is None


# ===========================================================================
# 2. enqueue_approval twice (same period_key) → idempotent — same row returned
# ===========================================================================

@pytest.mark.django_db
def test_enqueue_idempotent_same_period_key(django_db_setup, approval_seed):
    """
    Calling enqueue_approval twice with the same (tenant, patient, event_key, period_key)
    must return the same row both times — no duplicate, no reset.
    """
    from clinical.engagement_approval_service import enqueue_approval

    _cleanup_approvals()
    link_id = approval_seed["link_id"]
    ek = f"{_EK}-idempotent"
    pk = "2026-Q3-T2"

    first = enqueue_approval(1, link_id, event_key=ek, period_key=pk, channel="sms")
    second = enqueue_approval(1, link_id, event_key=ek, period_key=pk, channel="sms")

    assert first.id == second.id, "Second enqueue must return the SAME row id"

    # Confirm only one row in DB
    from clinical.models import EngagementApproval
    count = EngagementApproval.objects.filter(
        tenant_id=1, patient_link_id=link_id, event_key=ek, period_key=pk
    ).count()
    assert count == 1, f"Expected exactly 1 row, got {count}"


# ===========================================================================
# 3. list_pending shows the pending row
# ===========================================================================

@pytest.mark.django_db
def test_list_pending_shows_pending(django_db_setup, approval_seed):
    """list_pending returns the pending row for this tenant."""
    from clinical.engagement_approval_service import enqueue_approval, list_pending
    from clinical.models import EngagementApproval

    _cleanup_approvals()
    link_id = approval_seed["link_id"]
    ek = f"{_EK}-listpending"
    pk = "2026-Q3-T3"

    enqueue_approval(1, link_id, event_key=ek, period_key=pk, channel="sms")
    rows = list_pending(1)

    ids_in_list = [r.id for r in rows]
    matching = [r for r in rows if r.event_key == ek and r.period_key == pk]
    assert matching, f"Expected to find {ek!r}/{pk!r} in list_pending, got ids={ids_in_list}"
    assert matching[0].status == EngagementApproval.STATUS_PENDING


# ===========================================================================
# 4. approve → status=approved + decided_by + decided_at (aware)
# ===========================================================================

@pytest.mark.django_db
def test_approve_transitions_to_approved(django_db_setup, approval_seed):
    """approve() sets status='approved', decided_by, decided_at (timezone-aware)."""
    from clinical.engagement_approval_service import enqueue_approval, approve
    from clinical.models import EngagementApproval

    _cleanup_approvals()
    link_id = approval_seed["link_id"]
    ek = f"{_EK}-approve"
    pk = "2026-Q3-T4"

    approval = enqueue_approval(1, link_id, event_key=ek, period_key=pk, channel="sms")
    before = timezone.now()
    updated = approve(approval.id, 1, decided_by="testmanager")
    after = timezone.now()

    assert updated.status == EngagementApproval.STATUS_APPROVED
    assert updated.decided_by == "testmanager"
    assert updated.decided_at is not None
    # decided_at must be a timezone-aware datetime
    assert updated.decided_at.tzinfo is not None
    assert before <= updated.decided_at <= after
    # sent_at must still be null — no SMS sent here
    assert updated.sent_at is None


# ===========================================================================
# 5. reject → status=rejected + decided_by + decided_at
# ===========================================================================

@pytest.mark.django_db
def test_reject_transitions_to_rejected(django_db_setup, approval_seed):
    """reject() sets status='rejected', decided_by, decided_at."""
    from clinical.engagement_approval_service import enqueue_approval, reject
    from clinical.models import EngagementApproval

    _cleanup_approvals()
    link_id = approval_seed["link_id"]
    ek = f"{_EK}-reject"
    pk = "2026-Q3-T5"

    approval = enqueue_approval(1, link_id, event_key=ek, period_key=pk, channel="sms")
    updated = reject(approval.id, 1, decided_by="testmanager", reason="پیام نامناسب")

    assert updated.status == EngagementApproval.STATUS_REJECTED
    assert updated.decided_by == "testmanager"
    assert updated.decided_at is not None
    assert updated.decided_at.tzinfo is not None  # timezone-aware
    # sent_at must still be null
    assert updated.sent_at is None


# ===========================================================================
# 6. double-approve → 409 InvalidApprovalTransition
# ===========================================================================

@pytest.mark.django_db
def test_double_approve_raises_invalid_transition(django_db_setup, approval_seed):
    """Approving an already-approved row raises InvalidApprovalTransition."""
    from clinical.engagement_approval_service import (
        enqueue_approval, approve, InvalidApprovalTransition
    )

    _cleanup_approvals()
    link_id = approval_seed["link_id"]
    ek = f"{_EK}-double-approve"
    pk = "2026-Q3-T6"

    approval = enqueue_approval(1, link_id, event_key=ek, period_key=pk)
    approve(approval.id, 1, decided_by="testmanager")

    with pytest.raises(InvalidApprovalTransition) as exc_info:
        approve(approval.id, 1, decided_by="testmanager")

    assert exc_info.value.approval_id == approval.id
    assert exc_info.value.current_status == "approved"


# ===========================================================================
# 7. reject then approve → 409 (already decided)
# ===========================================================================

@pytest.mark.django_db
def test_reject_then_approve_raises_invalid_transition(django_db_setup, approval_seed):
    """Approving a rejected row raises InvalidApprovalTransition."""
    from clinical.engagement_approval_service import (
        enqueue_approval, reject, approve, InvalidApprovalTransition
    )

    _cleanup_approvals()
    link_id = approval_seed["link_id"]
    ek = f"{_EK}-reject-then-approve"
    pk = "2026-Q3-T7"

    approval = enqueue_approval(1, link_id, event_key=ek, period_key=pk)
    reject(approval.id, 1, decided_by="testmanager")

    with pytest.raises(InvalidApprovalTransition) as exc_info:
        approve(approval.id, 1, decided_by="testmanager")

    assert exc_info.value.current_status == "rejected"


# ===========================================================================
# 8. STAFF cannot approve (403)
# ===========================================================================

@pytest.mark.django_db
def test_staff_cannot_approve(django_db_setup, approval_seed):
    """POST /engagement/approvals/{id}/approve by staff → 403."""
    from clinical.engagement_approval_service import enqueue_approval

    _cleanup_approvals()
    link_id = approval_seed["link_id"]
    ek = f"{_EK}-staff-approve"
    pk = "2026-Q3-T8"

    approval = enqueue_approval(1, link_id, event_key=ek, period_key=pk)

    # Mint a STAFF token (testuser from seed_data is role='staff')
    staff_token = _mint_token(
        user_id=approval_seed["user_id"],
        tenant_id=1,
        role="staff",
        username="testuser",
    )

    resp = _client().post(
        f"/engagement/approvals/{approval.id}/approve",
        headers=_auth_headers(staff_token),
        json={},
    )
    assert resp.status_code == 403, f"Expected 403 for staff, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["code"] == "forbidden"


# ===========================================================================
# 9. STAFF cannot reject (403)
# ===========================================================================

@pytest.mark.django_db
def test_staff_cannot_reject(django_db_setup, approval_seed):
    """POST /engagement/approvals/{id}/reject by staff → 403."""
    from clinical.engagement_approval_service import enqueue_approval

    _cleanup_approvals()
    link_id = approval_seed["link_id"]
    ek = f"{_EK}-staff-reject"
    pk = "2026-Q3-T9"

    approval = enqueue_approval(1, link_id, event_key=ek, period_key=pk)

    staff_token = _mint_token(
        user_id=approval_seed["user_id"],
        tenant_id=1,
        role="staff",
        username="testuser",
    )

    resp = _client().post(
        f"/engagement/approvals/{approval.id}/reject",
        headers=_auth_headers(staff_token),
        json={},
    )
    assert resp.status_code == 403, f"Expected 403 for staff, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["code"] == "forbidden"


# ===========================================================================
# 10. MANAGER can approve (200) via the endpoint
# ===========================================================================

@pytest.mark.django_db
def test_manager_can_approve_via_endpoint(django_db_setup, approval_seed):
    """POST /engagement/approvals/{id}/approve by manager → 200 + approved DTO."""
    from clinical.engagement_approval_service import enqueue_approval
    from clinical.models import EngagementApproval

    _cleanup_approvals()
    link_id = approval_seed["link_id"]
    ek = f"{_EK}-mgr-approve"
    pk = "2026-Q3-T10"

    approval = enqueue_approval(1, link_id, event_key=ek, period_key=pk, channel="sms")

    mgr_token = _mint_token(
        user_id=approval_seed["mgr_id"],
        tenant_id=1,
        role="manager",
        username=approval_seed["mgr_username"],
    )

    resp = _client().post(
        f"/engagement/approvals/{approval.id}/approve",
        headers=_auth_headers(mgr_token),
        json={},
    )
    assert resp.status_code == 200, f"Manager approve failed: {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["status"] == EngagementApproval.STATUS_APPROVED
    assert data["decided_by"] == approval_seed["mgr_username"]
    assert data["decided_at"] is not None
    assert data["sent_at"] is None   # Step 18 only


# ===========================================================================
# 11. Tenant isolation: approve in wrong tenant → 404
#
# Uses a REAL tenant-2 manager user (testmanager2, tenant_id=2 in the DB).
# The JWTBearer resolves tenant_id from the DB User row (not the JWT claims),
# so the request.tenant_id=2 comes from the actual user record — giving a
# genuine cross-tenant isolation test at the endpoint level.
# ===========================================================================

@pytest.mark.django_db
def test_tenant_isolation_approve_wrong_tenant(django_db_setup, approval_seed):
    """
    Approving a tenant-1 approval row via a tenant-2 manager's JWT must
    return 404 (no information leakage across tenant boundary).

    request.tenant_id is resolved from the REAL DB user record, so using a
    real tenant-2 user (testmanager2) guarantees request.tenant_id=2.
    """
    from clinical.engagement_approval_service import enqueue_approval

    _cleanup_approvals()
    link_id = approval_seed["link_id"]   # tenant-1 patient
    ek = f"{_EK}-tenant-isolation"
    pk = "2026-Q3-T11"

    # Create the approval for tenant-1
    approval = enqueue_approval(1, link_id, event_key=ek, period_key=pk)

    # Token for the REAL tenant-2 manager user (JWTBearer loads from DB → tenant_id=2)
    tenant2_mgr_token = _mint_token(
        user_id=approval_seed["t2_mgr_id"],
        tenant_id=2,
        role="manager",
        username=approval_seed["t2_mgr_username"],
    )

    resp = _client().post(
        f"/engagement/approvals/{approval.id}/approve",
        headers=_auth_headers(tenant2_mgr_token),
        json={},
    )
    assert resp.status_code == 404, (
        f"Wrong-tenant approve must return 404, got {resp.status_code}: {resp.text}"
    )
    data = resp.json()
    assert data["code"] == "not_found"


# ===========================================================================
# 12. GET /engagement/approvals — returns pending queue, not approved/rejected
# ===========================================================================

@pytest.mark.django_db
def test_get_approvals_returns_only_pending(django_db_setup, approval_seed):
    """
    GET /engagement/approvals returns only status='pending' rows.
    After approving one, it must NOT appear in the list.
    """
    from clinical.engagement_approval_service import enqueue_approval, approve

    _cleanup_approvals()
    link_id = approval_seed["link_id"]
    ek_pending = f"{_EK}-get-pending"
    ek_approved = f"{_EK}-get-approved"
    pk_pending = "2026-Q3-T12a"
    pk_approved = "2026-Q3-T12b"

    pending = enqueue_approval(1, link_id, event_key=ek_pending, period_key=pk_pending)
    approved = enqueue_approval(1, link_id, event_key=ek_approved, period_key=pk_approved)
    approve(approved.id, 1, decided_by="testmanager")

    # Any user can view (use staff token)
    staff_token = _mint_token(
        user_id=approval_seed["user_id"],
        tenant_id=1,
        role="staff",
        username="testuser",
    )
    resp = _client().get(
        "/engagement/approvals",
        headers=_auth_headers(staff_token),
    )
    assert resp.status_code == 200, f"GET /engagement/approvals failed: {resp.text}"
    data = resp.json()

    returned_ids = [item["id"] for item in data["items"]]
    assert pending.id in returned_ids, "Pending row must appear in queue"
    assert approved.id not in returned_ids, "Approved row must NOT appear in pending queue"

    # All returned items must be pending
    for item in data["items"]:
        assert item["status"] == "pending", f"Non-pending item in queue: {item}"


# ===========================================================================
# 13. Audit: approve and reject write activity_log rows
# ===========================================================================

@pytest.mark.django_db
def test_approve_writes_audit_log(django_db_setup, approval_seed):
    """approve() inserts an audit row action_type='engagement_approval_approved'."""
    from clinical.engagement_approval_service import enqueue_approval, approve
    from clinical.models import ActivityLog

    _cleanup_approvals()
    link_id = approval_seed["link_id"]
    ek = f"{_EK}-audit-approve"
    pk = "2026-Q3-T13a"

    approval = enqueue_approval(1, link_id, event_key=ek, period_key=pk)
    before_count = ActivityLog.objects.filter(
        tenant_id=1, action_type="engagement_approval_approved"
    ).count()

    approve(approval.id, 1, decided_by="testmanager")

    after_count = ActivityLog.objects.filter(
        tenant_id=1, action_type="engagement_approval_approved"
    ).count()
    assert after_count == before_count + 1, (
        f"Expected +1 audit row for approve; was {before_count}, now {after_count}"
    )


@pytest.mark.django_db
def test_reject_writes_audit_log(django_db_setup, approval_seed):
    """reject() inserts an audit row action_type='engagement_approval_rejected'."""
    from clinical.engagement_approval_service import enqueue_approval, reject
    from clinical.models import ActivityLog

    _cleanup_approvals()
    link_id = approval_seed["link_id"]
    ek = f"{_EK}-audit-reject"
    pk = "2026-Q3-T13b"

    approval = enqueue_approval(1, link_id, event_key=ek, period_key=pk)
    before_count = ActivityLog.objects.filter(
        tenant_id=1, action_type="engagement_approval_rejected"
    ).count()

    reject(approval.id, 1, decided_by="testmanager", reason="متن نامناسب")

    after_count = ActivityLog.objects.filter(
        tenant_id=1, action_type="engagement_approval_rejected"
    ).count()
    assert after_count == before_count + 1, (
        f"Expected +1 audit row for reject; was {before_count}, now {after_count}"
    )


# ===========================================================================
# 14. NO SMS/provider invoked — structural assertion
# ===========================================================================

def test_no_sms_import_in_service():
    """
    engagement_approval_service.py must NOT import any SMS provider or send any message.
    This is the structural guarantee that the service is a pure queue — Step 18 only.

    Checks: the service module's source must not contain direct sms imports or send calls.
    """
    import importlib, inspect, sys

    # Import (or re-import) the service module
    mod_name = "clinical.engagement_approval_service"
    if mod_name in sys.modules:
        mod = sys.modules[mod_name]
    else:
        mod = importlib.import_module(mod_name)

    source = inspect.getsource(mod)

    # Banned patterns: any sms provider import or send call
    banned = [
        "kavenegar",
        "mediana",
        "NullProvider",
        "send_sms",
        "sms_provider",
        "sms.provider",
    ]
    for pattern in banned:
        assert pattern not in source, (
            f"engagement_approval_service.py must NOT contain {pattern!r} — "
            f"no SMS sending in Step 17 (that's Step 18 only)."
        )
