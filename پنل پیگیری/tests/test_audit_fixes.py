"""Gaps found in the pre-pilot audit: G12 (needs_review), P-8, edit restore, custom suture date, G4 counting."""
from __future__ import annotations

from datetime import date

import pytest

from src.common.jalali import jalali_date, jalali_month_start
from src.services import calls, encounters, journeys
from test_returns import env  # noqa: F401  (fixture)


# ------------------------------------------------------------------ G12: origin visit deleted
def test_deleted_origin_visit_sends_journeys_to_review_and_stops_calls(env):
    iid, vid = env.origin({"lab_order": True, "renewal_months": 1})
    env.rec.delete_item(iid, "visit", vid)
    env.poller.step()
    assert {s for _, s, _ in env.q("SELECT id, status, close_reason FROM journey")} == {"needs_review"}
    assert env.q("SELECT status FROM encounter") == [("source_deleted",)]
    env.goto(3)                                                        # lab_check came due on day 2
    lists = calls.worklists(env.conn, env.now)
    assert lists["today"] == [] and lists["overdue"] == []             # no calls while waiting for a decision
    assert {r["title"] for r in journeys.review_rows(env.conn, 1, viewer_staff_id=1)} == {"پیگیری جواب آزمایش", "تمدید نسخه"}
    assert journeys.review_rows(env.conn, 2, viewer_staff_id=2) == []  # another doctor sees none of them


def test_review_keep_resumes_and_is_not_flagged_again(env):
    iid, vid = env.origin({"lab_order": True})
    env.rec.delete_item(iid, "visit", vid)
    env.poller.step()
    jid = env.journey("lab_order")[0]
    msg = journeys.review(env.conn, jid, True, role="doctor", staff_id=1, is_director=False,
                          actor="doctor:dr", now=env.now)
    assert "ادامه" in msg and env.journey("lab_order")[1] == "active"
    env.rec.set_paid(iid, "injection", env.rec.add_injection(iid, 1, "تزریق"))   # the invoice changes again
    env.poller.step()
    assert env.journey("lab_order")[1] == "active"                     # one decision per deleted visit
    env.goto(2)
    assert [c["purpose"] for c in calls.worklists(env.conn, env.now)["today"]] == ["lab_check"]


def test_review_cancel_and_permissions(env):
    iid, vid = env.origin({"lab_order": True})
    env.rec.delete_item(iid, "visit", vid)
    env.poller.step()
    jid = env.journey("lab_order")[0]
    with pytest.raises(journeys.JourneyError, match="فقط پزشکی"):
        journeys.review(env.conn, jid, False, role="doctor", staff_id=2, is_director=False, actor="doctor:x", now=env.now)
    journeys.review(env.conn, jid, False, role="manager", staff_id=None, is_director=False, actor="acc:boss", now=env.now)
    assert env.journey("lab_order")[1:] == ("cancelled", "manual")
    with pytest.raises(journeys.JourneyError, match="دیگر نیازمند بررسی نیست"):
        journeys.review(env.conn, jid, True, role="manager", staff_id=None, is_director=False, actor="acc:boss",
                        now=env.now)


def test_deleted_visit_without_panel_or_closed_journey_is_untouched(env):
    iid, vid = env.origin({"lab_order": True})
    env.come_back(4)                                                   # lab journey succeeds
    env.rec.delete_item(iid, "visit", vid)
    env.poller.step()
    assert env.journey("lab_order")[1] == "succeeded"


# ------------------------------------------------------------------ P-8
def test_ear_norx_return_reminds_the_doctor(env):
    env.origin({"ear_wax": "norx"})
    first = encounters.panel(env.conn, env.q("SELECT acc_visit_id FROM encounter")[0][0], 1, env.day(0))
    assert first["ear_drop_return"] is False                           # not on the visit that created it
    iid, vid = env.come_back(5, doctor=1)                              # return visit closes the journey
    assert env.journey("ear_wax_norx")[1] == "succeeded"
    assert encounters.panel(env.conn, vid, 1, env.day(5))["ear_drop_return"] is True


# ------------------------------------------------------------------ edit restores the saved choices
def test_panel_returns_saved_parameters_for_edit(env):
    _, vid = env.origin({"renewal_months": 2, "series_bp": {"count": 4, "every_days": 2}, "ear_wax": "rx",
                         "wound": {"suture_day": 12, "dressing_every": 0}, "note": "یادداشت",
                         "bp": {"systolic": 150, "diastolic": 95}})
    enc = encounters.panel(env.conn, vid, 1, env.day(0))["encounter"]
    choices = {c["code"]: c for c in enc["choices"]}
    assert choices["renewal"]["params"]["interval_months"] == 2
    assert choices["control_series_bp"]["params"] == {"count": 4, "every_days": 2}
    assert "ear_wax_rx" in choices
    assert choices["wound_care"]["suture_date_fa"] == jalali_date(env.day(12))
    assert enc["note"] == "یادداشت"
    assert enc["measurements"] == [{"kind": "bp", "systolic": 150, "diastolic": 95, "glucose": None,
                                    "glucose_type": None}]


def test_custom_suture_date_from_calendar(env):
    _, vid = env.origin({"lab_order": True})
    encounters.save(env.conn, vid, {"decision": "followup", "wound": {
        "suture_day": None, "suture_date_fa": jalali_date(env.day(9)), "dressing_every": 3}},
        staff_id=1, actor="doctor:dr", now=env.now)
    assert env.q("SELECT params FROM journey WHERE template_code = 'wound_care'") == [
        ('{"dressing_every": 3, "suture_day": 9}',)]
    with pytest.raises(encounters.EncounterError, match="۲ تا ۳۰ روز"):
        encounters.save(env.conn, vid, {"decision": "followup", "wound": {
            "suture_day": None, "suture_date_fa": jalali_date(env.day(40)), "dressing_every": 0}},
            staff_id=1, actor="doctor:dr", now=env.now)


# ------------------------------------------------------------------ G4 counts unanswered calls only
def test_lab_not_done_answers_do_not_count_as_no_answer(env):
    env.origin({"lab_order": True})
    env.goto(2)
    env.outcome(env.call("lab_order"), "lab_not_done")                 # answered: «not yet»
    env.goto(5)
    env.outcome(env.call("lab_order"), "lab_not_done")
    env.goto(8)
    row = calls.worklists(env.conn, env.now)["today"][0]
    assert row["no_answers"] == 0
    env.outcome(env.call("lab_order"), "no_answer")                    # first unanswered call
    assert env.journey("lab_order")[1] == "active"


# ------------------------------------------------------------------ Jalali month
def test_jalali_month_start():
    assert jalali_month_start(date(2026, 10, 6)) == date(2026, 9, 23)        # ۱۴ مهر → ۱ مهر ۱۴۰۵
    assert jalali_month_start(date(2026, 9, 23)) == date(2026, 9, 23)
    assert jalali_month_start(date(2026, 3, 20)) == date(2026, 2, 20)        # ۲۹ اسفند ۱۴۰۴ → ۱ اسفند
