"""
tests/test_engagement_models.py — Step 16: engagement engine models + seed.

WHAT THIS TESTS
---------------
1. EngagementEvent ORM round-trip: create → fetch → field values correct.
2. EngagementDispatch ORM round-trip: create → fetch → field values correct.
3. Postgres CHECK rejects bad category ('bad_cat') for engagement_events.
4. Postgres CHECK rejects bad channel ('bad_chan') for engagement_events.
5. UNIQUE(tenant_id, event_key) rejects a duplicate event_key for same tenant.
6. UNIQUE(tenant_id, patient_link_id, event_key, period_key, channel) rejects
   a duplicate dispatch — this is the idempotency guarantee Step 18 relies on.
7. seed_engagement_events command is idempotent: run twice → same count, and
   re-run with DO NOTHING does NOT overwrite an edited row.
8. seed_engagement_events --force-update updates rows.

SEED STRATEGY
-------------
Tests 1-6 use psycopg (superuser) for direct DB inserts to stay independent of
the seed command.  Tests 7-8 invoke the management command via Django's
call_command (which uses the app-role connection from settings.DATABASES).

All engagement_events inserts use a UNIQUE prefix ("TEST-") to avoid collision
with real seeds.  All dispatch rows are cleaned up in teardown via the
session fixture's DB-drop (conftest.py).

NOTE: All tests require the schema slices to be applied (django_db_setup does
this).  We use seed_data to ensure patient_links exists for dispatch tests.
"""
import pytest
import psycopg
from django.db import IntegrityError

# ---------------------------------------------------------------------------
# Direct DB connection (superuser) — same params as conftest.py
# ---------------------------------------------------------------------------
_CONNINFO = (
    "host='localhost' port='55432' "
    "user='postgres' password='validate_only' "
    "dbname='halqe_app_test'"
)

# Total expected rows from the default catalog (must match len(_DEFAULT_EVENTS))
_EXPECTED_SEED_COUNT = 14


# ===========================================================================
# 1. EngagementEvent ORM round-trip
# ===========================================================================
@pytest.mark.django_db
def test_engagement_event_roundtrip(django_db_setup, seed_data):
    """Create an EngagementEvent row via psycopg and read it back via ORM."""
    from clinical.models import EngagementEvent

    event_key = "TEST-roundtrip-event"
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO clinical.engagement_events
                (tenant_id, event_key, label, category, channel,
                 sms_template, lead_days, cooldown_days, source_action, priority, is_active)
            VALUES (1, %s, 'تست رفت‌وبرگشت', 'clinical', 'sms',
                    'سلام {name}', 3, 30, 'create_followup', 55, TRUE)
            ON CONFLICT (tenant_id, event_key) DO NOTHING
            """,
            (event_key,),
        )

    obj = EngagementEvent.objects.get(tenant_id=1, event_key=event_key)
    assert obj.label == "تست رفت‌وبرگشت"
    assert obj.category == "clinical"
    assert obj.channel == "sms"
    assert obj.sms_template == "سلام {name}"
    assert obj.lead_days == 3
    assert obj.cooldown_days == 30
    assert obj.source_action == "create_followup"
    assert obj.priority == 55
    assert obj.is_active is True
    assert obj.is_custom is False  # schema default


# ===========================================================================
# 2. EngagementDispatch ORM round-trip
# ===========================================================================
@pytest.mark.django_db
def test_engagement_dispatch_roundtrip(django_db_setup, seed_data):
    """Create an EngagementDispatch row via psycopg and read it back via ORM."""
    from clinical.models import EngagementDispatch

    link_id = seed_data["link_id"]
    event_key = "TEST-dispatch-roundtrip"
    period_key = "2026-Q2"

    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        # engagement_dispatch has FK → engagement_events(tenant_id, event_key)
        # (slice2b); insert the parent event first.
        conn.execute(
            """
            INSERT INTO clinical.engagement_events
                (tenant_id, event_key, label, category, channel, is_active)
            VALUES (1, %s, 'رفت‌وبرگشت dispatch', 'clinical', 'worklist', TRUE)
            ON CONFLICT (tenant_id, event_key) DO NOTHING
            """,
            (event_key,),
        )
        conn.execute(
            """
            INSERT INTO clinical.engagement_dispatch
                (tenant_id, patient_link_id, event_key, period_key,
                 channel, ref_id, status)
            VALUES (1, %s, %s, %s, 'worklist', NULL, 'done')
            ON CONFLICT (tenant_id, patient_link_id, event_key, period_key, channel)
            DO NOTHING
            """,
            (link_id, event_key, period_key),
        )

    obj = EngagementDispatch.objects.get(
        tenant_id=1,
        patient_link_id=link_id,
        event_key=event_key,
        period_key=period_key,
        channel="worklist",
    )
    assert obj.status == "done"
    assert obj.ref_id is None
    assert obj.created_at is not None


# ===========================================================================
# 3. Postgres CHECK rejects bad category
# ===========================================================================
@pytest.mark.django_db
def test_check_rejects_bad_category(django_db_setup, seed_data):
    """Postgres CHECK (category IN ...) must reject 'bad_cat'."""
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                """
                INSERT INTO clinical.engagement_events
                    (tenant_id, event_key, label, category, channel)
                VALUES (1, 'TEST-bad-cat', 'تست', 'bad_cat', 'sms')
                """
            )


# ===========================================================================
# 4. Postgres CHECK rejects bad channel
# ===========================================================================
@pytest.mark.django_db
def test_check_rejects_bad_channel(django_db_setup, seed_data):
    """Postgres CHECK (channel IN ...) must reject 'bad_chan'."""
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                """
                INSERT INTO clinical.engagement_events
                    (tenant_id, event_key, label, category, channel)
                VALUES (1, 'TEST-bad-chan', 'تست', 'clinical', 'bad_chan')
                """
            )


# ===========================================================================
# 5. UNIQUE(tenant_id, event_key) rejects duplicate event
# ===========================================================================
@pytest.mark.django_db
def test_unique_event_key_per_tenant(django_db_setup, seed_data):
    """Inserting a duplicate (tenant_id, event_key) must raise UniqueViolation."""
    event_key = "TEST-unique-event-check"
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        # First insert — must succeed
        conn.execute(
            """
            INSERT INTO clinical.engagement_events
                (tenant_id, event_key, label, category, channel)
            VALUES (1, %s, 'اول', 'clinical', 'worklist')
            """,
            (event_key,),
        )
        # Second insert with same (tenant_id, event_key) — must fail
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                """
                INSERT INTO clinical.engagement_events
                    (tenant_id, event_key, label, category, channel)
                VALUES (1, %s, 'دوم', 'operational', 'sms')
                """,
                (event_key,),
            )


# ===========================================================================
# 6. UNIQUE dispatch constraint — idempotency guarantee for Step 18
# ===========================================================================
@pytest.mark.django_db
def test_dispatch_unique_idempotency(django_db_setup, seed_data):
    """
    UNIQUE(tenant_id, patient_link_id, event_key, period_key, channel) on
    engagement_dispatch must reject a second dispatch for the same bucket.

    This is the hard idempotency guarantee that Step 18's dispatch logic will
    rely on: attempting to fire the same event twice for the same period raises
    UniqueViolation, which the dispatcher catches and treats as 'already done'.
    """
    link_id = seed_data["link_id"]
    event_key = "TEST-dispatch-idempotency"
    period_key = "2026-07"
    channel = "sms"

    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        # engagement_dispatch has FK → engagement_events(tenant_id, event_key)
        # (slice2b); insert the parent event first.
        conn.execute(
            """
            INSERT INTO clinical.engagement_events
                (tenant_id, event_key, label, category, channel, is_active)
            VALUES (1, %s, 'تست idempotency', 'clinical', 'sms', TRUE)
            ON CONFLICT (tenant_id, event_key) DO NOTHING
            """,
            (event_key,),
        )
        # First dispatch — must succeed
        conn.execute(
            """
            INSERT INTO clinical.engagement_dispatch
                (tenant_id, patient_link_id, event_key, period_key, channel, status)
            VALUES (1, %s, %s, %s, %s, 'done')
            """,
            (link_id, event_key, period_key, channel),
        )
        # Second dispatch — same bucket — must fail
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                """
                INSERT INTO clinical.engagement_dispatch
                    (tenant_id, patient_link_id, event_key, period_key, channel, status)
                VALUES (1, %s, %s, %s, %s, 'done')
                """,
                (link_id, event_key, period_key, channel),
            )


# ===========================================================================
# 7. seed_engagement_events is idempotent (run twice → same count)
#    and does NOT overwrite an edited row on second run.
# ===========================================================================
@pytest.mark.django_db(transaction=True)
def test_seed_idempotent_preserves_edits(django_db_setup, seed_data):
    """
    Running seed_engagement_events twice must not change the row count and
    must NOT overwrite an edited row (DO NOTHING semantics).

    Steps:
      1. Run seed once → rows inserted.
      2. Manually edit the 'appointment_reminder' row's cooldown_days.
      3. Run seed again → edited row unchanged (cooldown_days still edited value).
      4. Row count is the same after both runs.
    """
    from django.core.management import call_command
    from clinical.models import EngagementEvent

    # Run seed once — may already have some rows from previous tests; that's fine
    call_command("seed_engagement_events", "--tenant-id", "1", verbosity=0)

    # Count after first seed
    count_after_first = EngagementEvent.objects.filter(tenant_id=1).count()
    assert count_after_first >= _EXPECTED_SEED_COUNT, (
        f"Expected at least {_EXPECTED_SEED_COUNT} events after first seed, "
        f"got {count_after_first}"
    )

    # Edit the appointment_reminder row — simulate manager customization
    edited_cooldown = 999
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        conn.execute(
            """
            UPDATE clinical.engagement_events
            SET cooldown_days = %s
            WHERE tenant_id = 1 AND event_key = 'appointment_reminder'
            """,
            (edited_cooldown,),
        )

    # Run seed a second time
    call_command("seed_engagement_events", "--tenant-id", "1", verbosity=0)

    # Count must be the same
    count_after_second = EngagementEvent.objects.filter(tenant_id=1).count()
    assert count_after_second == count_after_first, (
        f"Row count changed after second seed: "
        f"{count_after_first} → {count_after_second}"
    )

    # Edited row must NOT be overwritten
    obj = EngagementEvent.objects.get(tenant_id=1, event_key="appointment_reminder")
    assert obj.cooldown_days == edited_cooldown, (
        f"Manager edit was overwritten: expected cooldown_days={edited_cooldown}, "
        f"got {obj.cooldown_days}"
    )


# ===========================================================================
# 8. --force-update does update rows
# ===========================================================================
@pytest.mark.django_db(transaction=True)
def test_seed_force_update_overwrites_edits(django_db_setup, seed_data):
    """
    Running seed_engagement_events --force-update MUST overwrite edited rows
    and restore them to the catalog defaults.
    """
    from django.core.management import call_command
    from clinical.models import EngagementEvent

    # Ensure seeded
    call_command("seed_engagement_events", "--tenant-id", "1", verbosity=0)

    # Edit refill_due priority to an unusual value
    edited_priority = 777
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        conn.execute(
            """
            UPDATE clinical.engagement_events
            SET priority = %s
            WHERE tenant_id = 1 AND event_key = 'refill_due'
            """,
            (edited_priority,),
        )

    # Confirm edit is in place
    obj = EngagementEvent.objects.get(tenant_id=1, event_key="refill_due")
    assert obj.priority == edited_priority

    # Run with --force-update
    call_command("seed_engagement_events", "--tenant-id", "1", "--force-update", verbosity=0)

    # Row must now be restored to catalog default (priority=20 from _DEFAULT_EVENTS)
    obj = EngagementEvent.objects.get(tenant_id=1, event_key="refill_due")
    assert obj.priority == 20, (
        f"--force-update should have restored priority to 20, got {obj.priority}"
    )
