"""M3: journey engine, doctor panel, nurse paper and cut-offs — service level, synthetic data, injected clock."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from accounting_factory import BP_CHECK_ID, BS_TEST_ID, TODAY, Reception
from src.adapters.accounting.bridge import AccountingBridge
from src.adapters.sqlite import core
from src.domain import cutoffs as cutoff_rules
from src.services import cutoffs, encounters, journeys, walkins
from src.services.bridge_monitor import BridgeMonitor
from src.sync.poller import Poller

NOW = datetime(2026, 10, 6, 10, 0, 0)
T = TODAY.isoformat()
NID, NID2 = "0499370899", "2170415981"
DOCTOR, OTHER_DOCTOR = 1, 2


class Env:
    def __init__(self, tmp_path, acc_db):
        self.rec = Reception(acc_db)
        self.panel = tmp_path / "peygiri_panel.db"
        core.init_db(self.panel, tmp_path / "backups")
        self.now = NOW
        bridge = AccountingBridge(str(acc_db), budget_ms=200, busy_timeout_ms=250)
        assert BridgeMonitor(bridge).check_now().state == "ok"
        self.poller = Poller(bridge, self.panel, interval_seconds=1, clock=lambda: self.now)
        self.conn = core.connect(self.panel)
        journeys.ensure_templates(self.conn, "2026-10-06 09:00:00")
        self.poller.step()

    def visit(self, *, name="مریم", family="احمدی", nid=NID, phone="09121234567", doctor=DOCTOR,
              extra=None) -> tuple[int, int]:
        pid = self.rec.add_patient(name, family, nid, phone)
        iid = self.rec.open_invoice(pid, T, "morning")
        vid = self.rec.add_visit(iid, doctor_id=doctor, at=f"{T} 09:30:00")
        if extra:
            extra(iid)
        self.poller.step()
        return vid, iid

    def save(self, vid, form, staff=DOCTOR):
        return encounters.save(self.conn, vid, form, staff_id=staff, actor="doctor:dr", now=self.now)

    def q(self, sql, *params):
        return [tuple(r) for r in self.conn.execute(sql, params).fetchall()]


@pytest.fixture
def env(tmp_path, acc_db):
    e = Env(tmp_path, acc_db)
    yield e
    e.conn.close()


FOLLOW = {"decision": "followup"}


# ------------------------------------------------------------------ templates
def test_templates_seeded_once_with_call_texts(env):
    assert len(env.q("SELECT code FROM journey_template WHERE is_current = 1")) == 10
    assert journeys.ensure_templates(env.conn, "2026-10-07 09:00:00") == 0
    assert env.q("SELECT is_enabled FROM journey_template WHERE code = 'respiratory'") == [(0,)]
    text = env.q("SELECT value FROM setting WHERE key = 'call_text.ear_invite_visit'")[0][0]
    assert "قطره" not in json.loads(text)
    with pytest.raises(journeys.JourneyError, match="D18"):
        journeys.validate_call_text("ear_invite_visit", "برای گرفتن قطره بیایید")


# ------------------------------------------------------------------ doctor panel
def test_panel_creates_journeys_with_exact_dates(env):
    vid, iid = env.visit(extra=lambda i: env.rec.add_injection(i, BS_TEST_ID, "تست قند"))
    view = encounters.panel(env.conn, vid, DOCTOR, T)
    assert view["identity_ok"] and view["has_bs_test"] and view["invoice_services"] == ["تست قند"]
    result = env.save(vid, {**FOLLOW, "tags": {"diabetes": True}, "renewal_months": 2, "quarterly_lab": True,
                            "bs": {"glucose": 180, "glucose_type": "fasting"}})
    assert result["message"] == "ثبت شد — ۲ پیگیری ساخته شد"
    rows = env.q("SELECT j.template_code, j.status, j.origin_doctor_staff_id, s.kind, s.due_date, s.window_end "
                 "FROM journey j JOIN journey_step s ON s.journey_id = j.id ORDER BY j.id, s.seq")
    assert rows == [
        ("renewal", "active", 1, "expect", "2026-10-07", "2027-01-04"),
        ("renewal", "active", 1, "call", "2026-11-25", None),
        ("quarterly_lab", "active", 1, "expect", "2026-10-07", "2027-02-03"),
        ("quarterly_lab", "active", 1, "call", "2027-01-01", None),
    ]
    assert env.q("SELECT tag, status FROM chronic_tag") == [("diabetes", "active")]
    assert env.q("SELECT kind, glucose, glucose_type FROM measurement") == [("bs", 180, "fasting")]
    assert env.q("SELECT decision FROM encounter WHERE acc_visit_id = ?", vid) == [("followup",)]
    # the queue now shows the visit as done
    from src.services import queue
    from src.services.shift import ShiftInfo
    [row] = queue.doctor_queue(env.conn, DOCTOR, ShiftInfo(T, "morning", "accounting"))
    assert row.status == "done"


@pytest.mark.parametrize("form,message", [
    ({"quarterly_lab": True}, "دیابتی"),
    ({"wound": {"dressing_every": 2}}, "روز کشیدن بخیه"),
    ({"wound": {"suture_day": 7}}, "پانسمان"),
    ({"renewal_months": 4}, "۱، ۲ یا ۳"),
    ({"series_bp": {"count": 30, "every_days": 1}}, "بین ۱ و ۱۰"),
    ({"ear_wax": "maybe"}, "تجویز"),
    ({"bp": {"systolic": 80, "diastolic": 90}, "lab_order": True}, "کمتر از سیستولیک"),
    ({}, "دست‌کم یک پیگیری"),
])
def test_panel_validation(env, form, message):
    vid, _ = env.visit()
    with pytest.raises(encounters.EncounterError, match=message):
        env.save(vid, {**FOLLOW, **form})
    assert env.q("SELECT count(*) FROM journey") == [(0,)] and env.q("SELECT count(*) FROM encounter") == [(0,)]


def test_no_followup_one_click(env):
    vid, _ = env.visit()
    assert env.save(vid, {"decision": "no_followup"})["message"] == "ثبت شد — بدون پیگیری"
    assert env.q("SELECT count(*) FROM journey") == [(0,)]


def test_only_own_visit_and_same_day_edit(env):
    vid, _ = env.visit(doctor=OTHER_DOCTOR)
    with pytest.raises(encounters.EncounterError, match="پزشک دیگری") as info:
        env.save(vid, {**FOLLOW, "lab_order": True})
    assert info.value.status == 403

    vid, _ = env.visit(nid=NID2, name="علی", family="رضایی")
    env.save(vid, {**FOLLOW, "lab_order": True, "ear_wax": "rx"})
    env.save(vid, {**FOLLOW, "lab_order": True})                         # edit: ear wax removed
    assert env.q("SELECT template_code, status, close_reason FROM journey ORDER BY id") == [
        ("lab_order", "cancelled", "manual"), ("ear_wax_rx", "cancelled", "manual"), ("lab_order", "active", None)]
    env.now = NOW + timedelta(days=1)
    with pytest.raises(encounters.EncounterError, match="همان روز"):
        env.save(vid, {"decision": "no_followup"})


def test_g9_new_choice_replaces_open_journey(env):
    vid1, _ = env.visit()
    env.save(vid1, {**FOLLOW, "renewal_months": 1})
    iid2 = env.rec.open_invoice(env.q("SELECT acc_patient_id FROM encounter")[0][0], T, "morning")
    vid2 = env.rec.add_visit(iid2, doctor_id=DOCTOR)
    env.poller.step()
    env.save(vid2, {**FOLLOW, "renewal_months": 3})
    assert env.q("SELECT status, close_reason, json_extract(params, '$.interval_months') FROM journey ORDER BY id") \
        == [("cancelled", "duplicate", 1), ("active", None, 3)]


def test_unknown_identity_waits_then_activates_with_tags(env):
    vid, iid = env.visit(name="خ", family="حسینی", nid=None, phone=None)
    result = env.save(vid, {**FOLLOW, "tags": {"hypertension": True}, "series_bp": {"count": 3, "every_days": 1}})
    assert "پس از تکمیل هویت" in result["message"]
    assert env.q("SELECT status, person_id FROM journey") == [("awaiting_identity", None)]
    assert env.q("SELECT count(*) FROM chronic_tag") == [(0,)]
    pid = env.q("SELECT acc_patient_id FROM encounter")[0][0]
    env.rec.update_patient(pid, name="فاطمه", national_id=NID2, phone_number="09351112233")
    env.poller.step()                                                     # M2 auto-link by national ID
    assert env.q("SELECT status FROM journey") == [("active",)]
    assert env.q("SELECT tag, status FROM chronic_tag") == [("hypertension", "active")]
    assert env.q("SELECT chronic_tags FROM encounter") == [(None,)]


# ------------------------------------------------------------------ engine ticks (day-by-day simulation)
def tick_days(env, n):
    for d in range(1, n + 1):
        journeys.tick_all(env.conn, NOW + timedelta(days=d))


def test_series_simulated_day_by_day(env):
    vid, _ = env.visit()
    env.save(vid, {**FOLLOW, "series_bp": {"count": 3, "every_days": 1}})
    tick_days(env, 2)
    assert env.q("SELECT status FROM journey_step WHERE kind = 'expect' ORDER BY seq") == [
        ("missed",), ("pending",), ("pending",)]
    assert env.q("SELECT purpose, due_date, about_category FROM journey_step WHERE kind = 'call'") == [
        ("missed", "2026-10-08", "bp_check")]
    tick_days(env, 2)                                                     # idempotent re-run of the same days
    assert env.q("SELECT count(*) FROM journey_step WHERE kind = 'call'") == [(1,)]
    tick_days(env, 40)
    assert env.q("SELECT status, close_reason FROM journey") == [("failed", "expired")]
    assert env.q("SELECT count(*) FROM journey_step WHERE status = 'pending'") == [(0,)]
    assert ("journey.failed",) in env.q("SELECT action FROM audit_log")


def test_awaiting_identity_cancelled_after_thirty_days(env):
    vid, _ = env.visit(name="خ", family="حسینی", nid=None, phone=None)
    env.save(vid, {**FOLLOW, "lab_order": True})
    tick_days(env, 29)
    assert env.q("SELECT status FROM journey") == [("awaiting_identity",)]
    tick_days(env, 30)
    assert env.q("SELECT status, close_reason FROM journey") == [("cancelled", "expired")]


def test_manual_cancel_and_continuation(env):
    vid, _ = env.visit()
    env.save(vid, {**FOLLOW, "renewal_months": 1})
    [(jid,)] = env.q("SELECT id FROM journey")
    # simulate the return (M4 will do this from a paid visit): expect done → succeeded → A1
    with core.transaction(env.conn):
        env.conn.execute("UPDATE journey_step SET status = 'done' WHERE journey_id = ? AND kind = 'expect'", (jid,))
        journeys.tick_journey(env.conn, jid, TODAY + timedelta(days=20), "2026-10-26 10:00:00")
        new = journeys.continue_after_success(env.conn, jid, "2026-10-26", 2, "2026-10-26 10:00:00")
    assert env.q("SELECT status FROM journey WHERE id = ?", jid) == [("succeeded",)]
    assert env.q("SELECT template_code, origin_kind, origin_doctor_staff_id, start_date FROM journey WHERE id = ?",
                 new) == [("renewal", "continuation", 2, "2026-10-26")]
    with core.transaction(env.conn):
        journeys.cancel(env.conn, new, "manual", "acc:boss", "2026-10-27 08:00:00")
    assert env.q("SELECT status, close_reason FROM journey WHERE id = ?", new) == [("cancelled", "manual")]


# ------------------------------------------------------------------ cut-offs
def full_rules():
    r = json.loads(json.dumps(cutoff_rules.EMPTY_TEMPLATE))
    r["bp"][0]["when"]["any"][0]["gte"], r["bp"][0]["when"]["any"][1]["gte"] = 160, 100
    r["bp"][1]["when"]["any"][0]["gte"], r["bp"][1]["when"]["any"][1]["gte"] = 140, 90
    r["bs"][0]["when"]["all"][1]["gte"], r["bs"][1]["when"]["all"][1]["gte"] = 126, 200
    return r


def test_cutoff_needs_every_number_and_a_director(env):
    assert "خالی" in " ".join(cutoff_rules.validate(cutoff_rules.EMPTY_TEMPLATE))
    cutoffs.save_draft(env.conn, cutoff_rules.EMPTY_TEMPLATE, actor="acc:boss", now=NOW)
    with pytest.raises(cutoffs.CutoffError) as info:
        cutoffs.approve(env.conn, director_staff_id=1, actor="doctor:dr", now=NOW)
    assert len(info.value.problems) == 6
    cutoffs.save_draft(env.conn, full_rules(), actor="acc:boss", now=NOW)
    assert cutoffs.approve(env.conn, director_staff_id=1, actor="doctor:dr", now=NOW) == 1
    r2 = full_rules()
    r2["series"]["count"] = 5
    cutoffs.save_draft(env.conn, r2, actor="doctor:dr", now=NOW)
    assert cutoffs.approve(env.conn, director_staff_id=1, actor="doctor:dr", now=NOW) == 2
    assert env.q("SELECT version, status FROM cutoff_ruleset ORDER BY version") == [(1, "retired"), (2, "approved")]


def test_cutoff_evaluation_first_match():
    r = full_rules()
    assert cutoff_rules.evaluate(r, "bp", {"systolic": 170, "diastolic": 80}) == ["invite_visit", "control_series_bp"]
    assert cutoff_rules.evaluate(r, "bp", {"systolic": 150, "diastolic": 80}) == ["control_series_bp"]
    assert cutoff_rules.evaluate(r, "bp", {"systolic": 120, "diastolic": 80}) == []
    assert cutoff_rules.evaluate(r, "bs", {"glucose": 130, "glucose_type": "fasting"}) == ["invite_visit"]
    assert cutoff_rules.evaluate(r, "bs", {"glucose": 130, "glucose_type": "random"}) == []


# ------------------------------------------------------------------ nurse paper
def walkin_invoice(env, service=BP_CHECK_ID, name="کنترل فشار", nid=NID):
    pid = env.rec.add_patient("مریم", "احمدی", nid, "09121234567")
    iid = env.rec.open_invoice(pid, T, "morning")
    env.rec.add_injection(iid, service, name)
    env.poller.step()
    return iid


def save_walkin(env, iid, form):
    return walkins.save(env.conn, iid, form, actor="acc:reza", now=env.now)


def test_walkin_before_approval_only_records(env):
    iid = walkin_invoice(env)
    assert [r["invoice_id"] for r in walkins.worklist(env.conn, NOW)["rows"]] == [iid]
    res = save_walkin(env, iid, {"status": "entered", "bp": {"systolic": 190, "diastolic": 110},
                                 "on_medication": True, "renewal": 20})
    assert "تأیید نشده" in res["message"] and res["actions"] == ["renewal"]
    assert env.q("SELECT template_code, json_extract(params, '$.due_day') FROM journey") == [("renewal", 20)]
    assert env.q("SELECT cutoff_ruleset_id FROM walkin_entry") == [(None,)]
    assert walkins.worklist(env.conn, NOW)["rows"] == []


def test_walkin_after_approval_creates_actions(env):
    cutoffs.save_draft(env.conn, full_rules(), actor="acc:boss", now=NOW)
    cutoffs.approve(env.conn, director_staff_id=1, actor="doctor:dr", now=NOW)
    iid = walkin_invoice(env)
    res = save_walkin(env, iid, {"status": "entered", "bp": {"systolic": 165, "diastolic": 85}})
    assert res["actions"] == ["invite_visit", "control_series_bp"]
    assert env.q("SELECT template_code, origin_kind, json_extract(params, '$.count') FROM journey ORDER BY id") == [
        ("invite_visit", "walkin", None), ("control_series_bp", "walkin", 3)]
    iid2 = walkin_invoice(env, BS_TEST_ID, "تست قند", nid=NID2)
    assert save_walkin(env, iid2, {"status": "entered", "bs": {"glucose": 110, "glucose_type": "fasting"}}
                       )["message"] == "ثبت شد — بدون اقدام"


@pytest.mark.parametrize("form,message", [
    ({"status": "entered"}, "دست‌کم یک عدد"),
    ({"status": "entered", "bs": {"glucose": 120, "glucose_type": "fasting"}}, "جور نیست"),
    ({"status": "entered", "bp": {"systolic": 130, "diastolic": 80}, "on_medication": True,
      "renewal": "۱۴۰۵/۰۷/۱۰"}, "بعد از روز مراجعه"),
])
def test_walkin_validation(env, form, message):
    iid = walkin_invoice(env)
    with pytest.raises(walkins.WalkinError, match=message):
        save_walkin(env, iid, form)
    assert env.q("SELECT count(*) FROM walkin_entry") == [(0,)]


def test_walkin_no_paper(env):
    iid = walkin_invoice(env)
    save_walkin(env, iid, {"status": "no_paper"})
    assert env.q("SELECT status FROM walkin_entry") == [("no_paper",)]
    with pytest.raises(walkins.WalkinError, match="فهرست"):
        save_walkin(env, iid, {"status": "no_paper"})
