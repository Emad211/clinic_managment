"""
tests/test_run_engagement_command.py — Step 51 (cluster L):
production hardening of the run_engagement command.

WHAT THIS TESTS
───────────────
No-concurrent-run guard (advisory lock):
  L1. A second, independent connection holds pg_advisory_lock(KEY); running the
      command reports skipped_locked, writes ZERO dispatch rows, exits cleanly.
  L2. Lock is released after a normal run — a subsequent run acquires it and works.

Idempotency (ledger backstop, no concurrent lock):
  L3. Two sequential runs (no concurrent lock) → no duplicate dispatch rows.

Guardrails (counted correctly in the summary):
  L4. opt-out → counted in opt_out_skipped, no approval.
  L5. cooldown → counted in cooldown_skipped, no approval.
  L6. holdout → counted in holdout, dispatch row recorded as 'holdout'.

dry-run:
  L7. --dry-run writes NOTHING (no dispatch, no followup, no approval).

Observability + no real SMS:
  L8. run_all summary returns the new breakdown keys with correct counts.
  L9. NullProvider only — urllib.urlopen is never called on this path.

STRATEGY
────────
- The command's run_all walks REAL active patients for a tenant.  To make the due
  events deterministic we monkey-patch clinical.engagement_service._collect_due_events
  to return a fixed event for the seeded patient and {} for everyone else.
- We patch _get_patient_phone so the SMS path does not depend on the accounting Port.
- A SEPARATE psycopg connection (superuser) is used to grab/release the advisory lock
  for the no-concurrent-run test — it is ALWAYS released + closed in finally so it
  cannot leak into the next test.
- Cleanup of all rows created (event_key LIKE prefix) before and after each test.
"""
from __future__ import annotations

import io
import os
import unittest.mock

import psycopg
import pytest

from django.core.management import call_command

# Reuse the self-contained dispatcher seed (manager + tenant-2 + events).
from tests.test_engagement_dispatch import dispatch_seed, _seed_event  # noqa: F401

_PG_HOST = os.environ.get("PG_HOST", "localhost")
_PG_PORT = os.environ.get("PG_PORT", "55432")
_PG_SU_USER = os.environ.get("PG_USER", "postgres")
_PG_SU_PW = os.environ.get("PG_PASSWORD", "validate_only")
_DB_NAME = os.environ.get("PG_TEST_DB", "halqe_app_test")

_CONNINFO = (
    f"host='{_PG_HOST}' port='{_PG_PORT}' "
    f"user='{_PG_SU_USER}' password='{_PG_SU_PW}' dbname='{_DB_NAME}'"
)

# Namespaced so cleanup never touches other test files' rows.
_EK = "TEST-cmd-step51"


def _cleanup(prefix: str = _EK):
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
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


def _restore_tenant_guc(tid: int = 1):
    """
    Re-set the tenant GUC after run_engagement.

    The command sets the GUC per-tenant and CLEARS it (to '') in finally — exactly
    as production does.  Under RLS (slice5, fail-closed) any ORM query the TEST then
    runs would see ZERO rows with an empty GUC.  Tests that assert on DB state after
    the command must therefore restore the GUC first (the autouse fixture set it at
    test start, but the command cleared it).  This is also a faithful proof that the
    command's GUC handling is real.
    """
    from platform_core.tenant_context import set_tenant_guc
    set_tenant_guc(tid)


def _patch_due_event(ek: str, period_key: str | None = None):
    """
    Return a _collect_due_events replacement that yields ONE due event (ek) for the
    seeded tenant-1 patient and nothing for any other patient.  cfg is read live
    from the engagement_events table so channel/cooldown reflect the seeded row.
    """
    pk = period_key or f"{ek}:2026-06"

    def _mock_collect(tenant_id, pid):
        from clinical.models import EngagementEvent
        ev_obj = EngagementEvent.objects.filter(tenant_id=tenant_id, event_key=ek).first()
        if not ev_obj:
            return [], {}
        cfg = {ek: ev_obj}
        events = [{"event_key": ek, "period_key": pk, "detail": "تست قدم۵۱"}]
        return events, cfg

    return _mock_collect


def _dispatch_count(link_id: int, ek: str) -> int:
    from clinical.models import EngagementDispatch
    return EngagementDispatch.objects.filter(
        tenant_id=1, patient_link_id=link_id, event_key=ek
    ).count()


# ===========================================================================
# L1 — no-concurrent-run: second connection holds the lock → skipped_locked
# ===========================================================================
@pytest.mark.django_db
def test_command_skips_when_lock_held(django_db_setup, dispatch_seed):
    """
    L1: An independent connection holds the global advisory lock.  The command
    must report skipped_locked, write ZERO dispatch rows, and exit cleanly.
    """
    from clinical.advisory_lock import ENGAGEMENT_RUN_LOCK_KEY
    import clinical.engagement_service as svc

    _cleanup()
    link_id = dispatch_seed["link_id"]
    ek = f"{_EK}-l1"
    _seed_event(ek, "worklist")

    # Hold the lock on a SEPARATE connection (simulates another run in progress).
    holder = psycopg.connect(_CONNINFO, autocommit=True)
    try:
        got = holder.execute(
            "SELECT pg_try_advisory_lock(%s)", (ENGAGEMENT_RUN_LOCK_KEY,)
        ).fetchone()[0]
        assert got is True, "Test setup: holder must acquire the lock"

        original = svc._collect_due_events
        svc._collect_due_events = _patch_due_event(ek)
        out = io.StringIO()
        try:
            call_command("run_engagement", "--tenant-id", "1", stdout=out)
        finally:
            svc._collect_due_events = original

        text = out.getvalue()
        assert "skipped_locked" in text, f"Expected skipped_locked in output:\n{text}"

        # ZERO dispatch rows — the command did no work.
        assert _dispatch_count(link_id, ek) == 0, (
            "A locked-out run must write no dispatch rows"
        )
    finally:
        # ALWAYS release + close so the next test is not blocked.
        try:
            holder.execute("SELECT pg_advisory_unlock(%s)", (ENGAGEMENT_RUN_LOCK_KEY,))
        finally:
            holder.close()
        _cleanup()


# ===========================================================================
# L2 — lock is released after a normal run (next run can acquire it)
# ===========================================================================
@pytest.mark.django_db
def test_lock_released_after_normal_run(django_db_setup, dispatch_seed):
    """
    L2: After a normal command run the advisory lock is released — proven by
    acquiring it from an independent connection immediately afterwards.
    """
    from clinical.advisory_lock import ENGAGEMENT_RUN_LOCK_KEY
    import clinical.engagement_service as svc

    _cleanup()
    ek = f"{_EK}-l2"
    _seed_event(ek, "worklist")

    original = svc._collect_due_events
    svc._collect_due_events = _patch_due_event(ek)
    out = io.StringIO()
    try:
        call_command("run_engagement", "--tenant-id", "1", stdout=out)
    finally:
        svc._collect_due_events = original

    # The lock must be free now.
    probe = psycopg.connect(_CONNINFO, autocommit=True)
    try:
        got = probe.execute(
            "SELECT pg_try_advisory_lock(%s)", (ENGAGEMENT_RUN_LOCK_KEY,)
        ).fetchone()[0]
        assert got is True, (
            "Lock must be released after a normal run — but a fresh connection "
            "could not acquire it (still held → leak)."
        )
    finally:
        probe.execute("SELECT pg_advisory_unlock(%s)", (ENGAGEMENT_RUN_LOCK_KEY,))
        probe.close()
        _cleanup()


# ===========================================================================
# L3 — idempotency: two sequential runs → no duplicate dispatch rows
# ===========================================================================
@pytest.mark.django_db
def test_two_runs_idempotent(django_db_setup, dispatch_seed):
    """
    L3: Running the command twice (no concurrent lock) produces no duplicate
    dispatch rows for the same (tenant, patient, event, period, channel).
    """
    import clinical.engagement_service as svc

    _cleanup()
    link_id = dispatch_seed["link_id"]
    ek = f"{_EK}-l3"
    _seed_event(ek, "worklist")

    original = svc._collect_due_events
    svc._collect_due_events = _patch_due_event(ek)
    try:
        call_command("run_engagement", "--tenant-id", "1", stdout=io.StringIO())
        call_command("run_engagement", "--tenant-id", "1", stdout=io.StringIO())
    finally:
        svc._collect_due_events = original
        _restore_tenant_guc()  # command cleared the GUC; ORM read needs it

    from clinical.models import EngagementDispatch
    count = EngagementDispatch.objects.filter(
        tenant_id=1, patient_link_id=link_id, event_key=ek, channel="worklist"
    ).count()
    assert count == 1, f"Expected exactly 1 dispatch row (idempotent), got {count}"

    _cleanup()


# ===========================================================================
# L4 — opt-out guardrail counted as opt_out_skipped, no approval
# ===========================================================================
@pytest.mark.django_db
def test_optout_counted_and_no_approval(django_db_setup, dispatch_seed):
    """L4: opted-out patient → opt_out_skipped incremented, no approval row."""
    import clinical.engagement_service as svc
    from clinical.models import PatientLink, EngagementApproval

    _cleanup()
    link_id = dispatch_seed["link_id"]
    ek = f"{_EK}-l4"
    _seed_event(ek, "sms")

    PatientLink.objects.filter(id=link_id).update(sms_opt_out=True)

    original = svc._collect_due_events
    original_phone = svc._get_patient_phone
    svc._collect_due_events = _patch_due_event(ek)
    svc._get_patient_phone = lambda *a, **kw: None  # opted-out → no phone fetched
    try:
        result = svc.run_all(1)
    finally:
        svc._collect_due_events = original
        svc._get_patient_phone = original_phone
        PatientLink.objects.filter(id=link_id).update(sms_opt_out=False)

    assert result["opt_out_skipped"] >= 1, f"opt_out_skipped not counted: {result}"
    assert result["skipped"] >= result["opt_out_skipped"], (
        "opt_out_skipped must be a subset of skipped"
    )
    assert EngagementApproval.objects.filter(
        tenant_id=1, patient_link_id=link_id, event_key=ek
    ).count() == 0, "opted-out patient must get no approval"

    _cleanup()


# ===========================================================================
# L5 — cooldown guardrail counted as cooldown_skipped, no approval
# ===========================================================================
@pytest.mark.django_db
def test_cooldown_counted_and_no_approval(django_db_setup, dispatch_seed):
    """L5: in-cooldown event → cooldown_skipped incremented, no approval row."""
    import clinical.engagement_service as svc
    from clinical.models import EngagementApproval

    _cleanup()
    link_id = dispatch_seed["link_id"]
    ek = f"{_EK}-l5"
    _seed_event(ek, "sms", cooldown_days=30)

    # Seed a recent sms dispatch row to put the event inside cooldown.
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO clinical.engagement_dispatch
                (tenant_id, patient_link_id, event_key, period_key, channel, status)
            VALUES (1, %s, %s, %s, 'sms', 'done')
            ON CONFLICT (tenant_id, patient_link_id, event_key, period_key, channel)
            DO NOTHING
            """,
            (link_id, ek, f"{ek}:prev"),
        )

    original = svc._collect_due_events
    original_phone = svc._get_patient_phone
    # New period_key so idempotency does NOT short-circuit before cooldown check.
    svc._collect_due_events = _patch_due_event(ek, period_key=f"{ek}:2026-07")
    svc._get_patient_phone = lambda *a, **kw: "09120000001"
    try:
        result = svc.run_all(1)
    finally:
        svc._collect_due_events = original
        svc._get_patient_phone = original_phone

    assert result["cooldown_skipped"] >= 1, f"cooldown_skipped not counted: {result}"
    assert EngagementApproval.objects.filter(
        tenant_id=1, patient_link_id=link_id, event_key=ek
    ).count() == 0, "cooldown must prevent approval creation"

    _cleanup()


# ===========================================================================
# L6 — holdout guardrail counted, dispatch row recorded as 'holdout'
# ===========================================================================
@pytest.mark.django_db
def test_holdout_counted_and_recorded(django_db_setup, dispatch_seed):
    """
    L6: patient in engagement holdout → holdout incremented, an auditable
    'holdout' dispatch row recorded, and NO worklist/sms action taken.
    """
    import datetime
    import clinical.engagement_service as svc
    from clinical.models import PatientLink, EngagementDispatch, FollowupTask

    _cleanup()
    link_id = dispatch_seed["link_id"]
    ek = f"{_EK}-l6"
    _seed_event(ek, "worklist")

    PatientLink.objects.filter(id=link_id).update(
        engagement_holdout=True,
        engagement_holdout_until=datetime.date.today() + datetime.timedelta(days=30),
    )

    original = svc._collect_due_events
    svc._collect_due_events = _patch_due_event(ek)
    try:
        result = svc.run_all(1)
    finally:
        svc._collect_due_events = original
        PatientLink.objects.filter(id=link_id).update(
            engagement_holdout=False, engagement_holdout_until=None,
        )

    assert result["holdout"] >= 1, f"holdout not counted: {result}"

    # Auditable holdout dispatch row, status='holdout'
    hd = EngagementDispatch.objects.filter(
        tenant_id=1, patient_link_id=link_id, event_key=ek, status="holdout"
    ).first()
    assert hd is not None, "holdout must record an auditable dispatch row"

    # No worklist task created for the held-out engagement event
    assert FollowupTask.objects.filter(
        tenant_id=1, patient_link_id=link_id, source_event=ek
    ).count() == 0, "holdout must not create an engagement worklist task"

    _cleanup()


# ===========================================================================
# L7 — dry-run writes nothing
# ===========================================================================
@pytest.mark.django_db
def test_dry_run_writes_nothing(django_db_setup, dispatch_seed):
    """L7: --dry-run → no dispatch rows, no followup tasks, no approvals."""
    import clinical.engagement_service as svc
    from clinical.models import EngagementDispatch, FollowupTask, EngagementApproval

    _cleanup()
    link_id = dispatch_seed["link_id"]
    ek = f"{_EK}-l7"
    _seed_event(ek, "both")

    original = svc._collect_due_events
    original_phone = svc._get_patient_phone
    svc._collect_due_events = _patch_due_event(ek)
    svc._get_patient_phone = lambda *a, **kw: "09120000001"
    out = io.StringIO()
    try:
        call_command("run_engagement", "--tenant-id", "1", "--dry-run", stdout=out)
    finally:
        svc._collect_due_events = original
        svc._get_patient_phone = original_phone
        _restore_tenant_guc()  # command cleared the GUC; ORM reads need it

    assert "[dry-run]" in out.getvalue()
    assert EngagementDispatch.objects.filter(
        tenant_id=1, patient_link_id=link_id, event_key=ek
    ).count() == 0, "dry-run must not write dispatch rows"
    assert FollowupTask.objects.filter(
        tenant_id=1, patient_link_id=link_id, source_event=ek
    ).count() == 0, "dry-run must not create followup tasks"
    assert EngagementApproval.objects.filter(
        tenant_id=1, patient_link_id=link_id, event_key=ek
    ).count() == 0, "dry-run must not enqueue approvals"

    _cleanup()


# ===========================================================================
# L8 — observability: run_all summary exposes the breakdown keys
# ===========================================================================
@pytest.mark.django_db
def test_run_all_summary_shape(django_db_setup, dispatch_seed):
    """L8: run_all returns the new observability keys with correct values."""
    import clinical.engagement_service as svc

    _cleanup()
    ek = f"{_EK}-l8"
    _seed_event(ek, "worklist")

    original = svc._collect_due_events
    svc._collect_due_events = _patch_due_event(ek)
    try:
        result = svc.run_all(1, dry_run=True)
    finally:
        svc._collect_due_events = original

    for key in ("patients", "queued", "worklist", "skipped",
                "opt_out_skipped", "cooldown_skipped", "holdout", "errors"):
        assert key in result, f"summary missing key {key!r}: {result}"
    assert result["patients"] >= 1
    # worklist channel due event for the seeded patient → at least one worklist count
    assert result["worklist"] >= 1, f"expected worklist>=1, got {result}"

    _cleanup()


# ===========================================================================
# L9 — no real SMS on the command path (NullProvider; urllib never called)
# ===========================================================================
@pytest.mark.django_db
def test_command_never_sends_real_sms(django_db_setup, dispatch_seed):
    """
    L9: Running the command with an sms-channel due event enqueues an approval but
    NEVER sends — urllib.request.urlopen must not be called anywhere on this path.
    """
    import urllib.request
    import clinical.engagement_service as svc
    from clinical.models import EngagementApproval

    _cleanup()
    link_id = dispatch_seed["link_id"]
    ek = f"{_EK}-l9"
    _seed_event(ek, "sms")

    original = svc._collect_due_events
    original_phone = svc._get_patient_phone
    svc._collect_due_events = _patch_due_event(ek)
    svc._get_patient_phone = lambda *a, **kw: "09120000001"
    with unittest.mock.patch.object(urllib.request, "urlopen") as mock_open:
        try:
            call_command("run_engagement", "--tenant-id", "1", stdout=io.StringIO())
        finally:
            svc._collect_due_events = original
            svc._get_patient_phone = original_phone
            _restore_tenant_guc()  # command cleared the GUC; ORM read needs it
        mock_open.assert_not_called()

    # An approval was enqueued (pending) but never sent.
    ap = EngagementApproval.objects.filter(
        tenant_id=1, patient_link_id=link_id, event_key=ek
    ).first()
    assert ap is not None, "sms-channel event should enqueue an approval"
    assert ap.status == EngagementApproval.STATUS_PENDING
    assert ap.sent_at is None, "command must never send — sent_at must be None"

    _cleanup()
