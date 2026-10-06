"""M3 HTTP layer: roles (docs/06 §1), CSRF, error bodies and the happy paths."""
from __future__ import annotations

import json

from accounting_factory import BP_CHECK_ID, TODAY
from src.domain import cutoffs as cutoff_rules
from test_app import NOW, env, login, make_doctor, post_json  # noqa: F401  (fixture reuse)

T = TODAY.isoformat()
NID = "0499370899"


def doctor_client(app, rt, username="dr.alef", staff_id=1, director=False):
    make_doctor(app, rt, username=username, staff_id=staff_id, director=director)
    c = app.test_client()
    assert login(c, username, "doctor-pass").status_code == 302
    return c


def user_client(app, username, password):
    c = app.test_client()
    assert login(c, username, password).status_code == 302
    return c


def visit(rec, rt, doctor=1, nid=NID):
    pid = rec.add_patient("مریم", "احمدی", nid, "09121234567")
    iid = rec.open_invoice(pid, T, "morning")
    vid = rec.add_visit(iid, doctor_id=doctor, at=f"{T} 09:10:00")
    rt.poller.step()
    return vid


def full_rules():
    r = json.loads(json.dumps(cutoff_rules.EMPTY_TEMPLATE))
    for kind, i, mode, j, v in (("bp", 0, "any", 0, 160), ("bp", 0, "any", 1, 100), ("bp", 1, "any", 0, 140),
                                ("bp", 1, "any", 1, 90), ("bs", 0, "all", 1, 126), ("bs", 1, "all", 1, 200)):
        r[kind][i]["when"][mode][j]["gte"] = v
    return r


def test_doctor_panel_round_trip(env):
    app, rt, rec, _ = env
    c = doctor_client(app, rt)
    vid = visit(rec, rt)
    assert c.get(f"/doctor/visit/{vid}").status_code == 200
    data = c.get(f"/api/doctor/visit/{vid}").get_json()
    assert data["name"] == "مریم احمدی" and data["encounter"] is None
    bad = post_json(c, f"/api/doctor/visit/{vid}", {"decision": "followup", "wound": {"dressing_every": 1}})
    assert bad.status_code == 400 and "بخیه" in bad.get_json()["error"]
    ok = post_json(c, f"/api/doctor/visit/{vid}", {"decision": "followup", "renewal_months": 1, "lab_order": True})
    assert ok.status_code == 200 and ok.get_json()["message"] == "ثبت شد — ۲ پیگیری برای بیمار ساخته شد"
    assert c.get("/api/doctor/queue").get_json()["rows"][0]["status"] == "done"
    assert c.post(f"/api/doctor/visit/{vid}", json={"decision": "no_followup"}).status_code == 400   # no CSRF


def test_other_doctors_visit_is_forbidden(env):
    app, rt, rec, _ = env
    c = doctor_client(app, rt)
    vid = visit(rec, rt, doctor=2)
    assert c.get(f"/api/doctor/visit/{vid}").status_code == 403
    assert post_json(c, f"/api/doctor/visit/{vid}", {"decision": "no_followup"}).status_code == 403


def test_cancel_own_only_and_manager_any(env):
    app, rt, rec, _ = env
    a = doctor_client(app, rt)
    b = doctor_client(app, rt, username="dr.be", staff_id=2)
    vid = visit(rec, rt)
    post_json(a, f"/api/doctor/visit/{vid}", {"decision": "followup", "lab_order": True, "ear_wax": "rx"})
    from src.adapters.sqlite import core
    conn = core.connect(rt.settings.panel_db_path)
    j1, j2 = [r[0] for r in conn.execute("SELECT id FROM journey ORDER BY id")]
    conn.close()
    resp = post_json(b, f"/api/journeys/{j1}/cancel", {})
    assert resp.status_code == 400 and "فقط پزشکی" in resp.get_json()["error"]
    assert post_json(a, f"/api/journeys/{j1}/cancel", {}).status_code == 200
    m = user_client(app, "boss", "boss-pass")
    assert post_json(m, f"/api/journeys/{j2}/cancel", {}).status_code == 200
    r = user_client(app, "reza", "recep-pass")
    assert post_json(r, f"/api/journeys/{j2}/cancel", {}).status_code == 403


def test_cutoffs_roles(env):
    app, rt, rec, _ = env
    m = user_client(app, "boss", "boss-pass")
    assert m.get("/cutoffs").status_code == 200
    state = m.get("/api/cutoffs").get_json()
    assert state["approved"] is None and state["can_approve"] is False
    assert post_json(m, "/api/cutoffs/draft", {"rules": full_rules()}).get_json()["problems"] == []
    assert post_json(m, "/api/cutoffs/approve", {}).status_code == 403           # manager cannot approve

    plain = doctor_client(app, rt)
    assert plain.get("/cutoffs").status_code == 403                             # non-director doctor
    director = doctor_client(app, rt, username="dr.boss", staff_id=2, director=True)
    assert director.get("/api/cutoffs").get_json()["can_approve"] is True
    resp = post_json(director, "/api/cutoffs/approve", {})
    assert resp.status_code == 200 and "تأیید شد" in resp.get_json()["message"]
    assert m.get("/api/cutoffs").get_json()["approved"]["version"] == 1

    rec_c = user_client(app, "reza", "recep-pass")
    assert rec_c.get("/api/cutoffs").status_code == 403


def test_incomplete_draft_cannot_be_approved(env):
    app, rt, rec, _ = env
    director = doctor_client(app, rt, username="dr.boss", staff_id=2, director=True)
    post_json(director, "/api/cutoffs/draft", {"rules": cutoff_rules.EMPTY_TEMPLATE})
    resp = post_json(director, "/api/cutoffs/approve", {})
    assert resp.status_code == 400 and len(resp.get_json()["problems"]) == 6


def test_walkin_endpoints(env):
    app, rt, rec, _ = env
    r = user_client(app, "reza", "recep-pass")
    pid = rec.add_patient("مریم", "احمدی", NID, "09121234567")
    iid = rec.open_invoice(pid, T, "morning")
    rec.add_injection(iid, BP_CHECK_ID, "کنترل فشار")
    rt.poller.step()
    data = r.get("/api/reception/walkins").get_json()
    assert data["cutoff_approved"] is False and data["rows"][0]["work_date_fa"] == "۱۴۰۵/۰۷/۱۴"
    resp = post_json(r, f"/api/reception/walkins/{iid}", {"status": "entered", "bp": {"systolic": 150, "diastolic": 95}})
    assert resp.status_code == 200 and "تأیید نشده" in resp.get_json()["message"]
    assert post_json(r, f"/api/reception/walkins/{iid}", {"status": "no_paper"}).status_code == 409
    d = doctor_client(app, rt)
    assert d.get("/api/reception/walkins").status_code == 403


def test_call_endpoints_roles_and_flow(env):
    from datetime import timedelta
    app, rt, rec, clock = env
    d = doctor_client(app, rt)
    vid = visit(rec, rt)
    post_json(d, f"/api/doctor/visit/{vid}", {"decision": "followup", "lab_order": True})
    clock.at = NOW + timedelta(days=2)
    r = user_client(app, "reza", "recep-pass")
    lists = r.get("/api/reception/followups").get_json()
    [call] = lists["today"]
    assert call["purpose"] == "lab_check" and "lab_not_done" in call["outcomes"]
    assert r.get(f"/api/reception/calls/{call['step_id']}/slots").status_code == 200
    bad = post_json(r, f"/api/reception/calls/{call['step_id']}", {"outcome": "booked", "booked_date_fa": "x"})
    assert bad.status_code == 400 and "تاریخ" in bad.get_json()["error"]
    ok = post_json(r, f"/api/reception/calls/{call['step_id']}", {"outcome": "no_answer", "note": "خاموش بود"})
    assert ok.get_json()["message"] == "تماس بعدی: فردا"
    assert r.get("/api/reception/followups").get_json()["today"] == []
    assert d.get("/api/reception/followups").status_code == 403                    # doctors don't call
    assert post_json(d, f"/api/reception/calls/{call['step_id']}", {"outcome": "refused"}).status_code == 403
    m = user_client(app, "boss", "boss-pass")
    page = m.get("/manager/doctors").get_data(as_text=True)
    assert "پزشکان پیگیری" in page
