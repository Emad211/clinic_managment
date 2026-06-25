"""
tests/test_followup_engine.py — Step 12: followup engine port tests.

WHAT THIS TESTS
---------------
1. A patient with a due monitoring rule → generate creates a followup_task
   (correct reason + source_rule).
2. An item with a RECENT vital / lab → not due → no task created.
3. Redflag rules → no worklist task (panel only).
4. Running generate_for_patient twice → no duplicate (idempotent).
5. Tenant isolation: generate_for_patient for tenant-1 does not create tasks
   for tenant-2 patients.
6. Demographics path: evaluate_for_patient is used (not raw rule_engine.evaluate).
   Confirmed via monkey-patch — the engine call goes through suggestion_service.

SEED STRATEGY
-------------
We seed a MONITORING rule (action_type='create_followup') into clinical_rules
that fires for any diabetic patient. The seed_clinical_data fixture already
provides a diabetic patient (link_id with diabetes condition). We use that.

The rule is seeded with:
  rule_code: 'T2-MON-A1C-TEST'
  condition_code: 'diabetes'
  action_type: 'create_followup'
  action_params_json: {"item": "a1c", "interval_months": 6}
  trigger_json: {"all": [{"var": "condition", "op": "has", "value": "diabetes"}]}

For the "item already done recently" test we insert a vital_reading of type
'hba1c' dated 1 month ago — within the 6-month recall window → not due.
"""
import json
import uuid
import psycopg
import pytest

# ── DB connection params (same as conftest) ───────────────────────────────────
_CONNINFO = (
    "host='localhost' port='55432' "
    "user='postgres' password='validate_only' "
    "dbname='halqe_app_test'"
)

# ── Rule definition used in this test module ──────────────────────────────────
_MONITORING_RULE = {
    "rule_code": "T2-MON-A1C-TEST",
    "title": "پایش HbA1c — تست",
    "category": "monitoring",
    "condition_code": "diabetes",
    "trigger_json": {"all": [
        {"var": "condition", "op": "has", "value": "diabetes"},
    ]},
    "human_if": "دیابت فعال",
    "recommendation": "HbA1c هر ۶ ماه بررسی شود.",
    "action_type": "create_followup",
    "action_params_json": {"item": "a1c", "interval_months": 6},
    "severity": "info",
    "priority": 90,
    "source_ref": "ADA 6.1",
}

# A redflag rule that fires for VERY high HbA1c (>12) — we'll test this
# does NOT create a worklist task.
_REDFLAG_RULE = {
    "rule_code": "T2-REDFLAG-HYPER-TEST",
    "title": "هایپرگلیسمی شدید — تست",
    "category": "redflag",
    "condition_code": "diabetes",
    "trigger_json": {"any": [
        {"var": "indicator.hba1c.latest", "op": ">", "value": 12},
    ]},
    "human_if": "A1c >12",
    "recommendation": "ارزیابی DKA.",
    "action_type": "redflag",
    "action_params_json": None,
    "severity": "urgent",
    "priority": 1,
    "source_ref": "ADA 9.20",
}


@pytest.fixture(scope="session")
def seed_followup_data(seed_clinical_data):
    """
    Extend seed_clinical_data with:
      - clinical_rules: T2-MON-A1C-TEST (monitoring) + T2-REDFLAG-HYPER-TEST (redflag)
      - A patient (link_due) who has NO recent HbA1c → monitoring is due
      - A patient (link_recent) who has a RECENT HbA1c (1 month ago) → NOT due
      - A patient (link_redflag) with HbA1c=13 → redflag fires but no worklist task
      - tenant-2 patient (for tenant isolation test)

    All in tenant-1 except the tenant-2 isolation patient.
    """
    diabetes_condition_id = seed_clinical_data.get("diabetes_condition_id")

    due_uuid      = uuid.UUID("f0000001-0000-0000-0000-000000000001")
    recent_uuid   = uuid.UUID("f0000001-0000-0000-0000-000000000002")
    redflag_uuid  = uuid.UUID("f0000001-0000-0000-0000-000000000003")

    with psycopg.connect(_CONNINFO, autocommit=True) as conn:

        # ── Seed the two test rules ───────────────────────────────────────────
        for rule in (_MONITORING_RULE, _REDFLAG_RULE):
            conn.execute("""
                INSERT INTO clinical.clinical_rules
                    (tenant_id, rule_code, title, category, condition_code,
                     trigger_json, human_if, recommendation,
                     action_type, action_params_json, severity, priority,
                     source_ref, is_active)
                VALUES
                    (1, %(rule_code)s, %(title)s, %(category)s, %(condition_code)s,
                     %(trigger_json)s::jsonb, %(human_if)s, %(recommendation)s,
                     %(action_type)s, %(action_params_json)s::jsonb,
                     %(severity)s, %(priority)s, %(source_ref)s, TRUE)
                ON CONFLICT (tenant_id, rule_code) DO NOTHING
            """, {
                **rule,
                "trigger_json": json.dumps(rule["trigger_json"], ensure_ascii=False),
                "action_params_json": (
                    json.dumps(rule["action_params_json"], ensure_ascii=False)
                    if rule["action_params_json"] is not None else None
                ),
            })

        def _make_diabetic_patient(u, nid, phone, family_name):
            """Helper: seed accounting patient + patient_link + diabetes condition."""
            conn.execute("""
                INSERT INTO accounting.patients
                    (tenant_id, uuid, name, family_name, national_id,
                     phone_number, birthdate, gender)
                VALUES (1, %s, 'تست', %s, %s, %s, '1975-01-01', 'male')
                ON CONFLICT (uuid) DO NOTHING
            """, (u, family_name, nid, phone))

            row = conn.execute(
                "SELECT id FROM accounting.patients WHERE uuid=%s", (u,)
            ).fetchone()
            pat_id = row[0]

            conn.execute("""
                INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active)
                VALUES (1, %s, TRUE)
                ON CONFLICT (tenant_id, patient_id) DO NOTHING
            """, (pat_id,))

            row = conn.execute(
                "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s",
                (pat_id,)
            ).fetchone()
            link_id = row[0]

            # Add diabetes condition
            if diabetes_condition_id:
                conn.execute("""
                    INSERT INTO clinical.patient_conditions
                        (tenant_id, patient_link_id, condition_id, is_active, diagnosed_at)
                    VALUES (1, %s, %s, TRUE, now())
                    ON CONFLICT DO NOTHING
                """, (link_id, diabetes_condition_id))

            return pat_id, link_id

        # ── Patient 1: DUE — no recent HbA1c (last HbA1c was 8 months ago) ──
        due_pat_id, due_link_id = _make_diabetic_patient(
            due_uuid, "FU0000001", "09000000001", "بیمارِ سررسید"
        )
        # Old HbA1c (8 months ago — beyond 6-month recall) → item IS due
        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES (1, %s, 'hba1c', 7.8, '%%',
                    now() - interval '8 months', 'clinic')
            ON CONFLICT DO NOTHING
        """, (due_link_id,))

        # ── Patient 2: NOT DUE — HbA1c 1 month ago (within 6-month window) ──
        recent_pat_id, recent_link_id = _make_diabetic_patient(
            recent_uuid, "FU0000002", "09000000002", "بیمارِ انجام‌شده"
        )
        # Recent HbA1c (1 month ago — within 6-month recall) → NOT due
        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES (1, %s, 'hba1c', 7.0, '%%',
                    now() - interval '1 month', 'clinic')
            ON CONFLICT DO NOTHING
        """, (recent_link_id,))

        # ── Patient 3: REDFLAG — HbA1c = 13 (>12 threshold) ─────────────────
        redflag_pat_id, redflag_link_id = _make_diabetic_patient(
            redflag_uuid, "FU0000003", "09000000003", "بیمارِ رَدفلَگ"
        )
        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES (1, %s, 'hba1c', 13.0, '%%',
                    now() - interval '1 day', 'clinic')
            ON CONFLICT DO NOTHING
        """, (redflag_link_id,))

    return {
        **seed_clinical_data,
        "due_link_id":      due_link_id,
        "recent_link_id":   recent_link_id,
        "redflag_link_id":  redflag_link_id,
        "due_pat_id":       due_pat_id,
        "recent_pat_id":    recent_pat_id,
        "redflag_pat_id":   redflag_pat_id,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_due_clinical_events_returns_monitoring_for_due_patient(seed_followup_data):
    """
    due_clinical_events for a patient with stale HbA1c (8 months ago)
    must include the T2-MON-A1C-TEST monitoring rule.
    """
    from clinical.followup_engine import due_clinical_events

    pid = seed_followup_data["due_link_id"]
    events = due_clinical_events(pid, tenant_id=1)

    monitoring_codes = {e["rule_code"] for e in events if e["action"] != "redflag"}
    assert "T2-MON-A1C-TEST" in monitoring_codes, (
        f"T2-MON-A1C-TEST must be due (HbA1c last done 8 months ago, recall=6m). "
        f"Events: {events}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_generate_creates_task_for_due_patient(seed_followup_data):
    """
    generate_for_patient for a patient with due monitoring creates a followup_task
    with reason='monitoring' and source_rule='T2-MON-A1C-TEST'.
    """
    from clinical.followup_engine import generate_for_patient
    from clinical.models import FollowupTask

    pid = seed_followup_data["due_link_id"]

    # Clean any tasks from previous runs in this session
    FollowupTask.objects.filter(
        tenant_id=1, patient_link_id=pid, source_rule="T2-MON-A1C-TEST"
    ).delete()

    count = generate_for_patient(pid, tenant_id=1)

    assert count >= 1, f"Expected at least 1 task created, got {count}"

    task = FollowupTask.objects.filter(
        tenant_id=1,
        patient_link_id=pid,
        source_rule="T2-MON-A1C-TEST",
        status="open",
    ).first()

    assert task is not None, "FollowupTask with source_rule='T2-MON-A1C-TEST' must exist"
    assert task.reason == "monitoring", (
        f"reason must be 'monitoring', got {task.reason!r}"
    )
    assert task.detail == _MONITORING_RULE["title"], (
        f"detail must match rule title, got {task.detail!r}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_no_task_for_recently_done_item(seed_followup_data):
    """
    A patient with HbA1c 1 month ago (within 6-month recall window) must NOT
    receive a T2-MON-A1C-TEST task.
    """
    from clinical.followup_engine import due_clinical_events

    pid = seed_followup_data["recent_link_id"]
    events = due_clinical_events(pid, tenant_id=1)

    a1c_due = any(
        e["rule_code"] == "T2-MON-A1C-TEST"
        for e in events
        if e["action"] != "redflag"
    )
    assert not a1c_due, (
        "T2-MON-A1C-TEST must NOT be due — HbA1c was done 1 month ago (recall=6m)."
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_no_generate_task_for_recently_done_item(seed_followup_data):
    """
    generate_for_patient for a patient with recent HbA1c must create 0 tasks
    for the A1c monitoring rule.
    """
    from clinical.followup_engine import generate_for_patient
    from clinical.models import FollowupTask

    pid = seed_followup_data["recent_link_id"]

    # Clean any pre-existing tasks
    FollowupTask.objects.filter(
        tenant_id=1, patient_link_id=pid, source_rule="T2-MON-A1C-TEST"
    ).delete()

    count = generate_for_patient(pid, tenant_id=1)

    # The patient may have OTHER due rules fired (not the A1c monitoring one)
    # but specifically no T2-MON-A1C-TEST task should be created
    a1c_task = FollowupTask.objects.filter(
        tenant_id=1,
        patient_link_id=pid,
        source_rule="T2-MON-A1C-TEST",
    ).first()
    assert a1c_task is None, (
        "No T2-MON-A1C-TEST task should be created for patient with recent HbA1c."
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_redflag_does_not_create_worklist_task(seed_followup_data):
    """
    A redflag rule (action_type='redflag') must NOT create a followup_task.
    Redflags surface in the patient panel, not the worklist.
    """
    from clinical.followup_engine import generate_for_patient, due_clinical_events
    from clinical.models import FollowupTask

    pid = seed_followup_data["redflag_link_id"]

    # Clean any pre-existing tasks
    FollowupTask.objects.filter(tenant_id=1, patient_link_id=pid).delete()

    # Verify the redflag DOES appear in due_clinical_events (with action='redflag')
    events = due_clinical_events(pid, tenant_id=1)
    redflag_events = [e for e in events if e["action"] == "redflag"]
    assert any(e["rule_code"] == "T2-REDFLAG-HYPER-TEST" for e in redflag_events), (
        "T2-REDFLAG-HYPER-TEST must appear in due_clinical_events with action='redflag'"
    )

    # generate_for_patient must not create a task for this redflag
    generate_for_patient(pid, tenant_id=1)

    redflag_task = FollowupTask.objects.filter(
        tenant_id=1,
        patient_link_id=pid,
        source_rule="T2-REDFLAG-HYPER-TEST",
    ).first()
    assert redflag_task is None, (
        "Redflag rule must NOT create a followup_task (panel only, not worklist)."
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_generate_is_idempotent(seed_followup_data):
    """
    Running generate_for_patient twice for the same patient must not duplicate tasks.
    Second run should create 0 new tasks (open task for the same source_rule blocks).
    """
    from clinical.followup_engine import generate_for_patient
    from clinical.models import FollowupTask

    pid = seed_followup_data["due_link_id"]

    # Clean up all tasks to start fresh
    FollowupTask.objects.filter(tenant_id=1, patient_link_id=pid).delete()

    count1 = generate_for_patient(pid, tenant_id=1)
    count2 = generate_for_patient(pid, tenant_id=1)

    assert count2 == 0, (
        f"Second run must create 0 tasks (idempotent). "
        f"First run created {count1}, second run created {count2}."
    )

    # Total task count after two runs must equal the first run's count
    total_tasks = FollowupTask.objects.filter(
        tenant_id=1, patient_link_id=pid, source_rule="T2-MON-A1C-TEST"
    ).count()
    assert total_tasks == 1, (
        f"Exactly 1 T2-MON-A1C-TEST task expected after 2 idempotent runs, "
        f"got {total_tasks}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_generate_all_creates_tasks_for_all_active_patients(seed_followup_data):
    """
    generate_all for tenant-1 must create tasks for all active patients with due items.
    The due patient (due_link_id) must get a task; the recent patient must not
    get a T2-MON-A1C-TEST task.
    """
    from clinical.followup_engine import generate_all
    from clinical.models import FollowupTask

    # Clean up to start fresh
    FollowupTask.objects.filter(
        tenant_id=1,
        source_rule="T2-MON-A1C-TEST",
    ).delete()

    total = generate_all(tenant_id=1)
    assert total >= 1, f"generate_all must create at least 1 task, got {total}"

    # Due patient must have the task
    due_task = FollowupTask.objects.filter(
        tenant_id=1,
        patient_link_id=seed_followup_data["due_link_id"],
        source_rule="T2-MON-A1C-TEST",
        status="open",
    ).first()
    assert due_task is not None, "due patient must have a T2-MON-A1C-TEST task"

    # Recent patient must NOT have the A1c monitoring task
    recent_task = FollowupTask.objects.filter(
        tenant_id=1,
        patient_link_id=seed_followup_data["recent_link_id"],
        source_rule="T2-MON-A1C-TEST",
    ).first()
    assert recent_task is None, (
        "recent patient must NOT have a T2-MON-A1C-TEST task (HbA1c done 1m ago)"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_tenant_isolation_generate_all(seed_followup_data):
    """
    generate_all(tenant_id=1) must NOT create tasks for tenant-2 patients.
    Resolves the tenant-2 link from DB using tenant2_patient_id (available in
    seed_followup_data via the seed_clinical_data chain).
    """
    from clinical.followup_engine import generate_all
    from clinical.models import FollowupTask, PatientLink

    tenant2_patient_id = seed_followup_data.get("tenant2_patient_id")
    if not tenant2_patient_id:
        pytest.skip("tenant2_patient_id not available in seed_followup_data")

    # Resolve the tenant-2 link_id from the ORM
    t2_link = PatientLink.objects.filter(
        tenant_id=2, patient_id=tenant2_patient_id
    ).values_list("id", flat=True).first()
    if not t2_link:
        pytest.skip("Tenant-2 PatientLink not found in DB")

    # Clean up
    FollowupTask.objects.filter(tenant_id=2, patient_link_id=t2_link).delete()

    generate_all(tenant_id=1)

    t2_tasks = FollowupTask.objects.filter(
        tenant_id=2, patient_link_id=t2_link
    ).count()
    assert t2_tasks == 0, (
        f"generate_all(tenant=1) must not create tasks for tenant-2 patients, "
        f"found {t2_tasks}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_uses_evaluate_for_patient_not_raw_engine(seed_followup_data, monkeypatch):
    """
    Confirms due_clinical_events uses suggestion_service.evaluate_for_patient
    (the Step 6 demographics bridge) instead of rule_engine.evaluate directly.

    Mechanism: monkeypatch clinical.followup_engine._engine_evaluate to record
    calls, then call due_clinical_events and verify our patched function was used.
    """
    import clinical.followup_engine as fe

    calls = []

    original = fe._engine_evaluate

    def recording_evaluate(pid, tenant_id):
        calls.append({"pid": pid, "tenant_id": tenant_id})
        return original(pid, tenant_id)

    monkeypatch.setattr(fe, "_engine_evaluate", recording_evaluate)

    pid = seed_followup_data["due_link_id"]
    fe.due_clinical_events(pid, tenant_id=1)

    assert len(calls) >= 1, (
        "due_clinical_events must call _engine_evaluate "
        "(bound to suggestion_service.evaluate_for_patient)"
    )
    assert calls[0]["pid"] == pid
    assert calls[0]["tenant_id"] == 1

    # Verify the bound name matches evaluate_for_patient from suggestion_service
    from clinical.suggestion_service import evaluate_for_patient as canonical
    # After monkeypatching, original holds the pre-patch value — assert it matches
    assert original is canonical, (
        "clinical.followup_engine._engine_evaluate must be "
        "suggestion_service.evaluate_for_patient, not rule_engine.evaluate"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_due_events_event_structure(seed_followup_data):
    """
    Each event from due_clinical_events must have the expected fields:
    action, rule_code, title, item, months.
    """
    from clinical.followup_engine import due_clinical_events

    pid = seed_followup_data["due_link_id"]
    events = due_clinical_events(pid, tenant_id=1)

    assert isinstance(events, list)
    for ev in events:
        assert "action" in ev, f"Missing 'action' in event: {ev}"
        assert "rule_code" in ev, f"Missing 'rule_code' in event: {ev}"
        assert "title" in ev, f"Missing 'title' in event: {ev}"
        assert "item" in ev, f"Missing 'item' in event: {ev}"
        assert "months" in ev, f"Missing 'months' in event: {ev}"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_audit_log_created_per_task(seed_followup_data):
    """
    Each task created by generate_for_patient must produce one audit row
    with action_type='followup_generated'.
    """
    from clinical.followup_engine import generate_for_patient
    from clinical.models import FollowupTask, ActivityLog

    pid = seed_followup_data["due_link_id"]

    # Clean up
    FollowupTask.objects.filter(
        tenant_id=1, patient_link_id=pid, source_rule="T2-MON-A1C-TEST"
    ).delete()

    before_count = ActivityLog.objects.filter(
        tenant_id=1,
        patient_link_id=pid,
        action_type="followup_generated",
    ).count()

    count = generate_for_patient(pid, tenant_id=1)
    if count == 0:
        pytest.skip("No tasks created — cannot test audit log (no due items)")

    after_count = ActivityLog.objects.filter(
        tenant_id=1,
        patient_link_id=pid,
        action_type="followup_generated",
    ).count()

    assert after_count == before_count + count, (
        f"Expected {before_count + count} audit rows, got {after_count}. "
        f"{count} tasks created."
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_generate_followups_command_sets_guc_and_creates_tasks(seed_followup_data):
    """
    Step-51 follow-up: the generate_followups COMMAND must set the tenant GUC per
    tenant before calling generate_all (production RLS fail-closed → zero rows
    otherwise). Run via call_command (explicit --tenant-id) and assert the due
    patient gets its task — proving the command path (GUC set/clear + generate_all)
    works, not just the engine called directly.
    """
    from io import StringIO
    from django.core.management import call_command
    from clinical.models import FollowupTask

    FollowupTask.objects.filter(
        tenant_id=1, source_rule="T2-MON-A1C-TEST"
    ).delete()

    out = StringIO()
    # explicit tenant-id 1 (all-tenant discovery needs tenant fixtures; the GUC
    # set/clear path is identical either way).
    call_command("generate_followups", "--tenant-id", "1", stdout=out)

    # The command clears the tenant GUC in finally (correct production behavior);
    # re-establish it so this RLS-scoped ORM assertion can read (the autouse
    # fixture's ambient GUC=1 was wiped by the command's clear). Proves clear() ran.
    from platform_core.tenant_context import set_tenant_guc
    set_tenant_guc(1)

    due_task = FollowupTask.objects.filter(
        tenant_id=1,
        patient_link_id=seed_followup_data["due_link_id"],
        source_rule="T2-MON-A1C-TEST",
        status="open",
    ).first()
    assert due_task is not None, (
        "generate_followups command (with per-tenant GUC) must create the due "
        "patient's task; got none — GUC/command wiring broken."
    )
    assert "Done." in out.getvalue()
