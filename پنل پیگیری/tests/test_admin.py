"""M5: report, audit log, procedure-name mapping, call texts, weekly maintenance, health and stop."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest

from accounting_factory import TODAY
from src.adapters.sqlite import core
from src.services import admin, encounters, journeys
from test_app import NOW, env, login, make_doctor, post_json  # noqa: F401  (fixture reuse)
from test_clinical_api import doctor_client, user_client, visit

T = TODAY.isoformat()
RANGE = "۱۴۰۵/۰۷/۰۱ - ۱۴۰۵/۰۷/۱۴"


def db(rt):
    return core.connect(rt.settings.panel_db_path)


def csrf(client, path):
    import re
    return re.search(r'name="csrf-token" content="([^"]+)"', client.get(path).get_data(as_text=True)).group(1)


def test_parse_range():
    assert admin.parse_range(RANGE) == ("2026-09-23", "2026-10-06")
    assert admin.parse_range("1405/07/14") == ("2026-10-06", "2026-10-06")
    for bad in ("", "۱۴۰۵/۰۷/۱۴ - ۱۴۰۵/۰۷/۰۱", "x - y"):
        with pytest.raises(admin.AdminError):
            admin.parse_range(bad)


def test_report_counts_and_roles(env):
    app, rt, rec, _ = env
    d = doctor_client(app, rt)
    vid = visit(rec, rt)
    post_json(d, f"/api/doctor/visit/{vid}", {"decision": "followup", "lab_order": True, "renewal_months": 1})
    conn = db(rt)
    with core.transaction(conn):
        jid = conn.execute("SELECT id FROM journey WHERE template_code = 'lab_order'").fetchone()[0]
        journeys.cancel(conn, jid, "manual", "x", "2026-10-06 11:00:00")
    conn.close()
    m = user_client(app, "boss", "boss-pass")
    data = m.get("/api/reports/followup", query_string={"range": RANGE}).get_json()
    by = {t["title"]: t for t in data["templates"]}
    assert by["پیگیری جواب آزمایش"]["cancelled"] == 1 and by["تمدید نسخه"]["active"] == 1
    assert data["doctors"][0]["doctor"] == "دکتر الف" and data["baseline_rate"] == 8
    assert m.get("/reports").status_code == 200
    assert m.get("/api/reports/followup", query_string={"range": "bad"}).status_code == 400
    director = doctor_client(app, rt, username="dr.boss", staff_id=2, director=True)
    assert director.get("/reports").status_code == 200                       # director sees reports
    assert director.get("/manager/settings").status_code == 403              # but not settings
    assert user_client(app, "reza", "recep-pass").get("/reports").status_code == 403


def test_audit_log_filters_and_jalali(env):
    app, rt, rec, _ = env
    m = user_client(app, "boss", "boss-pass")
    data = m.get("/api/manager/audit", query_string={"range": RANGE}).get_json()
    assert any(r["action"] == "ورود" and r["actor"] == "boss" for r in data["rows"])
    assert all("۱۴۰۵" in r["at_fa"] for r in data["rows"])
    only = m.get("/api/manager/audit", query_string={"range": RANGE, "action": "auth.fail"}).get_json()
    assert only["rows"] == []
    assert m.get("/manager/audit").status_code == 200


def test_procedure_mapping_recategorizes_mirror(env):
    app, rt, rec, _ = env
    pid = rec.add_patient("علی", "رضایی")
    iid = rec.open_invoice(pid, T, "morning")
    ambiguous = rec.add_procedure(iid, "بخیه")
    rec.add_procedure(iid, "کشیدن بخیه")
    rt.poller.step()
    conn = db(rt)
    names = {p["name"]: p for p in admin.procedure_names(conn)}
    assert names["بخیه"]["needs_decision"] and names["بخیه"]["ambiguous"]
    assert not names["کشیدن بخیه"]["needs_decision"]
    assert next(iter(names.values()))["name"] == "بخیه"                      # decisions first
    assert admin.map_procedure(conn, "بخیه", "suture_removal", actor="acc:boss", now=NOW) == 1
    cats = conn.execute("SELECT category FROM acc_item_category WHERE item_type='procedure' AND item_id=?",
                        (ambiguous,)).fetchall()
    assert [r[0] for r in cats] == ["suture_removal"]
    admin.map_procedure(conn, "بخیه", "auto", actor="acc:boss", now=NOW)
    assert conn.execute("SELECT count(*) FROM acc_item_category WHERE item_id=? AND item_type='procedure'",
                        (ambiguous,)).fetchone()[0] == 0
    with pytest.raises(admin.AdminError):
        admin.map_procedure(conn, "بخیه", "visit", actor="acc:boss", now=NOW)
    conn.close()
    m = user_client(app, "boss", "boss-pass")
    page = m.get("/manager/settings").get_data(as_text=True)
    assert "بخیه" in page and "مبهم" in page
    resp = m.post("/manager/settings/procedure", data={"csrf_token": csrf(m, "/manager/settings"),
                                                       "name": "بخیه", "choice": "none"}, follow_redirects=True)
    assert "ذخیره شد" in resp.get_data(as_text=True)


def test_call_texts(env):
    app, rt, rec, _ = env
    conn = db(rt)
    texts = {t["purpose"]: t for t in admin.call_texts(conn)}
    assert "{due_date}" in texts["renewal_reminder"]["text"]
    admin.save_call_text(conn, "invite_visit", "لطفاً برای ویزیت مراجعه کنید.", actor="acc:boss", now=NOW)
    with pytest.raises(admin.AdminError, match="دارو"):
        admin.save_call_text(conn, "ear_invite_visit", "قطره را بگیرید", actor="acc:boss", now=NOW)
    with pytest.raises(admin.AdminError):
        admin.save_call_text(conn, "nope", "x", actor="acc:boss", now=NOW)
    assert {t["purpose"]: t for t in admin.call_texts(conn)}["invite_visit"]["text"] == "لطفاً برای ویزیت مراجعه کنید."
    conn.close()


def test_weekly_maintenance_backs_up_and_purges_unreferenced_old_rows(env):
    app, rt, rec, clock = env
    d = doctor_client(app, rt)
    vid = visit(rec, rt)
    post_json(d, f"/api/doctor/visit/{vid}", {"decision": "followup", "lab_order": True})
    old_unref = rec.open_invoice(rec.add_patient("کهنه", "بی‌ارجاع"), T, "morning")
    rec.add_visit(old_unref, doctor_id=2)
    rec.close_invoice(old_unref, 0)
    rt.poller.step()
    m = admin.Maintenance(rt.settings.panel_db_path, rt.settings.backups_dir, lambda: clock.at)
    first = m.run_once()
    assert first and first["purged"]["invoices"] == 0                       # nothing is old yet
    assert m.run_once() is None                                             # not due again this week
    clock.at = NOW + timedelta(days=130)
    second = m.run_once()
    assert second["purged"]["invoices"] >= 1
    conn = db(rt)
    kept = {r[0] for r in conn.execute("SELECT acc_id FROM acc_invoice")}
    origin = conn.execute("SELECT acc_invoice_id FROM encounter").fetchone()[0]
    assert origin in kept and old_unref not in kept                         # referenced rows survive
    conn.close()
    assert len(list(rt.settings.backups_dir.glob("peygiri_panel_weekly_*.db"))) == 2


def test_health_page_backup_and_stop(env):
    app, rt, rec, _ = env
    m = user_client(app, "boss", "boss-pass")
    page = m.get("/manager/health").get_data(as_text=True)
    assert "ارتباط با حسابداری برقرار است" in page and "توقف فقط از کامپیوتری" in page   # no stop hook in tests
    token = csrf(m, "/manager/health")
    resp = m.post("/manager/backup", data={"csrf_token": token}, follow_redirects=True)
    assert "پشتیبان گرفته شد" in resp.get_data(as_text=True)
    stopped = []
    rt.stop_server = lambda: stopped.append(True)
    assert m.post("/manager/stop", data={"csrf_token": token}, environ_base={"REMOTE_ADDR": "192.168.1.20"}
                  ).status_code == 403                                       # never from another PC
    resp = m.post("/manager/stop", data={"csrf_token": token})
    assert "متوقف شد" in resp.get_data(as_text=True)
    import time
    time.sleep(0.8)
    assert stopped == [True]
    assert user_client(app, "reza", "recep-pass").get("/manager/health").status_code == 403
