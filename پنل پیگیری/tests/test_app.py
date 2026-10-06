"""Web layer: login from two sources, roles, CSRF, queue, shift override, doctor accounts."""
from __future__ import annotations

import re
import time
from dataclasses import replace
from datetime import datetime, timedelta

import bcrypt
import pytest

from accounting_factory import BS_TEST_ID, TODAY, Reception
from src.app import create_app
from src.config.settings import load_settings

NOW = datetime(2026, 10, 6, 10, 0, 0)
T = TODAY.isoformat()


def pw_hash(password: str) -> bytes:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4))


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


@pytest.fixture
def env(tmp_path, acc_db):
    rec = Reception(acc_db)
    rec.add_user("reza", pw_hash("recep-pass"), "reception", full_name="رضا پذیرش")
    rec.add_user("boss", pw_hash("boss-pass"), "manager", full_name="مدیر درمانگاه")
    clock = Clock(NOW)
    settings = replace(load_settings(tmp_path), accounting_db_path=str(acc_db))
    app = create_app(settings, start_background=False, clock=clock)
    rt = app.extensions["peygiri"]
    assert rt.monitor.check_now().state == "ok"
    rt.poller.step()
    return app, rt, rec, clock


def csrf_of(client, path="/login") -> str:
    html = client.get(path, follow_redirects=True).get_data(as_text=True)
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


def login(client, username, password):
    token = csrf_of(client)
    return client.post("/login", data={"username": username, "password": password, "csrf_token": token})


def post_json(client, url, payload):
    token = csrf_of(client, "/")
    return client.post(url, json=payload, headers={"X-CSRF-Token": token})


def make_doctor(app, rt, username="dr.alef", password="doctor-pass", staff_id=1, director=False):
    from src.adapters.sqlite import core
    from src.services.auth import create_doctor
    conn = core.connect(rt.settings.panel_db_path)
    try:
        return create_doctor(conn, rt.bridge, username=username, password=password, staff_id=staff_id,
                             is_director=director, actor="acc:boss", now=NOW)
    finally:
        conn.close()


# ------------------------------------------------------------------ public
def test_healthz_and_login_redirect(env):
    app, *_ = env
    c = app.test_client()
    assert c.get("/healthz").get_json()["app"] == "peygiri-panel"
    assert c.get("/").headers["Location"].endswith("/login")
    assert c.get("/api/status").status_code == 401
    assert c.get("/doctor").status_code == 302


def test_health_local_or_manager_only(env):
    app, *_ = env
    c = app.test_client()
    body = c.get("/health").get_json()                         # test client is 127.0.0.1
    assert body["bridge"]["state"] == "ok" and body["sync"]["color"] == "green"
    assert c.get("/health", environ_base={"REMOTE_ADDR": "192.168.1.20"}).status_code == 403


# ------------------------------------------------------------------ accounting users
def test_reception_and_manager_log_in_with_accounting_credentials(env):
    app, *_ = env
    c = app.test_client()
    resp = login(c, "reza", "recep-pass")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/reception")
    page = c.get("/reception").get_data(as_text=True)
    assert "رضا پذیرش" in page and 'dir="rtl"' in page
    assert c.get("/doctor").status_code == 403                 # role guard
    assert c.get("/manager/doctors").status_code == 403

    m = app.test_client()
    assert login(m, "boss", "boss-pass").headers["Location"].endswith("/manager/doctors")


@pytest.mark.parametrize("username,role,stored,extra,message", [
    ("reza", None, None, {}, "نام کاربری یا رمز نادرست است"),                  # wrong password
    ("ghost", None, None, {}, "نام کاربری یا رمز نادرست است"),                 # unknown user
    ("off", "reception", "hash", {"active": 0}, "غیرفعال یا قفل"),
    ("lock", "reception", "hash", {"locked_until": "2026-10-06T10:10:00"}, "غیرفعال یا قفل"),
    ("legacy", "reception", "pbkdf2:sha256:600000$abc$def", {}, "یک بار در حسابداری"),
    ("drrole", "doctor", "hash", {}, "حساب پنل پیگیری"),
])
def test_accounting_login_rejections(env, username, role, stored, extra, message):
    app, rt, rec, _ = env
    if role:
        rec.add_user(username, pw_hash("p4ssword") if stored == "hash" else stored, role, **extra)
    resp = login(app.test_client(), username, "p4ssword")
    assert resp.status_code == 401 and message in resp.get_data(as_text=True)


def test_lockout_after_five_failures_and_expiry(env):
    app, rt, rec, clock = env
    c = app.test_client()
    for _ in range(5):
        assert login(c, "reza", "nope").status_code == 401
    resp = login(c, "reza", "recep-pass")                       # right password, but locked
    assert resp.status_code == 401 and "بسته است" in resp.get_data(as_text=True)
    clock.at = NOW + timedelta(minutes=16)
    assert login(c, "reza", "recep-pass").status_code == 302


def test_csrf_is_required(env):
    app, *_ = env
    c = app.test_client()
    c.get("/login")
    assert c.post("/login", data={"username": "reza", "password": "recep-pass"}).status_code == 400
    login(c, "reza", "recep-pass")
    resp = c.post("/api/shift", json={"clear": True})
    assert resp.status_code == 400 and "نشست" in resp.get_json()["error"]


# ------------------------------------------------------------------ doctors
def test_doctor_login_is_checked_against_accounting_staff(env):
    app, rt, rec, _ = env
    make_doctor(app, rt)
    c = app.test_client()
    assert login(c, "dr.alef", "doctor-pass").headers["Location"].endswith("/doctor")
    assert c.get("/doctor").status_code == 200

    rec.set_staff_active(1, False)                              # accounting deactivates the doctor
    resp = login(app.test_client(), "dr.alef", "doctor-pass")
    assert resp.status_code == 401 and "کادر درمان حسابداری فعال نیست" in resp.get_data(as_text=True)


def test_doctor_account_rules(env):
    from src.services.auth import AccountError
    app, rt, rec, _ = env
    make_doctor(app, rt)
    with pytest.raises(AccountError, match="قبلاً حساب"):
        make_doctor(app, rt, username="other", staff_id=1)
    with pytest.raises(AccountError, match="در حسابداری وجود دارد"):
        make_doctor(app, rt, username="reza", staff_id=2)        # A13: no clash with accounting users
    with pytest.raises(AccountError, match="کادر درمانِ فعال"):
        make_doctor(app, rt, username="nurse1", staff_id=5)      # staff 5 is a nurse
    with pytest.raises(AccountError, match="دست‌کم"):
        make_doctor(app, rt, username="dr.b", password="123", staff_id=2)


def test_manager_creates_and_manages_doctor_accounts(env):
    app, rt, rec, _ = env
    m = app.test_client()
    login(m, "boss", "boss-pass")
    page = m.get("/manager/doctors").get_data(as_text=True)
    assert "دکتر الف" in page and "دکتر ب" in page and "پرستار ج" not in page
    token = csrf_of(m, "/manager/doctors")
    resp = m.post("/manager/doctors", data={"csrf_token": token, "staff_id": "2", "username": "dr.be",
                                            "password": "secret-1", "is_director": "1"}, follow_redirects=True)
    assert "حساب پزشک ساخته شد" in resp.get_data(as_text=True)
    assert login(app.test_client(), "dr.be", "secret-1").status_code == 302

    from src.adapters.sqlite import account_repo, core
    conn = core.connect(rt.settings.panel_db_path)
    doc = account_repo.doctor_by_username(conn, "dr.be")
    assert doc["is_director"] == 1
    m.post(f"/manager/doctors/{doc['id']}", data={"csrf_token": token, "action": "deactivate"})
    resp = login(app.test_client(), "dr.be", "secret-1")
    assert resp.status_code == 401 and "در پنل غیرفعال" in resp.get_data(as_text=True)
    actions = [r[0] for r in conn.execute("SELECT action FROM audit_log ORDER BY id")]
    conn.close()
    assert "doctor.create" in actions and "doctor.update" in actions


# ------------------------------------------------------------------ queue (M1 acceptance)
def test_queue_shows_own_visits_of_current_shift_and_drops_deleted(env):
    app, rt, rec, _ = env
    make_doctor(app, rt)
    c = app.test_client()
    login(c, "dr.alef", "doctor-pass")
    assert c.get("/api/doctor/queue").get_json()["total"] == 0

    pid = rec.add_patient("مریم", "احمدی", "0499370899", "09121234567")
    iid = rec.open_invoice(pid, T, "morning")
    vid = rec.add_visit(iid, doctor_id=1, at=f"{T} 09:20:00")
    rec.add_injection(iid, BS_TEST_ID, "تست قند")
    other = rec.add_visit(rec.open_invoice(rec.add_patient("خ", "حسینی"), T, "morning"), doctor_id=1,
                          at=f"{T} 09:25:00")
    rec.add_visit(rec.open_invoice(pid, T, "morning"), doctor_id=2)          # another doctor's visit
    rec.add_visit(rec.open_invoice(pid, T, "evening"), doctor_id=1)          # another shift
    rt.poller.step()

    q = c.get("/api/doctor/queue").get_json()
    assert q["total"] == 2 and q["pending"] == 2
    first, second = q["rows"]
    assert first["visit_id"] == vid and first["name"] == "مریم احمدی" and first["identity_ok"]
    assert first["services"] == ["تست قند"] and first["time"] == "09:20"
    assert second["visit_id"] == other and not second["identity_ok"]

    rec.delete_item(iid, "visit", vid)
    rt.poller.step()
    assert [r["visit_id"] for r in c.get("/api/doctor/queue").get_json()["rows"]] == [other]


def test_visit_reaches_queue_within_ten_seconds_with_live_poller(tmp_path, acc_db):
    """Q-1 end to end: real threads, real interval (5 s), clock = real Tehran time."""
    from src.common import iran_time
    rec = Reception(acc_db)
    today = iran_time.today_str()
    rec.start_shift(2, "morning", today, f"{today} 00:00:01")
    settings = replace(load_settings(tmp_path), accounting_db_path=str(acc_db))
    app = create_app(settings, start_background=True)
    rt = app.extensions["peygiri"]
    try:
        t0 = time.monotonic()                                 # wait for schema check + first poll
        while rt.monitor.status.state != "ok" or not rt.poller.step().ok:
            assert time.monotonic() - t0 < 5
            time.sleep(0.05)
        make_doctor(app, rt)
        c = app.test_client()
        login(c, "dr.alef", "doctor-pass")
        pid = rec.add_patient("سارا", "کاظمی")
        vid = rec.add_visit(rec.open_invoice(pid, today, "morning"), doctor_id=1)
        t0 = time.monotonic()
        while time.monotonic() - t0 < 10:
            if any(r["visit_id"] == vid for r in c.get("/api/doctor/queue").get_json()["rows"]):
                break
            time.sleep(0.25)
        assert time.monotonic() - t0 < 10, "visit did not reach the queue within 10 s"
    finally:
        rt.shutdown()


# ------------------------------------------------------------------ shift
def test_shift_override_and_auto_clear(env):
    app, rt, rec, _ = env
    c = app.test_client()
    login(c, "reza", "recep-pass")
    s = c.get("/api/status").get_json()["shift"]
    assert (s["shift"], s["source"], s["work_date_fa"]) == ("morning", "accounting", "۱۴۰۵/۰۷/۱۴")

    resp = post_json(c, "/api/shift", {"work_date_fa": "۱۴۰۵/۰۷/۱۳", "shift": "night"})
    s = resp.get_json()["shift"]
    assert (s["shift"], s["source"], s["work_date_fa"]) == ("night", "manual", "۱۴۰۵/۰۷/۱۳")
    assert post_json(c, "/api/shift", {"work_date_fa": "۱۴۰۵/۱۳/۰۱", "shift": "night"}).status_code == 400

    rec.start_shift(3, "evening", T, f"{T} 14:59:00")            # reception switches shift in accounting
    rt.poller.step()
    s = c.get("/api/status").get_json()["shift"]
    assert (s["shift"], s["source"]) == ("evening", "accounting")


def test_sync_indicator_turns_red_when_stale(env):
    app, rt, rec, clock = env
    c = app.test_client()
    login(c, "reza", "recep-pass")
    assert c.get("/api/status").get_json()["sync"]["color"] == "green"
    clock.at = NOW + timedelta(seconds=30)
    assert c.get("/api/status").get_json()["sync"]["color"] == "yellow"
    clock.at = NOW + timedelta(seconds=90)
    sync = c.get("/api/status").get_json()["sync"]
    assert sync["color"] == "red" and "۹۰" not in sync["message"] and "90" in sync["message"]


def test_runs_without_accounting_path(tmp_path):
    app = create_app(load_settings(tmp_path), start_background=False)
    rt = app.extensions["peygiri"]
    assert rt.monitor.check_now().state == "disabled"
    resp = login(app.test_client(), "reza", "x")
    assert resp.status_code == 401 and "ارتباط با حسابداری برقرار نیست" in resp.get_data(as_text=True)


def test_allowed_clients(tmp_path, acc_db):
    settings = replace(load_settings(tmp_path), accounting_db_path=str(acc_db), allowed_clients=("192.168.1.20",))
    app = create_app(settings, start_background=False)
    c = app.test_client()
    assert c.get("/healthz").status_code == 200                                         # local
    assert c.get("/healthz", environ_base={"REMOTE_ADDR": "192.168.1.20"}).status_code == 200
    assert c.get("/healthz", environ_base={"REMOTE_ADDR": "192.168.1.99"}).status_code == 403
