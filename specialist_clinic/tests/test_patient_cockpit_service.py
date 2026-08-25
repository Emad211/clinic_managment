from src.services.patient_cockpit_service import PatientCockpitService


def test_next_action_uses_clinical_priority_order():
    result = PatientCockpitService.next_action(
        clinical_v2={"groups": [{"action_type": "redflag", "items": [{"rule_code": "R1"}]}]},
        followups=[{"status": "open", "reason": "refill"}],
        refill_due=2,
        appointments=[{"status": "scheduled", "scheduled_at": "2026-07-23"}],
        indicators=[{"latest": 7.2}],
    )
    assert result["tone"] == "danger"
    assert result["target"] == "cockpit"


def test_next_action_chooses_earliest_open_followup():
    result = PatientCockpitService.next_action(
        clinical_support={"sections": []},
        followups=[
            {"status": "open", "reason": "manual", "due_date": "2026-08-01"},
            {"status": "open", "reason": "refill", "due_date": "2026-07-22"},
        ],
        refill_due=0, appointments=[], indicators=[{"latest": 1}],
    )
    assert result["target"] == "worklist"
    assert result["date"] == "2026-07-22"
    assert result["detail"] == "تجدید نسخه"


def test_next_action_accepts_v2_projection_without_double_counting_priority():
    result = PatientCockpitService.next_action(
        clinical_support={"sections": [{"key": "redflags", "rules": [{"id": 1}]}]},
        clinical_v2={"groups": [
            {"action_type": "redflag", "items": [{"rule_code": "R1"}]},
            {"action_type": "suggest_med", "items": [{"rule_code": "M1"}]},
        ]},
        followups=[], refill_due=0, appointments=[], indicators=[{"latest": 1}],
    )
    assert result["tone"] == "danger"
    assert result["detail"].startswith("1 هشدار")


def test_retired_v1_projection_cannot_influence_priority():
    # The retired V1 clinical_support projection must create NO clinical priority.
    # With no V2 analysis present, the surface falls through to the neutral
    # "no clinical assessment" frame — never a V1 red flag, and never a green
    # all-clear that would falsely imply the engine ran.
    result = PatientCockpitService.next_action(
        clinical_support={"sections": [{"key": "redflags", "rules": [{"id": 1}]}]},
        followups=[], refill_due=0, appointments=[], indicators=[{"latest": 1}],
    )
    assert result["tone"] != "danger"  # the retired V1 redflag raised no priority
    assert result["tone"] == "info"
    assert result["title"] == "بدون ارزیابی بالینی"


def test_next_action_only_counts_unreviewed_or_deferred_v2_actions():
    result = PatientCockpitService.next_action(
        clinical_support={"sections": []},
        clinical_v2={"groups": [{
            "action_type": "suggest_med",
            "items": [
                {"rule_code": "A", "current_decision": {"decision": "ACCEPTED"}},
                {"rule_code": "D", "current_decision": {"decision": "DISMISSED"}},
                {"rule_code": "L", "current_decision": {"decision": "DEFERRED"}},
            ],
        }]},
        followups=[], refill_due=0, appointments=[], indicators=[{"latest": 1}],
    )
    assert result["tone"] == "warn"
    assert result["detail"].startswith("1 پیشنهاد")


def test_next_action_does_not_call_completed_v2_review_unreviewed():
    # A safety_alert already ACCEPTED must NOT be counted as unreviewed. With the
    # engine's current run present (current=True) and nothing else pending, the
    # green clearance is legitimate and preserved.
    result = PatientCockpitService.next_action(
        clinical_support={"sections": []},
        clinical_v2={"current": True, "groups": [{
            "action_type": "safety_alert",
            "items": [{"current_decision": {"decision": "ACCEPTED"}}],
        }]},
        followups=[], refill_due=0, appointments=[], indicators=[{"latest": 1}],
    )
    assert result["tone"] == "ok"
    assert result["title"] == "کار اداری باز ثبت نشده"


def test_timeline_merges_completed_appointment_with_same_day_visit_and_sorts():
    events = PatientCockpitService.timeline(
        appointments=[
            {"scheduled_at": "2026-07-20 09:00", "status": "done", "appt_type": "ویزیت"},
            {"scheduled_at": "2026-08-01 09:00", "status": "scheduled", "appt_type": "کنترل"},
        ],
        visits=[{"visit_date": "2026-07-20", "doctor_name": "دکتر تست"}],
        labs=[{"taken_at": "2026-07-21", "test_name": "HbA1c", "value": 7.2, "unit": "%"}],
        followups=[], medication_events=[],
    )
    assert [event["kind"] for event in events] == ["appointment", "lab", "visit"]
    assert sum(event["kind"] == "visit" for event in events) == 1
    assert sum(event["title"] == "نوبت انجام‌شده" for event in events) == 0


def test_timeline_respects_limit_and_omits_undated_events():
    events = PatientCockpitService.timeline(
        appointments=[], visits=[], labs=[],
        followups=[
            {"status": "open", "due_date": "2026-07-22", "reason": "manual"},
            {"status": "open", "due_date": None, "created_at": None, "reason": "manual"},
        ],
        medication_events=[{"event_type": "start", "event_date": "2026-07-21", "drug_name": "متفورمین"}],
        limit=1,
    )
    assert len(events) == 1
    assert events[0]["kind"] == "followup"
