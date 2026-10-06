"""M4 acceptance scenarios (docs/08 §1 M4): calls, return matching M1–M9, revocation, idempotency."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from accounting_factory import BP_CHECK_ID, Reception
from src.adapters.accounting.bridge import AccountingBridge
from src.adapters.sqlite import core
from src.common.jalali import jalali_date
from src.services import calls, encounters, journeys, returns
from src.services.bridge_monitor import BridgeMonitor
from src.sync.poller import Poller

D0 = date(2026, 10, 6)
NID, NID2 = "0499370899", "2170415981"
PHONE = "09121234567"


class Env:
    """Synthetic accounting + panel with a movable clock; poller wired to return detection like the app."""

    def __init__(self, tmp_path, acc_db):
        self.rec = Reception(acc_db)
        self.panel = tmp_path / "peygiri_panel.db"
        core.init_db(self.panel, tmp_path / "backups")
        self.now = datetime(2026, 10, 6, 10, 0)
        bridge = AccountingBridge(str(acc_db), budget_ms=200, busy_timeout_ms=250)
        assert BridgeMonitor(bridge).check_now().state == "ok"
        self.poller = Poller(bridge, self.panel, interval_seconds=1, clock=lambda: self.now,
                             on_events=lambda conn, ev: returns.on_poll_events(conn, ev, self.now))
        self.conn = core.connect(self.panel)
        journeys.ensure_templates(self.conn, "2026-10-06 09:00:00")
        self.poller.step()
        self.pid = None

    def day(self, n: int) -> str:
        return (D0 + timedelta(days=n)).isoformat()

    def goto(self, n: int, hour: int = 10) -> None:
        """Move the clock to day n and run the engine ticks for every day in between."""
        start = self.now.date()
        target = D0 + timedelta(days=n)
        d = start
        while d < target:
            d += timedelta(days=1)
            journeys.tick_all(self.conn, datetime.combine(d, datetime.min.time()).replace(hour=hour))
        self.now = datetime.combine(target, datetime.min.time()).replace(hour=hour)
        self.poller.step()

    def origin(self, form: dict, *, nid=NID, name="مریم", family="احمدی", phone=PHONE) -> tuple[int, int]:
        self.pid = self.rec.add_patient(name, family, nid, phone)
        iid = self.rec.open_invoice(self.pid, self.day(0), "morning")
        vid = self.rec.add_visit(iid, doctor_id=1, at=f"{self.day(0)} 09:00:00")
        self.poller.step()
        encounters.save(self.conn, vid, {"decision": "followup", **form}, staff_id=1, actor="doctor:dr", now=self.now)
        return iid, vid

    def come_back(self, n: int, *, kind="visit", paid=True, patient=None, close_total=None, doctor=2) -> tuple[int, int]:
        """Patient returns on day n: new invoice with one item, optionally paid/closed."""
        self.goto(n)
        iid = self.rec.open_invoice(patient or self.pid, self.day(n), "morning")
        if kind == "visit":
            item = self.rec.add_visit(iid, doctor_id=doctor)
        else:
            item = self.rec.add_injection(iid, BP_CHECK_ID, "کنترل فشار")
        if paid:
            self.rec.set_paid(iid, kind, item)
        if close_total is not None:
            self.rec.close_invoice(iid, close_total)
        self.poller.step()
        return iid, item

    def q(self, sql, *params):
        return [tuple(r) for r in self.conn.execute(sql, params).fetchall()]

    def journey(self, code):
        return self.q("SELECT id, status, close_reason FROM journey WHERE template_code = ? ORDER BY id DESC", code)[0]

    def call(self, code, purpose=None):
        rows = self.q("SELECT s.id FROM journey_step s JOIN journey j ON j.id = s.journey_id WHERE j.template_code = ? "
                      "AND s.kind = 'call' AND s.status = 'pending' AND (? IS NULL OR s.purpose = ?) ORDER BY s.id",
                      code, purpose, purpose)
        return rows[0][0]

    def outcome(self, step_id, outcome, **extra):
        return calls.record(self.conn, step_id, {"outcome": outcome, **extra}, actor="acc:reza", now=self.now)


@pytest.fixture
def env(tmp_path, acc_db):
    e = Env(tmp_path, acc_db)
    yield e
    e.conn.close()


# ------------------------------------------------------------------ returns
def test_early_return_counts_and_skips_reminder(env):
    env.origin({"renewal_months": 1})                                 # call day 20, visit window [1, 60], early ok
    env.come_back(12)
    jid, status = env.q("SELECT id, status FROM journey WHERE origin_kind = 'encounter'")[0]
    assert status == "succeeded"
    assert env.q("SELECT basis, matched_by, performer_staff_id, origin_doctor_staff_id FROM return_evidence") == [
        ("paid", "auto", 2, 1)]                                       # M8: any doctor counts, both recorded
    assert env.q("SELECT status FROM journey_step WHERE journey_id = ? AND kind = 'call'", jid) == [("skipped",)]
    # A1: next round starts from the return day, origin doctor = who performed the return
    assert env.q("SELECT start_date, origin_kind, origin_doctor_staff_id, status FROM journey "
                 "WHERE template_code = 'renewal' AND id <> ?", jid) == [(env.day(12), "continuation", 2, "active")]


def test_same_day_and_origin_invoice_never_count(env):
    iid, _ = env.origin({"lab_order": True})
    env.rec.set_paid(iid, "visit", env.q("SELECT acc_visit_id FROM encounter")[0][0])      # origin visit paid
    iid2 = env.rec.open_invoice(env.pid, env.day(0), "evening")                           # same day, other invoice
    env.rec.set_paid(iid2, "visit", env.rec.add_visit(iid2, doctor_id=1))
    env.poller.step()
    assert env.q("SELECT count(*) FROM return_evidence") == [(0,)]
    assert env.journey("lab_order")[1] == "active"


def test_unpaid_item_is_not_a_return_until_paid(env):
    env.origin({"lab_order": True})
    iid, vid = env.come_back(5, paid=False)
    assert env.journey("lab_order")[1] == "active"
    env.rec.set_paid(iid, "visit", vid)
    env.poller.step()
    assert env.journey("lab_order")[1] == "succeeded"


def test_zero_total_closed_invoice_counts(env):
    env.origin({"lab_order": True})
    env.come_back(4, paid=False, close_total=0)
    assert env.journey("lab_order")[1] == "succeeded"
    assert env.q("SELECT basis FROM return_evidence") == [("zero_total_closed",)]


def test_revoke_on_item_delete_reopens_and_cancels_continuation(env):
    env.origin({"renewal_months": 1})
    iid, vid = env.come_back(10)
    assert env.journey("renewal")[1] == "active"                      # the continuation is the newest
    env.rec.delete_item(iid, "visit", vid)
    env.poller.step()
    rows = env.q("SELECT origin_kind, status, close_reason FROM journey ORDER BY id")
    assert rows == [("encounter", "active", None), ("continuation", "cancelled", "manual")]
    assert env.q("SELECT revoke_reason FROM return_evidence") == [("item_deleted",)]
    assert env.q("SELECT status FROM journey_step WHERE kind = 'expect' AND journey_id = 1") == [("pending",)]


def test_revoke_on_payment_removed(env):
    env.origin({"lab_order": True})
    iid, vid = env.come_back(6)
    env.rec.set_paid(iid, "visit", vid, paid=False)
    env.poller.step()
    assert env.journey("lab_order")[1] == "active"
    assert env.q("SELECT revoke_reason FROM return_evidence") == [("payment_removed",)]
    env.rec.set_paid(iid, "visit", vid)                               # paid again → evidence again
    env.poller.step()
    assert env.journey("lab_order")[1] == "succeeded"
    assert env.q("SELECT count(*) FROM return_evidence WHERE revoked_at IS NULL") == [(1,)]


def test_partial_series(env):
    env.origin({"series_bp": {"count": 3, "every_days": 1}})
    env.come_back(1, kind="injection")
    env.goto(3)                                                       # day 2 missed
    env.come_back(3, kind="injection")
    jid, status, _ = env.journey("control_series_bp")
    assert status == "partial"
    assert env.q("SELECT status FROM journey_step WHERE journey_id = ? AND kind = 'expect' ORDER BY seq", jid) == [
        ("done",), ("missed",), ("done",)]


def test_duplicate_journey(env):
    env.origin({"lab_order": True})
    iid = env.rec.open_invoice(env.pid, env.day(0), "evening")
    vid = env.rec.add_visit(iid, doctor_id=1)
    env.poller.step()
    encounters.save(env.conn, vid, {"decision": "followup", "lab_order": True}, staff_id=1, actor="doctor:dr",
                    now=env.now)
    assert env.q("SELECT status, close_reason FROM journey ORDER BY id") == [("cancelled", "duplicate"), ("active", None)]


# ------------------------------------------------------------------ calls
def test_booked_then_no_show_then_return(env):
    env.origin({"lab_order": True})                                   # lab_check call on day 2
    env.goto(2)
    assert [c["purpose"] for c in calls.worklists(env.conn, env.now)["today"]] == ["lab_check"]
    msg = env.outcome(env.call("lab_order"), "booked", booked_date_fa=jalali_date(env.day(5)))
    assert "نوبت" in msg["message"]
    expect = env.q("SELECT due_date, window_end, purpose FROM journey_step WHERE kind = 'expect'")
    assert expect == [(env.day(5), env.day(30), "booked")]            # [booked, max(30, booked + 1)]
    env.goto(6)                                                       # did not come on day 5
    today = calls.worklists(env.conn, env.now)["today"]
    assert [c["purpose"] for c in today] == ["no_show"]
    env.come_back(7)
    assert env.journey("lab_order")[1] == "succeeded"
    assert env.q("SELECT status FROM journey_step WHERE purpose = 'no_show'") == [("skipped",)]


def test_three_no_answers_fail(env):
    env.origin({"lab_order": True})
    env.goto(2)
    for n in (2, 3, 4):
        if n > 2:
            env.goto(n)
        assert calls.worklists(env.conn, env.now)["today"], f"call missing on day {n}"
        env.outcome(env.call("lab_order"), "no_answer")
    assert env.journey("lab_order")[1:] == ("failed", "unreachable")


def test_refused_closes_normal_journey(env):
    env.origin({"lab_order": True})
    env.goto(2)
    env.outcome(env.call("lab_order"), "refused")
    assert env.journey("lab_order")[1:] == ("failed", "refused")


def test_ear_wax_norx_refused_retries_three_times(env):
    env.origin({"ear_wax": "norx"})
    env.goto(1)
    for n in (1, 4, 7):
        if n > 1:
            env.goto(n)
        assert env.journey("ear_wax_norx")[1] == "active"
        env.outcome(env.call("ear_wax_norx"), "refused")
    assert env.journey("ear_wax_norx")[1:] == ("failed", "refused")


def test_lab_not_done_three_times(env):
    env.origin({"lab_order": True})
    env.goto(2)
    for n in (2, 5, 8):
        if n > 2:
            env.goto(n)
        env.outcome(env.call("lab_order"), "lab_not_done")
    assert env.journey("lab_order")[1:] == ("failed", "lab_not_done")


def test_call_validation(env):
    env.origin({"ear_wax": "rx", "renewal_months": 1})
    env.goto(3)
    step = env.call("ear_wax_rx")
    with pytest.raises(calls.CallError, match="فقط برای پیگیری جواب آزمایش"):
        env.outcome(step, "lab_not_done")
    with pytest.raises(calls.CallError, match="گذشته"):
        env.outcome(step, "booked", booked_date_fa=jalali_date(env.day(1)))
    with pytest.raises(calls.CallError, match="هنوز نرسیده"):
        env.outcome(env.call("renewal"), "no_answer")                  # due on day 20
    assert env.q("SELECT count(*) FROM call_attempt") == [(0,)]


def test_overdue_list_and_call_text(env):
    env.origin({"renewal_months": 1})
    env.goto(23)
    lists = calls.worklists(env.conn, env.now)
    assert lists["today"] == [] and len(lists["overdue"]) == 1
    row = lists["overdue"][0]
    assert row["days_late"] == 3 and row["reason"] == "یادآوری تمدید نسخه"
    assert jalali_date(env.day(30)) in row["text"] and row["mobile"] == PHONE


# ------------------------------------------------------------------ anonymous invoices (M9)
def test_anonymous_return_then_identity_completion_matches(env):
    env.origin({"lab_order": True})
    other = env.rec.add_patient("خ", "احمدی", None, None)           # same person, duplicate placeholder file
    env.come_back(5, patient=other)
    assert env.journey("lab_order")[1] == "active"                    # not known yet
    # reception completes the identity in the panel → the file is linked to the existing person (M2)
    from src.services import identity
    person = env.q("SELECT id FROM person WHERE national_id = ?", NID)[0][0]
    with core.transaction(env.conn):
        identity.link_patient(env.conn, other, person, "manual", "acc:reza", env.now.strftime("%Y-%m-%d %H:%M:%S"))
    assert env.journey("lab_order")[1] == "succeeded"
    assert env.q("SELECT matched_by FROM return_evidence") == [("reception",)]


def test_mobile_suggestion_and_manual_link(env):
    env.origin({"lab_order": True})
    anon = env.rec.add_patient("ا", "ناشناس", None, PHONE)
    iid, _ = env.come_back(5, patient=anon)
    sugg = calls.worklists(env.conn, env.now)["suggestions"]
    assert [(s["invoice_id"], s["person_mobile"]) for s in sugg] == [(iid, PHONE)]
    calls.decide_suggestion(env.conn, sugg[0]["id"], True, actor="acc:reza", now=env.now)
    assert env.journey("lab_order")[1] == "succeeded"
    assert env.q("SELECT matched_by FROM return_evidence") == [("reception",)]

    # manual link from «انتظار امروز»
    env.origin({"lab_order": True}, nid=NID2, name="علی", family="رضایی", phone="09350000000")
    person = env.q("SELECT id FROM person WHERE national_id = ?", NID2)[0][0]
    stranger = env.rec.add_patient("ب", "ب", None, None)
    iid2, _ = env.come_back(9, patient=stranger)
    assert iid2 in [r["invoice_id"] for r in calls.worklists(env.conn, env.now)["unlinked_today"]]
    calls.link_invoice(env.conn, iid2, person, actor="acc:reza", now=env.now)
    assert env.q("SELECT status FROM journey WHERE person_id = ? AND template_code = 'lab_order'", person) == [
        ("succeeded",)]


def test_family_name_alone_never_suggests(env):
    env.origin({"lab_order": True})
    anon = env.rec.add_patient("ا", "احمدی", None, "09129999999")   # same surname, other mobile
    env.come_back(5, patient=anon)
    assert calls.worklists(env.conn, env.now)["suggestions"] == []


# ------------------------------------------------------------------ idempotency
def test_replaying_all_events_changes_nothing(env):
    env.origin({"renewal_months": 1, "lab_order": True})
    iid, vid = env.come_back(8)
    before = (env.q("SELECT * FROM return_evidence"), env.q("SELECT id, status FROM journey ORDER BY id"),
              env.q("SELECT id, status FROM journey_step ORDER BY id"))
    for _ in range(2):
        with core.transaction(env.conn):
            for inv in env.q("SELECT acc_id FROM acc_invoice"):
                returns.reconcile_invoice(env.conn, inv[0], env.now)
            returns.reconcile_patient(env.conn, env.pid, env.now)
    after = (env.q("SELECT * FROM return_evidence"), env.q("SELECT id, status FROM journey ORDER BY id"),
             env.q("SELECT id, status FROM journey_step ORDER BY id"))
    assert after == before
    # one visit may satisfy only one step (M5): lab_order and renewal both expect a visit
    assert env.q("SELECT count(*) FROM return_evidence") == [(1,)]
