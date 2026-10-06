"""Journey templates (docs/05 §5, §7) and the pure state machine (§2, §3)."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.domain import journey_rules as R
from src.domain.templates import TemplateError, evaluate, parse_template, plan

JOURNEYS = Path(__file__).resolve().parents[1] / "journeys"
D0 = date(2026, 10, 6)


def load(code):
    return parse_template(json.loads((JOURNEYS / f"{code}.json").read_text(encoding="utf-8")))


def days(steps):
    return [(s.kind, s.purpose if s.kind == "call" else s.category, (s.due_date - D0).days,
             None if s.window_end is None else (s.window_end - D0).days) for s in steps]


# ------------------------------------------------------------------ expressions
def test_expressions_are_safe_and_exact():
    assert evaluate("max(1, {d} - 10)", {"d": 30}) == 20
    assert evaluate("max(1, {d} - 10)", {"d": 5}) == 1
    assert evaluate("{a} * 30 + -2", {"a": 2}) == 58
    for bad in ("__import__('os')", "{a}.real", "2 ** 8", "[1][0]", "open('x')", "1 / 2"):
        with pytest.raises(TemplateError):
            evaluate(bad, {"a": 1})
    with pytest.raises(TemplateError, match="must be an integer"):
        evaluate("{a} + 1", {"a": "1; drop"})


def test_all_shipped_templates_parse():
    codes = sorted(p.stem for p in JOURNEYS.glob("*.json") if p.stem != "call_texts")
    assert codes == ["control_series_bp", "control_series_bs", "ear_wax_norx", "ear_wax_rx", "invite_visit",
                     "lab_order", "quarterly_lab", "renewal", "respiratory", "wound_care"]
    for code in codes:
        assert load(code).code == code
    assert load("respiratory").enabled is False                  # D25


@pytest.mark.parametrize("raw,msg", [
    ({"code": "x_y", "title": "t", "steps": [{"kind": "call", "day": 1, "purpose": "p"}]}, "at least one expect"),
    ({"code": "x_y", "title": "t", "steps": [{"kind": "expect", "category": "visit", "day": 1}]}, "exactly one"),
    ({"code": "x_y", "title": "t", "steps": [{"kind": "expect", "category": "spa", "day": 1, "end": 2}]}, "category"),
    ({"code": "x_y", "title": "t", "steps": [{"kind": "expect", "category": "visit", "day": "os.system()",
                                             "end": 2}]}, "unsupported"),
    ({"code": "x_y", "title": "t", "steps": [{"kind": "expect", "category": "visit", "day": 1, "end": 2,
                                             "evil": 1}]}, "unknown keys"),
    ({"code": "X", "title": "t", "steps": []}, "bad template code"),
])
def test_bad_templates_are_rejected(raw, msg):
    with pytest.raises(TemplateError, match=msg):
        parse_template(raw)


# ------------------------------------------------------------------ §5 schedules
def test_renewal_two_months():                                        # §5-1
    assert days(plan(load("renewal"), {"interval_months": 2, "due_day": 60}, D0)) == [
        ("expect", "visit", 1, 90), ("call", "renewal_reminder", 50, None)]


def test_renewal_reminder_never_before_day_one():
    assert days(plan(load("renewal"), {"due_day": 7}, D0))[0] == ("call", "renewal_reminder", 1, None)


def test_renewal_requires_due_day():
    with pytest.raises(TemplateError, match="due_day"):
        plan(load("renewal"), {}, D0)


def test_quarterly_lab():                                             # §5-2
    assert days(plan(load("quarterly_lab"), {}, D0)) == [("expect", "visit", 1, 120),
                                                         ("call", "quarterly_lab_reminder", 87, None)]


def test_control_series_default_and_edited():                         # §5-3, A15
    assert days(plan(load("control_series_bp"), {}, D0)) == [
        ("expect", "bp_check", 1, 1), ("expect", "bp_check", 2, 2), ("expect", "bp_check", 3, 3)]
    assert days(plan(load("control_series_bs"), {"count": 2, "every_days": 3}, D0)) == [
        ("expect", "bs_test", 3, 3), ("expect", "bs_test", 6, 6)]


def test_lab_order():                                                 # §5-4
    assert days(plan(load("lab_order"), {}, D0)) == [("expect", "visit", 1, 30), ("call", "lab_check", 2, None)]


def test_wound_care():                                                # §5-5
    assert days(plan(load("wound_care"), {"suture_day": 7, "dressing_every": 2}, D0)) == [
        ("expect", "dressing", 2, 3), ("expect", "dressing", 4, 5), ("expect", "dressing", 6, 7),
        ("expect", "suture_removal", 7, 10)]
    assert days(plan(load("wound_care"), {"suture_day": 10, "dressing_every": 0}, D0)) == [
        ("expect", "suture_removal", 10, 13)]                         # «ندارد»
    with pytest.raises(TemplateError, match="suture_day"):
        plan(load("wound_care"), {"dressing_every": 1}, D0)          # A11: no default


def test_ear_wax():                                                   # §5-6, §5-7
    assert days(plan(load("ear_wax_rx"), {}, D0)) == [("call", "ear_wash_reminder", 3, None),
                                                      ("expect", "ear_irrigation", 4, 14)]
    t = load("ear_wax_norx")
    assert days(plan(t, {}, D0)) == [("call", "ear_invite_visit", 1, None), ("expect", "visit", 1, 21)]
    assert t.refused_rule() == {"retry_days": 3, "max": 3} and load("ear_wax_rx").refused_rule() is None


def test_invite_visit():                                              # §5-9, A10
    assert days(plan(load("invite_visit"), {}, D0)) == [("call", "invite_visit", 1, None), ("expect", "visit", 1, 14)]


# ------------------------------------------------------------------ state machine
def mk(planned, statuses=None):
    statuses = statuses or {}
    return [R.Step(i, p.seq, p.kind, p.due_date, p.window_end, p.category, p.purpose,
                   statuses.get(p.seq, "pending"), 0, p.accept_early, p.recall_on_miss, p.completes)
            for i, p in enumerate(planned, start=100)]


def run_days(journey, steps, until):
    """Apply tick day by day, like the engine does; returns the journey status per day."""
    history = []
    for n in range(1, until + 1):
        ch = R.tick(journey, steps, D0 + timedelta(days=n))
        for s in steps:
            s.status = ch.step_status.get(s.id, s.status)
        for c in ch.new_calls:
            steps.append(R.Step(900 + len(steps), 99, "call", c.due_date, None, None, c.purpose, "pending"))
        if ch.journey_status:
            journey.status = ch.journey_status
        history.append(journey.status)
    return history


def J():
    return R.Journey(1, "active", D0, D0)


def test_series_all_missed_fails_expired_after_recalls_lapse():
    steps = mk(plan(load("control_series_bp"), {}, D0))
    j = J()
    run_days(j, steps, 3)
    assert [s.status for s in steps if s.kind == "expect"] == ["missed", "missed", "pending"]
    assert sum(1 for s in steps if s.purpose == "missed") == 2      # G7 recall for each miss
    run_days(j, steps, 40)
    assert j.status == "failed"                                      # recalls expired after 30 days (G6)


def test_series_partial_and_success():
    steps = mk(plan(load("control_series_bp"), {}, D0), {1: "done", 2: "missed", 3: "done"})
    ch = R.evaluate_completion(steps)
    assert ch.journey_status == "partial"
    steps = mk(plan(load("control_series_bp"), {}, D0), {1: "done", 2: "done", 3: "done"})
    assert R.evaluate_completion(steps).journey_status == "succeeded"


def test_wound_care_suture_completes_and_skips_remaining_dressings():
    steps = mk(plan(load("wound_care"), {"suture_day": 7, "dressing_every": 2}, D0), {1: "done", 4: "done"})
    ch = R.evaluate_completion(steps)
    assert ch.journey_status == "succeeded"
    assert {steps[1].id: "skipped", steps[2].id: "skipped"}.items() <= ch.step_status.items()


def test_pending_recall_keeps_journey_open():
    steps = mk(plan(load("ear_wax_rx"), {}, D0))
    j = J()
    run_days(j, steps, 15)
    assert j.status == "active" and any(s.purpose == "missed" and s.status == "pending" for s in steps)


def test_overdue_call_fails_after_thirty_days():                      # G6
    steps = mk(plan(load("renewal"), {"due_day": 60}, D0))         # call day 50, window open to day 90
    j = J()
    hist = run_days(j, steps, 85)
    assert hist[79] == "active" and hist[80] == "failed"            # day 81: 31 days overdue
    assert j.status == "failed" and all(s.status == "cancelled" for s in steps)


def test_window_end_without_return_and_without_recall_fails():
    steps = mk(plan(load("lab_order"), {}, D0))
    j = J()
    hist = run_days(j, steps, 31)
    assert hist[29] == "active" and hist[30] == "failed"            # window [1, 30] ends


def test_awaiting_identity_expires_after_thirty_days():              # G10
    steps = mk(plan(load("invite_visit"), {}, D0))
    j = R.Journey(1, "awaiting_identity", D0, D0)
    assert R.tick(j, steps, D0 + timedelta(days=29)).empty
    ch = R.tick(j, steps, D0 + timedelta(days=30))
    assert (ch.journey_status, ch.close_reason) == ("cancelled", "expired")
    assert set(ch.step_status.values()) == {"cancelled"}


def test_tick_is_idempotent():
    steps = mk(plan(load("control_series_bp"), {}, D0), {1: "missed"})
    j = J()
    first = R.tick(j, steps, D0 + timedelta(days=2))
    for s in steps:
        s.status = first.step_status.get(s.id, s.status)
    second = R.tick(j, steps, D0 + timedelta(days=2))
    assert second.empty or (not second.step_status and not second.new_calls)


def test_appointment_suggestions_follow_usual_schedule():
    from src.domain import schedule
    today = date(2026, 10, 6)                                         # a Tuesday
    rows = []
    for w in range(12):
        tue = today - timedelta(days=7 * (w + 1))
        rows.append((tue.isoformat(), "evening", 1))                  # doctor 1: every Tuesday evening
        if w % 3 == 0:
            rows.append(((tue + timedelta(days=1)).isoformat(), "morning", 1))   # 4/12 Wednesdays: not usual
        rows.append(((tue + timedelta(days=2)).isoformat(), "morning", 2))       # doctor 2: Thursdays
    assert schedule.usual_combos(rows, 1, today) == {(today.weekday(), "evening")}
    slots = schedule.suggest(rows, [1, 2, 1], today, days=7)
    assert [(s.day.isoformat(), s.shift, s.doctor_id) for s in slots] == [
        ("2026-10-06", "evening", 1), ("2026-10-08", "morning", 2)]
